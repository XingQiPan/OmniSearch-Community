# 独立搜索验收工具

仅 Python 标准库；不导入业务 app、不启动服务、不改依赖/配置/数据库。`cases.json` 包含中文、英文、最新版本、学术、历史各 2 题（共 10 题），逐题注明预期信息需求、人工 rubric 与时效/历史判定；**不提供预先编造的 URL、版本号或正确答案**。

## 执行方式

以下命令均从 `聚合大搜索引擎/backend/` 执行。`-B` 避免生成范围外的 `__pycache__`。

```console
# 仅查看说明：不发请求、不写数据
python -B -m evaluation.search_evaluation

# 一次小规模验收：只请求这一题；需使用者明确授权/自行启动本地服务后再执行
python -B -m evaluation.search_evaluation --collect --case latest-01 --out evaluation/runs/smoke-fast

# 人工编辑刚生成的 evaluation/runs/smoke-fast/labels.json 后，仅离线评分
python -B -m evaluation.search_evaluation --score evaluation/runs/smoke-fast

# 可选 agentic，小预算单轮；这是另一次显式采集，不是默认行为
python -B -m evaluation.search_evaluation --collect --case history-01 --mode agentic --out evaluation/runs/smoke-agentic

# 离线单测；不启动服务，不访问网络/LLM，不创建实采记录
python -B -m unittest discover -s tests -p test_search_evaluation.py -v
```

默认地址 `http://127.0.0.1:8088`，可用 `--base-url http://localhost:其他端口`；只接受本地回环 HTTP，禁用系统代理和 HTTP 重定向。采集动作只向本地 `POST /api/v1/agent/stream` 发请求，**但本地业务服务可能继续访问外部搜索、爬虫、LLM，可能付费**。没有 `--collect` 永不请求；不支持 `--all`；`--collect` 必须逐项给出 `--case`，每次 1–3 题，不自动重试、不并发。请勿把全部题批量联网当作默认验收。

默认 `fast`，可选 `agentic`；固定 `top_k=5`、`scrape_top_n=0`，agentic 为 `max_rounds=1`、`reading_budget=2`。历史题显式传 `time_range=all`；其余保持业务时间推断，便于发现“最新版本被时间过滤漏掉”等问题。`--timeout` 默认 90 秒，是 socket 等待超时，不是整次请求的墙钟总预算。工具不会配置服务或替用户启用任何引擎。

输入评分与输出路径均限制在 `backend/evaluation/` 内（包含符号链接解析检查）。采集目录须不存在；工具使用独占创建，不覆盖已有证据。评分报告输出 stdout，需存档可由使用者重定向至该目录内新文件。

## 证据与人工标签

每次 run 有：

- `attempt-1.json` 等：每次请求结束立即保存，包括失败尝试。
- `capture.json`：按题保存实际 request、UTC 采集时刻、HTTP 状态/头、最后一次 sources 排名、answer、latency_ms、first_token_ms、done/done_data、errors；完整解析事件保留在 `events`，SSE 原始逐行字节保留为 `raw_sse_lines_b64`。sources 原始字段和嵌套 metadata 不被裁剪/重写；中间 sources 快照在 events。HTTP 错误响应正文也以 base64 保留。
- `labels.json`：**由本次实采证据生成**，所有 judgment 默认 `null`，不代表失败或不相关。没有实采就没有真实标签模板；单测里的 `.test` URL 仅为内存测试样例，绝不是验收真值。

人工只编辑 labels，保留 capture 不变。每条标签含证据 SHA-256；评分会拒绝混用 run、修改 capture、替换/删改排名 URL、伪造 claim 文本或其引用 URL。

1. `relevance`：对实采前 5 个 URL 逐条填写整数 `0`/`1`；参照题目 information_needs、rubric 和 temporal。未检查/无法读取继续 `null` 并在 notes 解释，不以搜索摘要或域名猜真值。0/1 标签的审查依据建议写入 notes。
2. `claims`：模板仅按回答非空行提出候选，不保证每行是一个事实。人工按事实拆分为精确 `span: [start,end]`（Python 字符索引，左闭右开）与 `text`，必要时补足所有遗漏事实；标题、免责声明等可标 `factual=false`。事实标 `factual=true`，未审核留 `null`。每条 claim 的 citations 必须与该 span 内实际出现的内联 `[编号](https://...)` URL 一致。不能为无引用事实凭空补一个引用。
3. 对每个事实/引用对填写 `supported`、`unsupported` 或 `uncertain`；notes 必须给出核查原文定位、摘录或无法核验原因，证据可参照捕获的 content/snippet/metadata 或人工另行核查。抓取失败不等同不支持。只看到摘要不能证明全文支持；工具不会主动读取引用网页。
4. 完整检查并拆分后，将 `claim_inventory_reviewed=true`。此时必须为所有候选标明 factual，且 spans 覆盖回答全部非空白字符，不允许通过漏掉无引用段落提高支持率。false 时仍可看探索性评分，但不能作完整验收结论。
5. `temporal.judgment`：人工标 `correct`/`incorrect`/`uncertain`，notes 必填。只对明确稳定概念题允许 `not_applicable`。最新题以 `collected_at` 为截点，核验官方渠道、正式/预发布、LTS/Current；历史题核验事件时期，允许后来发表的历史回顾材料。不能把抓取时间当发布时间，也不能把可解析日期当正确或新鲜。

