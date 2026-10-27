"""Standard-library-only offline evaluation tests; all HTTP is in-memory."""
import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from evaluation import search_evaluation as evaluation


def packet(kind, data):
    return ('data: ' + json.dumps({'type': kind, 'data': data}, ensure_ascii=False) + '\n\n').encode('utf-8')


def sample_record(done=True, answer='一个事实[1](https://evidence.test/a)\n'):
    case = evaluation.load_json(evaluation.ROOT / 'cases.json')['cases'][0]
    body = (b': keepalive\r\n\r\n' + packet('sources', {'results': [
        {'url': 'https://evidence.test/a', 'published_at': '2020-01-02',
         'metadata': {'read_status': 'summary_only', 'nested': {'raw': 'unchanged'}}},
        {'url': 'https://evidence.test/b', 'published_at': None, 'metadata': {}}
    ]}) + packet('token', answer))
    if done:
        body += packet('done', {'status': 'completed'})
    response = io.BytesIO(body)
    response.status = 200
    response.headers = {'Content-Type': 'text/event-stream; charset=utf-8', 'X-Trace': 'test'}
    opener = Mock()
    opener.open.return_value = response
    record = evaluation.collect_case(case, 'http://127.0.0.1:8000/api/v1/agent/stream', opener=opener)
    return record, body, opener


def capture_and_labels():
    record, _, _ = sample_record()
    capture = {'schema_version': 1, 'run_id': 'offline-test', 'records': [record]}
    return capture, evaluation.make_labels(capture)


def mark_claim(label, judgment='supported'):
    label['claims'][0]['factual'] = True
    label['claims'][0]['citations'][0]['judgment'] = judgment
    label['claims'][0]['citations'][0]['notes'] = '离线测试中的人工标注样例，不是真实验收结论'
    label['claim_inventory_reviewed'] = True


