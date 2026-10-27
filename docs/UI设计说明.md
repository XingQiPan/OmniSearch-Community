# 控制台 UI 重构说明（Apple 风格设计系统）

> 目标：把原来的「Ant Design 默认皮肤 + 各页面自由发挥」统一成一套**克制、留白充分、层级清晰**的系统级界面，接近 macOS Sonoma / iOS 设置页的观感；同时保持全部业务逻辑不变。

---

## 一、设计原则

| 原则 | 具体做法 |
| :--- | :--- |
| 内容优先 | 去掉彩色渐变横幅、粗边框和嵌套卡片，页面只保留「标题 + 一句话说明 + 数据本体」 |
| 单色系统 | 除系统蓝 `--accent` 外，界面几乎不用高饱和色；绿/橙/红只用于状态 |
| hairline 分隔 | 用 1px 半透明描边代替阴影堆叠，卡片之间靠留白与极淡描边区分 |
| 大标题 | 页面标题 27px / 700 / 字距 -0.03em；正文 13~15px；辅助信息 11.5~12px 三级灰 |
| 系统字体 | `-apple-system, SF Pro, PingFang SC, Segoe UI …` 系统栈，不引入 Web Font |
| 克制的动效 | 页面入场 420ms、hover 160–220ms，曲线 `cubic-bezier(.32,.72,0,1)`，尊重 `prefers-reduced-motion` |
| 双主题 | 浅色近白 `#fbfbfd`，深色纯黑 `#000` + `#1c1c1e` 面板 |

---

## 二、设计令牌（`src/styles/app.css`）

| 类别 | 变量 | 浅色 | 深色 |
| :--- | :--- | :--- | :--- |
| 背景 | `--bg` | `#fbfbfd` | `#000000` |
| 面板 | `--surface` / `--surface-2` | `#ffffff` / `#f5f5f7` | `#1c1c1e` / `#2c2c2e` |
| 文字 | `--text` / `--text-2` / `--text-3` | `#1d1d1f` / `#6e6e73` / `#86868b` | `#f5f5f7` / `#a1a1a6` / `#8e8e93` |
| 描边 | `--line` / `--line-soft` | 8% / 5% 黑 | 10% / 6% 白 |
| 强调 | `--accent` | `#0071e3` | `#0a84ff` |
| 语义 | `--green` `--orange` `--red` `--purple` `--teal` | 系统色 | 系统色（提亮） |
| 圆角 | `--r-sm/md/lg/xl/pill` | 8 / 12 / 18 / 24 / 980 | 同 |
| 阴影 | `--shadow-xs/sm/md/lg` | 极淡多层 | 更深的黑色投影 |
| 焦点环 | `--ring` | 3.5px 蓝色 18% | 3.5px 蓝色 28% |

字号阶：11 / 11.5 / 12 / 12.5 / 13 / 13.5 / 14.5 / 15 / 23 / 27 / 30。

---

## 三、组件体系

### 3.1 布局与展示（`src/components/ui.tsx`）

| 组件 | 用途 |
| :--- | :--- |
| `PageHeader` | 页面头：图标 + 大标题 + 标签 + 右侧操作 + 副标题（操作与标题同行，副标题在下，移动端自动换行） |
| `Section` | 卡片容器：标题 / 副标题 / 右侧操作 / flush 表格模式 |
| `Stat` | 指标卡：标签 + 大数字 + 后缀 + 提示 + 可选 sparkline |
| `Pill` / `StatusDot` | 状态胶囊与状态点（accent/green/orange/red/purple/teal） |
| `Toolbar` | 筛选器行 |
| `SubTabs` | iOS 分段控件风格的页内切换（替代 antd Tabs） |
| `EmptyState` | 空状态 |
| `AreaChart` / `BarList` | 无依赖的轻量面积图与条形榜（替代引入图表库） |
| `CopyButton` / `CodeBlock` / `Mono` / `Kbd` | 代码与快捷键展示 |
| `KeyValue` | 两列键值信息 |

### 3.2 图标（`src/components/icons.tsx`）

40+ 个 24×24 线性图标（stroke 1.6，圆角端点），全部内联 SVG，**零依赖**、可随字体色变化。命名：`IconSearch`、`IconGrid`、`IconKey`、`IconWallet`、`IconBot`、`IconRoute`…

### 3.3 全局 CSS 类

`.card` `.card-head` `.card-body` `.grid.cols-2/3/4/6/auto` `.stat` `.pill` `.dot` `.empty` `.code-inline` `.code-block` `.toolbar` `.subtabs` `.list-row` `.icon-btn` `.hairline` `.truncate` `.num` `.tiny` `.faint` …

### 3.4 Ant Design 主题映射（`src/design/theme.ts`）

通过 `ConfigProvider` 的 token + components 覆盖，把存量组件一次性拉齐：

- 全局：字体栈、14px 基准、`borderRadius: 10`、`controlHeight: 36`、动效曲线；
- Button：去掉阴影、默认按钮走面板色；
- Table：透明表头、11.5px 灰色表头、hairline 行线、hover 极淡底色；
- Modal：24px 圆角、毛玻璃遮罩；
- Segmented：iOS 分段控件（内凹轨道 + 白色滑块）；
- Input/Select：聚焦 3.5px 蓝色 ring；
- Switch：选中态系统蓝；
- Tooltip/Popover/Dropdown：圆角 + 深色半透明。

---

## 四、布局骨架（`src/App.tsx`）

