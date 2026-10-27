# 搜索服务对外开放 API · 设计说明（v1）

> 目标：把现有的「OmniSearch 聚合网关」从**内部工具**升级为**可售卖的搜索服务**。
> 卖出的是检索技术本身，计价方式为 **元 / 千次**。本文说明「为什么这么设计」以及「落地了什么」。

---

## 一、改造前的问题清单（为什么说接口很简陋）

对 `backend/app/main.py` 做了一次审计，售卖前的硬伤：

| # | 问题 | 影响 |
| --- | --- | --- |
| 1 | `/api/v1/search`、`/v1/chat/completions` **完全无鉴权** | 任何人可白嫖，无法计费 |
| 2 | `gateway_tokens` 表存在但**从未被任何中间件校验** | 密钥只是摆设 |
| 3 | 响应体直接泄露内部结构（`engine_traces`、`per_engine_results`、`trace_id`） | 客户看不懂，且暴露上游渠道 |
| 4 | 没有 `usage` / 余额 / 单价 | 无法对账、无法开票 |
| 5 | 没有限流，也没有 `X-RateLimit-*` / `Retry-After` | 一个客户能打垮全站 |
| 6 | 错误直接抛 `HTTPException`，形状是 `{"detail": "..."}` | 客户 SDK 无法按 code 分支处理 |
| 7 | 没有套餐、没有配额、没有充值、没有账单 | 商业闭环缺失 |
| 8 | 没有 `/extract`、没有 `/answer`、没有文档 | 相比 Tavily / 博查，能力面太窄 |
| 9 | 参数是内部命名（`top_k`、`route_group`、`enable_rrf`） | 迁移成本高，客户不想学 |
| 10 | 没有幂等、没有缓存语义、没有版本化 | Agent 重试会重复扣费 |

---

## 二、主流对标：行业共识长什么样

调研了 Tavily / Exa / Serper / Brave / 博查 / Perplexity / Jina / Firecrawl（详见 `搜索API商业化调研报告.md`），提炼出 10 条共识，并逐条落到本项目的设计里：

| 维度 | 行业做法 | 本项目落地 |
| :--- | :--- | :--- |
| 鉴权 | 6/8 用 `Authorization: Bearer`（Exa 双支持），Serper 用 `X-API-KEY` | `Bearer sk-omni-xxx`，兼容 `X-API-Key` |
| 响应信封 | 扁平（Tavily/Exa/Brave）与包裹（Firecrawl/博查）两派 | 选扁平 + 统一 `request_id` / `usage`，学习成本最低 |
| 计量 | Tavily `credits`、Firecrawl `creditsUsed`、Exa `costDollars` | `usage.units` + `credits_used` / `credits_remaining` 双命名 |
| 错误码 | 400/401/402/403/429/5xx，**402 = 余额不足** | 完全对齐，并细分 `feature_not_in_plan`、`daily_limit_exceeded` |
| 限流 | `X-RateLimit-Limit/Remaining/Reset` + `Retry-After` | 全部返回，Key 级可覆盖套餐级 |
| 参数命名 | `query` / `max_results` / `search_depth` / `time_range` / `include_domains` | 主用主流命名，同时兼容 `q` / `top_k` / `mode` / `freshness` 别名 |
| 幂等 | 搜索类普遍缺失 | `Idempotency-Key` + 10 分钟窗口，重试不重复扣费 |
| 版本化 | 路径 `/v1` 为主 | 路径版本 + `/docs/api` 只暴露 v1 |
| 流式 | `text/event-stream` + `[DONE]` 收尾 | `/v1/answer` 与 `/v1/chat/completions` 均支持 SSE |
| OpenAI 兼容 | Perplexity / Brave Answers 已验证 | `/v1/chat/completions`，改 `base_url` 即接入 |

差异化卖点（相对单源 API）：**多源并发召回、跨源去重、RRF 融合、中文优化、免 Key 源兜底、OpenAI 兼容、结果可溯源、search+extract 一体**。

---

## 三、关键设计决策

### 1. 双层 API：内部 `/api/*`，对外 `/v1/*`

- `/api/*` 是控制台自用接口（无鉴权，假定部署在内网）；
- `/v1/*` 是**唯一对公网暴露的付费面**，强制鉴权、强制计量。

这样既不动现有前端，又能让售卖面保持干净。**生产部署必须只对外暴露 `/v1/*`**（见第七节）。

### 2. 余额用「次数」而不是「金额」

套餐价是「元/千次」，但每次调用消耗的是整数 `units`：

