# OmniSearch 开放 API v1 · 接入文档

> 一句话：**一个 Bearer Token，接走多源聚合搜索能力**——搜索 / 网页正文抽取 / 带引用的答案生成 / 深度研究与 Agent 自主研究 / OpenAI 兼容问答，按千次计费。

- 网关地址：`http://127.0.0.1:8088`（自建部署请替换为你的域名）
- 在线接口文档（Swagger，仅含 `/v1/*`）：`/docs/api`
- 机器可读 Schema：`/openapi-public.json`

---

## 1. 快速开始

```bash
# 1) 领取试用密钥（自助注册，送 500 次额度）
curl -s -X POST http://127.0.0.1:8088/v1/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"我的团队","email":"dev@example.com"}'

# 2) 搜索
curl -s -X POST http://127.0.0.1:8088/v1/search \
  -H "Authorization: Bearer sk-omni-你的密钥" \
  -H "Content-Type: application/json" \
  -d '{"query":"AI Agent 记忆机制","search_depth":"basic","max_results":5}'

# 3) 查看套餐与剩余额度
curl -s http://127.0.0.1:8088/v1/me -H "Authorization: Bearer sk-omni-你的密钥"
```

响应（节选）：

```json
{
  "request_id": "req_9f2c1a...",
  "object": "search",
  "query": "AI Agent 记忆机制",
  "route": "web",
  "answer": null,
  "results": [
    {
      "id": "r1",
      "title": "Agent Memory: A Survey",
      "url": "https://example.com/paper",
      "snippet": "……",
      "content": null,
      "domain": "example.com",
      "score": 1.0,
      "sources": ["bocha", "bing_web"],
      "category": "academic",
      "published_at": "2026-03-02",
      "metadata": {"source_engine": "bocha", "rrf_score": 0.0312}
    }
  ],
  "cached": false,
  "latency_ms": 1284,
  "engine_count": 4,
  "usage": {
    "units": 1,
    "unit": "request",
    "credits_used": 1,
    "unit_price_cny_per_1k": 19.0,
    "cost_cny": 0.019,
    "currency": "CNY",
    "billing_mode": "prepaid",
    "remaining_units": 499,
    "credits_remaining": 499
  }
}
```

### 1.1 由浅入深：先拿结果，再按需加工

控制台「搜索工作台」的四档模式与下面的调用一一对应。每往下一级多一步处理、多一点计费，接入时从第 1 级开始，够用就停：

| 级 | 调用 | 在上一级基础上增加 | 大模型 | 次数 | 工作台对应 |
| ---: | :--- | :--- | :---: | ---: | :--- |
| 1 | `POST /v1/search` `search_depth=basic` | 多源并发召回 · URL 去重 · RRF 融合 | — | 1 | 直接搜索 · 基础 |
| 2 | `POST /v1/search` `search_depth=advanced` | 语义重排 | — | 2 | 直接搜索 · 重排 |
| 3 | `POST /v1/search` `search_depth=deep` | Top 3 正文抽取（写入 `content`） | — | 3 | 直接搜索 · 深读 |
| 4 | `POST /v1/answer` `model=omni-fast` | 大模型带 `[n]` 引用的回答 | ✓ | 2 | 极速快答 |
| 5 | `POST /v1/research` `mode=deep` | 拆 3 个子问题并发检索 → 研究报告 | ✓ | 5 | 深度研究 |
| 6 | `POST /v1/research` `mode=agentic` | 多轮检索 · 正文精读 · 反思证据缺口 · 定向补检 | ✓ | 8 | Agent 自主 |

返回内容也是逐级变多，可按需打开：

- 第 1~3 级默认只返回 `results[]`（标题、链接、摘要、归一化 `score`、命中引擎 `sources`）；
- `include_trace=true` 追加 `trace`：路由、各引擎状态 / 耗时 / 条数、召回与去重统计（不额外计费）；
- `include_answer=true` 在搜索结果上直接附一段跨源答案；`response_format=markdown` 追加 LLM 友好的 `markdown`；
- `/v1/research` 额外返回研究过程：`plan[]`（子问题 / 各轮检索节点）、`reads[]`（正文精读）、`decisions[]`（每轮是否继续深挖）。

