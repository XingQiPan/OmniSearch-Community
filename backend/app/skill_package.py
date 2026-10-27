"""OmniSearch 开放网关 —— Skill 包生成器。

把本网关封装成可直接被 Agent（Claude Code / Cursor / Codex / 自研 Agent）加载的技能包：

    omnisearch-gateway/
      SKILL.md            # 技能说明（YAML frontmatter + 使用指引）
      skill.json          # 机器可读清单
      config.json         # 网关地址与接入 Token
      scripts/omni_search.py    # 零依赖 Python 客户端（仅标准库）
      scripts/omni_search.mjs   # 零依赖 Node 客户端（原生 fetch）
      reference.md        # 接口参数速查
      examples.md         # 典型调用示例

生成结果只依赖标准库，可在任意环境解压即用。
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Dict, List

SKILL_NAME = "omnisearch-gateway"
DEFAULT_BASE_URL = "http://127.0.0.1:8088"

__version__ = "2.0.0"

SKILL_MD_TEMPLATE = """---
name: omnisearch-gateway
description: 通过自建 OmniSearch 聚合大搜索网关检索全网 / 学术 / 代码 / 社区信息，返回已完成跨源去重与 RRF 融合排序的信源列表；支持 fast 极速聚合、deep 深度研究、agentic 多轮自主精读三种模式。当需要最新事实、多源交叉验证、论文或开源代码检索，或需要以 OpenAI 兼容方式为客户端提供联网搜索能力时使用。
---

# OmniSearch 聚合搜索网关 Skill

本技能把「{{BASE_URL}}」上的聚合搜索网关暴露给 Agent 使用。一个请求内部会并发扇出到
Bing / DuckDuckGo / Wikipedia / arXiv / OpenAlex / GitHub / Hacker News / Reddit
等多个免密引擎，并可按需叠加商业搜索与 Jina / Firecrawl 全文抓取。

## 网关地址与鉴权

- Base URL: `{{BASE_URL}}`
- 接入 Token: `{{TOKEN}}`
- 鉴权方式: 请求头 `Authorization: Bearer <token>`（本地自建网关默认放行，留空亦可）

## 三种搜索模式

| mode | 说明 | 适用场景 |
| --- | --- | --- |
| `fast` | 极速聚合，一次扇出 + RRF 融合 | 日常查证、事实核对 |
| `deep` | DAG 深度研究，多轮检索并生成综合报告 | 技术调研、竞品分析 |
| `agentic` | 多 Agent 并发检索 + 自主挑选高价值信源精读全文 + 自主判断是否继续深挖 | 复杂开放式问题 |

## 路由分组 (route_group)

`auto`（跟随网关默认智能路由）、`web`、`academic`、`code`、`social`，
也可显式指定决策方式：`rule`（关键词规则，0ms）、`jev`（TypeSafe System One 决策模型）、
`ai`（大模型判断）。

## 快速调用

### 1. 标准聚合搜索接口

```bash
curl -X POST {{BASE_URL}}/api/v1/search \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {{TOKEN}}" \\
  -d '{"query": "DeepSeek R1 推理架构", "route_group": "auto", "top_k": 10, "enable_rerank": true}'
```

返回 `results[]`（标题 / URL / 摘要 / 域名 / 来源引擎 / RRF 得分）、
`engine_traces[]`（各引擎耗时瀑布流）、`cross_engine_hits`（跨源重合数）与 `resolved_route`。

### 2. OpenAI 兼容接口（可直接填进 Cursor / NextChat / Open-WebUI / LobeChat）

```bash
curl -X POST {{BASE_URL}}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {{TOKEN}}" \\
  -d '{"model": "omni-deep-research", "messages": [{"role": "user", "content": "总结 2025 年开源 AI 搜索引擎的技术演进"}]}'
```

### 3. 脚本调用

```bash
python scripts/omni_search.py "Multi-Agent Deep Research survey 2025" --mode deep --route academic
node   scripts/omni_search.mjs "open source AI search engine metasearch" --route code
```

## 使用建议

