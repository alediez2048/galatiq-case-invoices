/** Small inline SVG icons; decorative (aria-hidden) because text always accompanies them. */
export type IconName =
  | "check"
  | "cross"
  | "alert"
  | "hourglass"
  | "warning"
  | "copy"
  | "spinner"
  | "superseded"
  | "pending"
  | "skipped"
  | "overview"
  | "list"
  | "review"
  | "arrow-right"
  | "arrow-left"
  | "download"
  | "plus"
  | "close"
  | "settings";

const PATHS: Record<IconName, JSX.Element> = {
  check: <path d="M3.5 8.5l3 3 6-7" />,
  cross: <path d="M4 4l8 8M12 4l-8 8" />,
  alert: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 4.5v4.25M8 11v.5" />
    </>
  ),
  hourglass: <path d="M4.5 2h7M4.5 14h7M5 2c0 3 6 3 6 6s-6 3-6 6M11 2c0 3-6 3-6 6s6 3 6 6" />,
  warning: (
    <>
      <path d="M8 2l6.5 11.5h-13z" />
      <path d="M8 6.5v3.25M8 11.5v.25" />
    </>
  ),
  copy: (
    <>
      <rect x="2.5" y="4.5" width="8" height="9" rx="1.5" />
      <path d="M5.5 2.5h6.5a1.5 1.5 0 011.5 1.5v7.5" />
    </>
  ),
  spinner: (
    <>
      <circle cx="8" cy="8" r="5.75" strokeOpacity="0.3" />
      <path d="M8 2.25a5.75 5.75 0 015.75 5.75" />
    </>
  ),
  superseded: <path d="M3 8h9M9 4.5L12.5 8 9 11.5M3 4v8" />,
  pending: <circle cx="8" cy="8" r="5" />,
  skipped: <path d="M3 8h10" />,
  overview: (
    <>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" />
      <rect x="9" y="2.5" width="4.5" height="4.5" />
      <rect x="2.5" y="9" width="4.5" height="4.5" />
      <rect x="9" y="9" width="4.5" height="4.5" />
    </>
  ),
  list: <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />,
  review: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 4.5V8l2.5 1.75" />
    </>
  ),
  "arrow-right": <path d="M3 8h10M9 4l4 4-4 4" />,
  "arrow-left": <path d="M13 8H3M7 4L3 8l4 4" />,
  download: <path d="M8 2.5v8M4.5 7L8 10.5 11.5 7M3 13.5h10" />,
  plus: <path d="M8 3v10M3 8h10" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  settings: (
    <>
      <circle cx="8" cy="8" r="2.25" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
    </>
  ),
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={["icon", className].filter(Boolean).join(" ")}
      data-icon={name}
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