---

## 2. 鉴权

两种方式等价，推荐 Bearer：

```http
Authorization: Bearer sk-omni-xxxxxxxxxxxxxxxx
```

```http
X-API-Key: sk-omni-xxxxxxxxxxxxxxxx
```

要点：

| 项目 | 说明 |
| :--- | :--- |
| 密钥格式 | `sk-omni-` + 40 位十六进制；绑定「客户 + 套餐 + 授权能力」 |
| 明文仅一次 | 签发 / 轮换时返回一次，服务端只存 SHA-256 摘要 |
| 授权能力 | `search` / `extract` / `answer` / `chat`，按 Key 独立授予 |
| 可与 IP 绑定 | 支持单 IP 与 CIDR，例如 `1.2.3.4,10.0.0.0/8` |
| 有效期 | 支持设置到期时间，过期返回 `key_expired` |
| 吊销 | 立即生效；轮换会同时签发新密钥并吊销旧密钥 |

---

## 3. 请求约定

| 约定 | 内容 |
| :--- | :--- |
| Base URL | `https://你的域名/v1` |
| 传输 | HTTPS（生产必须），`Content-Type: application/json`，UTF-8 |
| 版本化 | 路径版本 `/v1`，破坏性变更发 `/v2`；增量为可选项 |
| 超时 | 建议客户端超时 ≥ 20s；`timeout_ms` 可控制网关内部预算（2s~30s） |

### 3.1 响应头

| 响应头 | 含义 |
| :--- | :--- |
| `X-Request-Id` | 本次请求唯一 ID，排障时提供此值 |
| `X-Api-Version` | 固定 `v1` |
| `X-Latency-Ms` | 网关侧端到端耗时 |
| `X-Cache` | `HIT` / `MISS`，命中语义缓存不额外计费但仍返回本次 `usage` |
| `X-Quota-Remaining` | 扣费后剩余次数 |
| `X-Quota-Used` | 本次消耗次数 |
| `X-RateLimit-Limit` | 每分钟请求上限（RPM） |
| `X-RateLimit-Remaining` | 当前分钟剩余请求数 |
| `X-RateLimit-Reset` | 限流窗口重置秒数 |
| `X-RateLimit-Day-Limit` | 每日请求上限（RPD） |
| `Retry-After` | 仅在 `429` 返回，建议重试等待秒数 |
| `Idempotent-Replayed` | 仅在幂等重放时返回 `true` |

### 3.2 成功响应信封

字段扁平（对齐 Tavily / Exa / Brave），统一包含：

```json
{
  "request_id": "req_xxx",
  "object": "search | extract | answer | account | usage | list",
  "...": "业务字段",
  "usage": { "units": 1, "cost_cny": 0.019, "remaining_units": 499 }
}
```

`usage` 字段说明：

| 字段 | 含义 |
| :--- | :--- |
| `units` / `credits_used` | 本次消耗次数（同一数值的两种命名，便于对标不同厂商） |
| `unit_price_cny_per_1k` | 当前套餐千次单价 |
| `cost_cny` | 本次折算金额（元），保留 6 位小数 |
| `remaining_units` / `credits_remaining` | 预付费账户扣费后余额；后付费账户不返回 |
| `billing_mode` | `prepaid` / `postpaid` / `internal` |

### 3.3 错误响应信封

```json
{
  "error": {
    "code": "insufficient_balance",
    "type": "billing_error",
    "message": "本次调用需要 1 次额度，当前余额 0 次，请充值",
    "param": null,
    "details": {"required_units": 1, "balance_units": 0},
    "request_id": "req_xxx",
    "docs_url": "/docs/api"
  }
}
```

---

## 4. 计费与套餐

**计费单位是「次」，套餐按「元 / 千次」定价。** 失败请求（4xx / 5xx）不计费，但会记录一条用量事件用于成功率统计。

