import React, { useEffect, useMemo, useState } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { buildTheme, ThemeMode } from './design/theme';
import {
  IconBook,
  IconBot,
  IconClose,
  IconCode,
  IconDownload,
  IconExternal,
  IconFlask,
  IconFlame,
  IconGrid,
  IconLayers,
  IconMenu,
  IconMoon,
  IconPlay,
  IconRoute,
  IconSearch,
  IconSparkles,
  IconSun,
  IconTerminal,
} from './components/icons';
import { SearchWorkspace } from './pages/SearchWorkspace';
import { TrendingCenter } from './pages/TrendingCenter';
import { ResearchJobs } from './pages/ResearchJobs';
import { Dashboard } from './pages/Dashboard';
import { ProvidersPage } from './pages/ProvidersPage';
import { ModelSettingsPage } from './pages/ModelSettingsPage';
import { RoutingStudio } from './pages/RoutingStudio';
import { PlaygroundArena } from './pages/PlaygroundArena';
import { AuditAndGatewayPage } from './pages/AuditAndGatewayPage';
import { ApiPlatformPage } from './pages/ApiPlatformPage';

type NavItem = {
  key: string;
  label: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number }>;
  badge?: string;
};

type NavGroup = { label: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    label: '搜索',
    items: [
      { key: 'workspace', label: '搜索工作台', icon: IconSearch },
      { key: 'research', label: '深度研究', icon: IconFlask },
      { key: 'trending', label: '全网热榜', icon: IconFlame },
      { key: 'hongguo', label: '红果短剧', icon: IconPlay },
      { key: 'shortvideo', label: '视频下载', icon: IconDownload },
      { key: 'wangwen', label: '网文数据', icon: IconBook },
    ],
  },
  {
    label: '平台',
    items: [
      { key: 'api_platform', label: '开放 API 平台', icon: IconCode, badge: '售卖' },
      { key: 'audit', label: '调用日志', icon: IconTerminal },
      { key: 'dashboard', label: '态势大盘', icon: IconGrid },
      { key: 'providers', label: '渠道与密钥池', icon: IconLayers },
      { key: 'model_settings', label: '模型与重排', icon: IconBot },
      { key: 'routing', label: '路由与融合', icon: IconRoute },
      { key: 'playground', label: '多源演练场', icon: IconSparkles },
    ],
  },
];


const findPage = (key: string) => NAV.flatMap((g) => g.items.map((i) => ({ ...i, group: g.label }))).find((i) => i.key === key);

/** 旧书签兼容：两个配置页已合并。 */
const PAGE_ALIASES: Record<string, string> = { llm_config: 'model_settings', rerank_config: 'model_settings' };
const resolvePageKey = (key: string) => PAGE_ALIASES[key] || key;


