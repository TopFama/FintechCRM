// Ícones inline (SVG), sem dependências externas — mesmo estilo (stroke, 20x20).
import { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function IconDashboard(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.6" />
      <rect x="13" y="3.5" width="7.5" height="4.7" rx="1.6" />
      <rect x="13" y="10.3" width="7.5" height="10.2" rx="1.6" />
      <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.6" />
    </svg>
  );
}

export function IconPhone(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6.6 3.5h2.2l1.4 4-1.9 1.4a10.6 10.6 0 0 0 5 5l1.4-1.9 4 1.4v2.2a1.6 1.6 0 0 1-1.7 1.6A16.6 16.6 0 0 1 5 5.2a1.6 1.6 0 0 1 1.6-1.7Z" />
    </svg>
  );
}

export function IconTemplate(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5Z" />
      <path d="M7.5 9h9M7.5 12.5h9M7.5 16h5.5" />
    </svg>
  );
}

export function IconLayers(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="m12 3.5 8 4.3-8 4.3-8-4.3Z" />
      <path d="m4 12.2 8 4.3 8-4.3" />
      <path d="m4 16.5 8 4.3 8-4.3" />
    </svg>
  );
}

export function IconLogout(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 4.5H6A1.5 1.5 0 0 0 4.5 6v12A1.5 1.5 0 0 0 6 19.5h3" />
      <path d="M14.5 16 19 12l-4.5-4" />
      <path d="M19 12H9" />
    </svg>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconUpload(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 15.5V4.5M8 8.3 12 4l4 4.3" />
      <path d="M5 15.5v3A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-3" />
    </svg>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 4.5v11M8 12.2l4 4.3 4-4.3" />
      <path d="M5 15.5v3A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-3" />
    </svg>
  );
}

export function IconCheckCircle(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m8.5 12.3 2.4 2.4 4.6-4.9" />
    </svg>
  );
}

export function IconAlert(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12 4.5 3.9 18.6h16.2Z" />
      <path d="M12 10v3.4" />
      <circle cx="12" cy="16.3" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4.5 12h15M13.5 6l6 6-6 6" />
    </svg>
  );
}

export function IconBolt(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M12.5 3.5 5 13.5h5.5L11 20.5l7.5-11H13Z" />
    </svg>
  );
}

export function IconInbox(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 12.5h4.2l1.4 2.4h4.8l1.4-2.4H20" />
      <path d="M5.6 6.2 4 12.5v5A1.5 1.5 0 0 0 5.5 19h13a1.5 1.5 0 0 0 1.5-1.5v-5l-1.6-6.3A1.5 1.5 0 0 0 16.95 5H7.05a1.5 1.5 0 0 0-1.45 1.2Z" />
    </svg>
  );
}