| 能力 | 消耗次数 | 说明 |
| :--- | :--- | :--- |
| `search` + `search_depth=basic` | 1 | 多源并发召回 + 去重 + RRF 融合 |
| `search` + `search_depth=advanced` | 2 | 额外做 LLM 语义重排 |
| `search` + `search_depth=deep` | 3 | 多源 + 重排 + Top 3 正文抽取（无需再传 `include_raw_content`） |
| `extract` | 1 / 成功 URL | 单次最多 20 个 URL，失败条目不扣费 |
| `answer` + `omni-fast` | 2 | 检索 + 带引用答案 |
| `answer` + `omni-deep` | 5 | 深度检索 + 长答案 |
| `research` + `mode=deep` | 5 | 子问题拆解并发检索 + 研究报告 |
| `research` + `mode=agentic` | 8 | 多轮检索 + 正文精读 + 反思补检 + 研究报告 |
| `chat/completions` | 2 | OpenAI 兼容 |
| `me` / `usage` / `models` / `health` | 0 | 免费 |

默认套餐（可在控制台「套餐与定价」实时改价）：

| 套餐 | 千次单价 | 起充 | RPM | 每日上限 | 说明 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| 体验版 Trial | 免费 | — | 60 | 1,000 | 注册送 500 次，不含答案/深度/重排 |
| 轻量版 Starter | ¥19 | ¥100 | 60 | 3,000 | 免 Key 源为主，单价对标行业最低档 |
| 标准版 Pro | ¥35 | ¥500 | 300 | 50,000 | 含语义重排、深度研究、自定义引擎 |
| 专业版 Max | ¥59 | ¥2,000 | 600 | 200,000 | 含高级上游源、SSE、MCP（规划中）、优先队列 |
| 企业版 Enterprise | ¥45 | 年框 | 3,000 | 不限 | 独享源、SLA、后付费、私有化 |

> 余额不足返回 `402 insufficient_balance`；这是**预留值**，与行业一致（Exa / Firecrawl 均用 402 表达余额不足）。

---

## 5. 限流

- 维度：API Key 级 RPM + RPD（Key 可覆盖套餐默认值）。
- 触发返回 `429`，带 `Retry-After`、`X-RateLimit-*`。
- 建议客户端按指数退避重试：`1s → 2s → 4s`，最多 3 次。

---

## 6. 幂等（重试不重复扣费）

对 `POST /v1/search`、`POST /v1/extract` 等写操作，携带：

```http
Idempotency-Key: 3f9b7c2e-任意唯一串
```

- 10 分钟内相同 Key + 相同请求体 → 直接回放首次响应，**不重复扣费**，响应头 `Idempotent-Replayed: true`；
- 相同 Key 但请求体不同 → `409 idempotency_conflict`。

---

## 7. 错误码

| HTTP | code | type | 含义与处理建议 |
| ---: | :--- | :--- | :--- |
| 400 | `invalid_request` | invalid_request_error | 参数校验失败，`details.errors` 给出逐项原因 |
| 400 | `missing_query` | invalid_request_error | 缺少 `query`（或 `q`） |
| 400 | `invalid_url` / `too_many_urls` | invalid_request_error | 抽取 URL 非法或超过 20 个 |
| 401 | `missing_api_key` | authentication_error | 未带密钥 |
| 401 | `invalid_api_key` | authentication_error | 密钥不存在 |
| 401 | `key_revoked` / `key_expired` | authentication_error | 密钥被吊销或过期 |
| 402 | `insufficient_balance` | billing_error | 余额不足，充值后重试 |
| 403 | `account_suspended` | permission_error | 账户停用，联系商务 |
| 403 | `ip_not_allowed` | permission_error | 来源 IP 不在白名单 |
| 403 | `scope_denied` | permission_error | 该 Key 未授予此能力 |
| 403 | `feature_not_in_plan` | permission_error | 套餐未开通该能力（如重排/深度） |
| 409 | `idempotency_conflict` | invalid_request_error | 幂等键复用于不同请求体 |
| 429 | `rate_limit_exceeded` | rate_limit_error | 触发 RPM 限流，按 `Retry-After` 重试 |
| 429 | `daily_limit_exceeded` | rate_limit_error | 触发 RPD 上限 |
| 502 | `upstream_unavailable` / `search_failed` | upstream_error | 上游检索源异常，可重试 |
| 504 | `upstream_timeout` | upstream_error | 上游超时，可适当调大 `timeout_ms` 后重试 |
| 500 | `internal_error` | server_error | 请携带 `request_id` 联系支持 |

