import type { EvidenceRef, FindingCode, InvoiceDetail, ValidationFinding } from "../api/types";

/** schemas.CORRECTABLE_FIELD; the server re-checks every field. */
export const CORRECTABLE_FIELD =
  /^(vendor|invoice_number|invoice_date|due_date|currency|stated\.(subtotal|tax|shipping|total)|lines\[\d+\]\.(item|quantity|unit_price|line_total))$/;

export interface FieldOption {
  /** Correctable field path, e.g. "stated.total" or "lines[0].unit_price". */
  field: string;
  label: string;
  /** The value currently recorded for this version (what extraction produced). */
  extracted: string | null;
  /** Where the source shows it, from findings, normalization events or line evidence. */
  evidence: EvidenceRef[];
  /** The unresolved finding that points at this field, if any. */
  finding: FindingCode | null;
}

const STATED = ["subtotal", "tax", "shipping", "total"] as const;
const STATED_LABEL: Record<(typeof STATED)[number], string> = {
  subtotal: "Subtotal",
  tax: "Tax",
  shipping: "Shipping",
  total: "Total",
};
const LINE_PARTS = [
  ["item", "item"],
  ["quantity", "quantity"],
  ["unit_price", "unit price"],
  ["line_total", "line total"],
] as const;

/** Maps a finding's or event's `field` onto a correctable path ("total" -> "stated.total"). */
export function toCorrectableField(field: string | null | undefined): string | null {
  if (!field) return null;
  const f = field === "vendor_name" ? "vendor" : field.replace(/^line_items\[/, "lines[");
  if ((STATED as readonly string[]).includes(f)) return `stated.${f}`;
  return CORRECTABLE_FIELD.test(f) ? f : null;
}

function stated(detail: InvoiceDetail, key: (typeof STATED)[number]): string | null {
  const value = (detail.stated as Record<string, unknown>)[key];
  return typeof value === "string" ? value : value == null ? null : String(value);
}

/**
 * The fields a reviewer can pick, fields named by unresolved findings first. Presentation
 * only: whether a correction is accepted is decided by the server's evidence rule.
 */
export function correctableFields(detail: InvoiceDetail): FieldOption[] {
  const options: FieldOption[] = [
    { field: "vendor", label: "Vendor", extracted: detail.vendor, evidence: [], finding: null },
    { field: "invoice_number", label: "Invoice number", extracted: detail.invoice_number, evidence: [], finding: null },
    { field: "due_date", label: "Due date", extracted: detail.due_date, evidence: [], finding: null },
    { field: "currency", label: "Currency", extracted: detail.currency, evidence: [], finding: null },
    ...STATED.map((key) => ({
      field: `stated.${key}`,
      label: `${STATED_LABEL[key]} (stated)`,
      extracted: stated(detail, key),
      evidence: [],
      finding: null,
    })),
    ...detail.line_items.flatMap((line, i) =>
      LINE_PARTS.map(([part, word]) => ({
        field: `lines[${i}].${part}`,
        label: `Line ${i + 1} · ${word}`,
        extracted:
          part === "item"
            ? line.item
            : part === "quantity"
              ? line.requested
              : part === "unit_price"
                ? line.unit_price
                : line.line_total,
        evidence: [...line.evidence],
        finding: null as FindingCode | null,
      })),
    ),
  ];
  const byField = new Map(options.map((o) => [o.field, o]));

  for (const e of detail.normalization_events) {
    const o = byField.get(toCorrectableField(e.field) ?? "");
    if (o) o.evidence = [...e.evidence, ...o.evidence];
  }
  const open = detail.findings.filter(
    (f: ValidationFinding) => !f.resolved && (f.severity === "review" || f.severity === "blocker"),
  );
  for (const f of open) {
    const o = byField.get(toCorrectableField(f.field) ?? "");
    if (!o) continue;
    o.finding ??= f.code;
    o.evidence = [...f.evidence, ...o.evidence];
  }
  // De-duplicate evidence by location, keeping the first (most specific) one.
  for (const o of options) {
    const seen = new Set<string>();
    o.evidence = o.evidence.filter((r) => (seen.has(r.location) ? false : (seen.add(r.location), true)));
  }
  return [...options.filter((o) => o.finding), ...options.filter((o) => !o.finding)];
}
