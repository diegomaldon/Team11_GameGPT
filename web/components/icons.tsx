// Inline SVG icons (Lucide-style, 1.75 stroke) — one consistent visual
// language, no emoji as UI. Platform glyphs are simplified stylized marks for
// this mock (not official brand assets).

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
export function Compass(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M15.5 8.5l-2 5-5 2 2-5 5-2z" />
    </svg>
  );
}
export function Library(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="7" height="7" rx="1.5" />
      <rect x="14" y="4" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}
export function Gear(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1" />
    </svg>
  );
}
export function User(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20a8 8 0 0 1 16 0" />
    </svg>
  );
}
export function Plus(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
export function Trash(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
    </svg>
  );
}
export function Check(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}
export function X(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}
export function LogOut(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" />
      <path d="M10 12h9M16 8l3 4-3 4" />
      <path d="M10 4H6a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4" />
    </svg>
  );
}
export function Menu(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}
export function Search(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="11" cy="11" r="7" />
      <path d="M16.5 16.5L21 21" />
    </svg>
  );
}
export function Google(props: IconProps) {
  // Multi-color Google "G" (official-ish mark for the sign-in button).
  return (
    <svg viewBox="0 0 24 24" aria-hidden width="1em" height="1em" {...props}>
      <path fill="#4285F4" d="M21.6 12.2c0-.7-.06-1.4-.18-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3z" />
      <path fill="#34A853" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 .95-3.4.95-2.6 0-4.8-1.75-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22z" />
      <path fill="#FBBC05" d="M6.4 13.9a6 6 0 0 1 0-3.8V7.5H3.1a10 10 0 0 0 0 9z" />
      <path fill="#EA4335" d="M12 6.1c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 0 0 3.1 7.5l3.3 2.6C7.2 7.8 9.4 6.1 12 6.1z" />
    </svg>
  );
}

// ── Platform glyphs (simplified, stylized — not official brand assets) ──
export function Steam(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="15" cy="9.5" r="2.4" />
      <circle cx="8.5" cy="14.5" r="1.9" fill="currentColor" />
      <path d="M13.2 11.3L9.9 13.3" />
    </svg>
  );
}
export function Xbox(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M7 6.5c3 1.5 4.2 3.2 5 4.6.8-1.4 2-3.1 5-4.6" />
      <path d="M6 17.5c1.2-3 3.6-5.4 6-7 2.4 1.6 4.8 4 6 7" />
    </svg>
  );
}
export function Epic(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 4h12a1 1 0 0 1 1 1v11l-7 4-7-4V5a1 1 0 0 1 1-1z" />
      <path d="M10 8.5h4M10 12h3.5M10 15.5h4" />
    </svg>
  );
}
export function PlayStation(props: IconProps) {
  // The four face-button shapes — recognizably PlayStation.
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden {...props}>
      <path d="M12 3.2l2.1 3.6h-4.2L12 3.2z" />
      <circle cx="12" cy="17.5" r="2.2" />
      <path d="M4.4 9.6l1.6-1.6 1.6 1.6-1.6 1.6-1.6-1.6z" />
      <path d="M15.2 8.3h3.6v3.6h-3.6z" />
    </svg>
  );
}