---

## 8. 接口详解

### 8.1 `POST /v1/search` — 多源聚合搜索

并发扇出多个检索源 → URL 归一化去重 → RRF 倒数排名融合 → 跨源重合提权 →（advanced / deep）语义重排 →（deep）Top 3 正文抽取。不生成回答，与工作台「直接搜索」同一内核。

#### 请求参数

| 参数 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `query` | string | 必填 | 检索词，1~2000 字符；也可用别名 `q` |
| `search_depth` | enum | `basic` | `basic` / `advanced` / `deep`；别名 `mode` |
| `topic` | enum | `general` | `general` / `news` / `academic` / `code` / `social` / `entertainment`，决定路由分组与信源池 |
| `max_results` | int | 10 | 1~50，最终受套餐上限约束（超出静默截断）；别名 `top_k` |
| `include_domains` | string[] | `[]` | 仅保留这些域名 |
| `exclude_domains` | string[] | `[]` | 排除这些域名 |
| `time_range` | string | — | `day` / `week` / `month` / `year` |
| `freshness` | string | — | Brave 风格：`pd` / `pw` / `pm` / `py`，或 `YYYY-MM-DDtoYYYY-MM-DD` |
| `start_date` / `end_date` | string | — | `YYYY-MM-DD`，按结果发布时间做尽力而为过滤（无时间的条目不误杀） |
| `include_answer` | bool \| enum | `false` | `true` / `"basic"` / `"detailed"`，返回跨源答案；需要套餐开通答案能力 |
| `include_raw_content` | bool \| enum | `false` | `true` / `"markdown"` / `"text"`，为 Top 结果抓正文写入 `content`（最多 4 条） |
| `include_images` | bool | `false` | 返回结果配图 URL |
| `include_favicon` | bool | `true` | 返回站点 favicon |
| `include_trace` | bool | `false` | 返回 `trace`：路由、各引擎状态 / 耗时 / 条数、召回与去重统计，不额外计费 |
| `response_format` | enum | `json` | `markdown` 时额外返回 `markdown` 字段（LLM 友好） |
| `country` | string | — | 国家/地区偏好，如 `CN` / `US` |
| `language` | string | — | 语言偏好，如 `zh` / `en` |
| `engines` | string[] | — | 指定引擎 ID（Pro 及以上），如 `["bocha","bing_web"]` |
| `rerank` | bool | 随深度 | 是否语义重排（需套餐开通） |
| `cache` | bool | `true` | `false` 强制绕过网关缓存 |
| `timeout_ms` | int | 按深度 | 2000~30000 |

#### 响应字段

| 字段 | 含义 |
| :--- | :--- |
| `results[].id` | 本次响应内稳定编号，可直接用于引用 |
| `results[].title` / `url` / `domain` | 基础信息 |
| `results[].snippet` | 清洗后的检索摘要（≤2000 字符） |
| `results[].content` | 正文，`search_depth=deep`（Top 3）或 `include_raw_content`（Top 4）时填充 |
| `results[].score` | **归一化到 0~1** 的相关度（原始融合分见 `metadata.rrf_score`） |
| `results[].sources` | 命中该 URL 的引擎列表，长度 >1 表示跨源重合（更可信） |
| `results[].category` | `web` / `academic` / `code` / `social` / `news` / `entertainment` |
| `results[].published_at` | 发布时间（如有） |
| `results[].metadata` | `source_engine`、`positions`（各引擎原始排名）、`rrf_score`、`rerank_score`、`evidence`（可信度拆解：检索强度 / 跨源印证 / 域名权威 / 时效）等 |
| `answer` | `include_answer` 为真时的跨源答案（带 `[n]` 引用） |
| `trace` | `include_trace` 为真时：`route`、`queries`、`raw_results`、`merged_results`、`cross_engine_hits`、`engines[]`（`id` / `name` / `status` / `latency_ms` / `result_count`） |
| `cached` | 是否命中网关缓存 |
| `route` | 实际命中的路由分组 |