## 离线指标定义

评分不调用 LLM，也不请求 URL；人是相关性、支持关系与时效正确性的唯一裁判。

- **precision@5**：分母恒为 5；已确认相关数 / 5。返回不足 5 的空排名槽位按无命中处理，但**任何已返回 URL 未标注时，该题 p@5 为 null**，而不是将 null 当 0。聚合 `macro_complete_cases_only` 只平均完整标注题，必须连同 complete_cases/total_cases 阅读；同时输出 judged_precision（不是 p@5）、标注覆盖率、返回槽位覆盖率和全题上下界。未返回结果不是未标注 URL：零返回题 p@5=0，不能因无来源反而被排除。
- **引用支持率**：对 `factual=true` 的每项 claim/citation 对统计；同一 claim 中重复同一 URL 合并，不同 claim 独立计数。主值 `rate_decisive_only = supported / (supported+unsupported)`；uncertain 与 null 均不暗算作 unsupported。必须同时报告 supported/unsupported/uncertain/unlabeled、pair_denominator、decisive_denominator、人工标签覆盖率（含 uncertain）与决定性分母覆盖率。另报 supported/已人工分类对数的保守值、事实引用覆盖率、无引用事实数，以及 inventory_reviewed_cases。无引用事实不进入“引用对”分母，因此不能只看支持率。
- **日期可解析覆盖率**：分母为最终 sources 全部条目（含缺日期），分子为 `published_at` 可解析数；另报有值数量、有值中可解析率、超采集时刻 5 分钟的 future_dates。支持 ISO、RFC 邮件日期、秒/毫秒时间戳及常见中英相对日期（相对采集时刻，月/年近似30/365天）。不拿 retrieved_at 或 metadata 中的替代字段掩盖 published_at 缺失；这不是日期真实性、准确性或时效正确率。
- **耗时**：客户端请求开始至流结束/失败的 latency；首个非空 token 事件为 first_token，不是底层模型 token，也可能是抽取式回答。全部尝试 latency、成功尝试 latency 和观测到的 first_token 分别给出 n/p50/p95；分位数在 `(n-1)*p` 上线性插值，无观测为 null。缺首 token 不能当 0。
- **成功率**：HTTP 200、收到 done、无协议/服务/传输错误且有非空回答的尝试数 / 全部尝试数。done `{ok:false}` 或 status=error/failed 失败；EOF 无 done 失败。成功不等于答案正确或一定调用了模型；空 sources 仍可能完成回答，来源质量通过其他指标暴露。
- **时效正确性**：单独报告人工标签计数、correct/(correct+incorrect) 及其全题决定性覆盖率；uncertain/null 不自动视为错误或正确。

## 候选门槛（建议，不是已达标）

以下只用于后续人工验收讨论，**本次未联网采集，绝不表示系统已经达标**；脚本不会输出伪造的通过结论。

| 维度 | 初始候选门槛 |
| --- | --- |
| 样本与人工覆盖 | 五类均有覆盖；最终按显式小批次累计全部10题；前5实采URL标注100%，claim完整性复核100% |
| precision@5 | 全题宏平均 ≥0.80，各类平均 ≥0.60；同时说明不足5条与失败题 |
| 引用 | 决定性支持率 ≥0.90，人工标签覆盖100%，决定性覆盖 ≥0.90；事实引用覆盖 ≥0.90；不得通过忽略 uncertain 或无引用事实宣称达标 |
| 日期 | 全题 published_at 可解析覆盖 ≥0.70，最新版本题建议 ≥0.90；这是元数据门槛，不是事实正确性门槛 |
| 时效/历史 | 最新版本与历史题无已确认时间错误；相关题人工决定性覆盖100%，uncertain须复查，不算通过 |
| 成功率 | 小样本初验要求10/10协议成功；稳定性结论需以后更充分样本 |
| 性能 | 候选 fast p95 ≤30秒、first token p95 ≤15秒；agentic 单独统计，候选 p95 ≤90秒、first token p95 ≤60秒；需按部署预算再校准 |

## 局限

10题是检查工具和发现明显退化的起点，不代表无偏基准；单题/小批次 p95 基本只是最大值附近，不能代表生产 SLO。fast/agentic 不应混合比较，缓存、引擎、模型、网络、采集时刻均影响结果。请求与 sources 中含 trace/engine metadata，可辅助复现，但工具不能完整记录运行时部署设置或保证证据网页永久不变。采集保存业务流中已有正文，不额外下载网页。

claim 模板仅识别逐行候选和内联 Markdown HTTP(S) 链接；复杂嵌套括号 URL、引用式 Markdown、表格、代码段、多事实句需人工复核，不能当自动事实抽取器。人工判断仍可能有偏差；URL/span/hash 校验只防误配，不是密码学签名或防作弊。原始流全部在内存缓存，长流会增加内存及磁盘占用；若进程中断，当前未完成尝试可能没有完整记录，已保存 attempt 可供人工复核，不会自动续跑。保存证据可能包含原回答敏感信息，勿将 runs 当公共示例发布。
