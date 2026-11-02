import type { QueueItem } from "../api/review";
import type { InvoiceDetail } from "../api/types";
import { formatMoney } from "../format";
import { CHECK_GROUPS, findingText } from "../detail/findingCopy";

const CURRENCY_CODES = new Set(["non_usd_currency", "unsupported_currency", "currency_conflict"]);

function groupClear(detail: InvoiceDetail, label: string): boolean {
  const codes = CHECK_GROUPS.find((g) => g.label === label)?.codes ?? [];
  return !detail.findings.some(
    (f) => !f.resolved && codes.includes(f.code) && (f.severity === "blocker" || f.severity === "review"),
  );
}

/** Unresolved blockers: explanation only. No approval or correction control is offered. */
export function BlockerExplanation({ item, detail }: { item: QueueItem; detail: InvoiceDetail }) {
  const codes = [...new Set(item.reason_codes.length > 0 ? item.reason_codes : detail.findings.map((f) => f.code))];
  const currency = codes.some((c) => CURRENCY_CODES.has(c));
  const passed = [
    groupClear(detail, "Item quantities") && "Inventory",
    groupClear(detail, "Invoice arithmetic") && "arithmetic",
  ].filter(Boolean) as string[];
  const paidEarlier = codes.includes("revision_after_payment");

  return (
    <section className="panel review-form" aria-label="Why this invoice stays blocked">
      <p className="decision-message num">Total: {formatMoney(detail.total, detail.currency)}</p>
      {passed.length === 2 && <p className="sub">Inventory and arithmetic passed.</p>}
      <ul className="reasons">
        {codes.map((c) => (
          <li key={c}>{findingText(c)}</li>
        ))}
      </ul>
      <p className="strong">
        {currency
          ? `${detail.currency ?? "Non-USD"} settlement remains blocked; human approval cannot override it.`
          : "These findings remain unresolved; human approval cannot override them."}
      </p>
      <p className="sub">
        {paidEarlier
          ? "Earlier version already mock paid. Revised version blocked from additional payment."
          : "No payment has been made for this invoice."}
      </p>
    </section>
  );
}
