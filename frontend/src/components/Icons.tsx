/**
 * Inline icon set - stroke-based, 24x24, `currentColor`.
 * Inline SVG keeps icons themeable and animatable and avoids an icon-font or
 * sprite request.
 */

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 18, children, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconDashboard = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="3" width="7.5" height="8.5" rx="2" />
    <rect x="13.5" y="3" width="7.5" height="5" rx="2" />
    <rect x="13.5" y="11" width="7.5" height="10" rx="2" />
    <rect x="3" y="14.5" width="7.5" height="6.5" rx="2" />
  </Icon>
);

export const IconCamera = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7l1-2h7.6l1 2h1.7A2.5 2.5 0 0 1 21 8.5v9A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z" />
    <circle cx="12" cy="12.5" r="3.6" />
  </Icon>
);

export const IconScan = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 8V5.5A2.5 2.5 0 0 1 5.5 3H8M16 3h2.5A2.5 2.5 0 0 1 21 5.5V8M21 16v2.5a2.5 2.5 0 0 1-2.5 2.5H16M8 21H5.5A2.5 2.5 0 0 1 3 18.5V16" />
    <rect x="8" y="8" width="8" height="8" rx="1.5" />
  </Icon>
);

export const IconCube = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 2.6 21 7.4v9.2L12 21.4 3 16.6V7.4z" />
    <path d="M3 7.4 12 12l9-4.6M12 12v9.4" />
  </Icon>
);

export const IconRoute = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="5.5" cy="18.5" r="2.5" />
    <circle cx="18.5" cy="5.5" r="2.5" />
    <path d="M8 18.5h5a4 4 0 0 0 0-8H11a4 4 0 0 1 0-8h5" />
  </Icon>
);

export const IconAnalytics = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 20.5h18" />
    <rect x="4.5" y="12" width="3.6" height="6.5" rx="1.2" />
    <rect x="10.2" y="7" width="3.6" height="11.5" rx="1.2" />
    <rect x="15.9" y="3.5" width="3.6" height="15" rx="1.2" />
  </Icon>
);

export const IconDroplet = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 2.7s6.2 6.3 6.2 10.6A6.2 6.2 0 0 1 12 19.5a6.2 6.2 0 0 1-6.2-6.2C5.8 9 12 2.7 12 2.7z" />
    <path d="M9.2 13.4a2.9 2.9 0 0 0 2.9 2.9" />
  </Icon>
);

export const IconTerminal = (p: IconProps) => (
  <Icon {...p}>
    <rect x="2.8" y="4" width="18.4" height="16" rx="2.5" />
    <path d="M7 9.5 10 12l-3 2.5M12.5 15h4.5" />
  </Icon>
);

export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3.1" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.11a1.7 1.7 0 0 0-1.1-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.04H3a2 2 0 1 1 0-4h.11a1.7 1.7 0 0 0 1.56-1.1 1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9a1.7 1.7 0 0 0 1-1.56V3a2 2 0 1 1 4 0v.11a1.7 1.7 0 0 0 1.04 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9a1.7 1.7 0 0 0 1.56 1H21a2 2 0 1 1 0 4h-.11a1.7 1.7 0 0 0-1.49 1z" />
  </Icon>
);

export const IconPlay = (p: IconProps) => (
  <Icon {...p} fill="currentColor" stroke="none">
    <path d="M7.5 5.2a1 1 0 0 1 1.53-.85l9 6.8a1 1 0 0 1 0 1.7l-9 6.8a1 1 0 0 1-1.53-.85z" />
  </Icon>
);

export const IconPause = (p: IconProps) => (
  <Icon {...p} fill="currentColor" stroke="none">
    <rect x="6.5" y="5" width="4" height="14" rx="1.4" />
    <rect x="13.5" y="5" width="4" height="14" rx="1.4" />
  </Icon>
);

export const IconNext = (p: IconProps) => (
  <Icon {...p}>
    <path d="M7 5.5 14.5 12 7 18.5M17.5 5v14" />
  </Icon>
);

export const IconPrev = (p: IconProps) => (
  <Icon {...p}>
    <path d="M17 5.5 9.5 12 17 18.5M6.5 5v14" />
  </Icon>
);

export const IconRestart = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
    <path d="M3.2 4.2v5h5" />
  </Icon>
);

export const IconPower = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3.5v8" />
    <path d="M18 6.4a8.5 8.5 0 1 1-12 0" />
  </Icon>
);

export const IconSparkle = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
    <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />
  </Icon>
);

export const IconShuffle = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3.5 6.5h3.2c1.4 0 2.7.7 3.4 1.9l3.8 6.2a4 4 0 0 0 3.4 1.9h3.2" />
    <path d="M3.5 17.5h3.2a4 4 0 0 0 3.4-1.9l.7-1.2M14.2 9.6l.7-1.2a4 4 0 0 1 3.4-1.9h3.2" />
    <path d="M18.5 3.8 21.5 6.5l-3 2.7M18.5 13.8l3 2.7-3 2.7" />
  </Icon>
);

export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
  </Icon>
);

export const IconAlert = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3.8 21.2 19.4H2.8z" />
    <path d="M12 9.8v4.4M12 17.2h.01" />
  </Icon>
);

export const IconInfo = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5M12 7.8h.01" />
  </Icon>
);

export const IconSun = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
  </Icon>
);

export const IconMoon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20.5 14.4A8.5 8.5 0 1 1 9.6 3.5a6.9 6.9 0 0 0 10.9 10.9z" />
  </Icon>
);

export const IconMenu = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h11" />
  </Icon>
);

export const IconTrash = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 6.5h16M9.5 6.5V4.8a1.3 1.3 0 0 1 1.3-1.3h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
    <path d="M6.5 6.5 7.4 19a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5l.9-12.5" />
  </Icon>
);

export const IconSave = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4.5 5.8A1.8 1.8 0 0 1 6.3 4h9.3L20 8.4v9.8a1.8 1.8 0 0 1-1.8 1.8H6.3a1.8 1.8 0 0 1-1.8-1.8z" />
    <path d="M8 4v5h7M8 20v-5.5h8V20" />
  </Icon>
);

export const IconTarget = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
  </Icon>
);

export const IconChip = (p: IconProps) => (
  <Icon {...p}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
    <path d="M10 2.8v3.7M14 2.8v3.7M10 17.5v3.7M14 17.5v3.7M2.8 10h3.7M2.8 14h3.7M17.5 10h3.7M17.5 14h3.7" />
  </Icon>
);