const readTheme = (): ThemeMode => {
  try {
    const fromQuery = new URLSearchParams(window.location.search).get('theme');
    if (fromQuery === 'light' || fromQuery === 'dark') return fromQuery;
    const saved = localStorage.getItem('omni.theme');
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    /* ignore */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const readPage = (): string => {
  try {
    const fromHash = resolvePageKey(window.location.hash.replace(/^#\/?/, ''));
    if (fromHash && findPage(fromHash)) return fromHash;
    const saved = localStorage.getItem('omni.page');
    const savedKey = saved ? resolvePageKey(saved) : '';
    if (savedKey && findPage(savedKey)) return savedKey;
  } catch {
    /* ignore */
  }
  return 'workspace';
};

export const App: React.FC = () => {
  const [activeKey, setActiveKey] = useState<string>(readPage);
  const [themeMode, setThemeMode] = useState<ThemeMode>(readTheme);
  const [navOpen, setNavOpen] = useState(false);
  const [engine, setEngine] = useState<{ ready: number; total: number } | null>(null);
  const [providerFocus, setProviderFocus] = useState<string | undefined>();

  const theme = useMemo(() => buildTheme(themeMode), [themeMode]);
  const current = findPage(activeKey);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    try {
      localStorage.setItem('omni.theme', themeMode);
    } catch {
      /* ignore */
    }
  }, [themeMode]);

  useEffect(() => {
    try {
      localStorage.setItem('omni.page', activeKey);
      if (window.location.hash !== `#${activeKey}`) {
        window.history.replaceState(null, '', `#${activeKey}`);
      }
    } catch {
      /* ignore */
    }
    setNavOpen(false);
  }, [activeKey]);

  useEffect(() => {
    const onHash = () => {
      const next = resolvePageKey(window.location.hash.replace(/^#\/?/, ''));
      if (next && findPage(next)) setActiveKey(next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    let alive = true;
    fetch('/v1/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (alive && data) {
          setEngine({ ready: data.search_engines_ready || 0, total: data.search_engines_total || 0 });
        }
      })
      .catch(() => {
        /* 网关离线时保持静默 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const openProviderKeys = (providerId: string) => {
    setProviderFocus(providerId);
    setActiveKey('providers');
  };

  const renderPage = () => {
    switch (activeKey) {
      case 'workspace':
        return <SearchWorkspace  />;
      case 'trending':
        return <TrendingCenter  />;
      case 'research':
        return <ResearchJobs />;
      case 'dashboard':
        return <Dashboard />;
      case 'providers':
        return <ProvidersPage initialProviderId={providerFocus} onFocusConsumed={() => setProviderFocus(undefined)} />;
      case 'model_settings':
        return <ModelSettingsPage />;
      case 'routing':
        return <RoutingStudio onManageKeys={openProviderKeys} />;
      case 'playground':
        return <PlaygroundArena />;
      case 'audit':
        return <AuditAndGatewayPage onOpenPlatform={() => setActiveKey('api_platform')} />;
      case 'api_platform':
        return <ApiPlatformPage />;
      default:
        return <SearchWorkspace  />;
    }
  };

  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <div className="app">
        <aside className={`sidebar ${navOpen ? 'open' : ''}`}>
          <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
            <span className="brand-mark">
              <IconSearch size={18} strokeWidth={2} />
            </span>
            <span style={{ minWidth: 0 }}>
              <div className="brand-name">OmniSearch</div>
              <div className="brand-sub">聚合搜索 · 网关</div>
            </span>
          </a>

          <nav className="nav">
            {NAV.map((group) => (
              <div key={group.label}>
                <div className="nav-label">{group.label}</div>
                {group.items.map((item) => {
                  const ItemIcon = item.icon;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      className={`nav-item ${activeKey === item.key ? 'active' : ''}`}
                      onClick={() => setActiveKey(item.key)}
                    >
                      <ItemIcon size={17} strokeWidth={activeKey === item.key ? 2 : 1.7} />
                      <span className="truncate">{item.label}</span>
                      {item.badge ? <span className="nav-badge">{item.badge}</span> : null}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="sidebar-foot">
            <span className={`dot ${engine ? 'green' : 'orange'}`} />
            <span style={{ flex: 1 }}>{engine ? `${engine.ready}/${engine.total} 检索源在线` : '网关连接中'}</span>
            <span className="kbd">v2.1</span>
          </div>
        </aside>

        {navOpen ? <button className="scrim" type="button" aria-label="关闭导航" onClick={() => setNavOpen(false)} /> : null}

        <div className="main">
          <header className="topbar">
            <button
              className="icon-btn mobile-only"
              type="button"
              aria-label="打开导航"
              onClick={() => setNavOpen(true)}
            >
              {navOpen ? <IconClose size={17} /> : <IconMenu size={17} />}
            </button>

            <div className="crumb">
              <span>{current?.group || '控制台'}</span>
              <span className="crumb-sep">/</span>
              <strong>{current?.label || '搜索工作台'}</strong>
            </div>

            <div className="topbar-right">
              <span className="pill green" style={{ padding: '3px 10px' }}>
                <span className="dot green" style={{ boxShadow: 'none' }} />
                {engine ? `${engine.ready} 源可用` : '引擎在线'}
              </span>
              <a
                className="icon-btn"
                href="/docs/api"
                target="_blank"
                rel="noreferrer"
                title="对外开放 API 文档"
                style={{ textDecoration: 'none' }}
              >
                <IconExternal size={16} />
              </a>
              <button
                className="icon-btn"
                type="button"
                title={themeMode === 'dark' ? '切换到浅色' : '切换到深色'}
                onClick={() => setThemeMode(themeMode === 'dark' ? 'light' : 'dark')}
              >
                {themeMode === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
              </button>
            </div>
          </header>

          <main className="page" key={activeKey}>
            {renderPage()}
          </main>
        </div>
      </div>
    </ConfigProvider>
  );
};