1. 先判断信息类型再选 `route_group`：论文走 `academic`、开源实现走 `code`、舆情走 `social`，不确定就 `auto`。
2. 需要可核验结论时使用 `deep` 或 `agentic`，并对返回信源逐条核对，不要只读第一条。
3. 引用结果时保留 `url` 与 `source_engine`，便于用户回溯源。
4. `cross_engine_hits` 仅统计被多个搜索引擎返回的重合 URL 数，不表示独立信源数量，也不证明结论真实。核验结论需检查原始资料及独立来源。
"""

PY_CLIENT_TEMPLATE = '''#!/usr/bin/env python3
"""OmniSearch 聚合搜索网关 —— 零依赖 Python 客户端（仅用标准库）。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "{{BASE_URL}}"
TOKEN = "{{TOKEN}}"


def omni_search(
    query: str,
    mode: str = "fast",
    route_group: str = "auto",
    top_k: int = 10,
    enable_rerank: bool = True,
    base_url: str = BASE_URL,
    token: str = TOKEN,
    timeout: int = 90,
):
    payload = {
        "query": query,
        "mode": mode,
        "route_group": route_group,
        "top_k": top_k,
        "enable_rerank": enable_rerank,
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/search",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace"))) from e


def format_results(data) -> str:
    lines = [
        "trace_id=%s  route=%s  %d 条融合结果 / %d 条原始结果 / 跨源重合 %d / %dms"
        % (
            data.get("trace_id"),
            data.get("resolved_route"),
            data.get("total_merged_results", 0),
            data.get("total_raw_results", 0),
            data.get("cross_engine_hits", 0),
            data.get("total_latency_ms", 0),
        )
    ]
    for i, item in enumerate(data.get("results", []), 1):
        snippet = (item.get("snippet") or "").strip().replace("\\n", " ")[:160]
        lines.append(
            "%2d. [%s] %s\\n    %s\\n    score=%.4f engines=%s"
            % (
                i,
                ",".join(item.get("engines") or [item.get("source_engine", "?")]),
                item.get("title", ""),
                item.get("url", ""),
                item.get("final_score", 0.0),
                ",".join(item.get("engines") or []),
            )
        )
        if snippet:
            lines.append("    " + snippet)
    return "\\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniSearch 聚合搜索网关客户端")
    parser.add_argument("query", help="检索词")
    parser.add_argument("--mode", default="fast", choices=["fast", "deep", "agentic"])
    parser.add_argument("--route", default="auto",
                        choices=["auto", "web", "academic", "code", "social", "rule", "jev", "ai"])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    data = omni_search(
        args.query,
        mode=args.mode,
        route_group=args.route,
        top_k=args.top_k,
        enable_rerank=not args.no_rerank,
        base_url=args.base_url,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else format_results(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

JS_CLIENT_TEMPLATE = '''#!/usr/bin/env node
/**
 * OmniSearch 聚合搜索网关 —— 零依赖 Node 客户端（原生 fetch，Node >= 18）。
 */

const BASE_URL = "{{BASE_URL}}";
const TOKEN = "{{TOKEN}}";

export async function omniSearch(query, options = {}) {
  const {
    mode = "fast",
    routeGroup = "auto",
    topK = 10,
    enableRerank = true,
    baseUrl = BASE_URL,
    token = TOKEN,
    timeoutMs = 90000,
  } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${baseUrl.replace(/\\/$/, "")}/api/v1/search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        query,
        mode,
        route_group: routeGroup,
        top_k: topK,
        enable_rerank: enableRerank,
      }),
      signal: controller.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

export function formatResults(data) {
  const lines = [
    `trace_id=${data.trace_id}  route=${data.resolved_route}  ` +
      `${data.total_merged_results} 条融合结果 / ${data.total_raw_results} 条原始结果 / ` +
      `跨源重合 ${data.cross_engine_hits} / ${data.total_latency_ms}ms`,
  ];
  (data.results || []).forEach((item, i) => {
    lines.push(`${String(i + 1).padStart(2, " ")}. [${(item.engines || []).join(",")}] ${item.title}`);
    lines.push(`    ${item.url}`);
    const snippet = (item.snippet || "").replace(/\\s+/g, " ").slice(0, 160);
    if (snippet) lines.push(`    ${snippet}`);
  });
  return lines.join("\\n");
}

function parseArgs(argv) {
  const args = { query: "", mode: "fast", route: "auto", topK: 10, json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === "--mode") args.mode = argv[++i];
    else if (a === "--route") args.route = argv[++i];
    else if (a === "--top-k") args.topK = Number(argv[++i]);
    else if (a === "--json") args.json = true;
    else if (!args.query) args.query = a;
  }
  return args;
}

const invokedDirectly = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\\\/g, "/"));
if (invokedDirectly) {
  const args = parseArgs(process.argv.slice(2));
  if (!args.query) {
    console.error("用法: node omni_search.mjs \\"检索词\\" [--mode fast|deep|agentic] [--route auto|web|academic|code|social] [--top-k 10] [--json]");
    process.exit(2);
  }
  const data = await omniSearch(args.query, { mode: args.mode, routeGroup: args.route, topK: args.topK });
  console.log(args.json ? JSON.stringify(data, null, 2) : formatResults(data));
}
'''

REFERENCE_MD = """# 接口速查

Base URL: `{{BASE_URL}}`   Token: `{{TOKEN}}`

## POST /api/v1/search

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `query` | string | 必填 | 检索词 |
| `mode` | string | `fast` | `fast` / `deep` / `agentic` |
| `route_group` | string | `auto` | `auto` / `web` / `academic` / `code` / `social` / `rule` / `jev` / `ai` |
| `top_k` | int | 10 | 返回条数 |
| `enable_rerank` | bool | true | 是否启用语义重排 |
| `scrape_top_n` | int | - | 对前 N 条抓取全文 |

响应字段：

| 字段 | 说明 |
| --- | --- |
| `trace_id` | 全链路追踪 ID（可在控制台审计页查看耗时瀑布流） |
| `resolved_route` | 实际命中路由分组 |
| `results[]` | 融合后的信源：`title` / `url` / `snippet` / `content` / `domain` / `source_engine` / `engines` / `rrf_score` / `rerank_score` / `final_score` |
| `per_engine_results` | 各引擎原始结果，便于对比 |
| `engine_traces[]` | 各引擎状态 / 耗时 / 结果数 / 是否走代理 |
| `cross_engine_hits` | 被多个独立引擎同时返回的结果条数 |
| `total_latency_ms` | 端到端耗时 |

## POST /v1/chat/completions

OpenAI 兼容。`model` 可为 `omni-fast-search`、`omni-deep-research` 或任意字符串。

```json
{"model": "omni-deep-research", "messages": [{"role": "user", "content": "问题"}]}
```

## 其他可用接口

| 路径 | 说明 |
| --- | --- |
| `GET /api/v1/trending` | 全网热榜聚合 |
| `POST /api/v1/agent/stream` | Agent 多轮探索 SSE 流 |
| `GET /docs` | 完整 OpenAPI 文档 |
"""

EXAMPLES_MD = """# 典型调用示例

## 1. 事实核对（极速）

```bash
python scripts/omni_search.py "2025 年诺贝尔物理学奖得主" --route web --top-k 5
```

## 2. 论文调研（学术 + 深度）

```bash
python scripts/omni_search.py "Multi-Agent Deep Research survey 2025" --mode deep --route academic --json
```

## 3. 开源实现勘察（代码）

```bash
node scripts/omni_search.mjs "metasearch engine RRF fusion implementation" --route code
```

## 4. 作为库调用（Python）

```python
from omni_search import omni_search, format_results

data = omni_search("聚合搜索架构", mode="fast", route_group="code")
print(format_results(data))
for item in data["results"][:5]:
    print(item["title"], item["url"], item["final_score"])
```

## 5. 作为库调用（Node）

```js
import { omniSearch, formatResults } from "./scripts/omni_search.mjs";

const data = await omniSearch("DeepSeek R1 推理架构", { mode: "deep", routeGroup: "academic" });
console.log(formatResults(data));
```

## 6. 接入 IDE / 聊天客户端

在 Cursor、NextChat、Open-WebUI、LobeChat 里新增 OpenAI 兼容模型：

- Base URL: `{{BASE_URL}}/v1`
- API Key: `{{TOKEN}}`
- Model: `omni-deep-research`
"""


def _render(text: str, base_url: str, token: str) -> str:
    return text.replace("{{BASE_URL}}", base_url.rstrip("/")).replace("{{TOKEN}}", token)


def skill_manifest(base_url: str, token: str) -> Dict[str, Any]:
    return {
        "name": SKILL_NAME,
        "display_name": "OmniSearch 聚合搜索网关",
        "version": __version__,
        "entrypoints": {
            "http_search": f"{base_url.rstrip('/')}/api/v1/search",
            "openai_compatible": f"{base_url.rstrip('/')}/v1/chat/completions",
            "agent_stream": f"{base_url.rstrip('/')}/api/v1/agent/stream",
            "docs": f"{base_url.rstrip('/')}/docs",
        },
        "auth": {"type": "bearer", "header": "Authorization", "token": token or ""},
        "capabilities": [
            "web_search",
            "academic_search",
            "code_search",
            "social_search",
            "trending_boards",
            "deep_research",
            "agentic_multi_round",
            "openai_compatible_chat",
        ],
        "modes": ["fast", "deep", "agentic"],
        "route_groups": ["auto", "web", "academic", "code", "social", "rule", "jev", "ai"],
        "files": [
            "SKILL.md",
            "skill.json",
            "config.json",
            "reference.md",
            "examples.md",
            "scripts/omni_search.py",
            "scripts/omni_search.mjs",
        ],
    }


def build_skill_md(base_url: str, token: str) -> str:
    return _render(SKILL_MD_TEMPLATE, base_url, token)


def build_skill_zip(base_url: str, token: str) -> bytes:
    """打包为 zip 字节流（内存生成，不落盘）。"""
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    token = token or ""
    files: List[tuple] = [
        ("SKILL.md", build_skill_md(base_url, token)),
        ("skill.json", json.dumps(skill_manifest(base_url, token), ensure_ascii=False, indent=2)),
        (
            "config.json",
            json.dumps(
                {
                    "base_url": base_url,
                    "token": token,
                    "auth_header": "Authorization",
                    "auth_scheme": "Bearer",
                    "default_mode": "fast",
                    "default_route_group": "auto",
                    "timeout_ms": 90000,
                },
                ensure_ascii=False,
                indent=2,
            ),
        ),
        ("reference.md", _render(REFERENCE_MD, base_url, token)),
        ("examples.md", _render(EXAMPLES_MD, base_url, token)),
        ("scripts/omni_search.py", _render(PY_CLIENT_TEMPLATE, base_url, token)),
        ("scripts/omni_search.mjs", _render(JS_CLIENT_TEMPLATE, base_url, token)),
    ]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files:
            info = zipfile.ZipInfo(f"{SKILL_NAME}/{path}")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o644 << 16
            if path.endswith((".py", ".mjs")):
                info.external_attr = 0o755 << 16
            zf.writestr(info, content)
    return buf.getvalue()


def list_skill_files() -> List[Dict[str, str]]:
    return [
        {"path": "SKILL.md", "desc": "技能说明（YAML frontmatter，可被 Claude Code / Codex 直接识别）"},
        {"path": "skill.json", "desc": "机器可读清单：入口地址、鉴权、能力与模式"},
        {"path": "config.json", "desc": "网关地址与接入 Token 配置"},
        {"path": "reference.md", "desc": "接口参数速查表"},
        {"path": "examples.md", "desc": "Python / Node / curl / IDE 接入示例"},
        {"path": "scripts/omni_search.py", "desc": "零依赖 Python 客户端（仅标准库）"},
        {"path": "scripts/omni_search.mjs", "desc": "零依赖 Node 客户端（原生 fetch）"},
    ]