```
cost_cny = units × price_per_1k_cny / 1000
```

好处：扣费是整数运算、不会漂移；客户看到的是「还剩 8,742 次」，比「还剩 ¥166.098」直观；改价不影响历史账单。

### 3. 按能力分级计价，而不是一刀切

| 能力 | 次数 | 理由 |
| :--- | ---: | :--- |
| basic 搜索 | 1 | 走免 Key 源为主，边际成本≈0 |
| advanced 搜索 | 2 | 叠加 LLM 语义重排，有真实 token 成本 |
| deep 搜索 | 3 | 多源 + 重排 + 正文抽取 |
| extract | 1 / URL | 上游 Jina / 抓取有成本 |
| answer fast / deep | 2 / 5 | 绑定大模型 token 成本 |

这直接对应竞品做法：Tavily basic=1 / advanced=2 credits。

### 4. 失败不计费，但**一定留痕**

计量在 HTTP 中间件里做，而不是写在每个 endpoint：

- 成功（2xx）→ 扣 `units`、写 `platform_usage_events`；
- 失败（4xx/5xx）→ `units=0`，但依然写一条事件（带 `error_code`、`http_status`）。

好处：账单干净（失败不扣钱），大盘又看得见真实失败率与 P95。**并且任何绕过 endpoint 的新路由也自动被兜住。**

### 5. 余额校验后置到端点

鉴权依赖只做「身份 + 权限 + 限流」，**余额校验放到拿到本次精确定价之后**。
否则一个余额为 0 的客户传错参数，会先收到 `402` 而不是 `400`，排障体验很差。

### 6. 套餐能力开关 + 明确的升级提示

`allow_rerank` / `allow_extract` / `allow_answer` / `allow_deep` 是套餐字段，未开通时返回：

```json
{"error": {"code": "feature_not_in_plan", "message": "当前「轻量版 Starter」套餐未开通语义重排 Rerank，请升级套餐后重试"}}
```

这既是权限控制，也是**销售引导**。

### 7. 明文密钥只出现一次

- 存储：`SHA-256(key)` + 掩码 `sk-omni-xxxxxxxx...abcd`；
- 签发 / 轮换时的响应里返回明文；
- 数据库泄露也拿不到可用密钥。

### 8. 幂等键绑定「客户 + 键 + 请求体摘要」

```text
同一客户 + 同一 Idempotency-Key + 同一请求体 → 回放首次响应，不扣费
同一客户 + 同一 Idempotency-Key + 不同请求体 → 409 idempotency_conflict
```

这正好覆盖 Agent「超时重试」的高频场景。

---

## 四、架构与数据模型

```text
client
  │  Authorization: Bearer sk-omni-xxx
  ▼
┌──────────────────────────────────────────────────────────────┐
│ api_gateway_middleware  (/v1/*)                              │
│  · 生成 request_id (req_xxx)                                  │
│  · 计时 / 异常兜底 / X-Request-Id / X-Cache / X-Latency       │
│  · 成功调用 → 扣费 + 写 platform_usage_events                 │
└─────────────────────────────┬────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ require_auth  (app/platform/auth.py)                         │
│  密钥摘要查库 → 套餐 → 状态/过期/IP 白名单 → RPM/RPD 限流      │
└─────────────────────────────┬────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ router_public (app/platform/router_public.py)                │
│  /v1/search  /v1/extract  /v1/answer  /v1/chat/completions    │
│  /v1/me  /v1/usage  /v1/models  /v1/signup  /v1/health        │
└─────────────────────────────┬────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│ 既有引擎（零改动复用）                                        │
│  dispatcher.dispatch_unified_search  → 并发扇出 + 去重 + RRF  │
│  providers / key_pool / reranker / jina reader               │
└──────────────────────────────────────────────────────────────┘
```

新增数据表（全部在同一个 SQLite `gateway.db`，启动时 `init_platform_db()` 自动建表并补种子）：

| 表 | 作用 |
| :--- | :--- |
| `platform_plans` | 套餐：千次单价、起充、RPM/RPD、能力开关、卖点 |
| `platform_clients` | 客户：套餐、余额（次数）、计费模式、状态、来源 |
| `platform_api_keys` | 密钥：摘要、掩码、授权能力、IP 白名单、过期、累计消耗 |
| `platform_usage_events` | 每次调用的用量事件：request_id、端点、units、金额、状态、延迟、缓存 |
| `platform_topups` | 充值流水：金额、到账次数、操作人 → 营收口径 |
| `platform_idempotency` | 幂等回放缓存（24h 清理） |
| `platform_settings` | 计量单位、自助注册开关等运行时配置 |

