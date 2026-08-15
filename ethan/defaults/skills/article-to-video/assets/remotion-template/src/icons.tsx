import React from "react";

/**
 * Inline SVG icon library for article-to-video visuals.
 * All icons use currentColor — they inherit color from their parent element.
 * Unrecognized names fall back to emoji passthrough (rendered as text).
 */

const Lightning: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill={color} opacity={0.15} />
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </svg>
);

const Lock: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
);

const ChartUp: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
    <polyline points="16 7 22 7 22 13" />
  </svg>
);

const Check: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" fill={color} opacity={0.12} />
    <polyline points="9 12 11.5 14.5 16 9.5" />
  </svg>
);

const Star: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} opacity={0.2} stroke={color} strokeWidth={1.5}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

const ArrowRight: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <line x1="5" y1="12" x2="19" y2="12" />
    <polyline points="12 5 19 12 12 19" />
  </svg>
);

const Question: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" fill={color} opacity={0.1} />
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

const Bulb: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18h6" />
    <path d="M10 22h4" />
    <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" fill={color} opacity={0.1} />
    <path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
  </svg>
);

const Fire: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 2c1 3 2.5 3.5 3.5 4.5A5 5 0 0 1 17 10a5 5 0 1 1-10 0c0-1.5.5-2 1.5-3 1-1 1.5-1 1.5-3z" fill={color} opacity={0.12} />
    <path d="M12 2c1 3 2.5 3.5 3.5 4.5A5 5 0 0 1 17 10a5 5 0 1 1-10 0c0-1.5.5-2 1.5-3 1-1 1.5-1 1.5-3z" />
  </svg>
);

const Shield: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" fill={color} opacity={0.1} />
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

const Target: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <circle cx="12" cy="12" r="6" />
    <circle cx="12" cy="12" r="2" fill={color} />
  </svg>
);

const Clock: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

const Heart: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} opacity={0.2} stroke={color} strokeWidth={2}>
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  </svg>
);

const Rocket: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" fill={color} opacity={0.1} />
    <path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
    <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0" />
    <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" />
  </svg>
);

const Brain: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2z" fill={color} opacity={0.08} />
    <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2z" fill={color} opacity={0.08} />
  </svg>
);

const Book: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" fill={color} opacity={0.08} />
  </svg>
);

const Sparkle: React.FC<{size?: number; color?: string}> = ({size = 48, color = "currentColor"}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} opacity={0.2} stroke={color} strokeWidth={1.5}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

const ICON_MAP: Record<string, React.FC<{size?: number; color?: string}>> = {
  lightning: Lightning,
  lock: Lock,
  "chart-up": ChartUp,
  check: Check,
  star: Star,
  arrow: ArrowRight,
  question: Question,
  bulb: Bulb,
  fire: Fire,
  shield: Shield,
  target: Target,
  clock: Clock,
  heart: Heart,
  rocket: Rocket,
  brain: Brain,
  book: Book,
  sparkle: Sparkle,
};

export const Icon: React.FC<{name: string; size?: number; color?: string}> = ({name, size = 48, color}) => {
  const Component = ICON_MAP[name];
  if (Component) {
    return <Component size={size} color={color} />;
  }
  // Emoji passthrough: render the name as text (emoji render in color on Chromium).
  return <span style={{fontSize: size * 0.8, lineHeight: 1}}>{name}</span>;
};

export const ICON_NAMES = Object.keys(ICON_MAP);
