import React from 'react';

type IconProps = {
  size?: number;
  strokeWidth?: number;
  className?: string;
  style?: React.CSSProperties;
};

const Svg: React.FC<IconProps & { children: React.ReactNode }> = ({
  size = 18,
  strokeWidth = 1.6,
  className,
  style,
  children,
}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    style={style}
    aria-hidden="true"
  >
    {children}
  </svg>
);

export const IconSearch: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M16.6 16.6 21 21" />
  </Svg>
);

export const IconGrid: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="2" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="2" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="2" />
  </Svg>
);

export const IconFlame: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M12 3c3.2 3 5.5 5.6 5.5 9a5.5 5.5 0 0 1-11 0c0-2 .9-3.6 2-4.6.1 1.6.8 2.6 1.7 3 .4-3 .9-5.6 1.8-7.4Z" />
  </Svg>
);

export const IconPlay: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="3" y="4.5" width="18" height="15" rx="4" />
    <path d="M10.5 9.2 15 12l-4.5 2.8V9.2Z" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconDownload: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M12 3.5v11" />
    <path d="m7.8 10.6 4.2 4.2 4.2-4.2" />
    <path d="M4 16.5v1.2A2.8 2.8 0 0 0 6.8 20.5h10.4A2.8 2.8 0 0 0 20 17.7v-1.2" />
  </Svg>
);

export const IconBook: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 5.2A2.2 2.2 0 0 1 6.2 3H11v17H6.2A2.2 2.2 0 0 0 4 22V5.2Z" />
    <path d="M20 5.2A2.2 2.2 0 0 0 17.8 3H13v17h4.8A2.2 2.2 0 0 1 20 22V5.2Z" />
  </Svg>
);

export const IconCode: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="m8.5 8-4.2 4 4.2 4" />
    <path d="m15.5 8 4.2 4-4.2 4" />
    <path d="m13.2 5.5-2.4 13" />
  </Svg>
);

export const IconLayers: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="m12 3 8.5 4.6L12 12.2 3.5 7.6 12 3Z" />
    <path d="m3.5 12.4 8.5 4.6 8.5-4.6" />
    <path d="m3.5 16.9 8.5 4.6 8.5-4.6" />
  </Svg>
);

export const IconBot: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="4" y="8" width="16" height="12" rx="4" />
    <path d="M12 4v4" />
    <circle cx="9" cy="14" r="1" fill="currentColor" stroke="none" />
    <circle cx="15" cy="14" r="1" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconSliders: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M5 6h14M5 12h14M5 18h14" opacity=".35" />
    <circle cx="9" cy="6" r="2.1" />
    <circle cx="15" cy="12" r="2.1" />
    <circle cx="8" cy="18" r="2.1" />
  </Svg>
);

export const IconRoute: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="5.5" cy="18.5" r="2.5" />
    <circle cx="18.5" cy="5.5" r="2.5" />
    <path d="M8 18.5h5a4 4 0 0 0 4-4v-4" />
  </Svg>
);

export const IconFlask: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M9.5 3h5" />
    <path d="M10.5 3v6.2L5.4 18a2.4 2.4 0 0 0 2 3.5h9.2a2.4 2.4 0 0 0 2-3.5l-5.1-8.8V3" />
    <path d="M7.6 14.5h8.8" />
  </Svg>
);

export const IconTerminal: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="3" y="4.5" width="18" height="15" rx="3.5" />
    <path d="m7.5 10 2.6 2.4-2.6 2.4" />
    <path d="M13 15h4" />
  </Svg>
);

export const IconKey: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="4.2" />
    <path d="m11 11 9 9" />
    <path d="m15.5 15.5 2-2 2 2" />
  </Svg>
);

export const IconChart: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 4v15.5a.5.5 0 0 0 .5.5H20" />
    <path d="m7.5 15 3.5-4 3 2.5L20 7" />
  </Svg>
);

export const IconWallet: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="3" y="6" width="18" height="13" rx="3.5" />
    <path d="M3 10h18" />
    <circle cx="16.5" cy="14.5" r="1.1" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconUsers: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.4" />
    <path d="M3.5 19.5c.6-3.1 2.8-4.8 5.5-4.8s4.9 1.7 5.5 4.8" />
    <path d="M16 5.2a3.4 3.4 0 0 1 0 6.4" />
    <path d="M17.6 14.9c1.7.5 2.7 2 3 4.6" />
  </Svg>
);

export const IconCopy: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="8.5" y="8.5" width="11.5" height="12" rx="2.6" />
    <path d="M15.5 5.4A2.4 2.4 0 0 0 13.1 3H6.4A2.4 2.4 0 0 0 4 5.4v8.2a2.4 2.4 0 0 0 2.4 2.4" />
  </Svg>
);

