// Inline SVG icons (Lucide-style, 1.75 stroke) — no emoji as UI icons.
// One consistent visual language: 24px grid, currentColor, round joins.

type IconProps = React.SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };
}

export function Sparkle(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 3l1.9 4.9L18.8 10l-4.9 1.9L12 16.8 10.1 11.9 5.2 10l4.9-2.1L12 3z" />
      <path d="M19 15l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7L19 15z" />
    </svg>
  );
}

export function ArrowRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </svg>
  );
}

export function ThumbUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z" />
      <path d="M7 11l4-7a2.5 2.5 0 0 1 2.5 2.5V9h4.5a2 2 0 0 1 2 2.3l-1.1 6A2 2 0 0 1 17.9 19H7" />
    </svg>
  );
}

export function ThumbDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M17 13V4h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3z" />
      <path d="M17 13l-4 7a2.5 2.5 0 0 1-2.5-2.5V15H6a2 2 0 0 1-2-2.3l1.1-6A2 2 0 0 1 7.1 5H17" />
    </svg>
  );
}

export function Star(props: IconProps) {
  return (
    <svg {...base(props)} fill="currentColor" stroke="none">
      <path d="M12 3.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 17.9 6.7 19.6l1-5.8L3.5 9.7l5.9-.9L12 3.5z" />
    </svg>
  );
}

export function External(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 5h5v5" />
      <path d="M19 5l-8 8" />
      <path d="M19 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4.5" />
    </svg>
  );
}

export function Controller(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 9h10a4 4 0 0 1 4 4v.5a3.5 3.5 0 0 1-6.4 2L14 15h-4l-.6.5a3.5 3.5 0 0 1-6.4-2V13a4 4 0 0 1 4-4z" />
      <path d="M7.5 12v2M6.5 13h2M15.5 12.5h.01M17.5 14h.01" />
    </svg>
  );
}

export function Spinner(props: IconProps) {
  return (
    <svg {...base(props)} className={`animate-spin ${props.className ?? ""}`}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}
