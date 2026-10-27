"""Opt-in loopback SSE collection and offline, human-labelled search evaluation.

Standard library only. No app imports, service startup, or network on import/score.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import http.client
import ipaddress
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
LINK = re.compile(r"\[[^\]\n]*\]\((https?://[^\s]+?)\)")
TEMPORAL_VALUES = {None, "correct", "incorrect", "uncertain", "not_applicable"}
CITATION_VALUES = {None, "supported", "unsupported", "uncertain"}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def confined(path):
    """Reject output/input paths outside this tool, including symlink escapes."""
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError("数据路径必须位于 backend/evaluation/ 内的子目录或文件")
    return path


def write_json(path, value):
    path = confined(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def endpoint_url(value):
    parsed = urllib.parse.urlsplit(value)
    try:
        host_ok = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        host_ok, port = False, None
    if (parsed.scheme != "http" or not host_ok or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or port == 0):
        raise ValueError("--base-url 仅接受 http://localhost[:port] 或数字回环地址，不允许路径/认证/重定向")
    return value.rstrip("/") + "/api/v1/agent/stream"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def consume_sse(response, record, started, clock=time.perf_counter):
    """Keep byte-exact line evidence as base64, plus parsed packets and timings."""
    data_lines = []
    def dispatch():
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            packet = json.loads(raw)
            if not isinstance(packet, dict) or "type" not in packet or "data" not in packet:
                raise ValueError("expected {type, data}")
        except (ValueError, TypeError) as exc:
            record["errors"].append({"kind": "sse_parse", "message": str(exc), "data": raw})
            return
        record["events"].append(packet)
        kind, data = packet["type"], packet["data"]
        if kind == "sources":
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                # The last sources packet is the final ranked list; all snapshots remain in events.
                record["sources"] = data["results"]
            else:
                record["errors"].append({"kind": "sources_shape", "data": data})
        elif kind == "token":
            if isinstance(data, str):
                if data and record["first_token_ms"] is None:
                    record["first_token_ms"] = (clock() - started) * 1000
                record["answer"] += data
            else:
                record["errors"].append({"kind": "token_shape", "data": data})
        elif kind == "done":
            record["done"] = True
            record["done_data"] = data
            if isinstance(data, dict) and (data.get("ok") is False or data.get("status") in ("error", "failed")):
                record["errors"].append({"kind": "done_failure", "data": data})
        elif kind == "error":
            record["errors"].append({"kind": "server", "data": data})

    for raw_line in response:
        record["raw_sse_lines_b64"].append(base64.b64encode(raw_line).decode("ascii"))
        text = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
        if not text:
            dispatch()
        elif text.startswith("data:"):
            data_lines.append(text[5:].removeprefix(" "))
        # SSE comments/event/id fields remain in raw evidence, not answer text.
    dispatch()


def successful(record):
    return (record.get("http_status") == 200 and record.get("done") is True
            and not record.get("errors") and bool(record.get("answer", "").strip()))


def collect_case(case, endpoint, mode="fast", timeout=90, opener=None):
    payload = {"query": case["query"], "mode": mode, "route_group": "auto",
               "top_k": 5, "scrape_top_n": 0, "max_rounds": 1, "reading_budget": 2}
    if case["category"] == "历史":
        payload["time_range"] = "all"
    record = {
        "case": case, "collected_at": datetime.now(timezone.utc).isoformat(),
        "request": {"method": "POST", "url": endpoint, "json": payload},
        "http_status": None, "response_headers": [], "sources": [], "answer": "",
        "latency_ms": None, "first_token_ms": None, "done": False,
        "done_data": None, "errors": [], "events": [], "raw_sse_lines_b64": [],
    }
    # Never use system proxies or follow a redirect to an external host.
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                                     method="POST")
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:
            record["http_status"] = response.status
            record["response_headers"] = list(response.headers.items())
            if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("expected Content-Type: text/event-stream")
            consume_sse(response, record, started)
    except urllib.error.HTTPError as exc:
        record["http_status"] = exc.code
        record["response_headers"] = list(exc.headers.items()) if exc.headers else []
        record["errors"].append({"kind": "http", "message": str(exc)})
        try:
            record["http_error_body_b64"] = base64.b64encode(exc.read()).decode("ascii")
        except (OSError, http.client.HTTPException) as read_error:
            record["http_error_body_b64"] = base64.b64encode(getattr(read_error, "partial", b"")).decode("ascii")
            record["errors"].append({"kind": "http_error_body_read", "message": str(read_error)})
        finally:
            exc.close()
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
        if isinstance(exc, http.client.IncompleteRead) and exc.partial:
            record["incomplete_read_partial_b64"] = base64.b64encode(exc.partial).decode("ascii")
        record["errors"].append({"kind": type(exc).__name__, "message": str(exc)})
    finally:
        record["latency_ms"] = (time.perf_counter() - started) * 1000
    if not record["done"]:
        record["errors"].append({"kind": "missing_done", "message": "连接结束前未收到done"})
    record["success"] = successful(record)
    return record


def fingerprint(record):
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_claims(answer):
    """Exact line spans only; humans must split multi-fact lines and check coverage."""
    claims = []
    offset = 0
    for line in answer.splitlines(keepends=True):
        text = line.strip()
        if text:
            start = offset + len(line) - len(line.lstrip())
            citations = list(dict.fromkeys(LINK.findall(text)))
            claims.append({"span": [start, start + len(text)], "text": text, "factual": None,
                           "citations": [{"url": url, "judgment": None, "notes": ""} for url in citations],
                           "notes": ""})
        offset += len(line)
    return claims


def make_labels(capture):
    cases = []
    for record in capture["records"]:
        cases.append({
            "case_id": record["case"]["id"], "evidence_sha256": fingerprint(record),
            "relevance": [{"rank": i, "url": source.get("url", ""), "judgment": None, "notes": ""}
                          for i, source in enumerate(record["sources"][:5], 1)],
            "claims": candidate_claims(record["answer"]), "claim_inventory_reviewed": False,
            "temporal": {"judgment": None, "notes": ""},
        })
    return {"schema_version": 1, "run_id": capture["run_id"], "cases": cases}


def parse_date(value, anchor):
    """Independent parser; date parseability is not date correctness/freshness."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{10}(?:\.\d+)?|\d{13}", text):
            stamp = float(text)
            result = datetime.fromtimestamp(stamp / 1000 if stamp >= 1e12 else stamp, timezone.utc)
        elif text.lower() in ("today", "今天", "刚刚", "yesterday", "昨天"):
            result = anchor - timedelta(days=int(text.lower() in ("yesterday", "昨天")))
        else:
            relative = re.fullmatch(r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?|分钟|小时|天|周|个月|年)\s*(?:ago|前)", text, re.I)
            if relative:
                unit = relative[2].lower()
                days = 1 / 1440 if unit.startswith("min") or unit == "分钟" else 1 / 24 if unit.startswith("hour") or unit == "小时" else 1
                if unit.startswith("week") or unit == "周": days = 7
                if unit.startswith("month") or unit == "个月": days = 30
                if unit.startswith("year") or unit == "年": days = 365
                result = anchor - timedelta(days=int(relative[1]) * days)
            else:
                try:
                    result = datetime.fromisoformat(text.replace("Z", "+00:00"))
                except ValueError:
                    result = parsedate_to_datetime(text)
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def percentile(values, p):
    """Linear interpolation at (n-1)*p, including n=1."""
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def timings(records, field):
    values = [record[field] for record in records if record.get(field) is not None]
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid timing")
    return {"n": len(values), "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95)}


def validate_claims(record, label):
    answer = record["answer"]
    previous_end = 0
    for claim in sorted(label["claims"], key=lambda c: c["span"][0]):
        start, end = claim["span"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(answer)
                or start < previous_end or answer[start:end] != claim["text"]):
            raise ValueError("claim必须是实采answer中不重叠的精确span/text")
        previous_end = end
        if claim["factual"] is not None and type(claim["factual"]) is not bool:
            raise ValueError("factual仅允许true/false/null")
        # A citation must actually occur in this claim, not merely in the source list.
        expected = set(LINK.findall(claim["text"]))
        urls = [entry["url"] for entry in claim["citations"]]
        if len(urls) != len(set(urls)) or set(urls) != expected:
            raise ValueError("citation必须与实采claim中的内联Markdown URL逐项匹配")
        for entry in claim["citations"]:
            if entry["judgment"] not in CITATION_VALUES:
                raise ValueError("citation judgment仅允许supported/unsupported/uncertain/null")
            if entry["judgment"] is not None and not entry.get("notes", "").strip():
                raise ValueError("citation人工判断须填写原文定位/理由notes")
    reviewed = label["claim_inventory_reviewed"]
    if type(reviewed) is not bool:
        raise ValueError("claim_inventory_reviewed必须为布尔值")
    if reviewed:
        # Prevent dropping whole paragraphs to inflate support rate; strip only whitespace.
        mask = [False] * len(answer)
        for claim in label["claims"]:
            if claim["factual"] is None:
                raise ValueError("完整性复核前须标明每项factual")
            for i in range(*claim["span"]):
                mask[i] = True
        if any(not covered and not char.isspace() for char, covered in zip(answer, mask)):
            raise ValueError("完整性复核要求claim spans覆盖回答全部非空白字符（标题等可标factual=false）")


def score_capture(capture, labels):
    if labels["run_id"] != capture["run_id"]:
        raise ValueError("labels不属于该run")
    records = capture["records"]
    by_id = {label["case_id"]: label for label in labels["cases"]}
    ids = [record["case"]["id"] for record in records]
    if len(by_id) != len(labels["cases"]) or len(set(ids)) != len(ids) or set(ids) != set(by_id):
        raise ValueError("case_id必须与实采记录一一对应且不能重复")
    results = []
    precision_complete = []
    relevant_total = judged_total = slots_total = returned_total = 0
    counts = Counter()
    date_total = date_present = date_parsed = future_dates = 0
    factual_total = uncited_total = reviewed_total = 0
    temporal_counts = Counter()
    for record in records:
        label = by_id[record["case"]["id"]]
        if label["evidence_sha256"] != fingerprint(record):
            raise ValueError("证据hash不一致，请勿混用或修改capture")
        expected = [(i, source.get("url", "")) for i, source in enumerate(record["sources"][:5], 1)]
        if [(row["rank"], row["url"]) for row in label["relevance"]] != expected:
            raise ValueError("relevance必须保持实采前5个URL及排名，不能添加/删改")
        judgments = [row["judgment"] for row in label["relevance"]]
        if any(v is not None and (type(v) is not int or v not in (0, 1)) for v in judgments):
            raise ValueError("relevance judgment仅允许0/1/null，布尔值不接受")
        n, judged = len(judgments), sum(v is not None for v in judgments)
        relevant = sum(v == 1 for v in judgments)
        complete = judged == n
        # Missing results are empty ranking slots, not unlabelled actual URLs.
        p5 = relevant / 5 if complete else None
        if p5 is not None:
            precision_complete.append(p5)
        judged_total += judged
        relevant_total += relevant
        slots_total += 5
        returned_total += n
        validate_claims(record, label)
        reviewed_total += int(label["claim_inventory_reviewed"])
        local_counts = Counter()
        factual = uncited = 0
        for claim in label["claims"]:
            if claim["factual"] is not True:
                continue
            factual += 1
            if not claim["citations"]:
                uncited += 1
            for entry in claim["citations"]:
                local_counts[entry["judgment"] or "unlabeled"] += 1
        counts.update(local_counts)
        factual_total += factual
        uncited_total += uncited
        temporal = label["temporal"]["judgment"]
        if temporal not in TEMPORAL_VALUES:
            raise ValueError("invalid temporal judgment")
        if temporal is not None and not label["temporal"].get("notes", "").strip():
            raise ValueError("时效人工判断须填写证据/理由notes")
        if temporal == "not_applicable" and record["case"]["temporal"]["kind"] != "stable_concept":
            raise ValueError("本题需要时效/历史核验，不能标not_applicable")
        temporal_counts[temporal or "unlabeled"] += 1
        anchor = datetime.fromisoformat(record["collected_at"].replace("Z", "+00:00"))
        for source in record["sources"]:
            value = source.get("published_at")
            date_total += 1
            date_present += int(value is not None and str(value).strip() != "")
            parsed = parse_date(value, anchor)
            date_parsed += int(parsed is not None)
            future_dates += int(parsed is not None and parsed > anchor + timedelta(minutes=5))
        results.append({"case_id": record["case"]["id"], "category": record["case"]["category"],
                        "precision_at_5": p5, "judged_precision": fraction(relevant, judged),
                        "returned_at_5": n, "judged_at_5": judged,
                        "judgment_coverage": fraction(judged, n),
                        "precision_at_5_bounds": [relevant / 5, (relevant + n - judged) / 5],
                        "citation_counts": dict(local_counts), "factual_claims": factual,
                        "uncited_factual_claims": uncited, "inventory_reviewed": label["claim_inventory_reviewed"],
                        "temporal": temporal, "success": successful(record)})
    supported, unsupported, uncertain, unlabeled = (counts[key] for key in ("supported", "unsupported", "uncertain", "unlabeled"))
    pairs = supported + unsupported + uncertain + unlabeled
    classified = supported + unsupported + uncertain
    decisive = supported + unsupported
    temporal_decisive = temporal_counts["correct"] + temporal_counts["incorrect"]
    return {
        "run_id": capture["run_id"], "n": len(records), "cases": results,
        "precision_at_5": {
            "macro_complete_cases_only": fraction(sum(precision_complete), len(precision_complete)),
            "complete_cases": len(precision_complete), "total_cases": len(records),
            "judged_precision_not_p5": fraction(relevant_total, judged_total),
            "judged_urls": judged_total, "returned_urls_at_5": returned_total,
            "judgment_coverage": fraction(judged_total, returned_total),
            "returned_slot_coverage": fraction(returned_total, slots_total),
            "bounds_all_cases": [fraction(relevant_total, slots_total), fraction(relevant_total + returned_total - judged_total, slots_total)]},
        "citation_support": {
            "rate_decisive_only": fraction(supported, decisive), "supported": supported,
            "unsupported": unsupported, "uncertain": uncertain, "unlabeled": unlabeled,
            "pair_denominator": pairs, "decisive_denominator": decisive,
            "human_label_coverage": fraction(classified, pairs), "decisive_coverage": fraction(decisive, pairs),
            "conservative_support_among_labeled": fraction(supported, classified),
            "inventory_reviewed_cases": reviewed_total, "total_cases": len(records),
            "factual_claims": factual_total, "uncited_factual_claims": uncited_total,
            "cited_claim_coverage": fraction(factual_total - uncited_total, factual_total)},
        "date_parseability": {"field": "sources[].published_at", "parsed": date_parsed,
                              "present": date_present, "sources": date_total,
                              "coverage": fraction(date_parsed, date_total),
                              "parsed_among_present": fraction(date_parsed, date_present),
                              "future_dates": future_dates},
        "latency_all_attempts": timings(records, "latency_ms"),
        "first_token_observed": timings(records, "first_token_ms"),
        "latency_success_only": timings([r for r in records if successful(r)], "latency_ms"),
        "success": {"count": sum(successful(r) for r in records), "attempts": len(records),
                    "rate": fraction(sum(successful(r) for r in records), len(records))},
        "temporal_manual": {"counts": dict(temporal_counts),
                            "correct_rate_decisive_only": fraction(temporal_counts["correct"], temporal_decisive),
                            "decisive_coverage": fraction(temporal_decisive, len(records))},
        "warning": "人工判断而非自动真值；未标注不是0。候选claim需人工拆分与完整性复核；小样本分位数不代表SLO。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--collect", action="store_true", help="显式授权本次请求本地服务（可能间接调用付费模型/搜索）")
    action.add_argument("--score", metavar="RUN_DIR", help="仅离线读取capture.json及labels.json，JSON评分输出到stdout")
    parser.add_argument("--case", action="append", dest="case_ids", help="实采题目ID，必须逐个指定，每次最多3题")
    parser.add_argument("--mode", choices=("fast", "agentic"), default="fast")
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--timeout", type=float, default=90, help="socket等待超时秒数（不是总耗时上限）")
    parser.add_argument("--out", help="新建run目录，必须在evaluation内，不覆盖已有目录")
    args = parser.parse_args(argv)
    if not args.collect and not args.score:
        parser.print_help()
        return 0
    try:
        if args.score:
            if args.case_ids or args.out:
                raise ValueError("--score不能同时使用--case/--out")
            directory = confined(args.score)
            capture = load_json(confined(directory / "capture.json"))
            labels = load_json(confined(directory / "labels.json"))
            print(json.dumps(score_capture(capture, labels), ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        if not args.case_ids or len(args.case_ids) > 3 or len(set(args.case_ids)) != len(args.case_ids):
            raise ValueError("--collect必须显式指定1至3个不重复--case；不支持自动全题联网")
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout必须为正有限秒数")
        cases = {case["id"]: case for case in load_json(ROOT / "cases.json")["cases"]}
        selected = [cases[case_id] for case_id in args.case_ids]
        endpoint = endpoint_url(args.base_url)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        directory = confined(args.out or ROOT / "runs" / run_id)
        directory.mkdir(parents=True, exist_ok=False)
        capture = {"schema_version": 1, "run_id": run_id, "records": []}
        # Persist each finished attempt before starting another. No retries or concurrency.
        for index, case in enumerate(selected, 1):
            record = collect_case(case, endpoint, args.mode, args.timeout)
            capture["records"].append(record)
            write_json(directory / f"attempt-{index}.json", record)
        write_json(directory / "capture.json", capture)
        write_json(directory / "labels.json", make_labels(capture))
        print(str(directory))
        return 0 if all(successful(r) for r in capture["records"]) else 1
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
