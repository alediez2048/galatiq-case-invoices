import { useId } from "react";
import { useSearchParams } from "react-router";
import { useInvoices } from "../api/hooks";
import type { ExecutionMode, InvoiceStatus } from "../api/types";
import { MODE_LABEL } from "../format";
import { InvoiceTable } from "../components/InvoiceTable";
import { OUTCOME_SPEC } from "../components/StatusBadge";

const OUTCOME_FILTERS: { value: InvoiceStatus | ""; label: string }[] = [
  { value: "", label: "All invoices" },
  { value: "paid_mock", label: OUTCOME_SPEC.paid_mock.label },
  { value: "needs_review", label: OUTCOME_SPEC.needs_review.label },
  { value: "awaiting_human_approval", label: OUTCOME_SPEC.awaiting_human_approval.label },
  { value: "rejected", label: OUTCOME_SPEC.rejected.label },
  { value: "failed", label: OUTCOME_SPEC.failed.label },
];

const STATUSES = new Set(OUTCOME_FILTERS.map((f) => f.value));

function readStatus(value: string | null): InvoiceStatus | "" {
  return value && STATUSES.has(value as InvoiceStatus) ? (value as InvoiceStatus) : "";
}

function readMode(value: string | null): ExecutionMode | "" {
  return value === "offline" || value === "live" ? value : "";
}

export function InvoiceListPanel({
  fixedStatus,
  title,
  subtitle,
}: {
  fixedStatus?: InvoiceStatus;
  title: string;
  subtitle: string;
}) {
  const [params, setParams] = useSearchParams();
  const status = fixedStatus ?? readStatus(params.get("status"));
  const mode = readMode(params.get("mode"));
  const q = params.get("q") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const list = useInvoices({ status, mode, q, page });
  const searchId = useId();
  const modeId = useId();

  const update = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };
  const filtered = Boolean((!fixedStatus && status) || mode || q);
  const clear = () => setParams(new URLSearchParams(), { replace: true });

  const data = list.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / Math.max(1, data.page_size))) : 1;

  return (
    <>
      <section className="page-head">
        <div>
          <h1>{title}</h1>
          <p className="intro-text">{subtitle}</p>
        </div>
      </section>

      <div className="toolbar" role="search" aria-label="Filter invoices">
        {!fixedStatus && (
          <div className="tabs" role="group" aria-label="Outcome">
            {OUTCOME_FILTERS.map((f) => (
              <button
                key={f.value || "all"}
                type="button"
                className="tab"
                aria-pressed={status === f.value}
                onClick={() => update({ status: f.value })}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
        <div className="toolbar__fields">
          <label htmlFor={modeId} className="visually-hidden">
            Mode
          </label>
          <select
            id={modeId}
            className="select"
            value={mode}
            onChange={(e) => update({ mode: e.target.value })}
          >
            <option value="">All modes</option>
            <option value="offline">{MODE_LABEL.offline}</option>
            <option value="live">{MODE_LABEL.live}</option>
          </select>
          <label htmlFor={searchId} className="visually-hidden">
            Search invoices
          </label>
          <input
            id={searchId}
            className="search"
            type="search"
            placeholder="Search vendor or invoice…"
            value={q}
            onChange={(e) => update({ q: e.target.value })}
          />
        </div>
      </div>

      <div aria-live="polite" aria-busy={list.loading}>
        {list.error && (
          <div className="state-block" role="alert">
            <p className="strong">Invoice history could not be loaded.</p>
            <p className="sub">{list.error.message}</p>
            <button type="button" className="button button--secondary" onClick={list.reload}>
              Try again
            </button>
          </div>
        )}
        {!data && list.loading && <p className="sub">Loading invoice history…</p>}
        {data && list.loading && (
          <p className="sub visually-hidden">Loading invoice history…</p>
        )}
        {data && data.items.length > 0 && (
          <InvoiceTable invoices={data.items} caption={title} showMode />
        )}
        {data && data.items.length === 0 && (
          <div className="state-block">
            <p className="strong">
              {filtered ? "No invoices match these filters." : "No invoices processed yet."}
            </p>
            {filtered && (
              <button type="button" className="button button--secondary" onClick={clear}>
                Clear filters
              </button>
            )}
          </div>
        )}
        {data && pages > 1 && (
          <nav className="pager" aria-label="Pages">
            <button
              type="button"
              className="button button--secondary"
              disabled={page <= 1}
              onClick={() => update({ page: String(page - 1) })}
            >
              Previous
            </button>
            <span className="muted">
              Page {page} of {pages}
            </span>
            <button
              type="button"
              className="button button--secondary"
              disabled={page >= pages}
              onClick={() => update({ page: String(page + 1) })}
            >
              Next
            </button>
          </nav>
        )}
      </div>
    </>
  );
}

export function InvoicesView() {
  return (
    <InvoiceListPanel title="Invoices" subtitle="Every invoice. Its current outcome and the mode of its latest run." />
  );
}