export const IconCheck: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="m4.5 12.5 5 5 10-11" />
  </Svg>
);

export const IconRefresh: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M20 12a8 8 0 1 1-2.6-5.9" />
    <path d="M20 4v5h-5" />
  </Svg>
);

export const IconPlus: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M12 5v14M5 12h14" />
  </Svg>
);

export const IconTrash: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 7h16" />
    <path d="M9.5 7V5.4A1.9 1.9 0 0 1 11.4 3.5h1.2A1.9 1.9 0 0 1 14.5 5.4V7" />
    <path d="M6.5 7l.8 12a2.2 2.2 0 0 0 2.2 2h5a2.2 2.2 0 0 0 2.2-2l.8-12" />
  </Svg>
);

export const IconEdit: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 20h4l10.5-10.5a2.6 2.6 0 0 0-3.7-3.7L4 16.3V20Z" />
    <path d="m13.8 6.7 3.6 3.6" />
  </Svg>
);

export const IconExternal: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M13.5 4.5h6v6" />
    <path d="M19.5 4.5 11 13" />
    <path d="M18 14.5v3.2a2.3 2.3 0 0 1-2.3 2.3H6.3A2.3 2.3 0 0 1 4 17.7V8.3A2.3 2.3 0 0 1 6.3 6h3.2" />
  </Svg>
);

export const IconChevronRight: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />
  </Svg>
);

export const IconChevronDown: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="m5.5 9 6.5 6.5L18.5 9" />
  </Svg>
);

export const IconClose: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);

export const IconSun: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" />
  </Svg>
);

export const IconMoon: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M20 14.4A8.2 8.2 0 0 1 9.6 4a8.4 8.4 0 1 0 10.4 10.4Z" />
  </Svg>
);

export const IconMenu: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 7.5h16M4 12h16M4 16.5h16" />
  </Svg>
);

export const IconArrowUpRight: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M7 17 17 7" />
    <path d="M9 7h8v8" />
  </Svg>
);

export const IconClock: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Svg>
);

export const IconShield: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M12 3.2 19.5 6v6c0 4.4-3 7.4-7.5 8.8C7.5 19.4 4.5 16.4 4.5 12V6L12 3.2Z" />
    <path d="m9 12 2.2 2.2L15.4 10" />
  </Svg>
);

export const IconZap: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M13.5 2.8 5 13.6h5.4l-1 7.6 8.6-10.9h-5.5l1-7.5Z" />
  </Svg>
);

export const IconThunderbolt: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M13.5 2.8 5 13.6h5.4l-1 7.6 8.6-10.9h-5.5l1-7.5Z" />
  </Svg>
);

export const IconGlobe: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M3.6 12h16.8" />
    <path d="M12 3.4c2.4 2.4 3.6 5.3 3.6 8.6s-1.2 6.2-3.6 8.6c-2.4-2.4-3.6-5.3-3.6-8.6S9.6 5.8 12 3.4Z" />
  </Svg>
);

export const IconServer: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <rect x="3.5" y="4" width="17" height="7" rx="2.2" />
    <rect x="3.5" y="13" width="17" height="7" rx="2.2" />
    <path d="M7 7.5h.01M7 16.5h.01" />
  </Svg>
);

export const IconSparkles: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M12 3.5 13.6 9l5.4 1.6-5.4 1.6L12 17.6 10.4 12.2 5 10.6 10.4 9 12 3.5Z" />
    <path d="M18.5 15.5 19.2 18l2.3.7-2.3.7-.7 2.5-.7-2.5-2.3-.7 2.3-.7.7-2.5Z" />
  </Svg>
);

export const IconInfo: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.6" />
    <path d="M12 11v5.4" />
    <circle cx="12" cy="7.8" r="1" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconAlert: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M10.6 4.2 2.9 17.6a1.6 1.6 0 0 0 1.4 2.4h15.4a1.6 1.6 0 0 0 1.4-2.4L13.4 4.2a1.6 1.6 0 0 0-2.8 0Z" />
    <path d="M12 9.5v4" />
    <circle cx="12" cy="16.6" r=".9" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconFilter: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M4 6h16l-6.2 7.2v5.4l-3.6 1.8v-7.2L4 6Z" />
  </Svg>
);

export const IconLogout: React.FC<IconProps> = (p) => (
  <Svg {...p}>
    <path d="M10 4H6.5A2.5 2.5 0 0 0 4 6.5v11A2.5 2.5 0 0 0 6.5 20H10" />
    <path d="M9.5 12h11" />
    <path d="m17 8.5 3.5 3.5L17 15.5" />
  </Svg>
);
