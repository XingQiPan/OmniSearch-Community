import React from 'react';
import { IconArrowUpRight, IconSparkles } from './icons';

/**
 * 大模型中转站推荐位。
 *
 * 网关本身只管搜索渠道，需要聊天/生图/视频模型时，用户往往卡在
 * 「去哪拿 Key」这一步。这里给出一站式接入入口，把配置成本降到最低。
 * 视觉上沿用侧栏的材质与描边，不抢主流程注意力。
 */

/** 中转站地址：单点维护，改这里即可全站生效。 */
export const RELAY_SITE_URL = 'https://xingpan.site';

/** 与下方渠道配置的 Base URL 字段同格式（不带 /v1，最终会拼 endpoints）。 */
export const RELAY_BASE_URL = 'xingpan.site';

const CAPABILITIES = [
  'GPT / Claude / Gemini',
  'DeepSeek / Qwen / GLM / Kimi',
  '生图 · 视频 · 语音 · 重排',
];

/** 侧栏底部常驻小卡：空间有限，只放一句话和入口。 */
export const RelaySpotCompact: React.FC = () => (
  <a className="relay-spot compact" href={RELAY_SITE_URL} target="_blank" rel="noreferrer noopener">
    <span className="relay-spot-icon">
      <IconSparkles size={14} />
    </span>
    <span style={{ minWidth: 0, flex: 1 }}>
      <span className="relay-spot-name">星盘中转站</span>
      <span className="relay-spot-desc">一个 Key 打通全部模型</span>
    </span>
    <IconArrowUpRight size={13} />
  </a>
);

/** 模型配置页横幅：讲清楚能解决什么问题，适合放在需要选模型的页面顶部。 */
export const RelaySpotBanner: React.FC = () => (
  <a className="relay-spot banner" href={RELAY_SITE_URL} target="_blank" rel="noreferrer noopener">
    <div className="relay-spot-main">
      <div className="relay-spot-title">
        <span className="relay-spot-icon">
          <IconSparkles size={15} />
        </span>
        还在逐个平台开 Key？一个星盘账号就够了
        <span className="pill accent outline" style={{ marginLeft: 2 }}>推荐</span>
      </div>
      <div className="relay-spot-text">
        本站只聚合搜索渠道，对话模型、语义重排与生成式模型建议直接接
        <strong className="nowrap">星盘中转站</strong>：一个 Key 同时覆盖 GPT、Claude、Gemini、
        DeepSeek 等主流家底，文本、生图、视频、语音、重排全都有，
        原生支持 OpenAI / Anthropic / Gemini 三套协议。
        在下方渠道里新建一条 <strong>OpenAI 兼容</strong> 配置，
        Base URL 填 <code>xingpan.site</code>、粘贴它生成的 Key，
        模型名照抄即可用，不用再一家家注册充值。
      </div>
      <div className="relay-spot-chips">
        {CAPABILITIES.map((item) => (
          <span key={item} className="relay-spot-chip">{item}</span>
        ))}
        <span className="relay-spot-chip accent">国内直连 · 按量计费</span>
      </div>
    </div>
    <div className="relay-spot-cta">
      <span className="relay-spot-url">{RELAY_BASE_URL}</span>
      <span className="relay-spot-go">
        免费注册试用 <IconArrowUpRight size={13} />
      </span>
    </div>
  </a>
);