---

## 五、计量与定价

### 5.1 成本模型（决定定价红线）

调研给出的成本假设，可直接用于审查每一次改价：

| 上游 | 占比 | 单价（¥/千次） | 加权 |
| :--- | ---: | ---: | ---: |
| 自建免 Key 源（Bing/DDG/中文站内检索） | 60% | ≈1.5 | 0.9 |
| 博查 | 25% | 36 | 9.0 |
| Tavily basic | 10% | 57 | 5.7 |
| Exa / 高级源 | 5% | ≈110 | 5.5 |
| **合计** | | | **≈21.1** |

按 30% 缓存命中折算后上游成本 ≈ **¥15 / 千次**。

> **红线**：轻量档若把高级源全量透传，单价 ¥19 会立刻亏损。必须靠「意图路由 + 免 Key 源承接约 80% 流量 + 缓存」把成本压住。

### 5.2 在售套餐（默认值，控制台可实时改）

| 套餐 | ¥/千次 | 起充 | RPM | RPD | 能力 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| 体验版 Trial | 0 | — | 60 | 1,000 | 搜索 / 抽取，注册送 500 次 |
| 轻量版 Starter | 19 | ¥100 | 60 | 3,000 | + 答案生成 + SSE |
| 标准版 Pro | 35 | ¥500 | 300 | 50,000 | + 语义重排 + 深度研究 + 自定义引擎 |
| 专业版 Max | 59 | ¥2,000 | 600 | 200,000 | + 高级上游源 + 优先队列 |
| 企业版 Enterprise | 45 | 年框 | 3,000 | 不限 | 独享源 / SLA / 后付费 / 私有化 |

对标结论：同价位打博查（¥35 vs ¥36）但多出多源融合与 Markdown；比 Tavily / Brave 便宜约 35~40%；人民币结算，无需外币卡与代理。

---

## 六、运营闭环

```text
① 获客：POST /v1/signup 自助领 500 次
        └─ 或控制台「客户与密钥」手动新建 + 签发密钥
② 转化：用量页看到「余额不足 / 能力未开通」→ 引导升级套餐
③ 充值：控制台按 ¥ 或按「次」入账（两者都填以次数为准，便于人工赠送）
④ 使用：每次调用回传 usage + X-Quota-Remaining，客户可自建余额告警
⑤ 对账：月度账单按客户汇总 requests / units / 金额，支持 CSV 导出
⑥ 风控：单 Key 吊销 / 轮换、IP 白名单、RPM/RPD、账户停用
```

控制台页面（`/api-platform` 菜单：**开放 API 平台（商业化）**）包含 5 个页签：

1. **商业化概览**：窗口期营收、扣费消耗、付费客户数、调用量、P95、失败率/缓存命中、每日趋势、接口分布、Top 客户、上游源风险；
2. **客户与密钥**：新建客户、充值、签发/轮换/吊销密钥（明文仅弹窗一次）、客户详情；
3. **套餐与定价**：卡片式定价 + 编辑、**月调用量成本计算器**；
4. **用量与账单**：调用明细（可按客户/端点/状态/时间筛选）、月度账单、CSV 导出；
5. **接入文档与调试**：接口目录、错误码表、curl/Python/Node/OpenAI SDK 示例、**在线调试器**（真实调用、真实扣费）。

---

## 七、安全与部署

### 7.1 只对公网暴露 `/v1/*`

