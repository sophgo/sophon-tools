/** Inline SVG icons for the console chrome.
 *
 *  Inline on purpose: the board has no network, and the Unicode glyphs the nav
 *  used before (◎ ▤ ✎ ⚙ …) rendered differently per platform -- some as colour
 *  emoji, some as tofu. Every icon here is a 24-unit stroke drawing in
 *  `currentColor`, so it takes the text colour of whatever it sits in and
 *  switches with the theme for free.
 */
import type { ReactNode } from 'react'

export type IconName =
  | 'overview' | 'models' | 'agents' | 'playground' | 'apps' | 'keys' | 'records'
  | 'logs' | 'settings' | 'docs' | 'sun' | 'moon' | 'logout' | 'collapse' | 'expand'
  | 'inbox' | 'chip' | 'lock' | 'alert' | 'shield'

const PATHS: Record<IconName, ReactNode> = {
  // A gauge: the live status of the box.
  overview: <>
    <path d="M4 15a8 8 0 1 1 16 0" />
    <path d="M12 15l3.5-4.5" />
    <circle cx="12" cy="15" r="1.25" />
    <path d="M4 19h16" />
  </>,
  // Stacked layers: model weights.
  models: <>
    <path d="M12 3l9 4.5-9 4.5-9-4.5z" />
    <path d="M3 12l9 4.5 9-4.5" />
    <path d="M3 16.5l9 4.5 9-4.5" />
  </>,
  agents: <>
    <rect x="4" y="8" width="16" height="11" rx="3" />
    <path d="M12 4v4" />
    <circle cx="12" cy="3.5" r="1" />
    <path d="M9 13v1.5M15 13v1.5" />
    <path d="M2 13v2M22 13v2" />
  </>,
  playground: <>
    <path d="M20 12.5a7.5 7.5 0 0 1-11.2 6.5L4 20l1-4.4A7.5 7.5 0 1 1 20 12.5z" />
    <path d="M9 11h6M9 14h4" />
  </>,
  apps: <>
    <rect x="4" y="4" width="7" height="7" rx="1.5" />
    <rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" />
    <path d="M16.5 13.5v6M13.5 16.5h6" />
  </>,
  keys: <>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l8-8" />
    <path d="M16 7l2.5 2.5M14 9l2 2" />
  </>,
  records: <>
    <path d="M12 7v5l3 2" />
    <path d="M3.5 12a8.5 8.5 0 1 0 2.5-6" />
    <path d="M3 4v4h4" />
  </>,
  logs: <>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M7 9l3 3-3 3" />
    <path d="M12.5 15H17" />
  </>,
  settings: <>
    <path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" />
    <circle cx="15" cy="6" r="2" />
    <circle cx="9" cy="12" r="2" />
    <circle cx="17" cy="18" r="2" />
  </>,
  docs: <>
    <path d="M5 5a2 2 0 0 1 2-2h12v14H7a2 2 0 0 0-2 2z" />
    <path d="M5 19a2 2 0 0 0 2 2h12v-4" />
    <path d="M9 7.5h6M9 11h4" />
  </>,
  sun: <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
  </>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />,
  logout: <>
    <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
    <path d="M15 8l4 4-4 4" />
    <path d="M19 12H9" />
  </>,
  collapse: <>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M9 4v16" />
    <path d="M15.5 10l-2 2 2 2" />
  </>,
  expand: <>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <path d="M9 4v16" />
    <path d="M13.5 10l2 2-2 2" />
  </>,
  inbox: <>
    <path d="M3 13l2.5-7.5A2 2 0 0 1 7.4 4h9.2a2 2 0 0 1 1.9 1.5L21 13" />
    <path d="M3 13v5a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5h-5l-1.5 2.5h-5L8 13z" />
  </>,
  // The brand mark: a die with its pins.
  chip: <>
    <rect x="6" y="6" width="12" height="12" rx="2.5" />
    <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
    <path d="M9.5 2.5V6M14.5 2.5V6M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5" />
  </>,
  lock: <>
    <rect x="5" y="10.5" width="14" height="10" rx="2.5" />
    <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
    <path d="M12 14.5v2" />
  </>,
  alert: <>
    <path d="M12 3.5l9.5 16.5h-19z" />
    <path d="M12 10v4.5M12 17.2v.3" />
  </>,
  shield: <>
    <path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6z" />
    <path d="M9 12l2 2 4-4" />
  </>,
}

export default function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={className ? `ico ${className}` : 'ico'} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
    >
      {PATHS[name]}
    </svg>
  )
}
