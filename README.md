# OmniSearch（社区版）

多引擎聚合搜索 + AI 路由网关。把网页、学术、代码、社区、实时短贴等多个检索源并发扇出，
做跨源去重与 RRF 融合，再交给大模型产出带引用的答案。

本仓库是**社区版**：只包含公开可用的检索渠道，不包含任何需要绕过登录墙、
第三方签名、DRM 解密或版权限制流媒体的渠道。

## 能力

| 类别 | 渠道 |
| --- | --- |
| 网页 | Bing、DuckDuckGo、Wikipedia、腾讯新闻、知乎（站内收录） |
| 学术 | arXiv、OpenAlex |
| 代码 | GitHub 仓库检索、Hacker News、Stack Overflow（经搜索引擎） |
| 社区 | Reddit、Bluesky（AT Protocol，免 Key）、B站官方搜索 |
| 榜单 | 全网热榜聚合（百度 / 微博 / 知乎 / 抖音 / B站 / GitHub / V2L 等公开榜单） |
| 正文 | 链接直读正文抓取（含 SSRF 防护与编码识别） |

## 快速开始

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8088

# 前端（另开一个终端）
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173 。Windows 下也可以直接运行 `start-omnisearch.bat`。

## 模型配置

进入「模型与重排」页面，填入任意兼容 `POST /v1/chat/completions` 的端点
（OpenAI、OneAPI、NewAPI、Ollama、DeepSeek、通义千问等）。

密钥只保存在本地 SQLite 的 `api_keys` 表里，接口返回时一律掩码为 `sk-****xxxx`。
本仓库不包含任何密钥、数据库或日志文件。

## 目录结构

```
backend/app
  agents/       # 检索 Agent、证据构建、抽取式综述
  core/         # SQLite 数据层、渠道与路由组默认配置
  gateway/      # 路由、并发扇出、融合去重、时效推断、查询扩展
  platform/     # 对外 /v1/* 接口、计费与限流
  providers/    # 各检索渠道适配器
frontend/src
  pages/        # 搜索工作台、热榜、深度研究、渠道与路由配置
```

## 与商业版的差异

社区版移除了以下渠道与配套页面：
短剧聚合、网文数据看板、视频解析下载、音乐点歌、内置 SearXNG 解析内核。

移除原因分两类：
1. **合规**：涉及第三方签名、加密流解密、绕过登录态或去除水印，不适合公开分发。
2. **许可**：内置解析内核派生自 AGPL-3.0 项目的引擎实现，与本仓库的 MIT 许可不兼容。

## 许可

MIT，见 `LICENSE`。第三方依赖与其数据源各自遵循其原有许可与服务条款；
请自行确认所用渠道在你所在地区的可用性与合规性。