`trace.engines` 只列实际参与检索的引擎，不含密钥、代理与上游原始报错。

#### GET 快速验证

```bash
curl "http://127.0.0.1:8088/v1/search?q=AI搜索&max_results=5&search_depth=basic" \
  -H "Authorization: Bearer sk-omni-xxx"
```

---

### 8.2 `POST /v1/extract` — 网页正文抽取

把任意 URL 抓成 Markdown / 纯文本，适合作为大模型上下文。

| 参数 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `urls` | string[] | 必填 | 最多 20 个（受平台配置约束） |
| `format` | enum | `markdown` | `markdown` / `text` |
| `timeout_ms` | int | 15000 | 2000~60000 |

```json
{
  "request_id": "req_xxx",
  "object": "extract",
  "results": [
    {
      "url": "https://example.com/article",
      "title": "文章标题",
      "content": "# 文章标题\n\n正文……",
      "format": "markdown",
      "length": 8421,
      "status": "success",
      "error": null,
      "published_at": "2026-03-02",
      "retrieved_at": "2026-03-05T10:31:02Z",
      "truncated": false
    }
  ],
  "success_count": 1,
  "failed_count": 0,
  "latency_ms": 1620,
  "usage": {"units": 1, "cost_cny": 0.019, "remaining_units": 498}
}
```

> 单条失败不影响整体请求；**只对 `status=success` 的 URL 计费**，失败条目返回 `units=0` 语义上的免费。建议对 `status=error` 的条目做一次重试。

---

### 8.3 `POST /v1/answer` — 带引用的答案

检索 → 组织资料 → 大模型（未配置则用内置抽取式合成）→ 返回带 `[n]` 标注的答案与引用列表。

| 参数 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `query` | string | 必填 | 问题；别名 `q` |
| `model` | enum | `omni-fast` | `omni-fast`（2 次）/ `omni-deep`（5 次）；兼容 `omni-fast-search` / `omni-deep-research` |
| `topic` | enum | `general` | 同搜索 |
| `max_results` | int | 8 | 参与合成的信源条数 |
| `stream` | bool | `false` | `true` 返回 SSE |
| `citations` | bool | `true` | 是否返回引用列表 |
| `response_format` | enum | `json` | `markdown` 时 `markdown` 字段为答案原文 |

#### SSE 流式协议

`Content-Type: text/event-stream`，事件顺序：`meta` → 多个 `delta` → `done` → `[DONE]`。

```
event: meta
data: {"request_id":"req_xxx","object":"answer.chunk","query":"...","model":"omni-fast","citations":[{"index":1,"title":"...","url":"...","domain":"..."}],"usage":{"units":2,"cost_cny":0.038,"remaining_units":480}}

event: delta
data: {"type":"delta","text":"根据检索到的资料，"}

event: done
data: {"request_id":"req_xxx","object":"answer.done","latency_ms":2140,"llm_generated":true,"citations":[...],"usage":{...}}

data: [DONE]
```

---

### 8.4 `POST /v1/research` — 深度研究 / Agent 自主研究

与控制台「搜索工作台」的「深度研究 / Agent 自主」是**同一个研究引擎**。研究通常需要 10~90 秒，推荐 `stream=true`；非流式调用请把客户端超时设到 180 秒以上。权限复用 `answer` scope，需要套餐开通深度研究。

