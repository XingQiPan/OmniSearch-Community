import { theme as antdTheme } from 'antd';
import type { ThemeConfig } from 'antd';

export type ThemeMode = 'light' | 'dark';

const FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", ' +
  '"Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif';

const palette = {
  light: {
    bgLayout: '#fbfbfd',
    bgContainer: '#ffffff',
    bgElevated: '#ffffff',
    bgSpotlight: '#f5f5f7',
    fill: 'rgba(120,120,128,0.12)',
    text: '#1d1d1f',
    text2: '#6e6e73',
    text3: '#86868b',
    border: 'rgba(0,0,0,0.10)',
    borderSoft: 'rgba(0,0,0,0.06)',
    accent: '#0071e3',
    red: '#e02c20',
    green: '#1fa84a',
    orange: '#c76a00',
    purple: '#8e44cf',
  },
  dark: {
    bgLayout: '#000000',
    bgContainer: '#1c1c1e',
    bgElevated: '#2c2c2e',
    bgSpotlight: '#2c2c2e',
    fill: 'rgba(120,120,128,0.24)',
    text: '#f5f5f7',
    text2: '#a1a1a6',
    text3: '#8e8e93',
    border: 'rgba(255,255,255,0.14)',
    borderSoft: 'rgba(255,255,255,0.08)',
    accent: '#0a84ff',
    red: '#ff453a',
    green: '#30d158',
    orange: '#ff9f0a',
    purple: '#bf5af2',
  },
} as const;

export function buildTheme(mode: ThemeMode): ThemeConfig {
  const p = palette[mode];
  const isDark = mode === 'dark';

  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      fontFamily: FONT,
      fontSize: 14,
      fontSizeHeading1: 30,
      fontSizeHeading2: 24,
      fontSizeHeading3: 19,
      fontSizeHeading4: 16,
      fontSizeHeading5: 14,
      lineHeight: 1.5,
      colorPrimary: p.accent,
      colorInfo: p.accent,
      colorSuccess: p.green,
      colorWarning: p.orange,
      colorError: p.red,
      colorLink: p.accent,
      colorBgLayout: p.bgLayout,
      colorBgContainer: p.bgContainer,
      colorBgElevated: p.bgElevated,
      colorBgSpotlight: isDark ? '#2c2c2e' : 'rgba(29,29,31,0.92)',
      colorFillSecondary: p.fill,
      colorFillTertiary: p.fill,
      colorFillQuaternary: p.borderSoft,
      colorText: p.text,
      colorTextSecondary: p.text2,
      colorTextTertiary: p.text3,
      colorTextQuaternary: p.text3,
      colorBorder: p.border,
      colorBorderSecondary: p.borderSoft,
      colorSplit: p.borderSoft,
      borderRadius: 10,
      borderRadiusXS: 6,
      borderRadiusSM: 8,
      borderRadiusLG: 18,
      controlHeight: 36,
      controlHeightSM: 28,
      controlHeightLG: 42,
      motionDurationMid: '0.22s',
      motionEaseInOut: 'cubic-bezier(0.32, 0.72, 0, 1)',
      boxShadow: '0 2px 4px rgba(0,0,0,.03), 0 12px 32px -16px rgba(0,0,0,.18)',
      boxShadowSecondary: '0 32px 72px -32px rgba(0,0,0,.32)',
      wireframe: false,
    },
    components: {
      Button: {
        borderRadius: 10,
        borderRadiusLG: 12,
        controlHeight: 36,
        fontWeight: 500,
        primaryShadow: 'none',
        defaultShadow: 'none',
        dangerShadow: 'none',
        defaultBg: p.bgContainer,
        defaultBorderColor: p.border,
        colorText: p.text,
      },
      Card: {
        borderRadiusLG: 18,
        paddingLG: 20,
        headerHeight: 50,
        colorBorderSecondary: p.borderSoft,
        boxShadowTertiary: 'none',
      },
      Table: {
        headerBg: 'transparent',
        headerColor: p.text2,
        headerSplitColor: 'transparent',
        rowHoverBg: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.025)',
        borderColor: p.borderSoft,
        cellPaddingBlock: 12,
        cellPaddingInline: 12,
        footerBg: 'transparent',
        headerBorderRadius: 0,
      },
      Input: {
        paddingBlock: 7,
        activeShadow: isDark
          ? '0 0 0 3.5px rgba(10,132,255,.28)'
          : '0 0 0 3.5px rgba(0,113,227,.18)',
      },
      InputNumber: {
        activeShadow: isDark
          ? '0 0 0 3.5px rgba(10,132,255,.28)'
          : '0 0 0 3.5px rgba(0,113,227,.18)',
      },
      Select: {
        optionSelectedBg: isDark ? 'rgba(10,132,255,.22)' : 'rgba(0,113,227,.10)',
        optionActiveBg: p.fill,
        optionPadding: '6px 10px',
        borderRadius: 10,
      },
      Modal: {
        borderRadiusLG: 24,
        paddingContentHorizontalLG: 24,
        titleFontSize: 17,
        titleColor: p.text,
        contentBg: p.bgElevated,
        headerBg: 'transparent',
      },
      Tabs: {
        itemColor: p.text2,
        itemSelectedColor: p.text,
        itemHoverColor: p.text,
        inkBarColor: 'transparent',
        horizontalItemGutter: 4,
        titleFontSize: 13,
      },
      Segmented: {
        trackBg: p.fill,
        itemColor: p.text2,
        itemHoverColor: p.text,
        itemSelectedBg: p.bgContainer,
        itemSelectedColor: p.text,
        borderRadius: 9,
        trackPadding: 3,
      },
      Tag: {
        defaultBg: p.fill,
        defaultColor: p.text2,
        borderRadiusSM: 6,
      },
      Form: {
        labelColor: p.text2,
        labelFontSize: 12,
        verticalLabelPadding: '0 0 6px',
        itemMarginBottom: 18,
      },
      Tooltip: {
        borderRadius: 9,
        colorBgSpotlight: isDark ? '#3a3a3c' : 'rgba(29,29,31,0.92)',
        fontSize: 12,
      },
      Progress: {
        defaultColor: p.accent,
        remainingColor: p.fill,
      },
      Statistic: {
        contentFontSize: 24,
        titleFontSize: 12,
      },
      Descriptions: {
        labelBg: p.bgSpotlight,
        titleMarginBottom: 8,
      },
      Alert: {
        borderRadiusLG: 12,
      },
      Notification: {
        borderRadiusLG: 16,
      },
      Message: {
        contentBg: p.bgElevated,
        borderRadiusLG: 12,
      },
      Dropdown: {
        borderRadiusLG: 14,
        controlItemBgHover: p.fill,
      },
      Pagination: {
        itemActiveBg: p.fill,
      },
      Switch: {
        handleShadow: '0 1px 2px rgba(0,0,0,.18)',
      },
    },
  };
}