```text
┌─────────────── 264px ───────────────┬──────────────────────────────────────────┐
│ Sidebar（毛玻璃，分组导航）          │ Topbar 60px（面包屑 · 引擎状态 · 主题）   │
│ 品牌 / 产品 / 商业化 / 控制台        ├──────────────────────────────────────────┤
│ 底部：13/19 检索源在线 · v2.1        │ Page（max-width 1320，34px 边距）         │
│                                      │   PageHeader → 内容区块                   │
└──────────────────────────────────────┴──────────────────────────────────────────┘
```

- 侧边栏 `backdrop-filter: blur(28px) saturate(180%)`，选中项为白色胶囊 + 极淡阴影；
- 顶栏同样毛玻璃，常驻「N 源可用」状态、对外文档入口、明暗切换；
- 页面切换有 420ms 上浮淡入；移动端（≤900px）侧边栏变为抽屉 + 遮罩。

### 路由与深链

- 页面状态写入 `localStorage` 与 URL hash：`#api_platform`、`#providers` …可直接分享/刷新保持；
- 主题支持 `?theme=dark` 强制（便于截图与分享），否则读 `localStorage` → 系统偏好；
- 开放 API 平台支持 `?tab=plans` 直接落到某个页签。

---

## 五、响应式

| 断点 | 行为 |
| :--- | :--- |
| >1100px | 4/6 列指标卡，双栏内容，6 列海报 |
| 901–1100px | 指标卡降为 2~3 列，内容双栏 |
| ≤900px | 侧边栏抽屉；页面单列趋势；头部操作按钮换行；隐藏顶栏状态胶囊 |
| ≤620px | 所有网格单列；按钮组占满整行；标题 23px |

表格在窄屏横向滚动（`.ant-table-wrapper { overflow-x: auto }`），数字列右对齐、状态用 Pill。

---

## 六、页面改造清单

| 页面 | 改造要点 |
| :--- | :--- |
| 搜索工作台 | Spotlight 式搜索主卡、分段式模式切换、紧凑参数行、能力提示卡、状态 Pill |
| 全网热榜 | 双列榜单卡、grouped list 条目、热度仅用文字色分级、SubTabs 分类 |
| 视频解析 | 单卡片粘贴框 + pill 按钮、封面/元信息 chips、直链列表 + 复制 |
| 态势大盘 | 6 指标卡、渠道健康矩阵（隐藏停用）、路由分布、运行状态、最近调用 |
| 渠道与密钥池 | SubTabs 分类 + 健康汇总、表格化渠道、展开行密钥池 + 细进度条 |
| 大模型配置 | 默认模型摘要卡 + 分组表单（基础/密钥/代理） |
| 语义重排 | 3 个指标卡 + 首选通道 + 两阶段排序说明 + 渠道卡 |
| 路由与融合 | 命中测试、分段决策引擎、左列表右编排、勾选式引擎池 + 权重 |
| 多源演练场 | 单行查询卡、引擎 chip 网格（长名截断）、融合结果强调条 |
| 调用日志 | 迁移提示、技能包卡片、trace 瀑布流、细进度条 |
| 开放 API 平台 | 5 个页签全部重做：概览、客户与密钥、套餐定价（5 卡 + 计算器）、用量账单、接入调试 |

---

## 七、如何新增一个页面

```tsx
import { PageHeader, Section, Stat, Pill } from '../components/ui';
import { IconChart } from '../components/icons';
import { fmtNum } from '../utils/format';

export const MyPage: React.FC = () => (
  <div>
    <PageHeader
      icon={<IconChart size={21} />}
      title="我的页面"
      tags={<Pill tone="accent">新</Pill>}
      subtitle="一句话说明这个页面解决什么问题。"
      extra={<Button>操作</Button>}
    />
    <div className="grid cols-4 section-gap">
      <Stat label="指标" value={fmtNum(1234)} suffix="次" hint="口径说明" />
    </div>
    <Section title="区块标题" subtitle="补充说明" flush>
      {/* 表格 */}
    </Section>
  </div>
);
```

约定：
1. 不要在页面里硬编码颜色，只用 CSS 变量或 `Pill` 的 tone；
2. 不要 Card 套 Card；一个页面 3~6 个区块为宜；
3. 顶部必须是 `PageHeader`；表格放 `Section flush`；
4. 数字用 `fmtNum/fmtCny`，时间用 `fmtTime`，状态用 `Pill`；
5. 新增图标加在 `icons.tsx`，保持 stroke 1.6。

---

## 八、工程取舍

| 取舍 | 原因 |
| :--- | :--- |
| 不引入 Tailwind / CSS-in-JS | 项目已有 AntD，CSS 变量 + 少量类足够，构建零额外依赖 |
| 不引入图表库 | 需求只有趋势与条形榜，手写 SVG 约 100 行，避免 +300KB |
| 不引入图标库 | 40 个内联图标可控线宽与端点，风格统一且零依赖 |
| 字体用系统栈 | 不增加首屏字体下载；macOS 上即 SF Pro，Windows 上 Segoe UI / 微软雅黑 |
| 保留 AntD 组件 | 表单、表格、弹窗、日期等交互复杂，直接映射主题最稳 |
| 全局 CSS `!important` 适度使用 | 覆盖 AntD 内联样式所需，集中在一处便于维护 |

---

## 九、验证

```bash
cd frontend
npx tsc -b          # 类型检查通过
npm run build       # 生产构建通过（CSS 20KB / JS 1.37MB gzip 422KB）
```

视觉验收使用无头 Chrome 逐页截图（1600×1100 与 500×1050 两档），覆盖：浅色/深色、桌面/移动、13 个页面。关键检查点：

- 首屏无横向溢出、无卡片错位、无裸露的 AntD 默认蓝；
- 深色模式下文字对比度足够、面板层级清晰；
- 长文本（引擎名、Trace ID、URL）均有截断或换行策略；
- 所有 Switch/Tab/Tag 均已换皮，无残留默认样式。