| 参数 | 类型 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `query` | string | 必填 | 研究课题；别名 `q`。课题里带链接时会先直接读取网页正文 |
| `mode` | enum | `deep` | `deep`：拆 3 个子问题并发检索后写报告；`agentic`：多轮检索、精读正文、反思证据缺口并定向补检 |
| `topic` | enum | `general` | 同搜索 |
| `max_results` | int | 12 | 报告引用的信源条数上限（5~30） |
| `max_rounds` | int | 2 | `agentic` 最大探索轮数（1~4） |
| `reading_budget` | int | 8 | `agentic` 正文精读预算（0~12 篇，0 表示只用摘要） |
| `time_range` | string | — | 同搜索 |
| `stream` | bool | `false` | `true` 返回 SSE |
| `response_format` | enum | `json` | `markdown` 时 `markdown` 字段为报告原文 |

非流式响应：

```json
{
  "request_id": "req_xxx",
  "object": "research",
  "query": "AI Agent 记忆机制最新进展",
  "mode": "agentic",
  "route": "web",
  "answer": "## 结论\n…… [1](https://…)",
  "results": [{"id": "r1", "title": "…", "url": "…", "score": 1.0, "sources": ["bocha", "bing_web"], "...": "同 /v1/search"}],
  "plan": [{"id": "r1_1", "title": "官方资料与版本公告", "query": "…", "route": "web", "round": 1, "status": "completed", "result_count": 8, "latency_ms": 1320}],
  "reads": [{"round": 1, "title": "…", "url": "…", "domain": "…", "status": "fulltext", "chars": 6120, "truncated": false}],
  "decisions": [{"round": 1, "need_more": true, "thought": "缺少官方版本核实，继续定向检索"}],
  "pages": [],
  "suggestions": ["…"],
  "llm_generated": true,
  "data_direct": false,
  "latency_ms": 41250,
  "usage": {"units": 8, "cost_cny": 0.28, "remaining_units": 492}
}
```

`llm_generated=false` 表示报告由内置抽取式合成兜底（大模型未配置或调用失败），`data_direct=true` 表示命中榜单 / 链接直读，内容未经大模型改写。

SSE 事件顺序（`event:` 名称）：

```
meta        {request_id, object:"research.chunk", query, mode, usage}
status      {stage, message}                 # 规划 / 检索 / 精读 / 撰写等阶段提示，可多次
plan        {nodes:[...]}                    # 子问题或各轮检索节点，随进度刷新
read        {items:[...]}                    # agentic：本轮正文精读记录
decision    {round, need_more, thought}      # agentic：是否继续深挖
page        {pages:[...]}                    # 课题带链接时的网页正文
sources     {route, results:[...]}           # 融合信源，可多次推送，以最后一次为准
delta       {type:"delta", text}             # 报告增量（Markdown）
suggestions {items:[...]}
done        {request_id, object:"research.done", route, result_count, llm_generated, data_direct, latency_ms, usage}
data: [DONE]
```

流开始后若研究失败，会先推送 `error {code:"search_failed", message}` 再推送 `done`。

---

### 8.5 `POST /v1/chat/completions` — OpenAI 兼容

存量代码只改 `base_url` 与 `api_key` 即可接入 Cursor / NextChat / Open WebUI / LobeChat / Dify。

- `model`：`omni-fast`（快答）或 `omni-deep`（深度）；
- 支持 `stream: true`，返回标准 `chat.completion.chunk`；
- 非流式响应额外带 `citations[]` 与 `x_omnisearch.usage`，最后一个 chunk 的 `x_omnisearch` 同样包含用量。

```bash
curl -s http://127.0.0.1:8088/v1/chat/completions \
  -H "Authorization: Bearer sk-omni-xxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"omni-fast","messages":[{"role":"user","content":"总结今天 AI 圈大事"}]}'
```

---

### 8.6 账户与用量

| 接口 | 说明 |
| :--- | :--- |
| `GET /v1/me` | 套餐、余额、限流、Key 授权、近 30 天用量汇总 |
| `GET /v1/usage?days=30` | 按天序列 + 端点分布 + 总量（请求数、次数、金额、错误率、缓存命中率、P50/P95） |
| `GET /v1/models` | 可用模型列表（OpenAI 客户端会调用） |
| `GET /v1/health` | 健康检查，免鉴权 |

