import React from 'react';
import { Tabs } from 'antd';
import { IconBot, IconSliders } from '../components/icons';
import { PageHeader, Pill } from '../components/ui';
import { LlmConfigPage } from './LlmConfigPage';
import { RerankerConfigPage } from './RerankerConfigPage';

/** 把大模型与语义重排收敛到一个入口，减少侧边栏层级。 */
export const ModelSettingsPage: React.FC = () => (
  <div>
    <PageHeader
      icon={<IconBot size={21} />}
      title="模型与重排"
      tags={<Pill tone="accent">LLM / Reranker</Pill>}
      subtitle="统一管理对话模型、精排通道与默认策略。"
    />
    <Tabs
      defaultActiveKey="llm"
      style={{ marginTop: 16 }}
      items={[
        {
          key: 'llm',
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <IconBot size={14} /> 大模型配置
            </span>
          ),
          children: <LlmConfigPage embedded />,
        },
        {
          key: 'rerank',
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <IconSliders size={14} /> 语义重排
            </span>
          ),
          children: <RerankerConfigPage embedded />,
        },
      ]}
    />
  </div>
);
