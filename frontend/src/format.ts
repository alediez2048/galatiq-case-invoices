import type { DecimalStr, ExecutionMode } from "./api/types";

/**
 * Adds thousands separators to an API decimal string without changing a digit.
 * "5000.00" -> "5,000.00"; "-1234.5" -> "-1,234.5". Non-numeric input is returned as-is.
 */
export function groupDigits(value: DecimalStr): string {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value.trim());
  if (!match) return value;
  const [, sign = "", int = "", frac = ""] = match;
  return `${sign}${int.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${frac}`;
}

/** "USD 5,000.00"; currency is always explicit. Missing amount renders an em dash. */
export function formatMoney(amount: DecimalStr | null | undefined, currency?: string | null) {
  if (amount === null || amount === undefined || amount === "") return "—";
  const grouped = groupDigits(amount);
  return currency ? `${currency} ${grouped}` : grouped;
}

/** Quantities are decimal strings too ("10" or "10.00" are shown as supplied, trimmed). */
export function formatQuantity(value: DecimalStr | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  return groupDigits(/^-?\d+\.0+$/.test(text) ? text.replace(/\.0+$/, "") : text);
}

/** Exact decimal subtraction on strings via BigInt; used for display differences only. */
export function decimalSubtract(a: DecimalStr, b: DecimalStr): DecimalStr | null {
  const parse = (v: string) => /^(-?)(\d+)(?:\.(\d+))?$/.exec(v.trim());
  const ma = parse(a);
  const mb = parse(b);
  if (!ma || !mb) return null;
  const scale = Math.max((ma[3] ?? "").length, (mb[3] ?? "").length);
  const toInt = (m: RegExpExecArray) =>
    BigInt(`${m[1]}${m[2]}${(m[3] ?? "").padEnd(scale, "0")}`);
  const diff = toInt(ma) - toInt(mb);
  const negative = diff < 0n;
  const digits = (negative ? -diff : diff).toString().padStart(scale + 1, "0");
  const int = digits.slice(0, digits.length - scale);
  const frac = scale ? `.${digits.slice(digits.length - scale)}` : "";
  return `${negative ? "-" : ""}${int}${frac}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-02-01" -> "Feb 1, 2026" without timezone conversion. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const [, y, m, d] = match;
  const month = MONTHS[Number(m) - 1];
  return month ? `${month} ${Number(d)}, ${y}` : iso;
}

/** "2026-11-01T18:04:05Z" -> "Nov 1, 2026 18:04 UTC" (shown in UTC to stay unambiguous). */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const utc = /(?:Z|[+-]00:?00)$/.test(iso) ? " UTC" : "";
  return `${formatDate(match[1])} ${match[2]}:${match[3]}${utc}`;
}

export const MODE_LABEL: Record<ExecutionMode, string> = {
  offline: "Offline simulation",
  live: "Live model",
};

/** ISO date comparison works lexicographically. */
export function isOverdue(due: string | null | undefined, evaluated: string | null | undefined) {
  return Boolean(due && evaluated && evaluated.slice(0, 10) > due.slice(0, 10));
}