---

### 8.7 `POST /v1/signup` — 自助注册试用

| 参数 | 类型 | 说明 |
| :--- | :--- | :--- |
| `name` | string | 团队/客户名，2~80 字符 |
| `email` | string | 唯一，微信/邮箱不可重复注册 |
| `company` | string | 可选 |
| `use_case` | string | 可选，便于商务跟进 |

返回 `api_key`（仅一次）、套餐、赠送额度与三段 quickstart 命令。平台侧可关闭自助注册或设置每日名额。

---

## 9. 最佳实践

1. **由浅入深按需升级**：大多数场景 `basic` 足够；需要更稳排序用 `advanced`；要拿 Top 正文用 `deep`；要现成答案用 `/v1/answer`；要研究报告再上 `/v1/research`（见 1.1 节）。
2. **优先用 `sources` 判断可信度**：被 2 个以上引擎同时命中的 URL，通常比单源结果更可靠。
3. **`include_raw_content` 与 `/v1/extract` 二选一**：只需要 Top 2~3 正文时用 `include_raw_content`（一次请求搞定）；需要批量抓取时用 `/v1/extract`。
4. **给重试加 `Idempotency-Key`**：Agent 自动重试链路里这是防重复扣费的关键。
5. **缓存很划算**：相同 Query 命中缓存时耗时 <100ms，且不会再次调用上游（仍返回 `usage` 便于统计）。
6. **善用 `time_range` / `freshness`**：新闻、舆情类请求务必带时间过滤，否则会召回大量旧文。
7. **中文 Query 不需要翻译**：网关会并发做英文扩展检索，再与主检索结果融合。

---

## 10. 代码示例

### Python

```python
import requests

BASE = "http://127.0.0.1:8088"
KEY = "sk-omni-xxxxxxxx"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

# 搜索
resp = requests.post(f"{BASE}/v1/search", headers=HEADERS, timeout=20, json={
    "query": "多源搜索融合 RRF",
    "search_depth": "basic",
    "max_results": 5,
    "response_format": "markdown",
})
data = resp.json()
if resp.status_code != 200:
    raise RuntimeError(data["error"]["code"], data["error"]["message"])

for item in data["results"]:
    print(item["score"], item["title"], item["url"])
print("消耗", data["usage"]["units"], "次，剩余", data["usage"].get("remaining_units"))

# 流式答案
with requests.post(f"{BASE}/v1/answer", headers=HEADERS, stream=True, json={
    "query": "2026 年开源搜索框架有哪些", "model": "omni-fast", "stream": True
}) as r:
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data:") and line != "data: [DONE]":
            print(line[5:].strip()[:120])
```

### Node.js

```js
const BASE = "http://127.0.0.1:8088";
const KEY = "sk-omni-xxxxxxxx";

const resp = await fetch(`${BASE}/v1/search`, {
  method: "POST",
  headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify({ query: "AI 搜索", search_depth: "basic", max_results: 5 }),
});
const data = await resp.json();
if (!resp.ok) throw new Error(`${data.error.code}: ${data.error.message}`);
console.log(data.usage, data.results.length);
```

### OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8088/v1", api_key="sk-omni-xxxxxxxx")
resp = client.chat.completions.create(
    model="omni-fast",
    messages=[{"role": "user", "content": "总结今天 AI 圈大事"}],
)
print(resp.choices[0].message.content)
```

---

## 11. 变更记录

| 版本 | 日期 | 内容 |
| :--- | :--- | :--- |
| v1 | 2026-03 | 首发：search / extract / answer / chat.completions / me / usage / models / signup / health；Bearer 鉴权、按次计量、限流头、幂等键、结构化错误码、`/docs/api` 对外文档 |
| v1.1 | 2026-10 | 新增 `POST /v1/research`（deep / agentic，支持 SSE）；`/v1/search` 新增 `include_trace`，结果 `metadata` 增加 `evidence`；`search_depth=deep` 按计费口径自动抓取 Top 3 正文 |