`/api/*` 是控制台接口（无鉴权），必须留在内网或加一层 Basic Auth。nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    # 对外只放行付费 API 与对外文档
    location /v1/          { proxy_pass http://127.0.0.1:8088; proxy_read_timeout 60s; }
    location = /docs/api   { proxy_pass http://127.0.0.1:8088; }
    location = /openapi-public.json { proxy_pass http://127.0.0.1:8088; }

    # 内部接口一律拒绝公网访问
    location /api/  { deny all; }
    location /      { deny all; }
}
```

### 7.2 其他建议

| 风险 | 措施 |
| :--- | :--- |
| 密钥泄露 | 定期轮换；给每个应用单独发 Key；绑定 IP 白名单 |
| 盗刷 | 套餐 RPM/RPD + 余额上限 + 余额告警 |
| 上游封禁 | 免 Key 源只做兜底，商业源做主力，路由权重可调 |
| 多实例 | 现在限流是进程内滑动窗口；多实例时把 `ratelimit.py` 换成 Redis ZSET 实现 |
| 审计 | `platform_usage_events` 保留 request_id / query / 错误码，可回溯单次调用 |

---

## 八、已验证内容

新增 `backend/tests/test_public_api.py`（21 项，全部离线、内存 SQLite）：

- 无密钥 / 错误密钥 / 已吊销密钥 → 结构化 401；
- 搜索扣 1 次、`advanced` 扣 2 次、余额不足返回 402；
- 套餐能力门禁（轻量版用重排 → 403 `feature_not_in_plan`）；
- 抽取按 URL 计费；非法 URL 400；
- 幂等重放不重复扣费；
- 参数校验 400 + `details.errors`；
- `markdown` 输出、答案引用、`/v1/me`、`/v1/models`、`/v1/health`；
- 充值 → 账单汇总 → 月度对账；
- 自助注册发放 500 次试用；
- 管理端营收大盘与接口/错误码目录。

执行：

```bash
cd backend
python -m unittest discover -s tests -p "test_*.py"      # 85 项，全绿
```

前端：`cd frontend && npm run build` 通过（tsc + vite）。

---

## 九、后续路线（按售卖优先级）

| 优先级 | 事项 | 价值 |
| :--- | :--- | :--- |
| P0 | MCP 端点（`/mcp`，暴露 `search` / `extract` 工具） | Claude / Cursor 一行配置接入，目前只有 Tavily / 博查 / Exa 有 |
| P0 | 客户自助门户（登录、充值、余额、发票下载） | 减少人工商务成本 |
| P1 | 余额/失败率告警（邮件 / 飞书 Webhook） | 降低投诉与流失 |
| P1 | 分页 `cursor`、`page` 透传 | 深度检索场景 |
| P1 | Redis 限流 + 多实例部署 | 横向扩容 |
| P2 | 发票与对公转账流程、合同模板 | 企业客户必需 |
| P2 | Python / Node SDK 与 Postman 集合 | 降低接入摩擦 |
| P2 | 计费单位在线调整（`platform_settings.units`）已支持，补 UI | 运营自助调价 |

---

## 十、改动文件索引

| 文件 | 说明 |
| :--- | :--- |
| `backend/app/platform/store.py` | 建表 + 种子 + 套餐/客户/密钥/用量/充值/幂等 CRUD 与聚合 |
| `backend/app/platform/errors.py` | 错误码目录、`ApiError`、统一异常处理（`/api/*` 保持旧形状） |
| `backend/app/platform/auth.py` | Bearer 解析、套餐校验、IP 白名单、RPM/RPD 限流、`ensure_scope` / `ensure_balance` |
| `backend/app/platform/ratelimit.py` | 线程安全滑动窗口限流器 |
| `backend/app/platform/metering.py` | 次数折算、`usage` 构造、套餐能力门禁 |
| `backend/app/platform/schemas.py` | 对外请求/响应 Pydantic 模型（即 OpenAPI 文档） |
| `backend/app/platform/router_public.py` | `/v1/*` 全部对外接口（含 SSE） |
| `backend/app/platform/router_admin.py` | `/api/admin/platform/*` 管理端接口 |
| `backend/app/platform/middleware.py` | request_id、限流头、计量落库、5xx 兜底 |
| `backend/app/main.py` | 注册路由/中间件/错误处理、`/docs/api` 与 `/openapi-public.json` |
| `backend/app/schemas.py` / `backend/app/gateway/dispatcher.py` | 新增 `use_cache`，支持 `cache=false` 绕过缓存 |
| `backend/tests/test_public_api.py` | 21 项离线回归测试 |
| `frontend/src/pages/api-platform/*` | 商业化控制台（概览 / 客户密钥 / 套餐定价 / 用量账单 / 接入调试，5 个页签） |
| `frontend/src/App.tsx` | 新的应用外壳：毛玻璃侧边栏、顶栏、明暗切换、hash 深链 |
| `frontend/src/styles/app.css` | 设计系统：令牌、卡片、Pill、表格、AntD 换肤、响应式 |
| `frontend/src/design/theme.ts` | AntD 主题映射（浅色/深色） |
| `frontend/src/components/ui.tsx` / `icons.tsx` | 组件原语与 40+ 内联线性图标 |
| `docs/UI设计说明.md` | Apple 风格 UI 的设计原则、令牌、组件与扩展指南 |
| `docs/API.md` | 面向客户的接入文档 |
| `docs/API平台设计说明.md` | 本文 |
| `搜索API商业化调研报告.md` | 主流产品对标与定价行情 |
