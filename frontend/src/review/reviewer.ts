import { useCallback, useState } from "react";

/**
 * The reviewer's name, remembered per browser as a convenience. A free-text audit label,
 * not authentication. Storage can be unavailable (private mode, blocked site data), so
 * every access is guarded and the form works without it.
 */
export const REVIEWER_KEY = "invoice-review.reviewer";

function read(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

function write(value: string) {
  try {
    const trimmed = value.trim();
    if (trimmed) window.localStorage.setItem(REVIEWER_KEY, trimmed);
  } catch {
    // Not remembered; nothing else depends on it.
  }
}

export function useReviewerName() {
  const [reviewer, setReviewer] = useState(read);
  /** Call after a successful submission so only names actually used are remembered. */
  const remember = useCallback((value: string) => write(value), []);
  return { reviewer, setReviewer, remember };
}
