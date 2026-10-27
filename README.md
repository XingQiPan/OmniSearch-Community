# OmniSearch

多引擎聚合搜索 + AI 路由网关。把网页、学术、代码、社区、实时短贴等多个检索源并发扇出，
做跨源去重与 RRF 融合，再交给大模型产出带引用的答案。

开箱即用，绝大多数渠道免 API Key：克隆下来装好依赖就能搜。

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

### 推荐：一个 Key 接遍主流模型

本项目只汇聚检索渠道，本身不提供模型。如果你不想为 GPT、Claude、Gemini、DeepSeek
分别开户充值，可以直接接入 **[星盘中转站](https://xingpan.site)**：

- **厂商齐全**：OpenAI、Anthropic、Google Gemini、xAI、DeepSeek、Qwen、GLM、Kimi、
  MiniMax、腾讯混元等十余家，近百个模型
- **模态齐全**：文本对话、图片生成、视频生成、语音合成与识别、语义重排
- **三套原生协议**：OpenAI（`/v1/chat/completions`）、Anthropic（`/v1/messages`）、
  Gemini（`/v1beta/models`）都能直连，其余客户端按 OpenAI 兼容接入
- **国内直连**：无需代理，按量计费，分组可选（官方线路 / 企业稳定 / 优惠号池）

接入方式：

1. 在 `xingpan.site` 注册并创建 API Key
2. 打开「模型与重排 → 大模型配置」，新建一条 **OpenAI 兼容** 渠道
3. Base URL 填 `xingpan.site`，粘贴 Key，模型名照抄上游模型列表即可
4. 语义重排同理，Base URL 相同，路径走 `/v1/rerank`

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

## 许可

MIT，见 `LICENSE`。第三方依赖与其数据源各自遵循其原有许可与服务条款；
请自行确认所用渠道在你所在地区的可用性与合规性。