class SearchEvaluationTests(unittest.TestCase):
    def test_suite_categories_and_rubric(self):
        suite = evaluation.load_json(evaluation.ROOT / 'cases.json')
        cases = suite['cases']
        counts = {}
        for case in cases:
            counts[case['category']] = counts.get(case['category'], 0) + 1
            self.assertTrue(case['information_needs'])
            self.assertTrue(case['rubric'])
            self.assertTrue(case['temporal']['criteria'])
        self.assertEqual(len(cases), len({case['id'] for case in cases}))
        self.assertEqual(set(counts), {'中文', '英文', '最新版本', '学术', '历史'})
        self.assertTrue(all(n >= 2 for n in counts.values()))

    def test_post_default_fast_and_exact_raw_metadata(self):
        record, body, opener = sample_record()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data)['mode'], 'fast')
        self.assertEqual(json.loads(request.data)['top_k'], 5)
        self.assertTrue(record['success'])
        self.assertTrue(record['done'])
        self.assertGreaterEqual(record['latency_ms'], record['first_token_ms'])
        raw = b''.join(evaluation.base64.b64decode(line) for line in record['raw_sse_lines_b64'])
        self.assertEqual(raw, body)
        self.assertEqual(record['sources'][0]['metadata']['nested'], {'raw': 'unchanged'})
        self.assertEqual(record['events'][0]['data']['results'], record['sources'])

    def test_missing_done_and_server_failure_do_not_succeed(self):
        record, _, _ = sample_record(done=False)
        self.assertFalse(record['success'])
        self.assertTrue(any(error['kind'] == 'missing_done' for error in record['errors']))
        record, _, _ = sample_record()
        evaluation.consume_sse(io.BytesIO(packet('done', {'ok': False})), record, 0)
        self.assertFalse(evaluation.successful(record))

    def test_sse_malformed_and_last_snapshot(self):
        record, _, _ = sample_record()
        stream = io.BytesIO(b'data: broken\n\n' + packet('sources', {'results': []}))
        evaluation.consume_sse(stream, record, 0)
        self.assertEqual(record['sources'], [])
        self.assertEqual(record['errors'][0]['kind'], 'sse_parse')
        self.assertEqual(len([event for event in record['events'] if event['type'] == 'sources']), 2)

    def test_multiline_sse_and_first_nonempty_token(self):
        record, _, _ = sample_record(answer='')
        self.assertIsNone(record['first_token_ms'])
        body = b'data: {"type":"token",\r\ndata: "data":"actual"}\r\n\r\n'
        evaluation.consume_sse(io.BytesIO(body), record, 10, clock=lambda: 10.25)
        self.assertEqual(record['first_token_ms'], 250)
        self.assertEqual(record['answer'], 'actual')

    def test_http_error_is_preserved(self):
        case = evaluation.load_json(evaluation.ROOT / 'cases.json')['cases'][0]
        opener = Mock()
        opener.open.side_effect = evaluation.urllib.error.HTTPError(
            'http://127.0.0.1:8000/api/v1/agent/stream', 503, 'offline fixture',
            {'Content-Type': 'text/plain'}, io.BytesIO(b'fixture unavailable'))
        record = evaluation.collect_case(case, 'http://127.0.0.1:8000/api/v1/agent/stream', opener=opener)
        self.assertEqual(record['http_status'], 503)
        self.assertFalse(record['success'])
        self.assertEqual(evaluation.base64.b64decode(record['http_error_body_b64']), b'fixture unavailable')

    def test_truncated_transfer_is_a_recorded_failure(self):
        case = evaluation.load_json(evaluation.ROOT / 'cases.json')['cases'][0]
        opener = Mock()
        opener.open.side_effect = evaluation.http.client.IncompleteRead(b'partial evidence', 100)
        record = evaluation.collect_case(case, 'http://127.0.0.1:8000/api/v1/agent/stream', opener=opener)
        self.assertFalse(record['success'])
        self.assertEqual(record['errors'][0]['kind'], 'IncompleteRead')
        self.assertEqual(evaluation.base64.b64decode(record['incomplete_read_partial_b64']), b'partial evidence')

    def test_template_comes_from_evidence_and_has_no_truth(self):
        capture, labels = capture_and_labels()
        label = labels['cases'][0]
        self.assertEqual([row['url'] for row in label['relevance']],
                         [source['url'] for source in capture['records'][0]['sources']])
        self.assertTrue(all(row['judgment'] is None for row in label['relevance']))
        claim = label['claims'][0]
        start, end = claim['span']
        self.assertEqual(claim['text'], capture['records'][0]['answer'][start:end])
        self.assertIsNone(claim['factual'])
        self.assertIsNone(claim['citations'][0]['judgment'])
        self.assertIsNone(label['temporal']['judgment'])
        self.assertFalse(label['claim_inventory_reviewed'])

    def test_unlabelled_precision_is_null_not_zero(self):
        capture, labels = capture_and_labels()
        report = evaluation.score_capture(capture, labels)
        self.assertIsNone(report['cases'][0]['precision_at_5'])
        self.assertIsNone(report['precision_at_5']['macro_complete_cases_only'])
        self.assertIsNone(report['precision_at_5']['judged_precision_not_p5'])
        self.assertEqual(report['precision_at_5']['bounds_all_cases'], [0, .4])
        labels['cases'][0]['relevance'][0]['judgment'] = 1
        report = evaluation.score_capture(capture, labels)
        self.assertIsNone(report['cases'][0]['precision_at_5'])
        self.assertEqual(report['precision_at_5']['judged_precision_not_p5'], 1)
        self.assertEqual(report['precision_at_5']['judgment_coverage'], .5)
        labels['cases'][0]['relevance'][1]['judgment'] = 0
        report = evaluation.score_capture(capture, labels)
        self.assertEqual(report['cases'][0]['precision_at_5'], .2)
        self.assertEqual(report['precision_at_5']['returned_slot_coverage'], .4)

    def test_citations_uncertain_and_denominator_coverage(self):
        capture, labels = capture_and_labels()
        label = labels['cases'][0]
        mark_claim(label, 'uncertain')
        report = evaluation.score_capture(capture, labels)
        result = report['citation_support']
        self.assertIsNone(result['rate_decisive_only'])
        self.assertEqual(result['uncertain'], 1)
        self.assertEqual(result['human_label_coverage'], 1)
        self.assertEqual(result['decisive_coverage'], 0)
        self.assertEqual(result['pair_denominator'], 1)
        self.assertEqual(result['conservative_support_among_labeled'], 0)
        mark_claim(label, 'supported')
        self.assertEqual(evaluation.score_capture(capture, labels)['citation_support']['rate_decisive_only'], 1)
        mark_claim(label, 'unsupported')
        self.assertEqual(evaluation.score_capture(capture, labels)['citation_support']['rate_decisive_only'], 0)

    def test_uncited_fact_and_inventory_cannot_silently_be_dropped(self):
        capture, labels = capture_and_labels()
        record = capture['records'][0]
        record['answer'] += '无引用事实。'
        labels = evaluation.make_labels(capture)
        label = labels['cases'][0]
        mark_claim(label)
        label['claims'][1]['factual'] = True
        report = evaluation.score_capture(capture, labels)
        self.assertEqual(report['citation_support']['cited_claim_coverage'], .5)
        self.assertEqual(report['citation_support']['uncited_factual_claims'], 1)
        label['claims'].pop()
        with self.assertRaisesRegex(ValueError, '覆盖'):
            evaluation.score_capture(capture, labels)

    def test_reject_tampered_evidence_urls_claims_and_labels(self):
        capture, labels = capture_and_labels()
        bad = copy.deepcopy(labels)
        bad['cases'][0]['relevance'][0]['url'] = 'https://fabricated.test/'
        with self.assertRaisesRegex(ValueError, '实采'):
            evaluation.score_capture(capture, bad)
        bad = copy.deepcopy(labels)
        bad['cases'][0]['claims'][0]['text'] = 'fabricated'
        with self.assertRaisesRegex(ValueError, '实采'):
            evaluation.score_capture(capture, bad)
        bad = copy.deepcopy(labels)
        bad['cases'][0]['claims'][0]['citations'][0]['url'] = 'https://fabricated.test/'
        with self.assertRaisesRegex(ValueError, '实采'):
            evaluation.score_capture(capture, bad)
        capture['records'][0]['answer'] += 'tampered'
        with self.assertRaisesRegex(ValueError, 'hash'):
            evaluation.score_capture(capture, labels)

    def test_manual_temporal_not_inferred_from_dates(self):
        capture, labels = capture_and_labels()
        label = labels['cases'][0]
        report = evaluation.score_capture(capture, labels)
        self.assertEqual(report['date_parseability']['coverage'], .5)
        self.assertEqual(report['temporal_manual']['counts'], {'unlabeled': 1})
        label['temporal'] = {'judgment': 'incorrect', 'notes': '离线示例：政策适用时间不匹配'}
        report = evaluation.score_capture(capture, labels)
        self.assertEqual(report['temporal_manual']['correct_rate_decisive_only'], 0)
        self.assertEqual(report['temporal_manual']['decisive_coverage'], 1)

    def test_date_formats_and_percentiles(self):
        anchor = datetime(2026, 10, 17, tzinfo=timezone.utc)
        for value in ['2020-01-02', '2020-01-02T03:00:00Z',
                      'Fri, 16 Oct 2026 10:00:00 GMT', '1600000000', '1600000000000', '2 days ago']:
            self.assertIsNotNone(evaluation.parse_date(value, anchor), value)
        for value in [None, '', 'not a date', True, '2026-02-30']:
            self.assertIsNone(evaluation.parse_date(value, anchor))
        # A future date may parse but is separately flagged, never treated as proof of freshness.
        self.assertIsNotNone(evaluation.parse_date('2099-01-01', anchor))
        self.assertEqual(evaluation.percentile([10, 20, 30], .5), 20)
        self.assertEqual(evaluation.percentile([10, 20, 30], .95), 29)
        self.assertIsNone(evaluation.percentile([], .95))
        capture, labels = capture_and_labels()
        self.assertEqual(evaluation.score_capture(capture, labels)['success']['rate'], 1)
        capture['records'][0]['done'] = False
        labels = evaluation.make_labels(capture)
        self.assertEqual(evaluation.score_capture(capture, labels)['success']['rate'], 0)

    def test_no_network_without_collect_and_bounded_selection(self):
        with patch.object(evaluation.urllib.request, 'build_opener') as opener, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(evaluation.main([]), 0)
            for args in [['--collect'], ['--collect', '--case', 'missing'],
                         ['--collect'] + sum((['--case', case] for case in ['a', 'b', 'c', 'd']), []),
                         ['--score', str(evaluation.ROOT / 'nonexistent-offline-run')]]:
                with self.assertRaises(SystemExit):
                    evaluation.main(args)
            opener.assert_not_called()

    def test_loopback_only_and_output_confinement(self):
        for value in ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://[::1]:8000']:
            self.assertTrue(evaluation.endpoint_url(value).endswith('/api/v1/agent/stream'))
        for value in ['https://example.com', 'http://example.com', 'http://localhost.evil.test',
                      'http://user@localhost:8000', 'http://127.0.0.1:8000/redirect',
                      'http://127.0.0.1:8000?target=evil', 'file:///tmp/x']:
            with self.assertRaises(ValueError):
                evaluation.endpoint_url(value)
        with self.assertRaises(ValueError):
            evaluation.confined(evaluation.ROOT.parent / 'outside.json')
        self.assertEqual(evaluation.confined(evaluation.ROOT / 'runs'), evaluation.ROOT / 'runs')


if __name__ == '__main__':
    unittest.main()
