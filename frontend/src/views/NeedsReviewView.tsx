import { useCallback, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { resultJsonUrl } from "../api/client";
import { useApiQuery, useInvoice } from "../api/hooks";
import {
  QUEUE_GROUPS,
  reviewApi,
  type QueueGroup,
  type QueueItem,
  type ReviewActionResponse,
  type ReviewAllowedActions,
  type ReviewFailure,
} from "../api/review";
import type { InvoiceDetail } from "../api/types";
import { formatMoney } from "../format";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import { findingText } from "../detail/findingCopy";
import { ApprovalPanel, type Decision } from "../review/ApprovalPanel";
import { BlockerExplanation } from "../review/BlockerExplanation";
import { CorrectionForm } from "../review/CorrectionForm";
import { ReviewHistory } from "../review/ReviewHistory";

const GROUP_COPY: Record<QueueGroup, { title: string; sub: string; empty: string }> = {
  correctable_extraction: {
    title: "Extraction corrections",
    sub: "A value was misread. Correct it with source evidence and a reason; the invoice is checked again.",
    empty: "No extraction mistakes to correct.",
  },
  awaiting_human_approval: {
    title: "Awaiting human approval",
    sub: "Otherwise-valid invoices that need a person to approve or decline mock payment.",
    empty: "No invoices are waiting for approval.",
  },
  unresolved_blocker: {
    title: "Unresolved blockers",
    sub: "Problems that neither a correction nor an approval can clear.",
    empty: "No unresolved blockers.",
  },
};

function label(item: { invoice_number: string | null }) {
  return item.invoice_number ?? "No invoice number";
}

function reasonText(item: QueueItem): string {
  const first = item.reason_codes[0];
  if (!first) {
    return item.status === "awaiting_human_approval" ? "Above the USD 10,000 auto-pay limit" : "Needs review";
  }
  const text =
    first === "model_disagreement"
      ? "The model did not recommend approval"
      : findingText(first).replace(/\.$/, "");
  return item.reason_codes.length > 1 ? `${text} (+${item.reason_codes.length - 1} more)` : text;
}

function QueueTable({
  group,
  items,
  selected,
  onSelect,
}: {
  group: QueueGroup;
  items: QueueItem[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const copy = GROUP_COPY[group];
  const headingId = `queue-${group}`;
  return (
    <section className="review-group" aria-labelledby={headingId}>
      <div className="section-head">
        <h2 id={headingId} className="section-title">
          {copy.title} <span className="muted">· {items.length}</span>
        </h2>
      </div>
      <p className="sub">{copy.sub}</p>
      {items.length === 0 ? (
        <p className="empty-note">{copy.empty}</p>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">{copy.title}</caption>
            <thead>
              <tr>
                <th scope="col">Invoice</th>
                <th scope="col">Vendor</th>
                <th scope="col">Reason</th>
                <th scope="col" className="num">
                  Total
                </th>
                <th scope="col">
                  <span className="visually-hidden">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.invoice_id} aria-selected={selected === item.invoice_id || undefined}>
                  <td className="strong">{label(item)}</td>
                  <td className="truncate" title={item.vendor_name ?? undefined}>
                    {item.vendor_name ?? "Vendor missing"}
                  </td>
                  <td>{reasonText(item)}</td>
                  <td className="num">{formatMoney(item.total, item.currency)}</td>
                  <td className="open-cell">
                    <button
                      type="button"
                      className="row-open"
                      aria-label={`Review ${label(item)}`}
                      aria-pressed={selected === item.invoice_id}
                      onClick={() => onSelect(item.invoice_id)}
                    >
                      <Icon name="arrow-right" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type Conflict = Extract<ReviewFailure, { kind: "conflict" }>;

function Outcome({ decision, response }: { decision: Decision; response: ReviewActionResponse }) {
  const receipt = response.receipt ?? response.result?.receipt ?? null;
  const status = response.result?.status ?? response.status;
  const text =
    status === "paid_mock"
      ? `Mock payment approved${receipt ? `. Receipt ${receipt.receipt_id} · ${formatMoney(receipt.amount, receipt.currency)}` : ""}.`
      : decision === "decline" && status === "rejected"
        ? "Declined. No payment was made."
        : `Recorded. The invoice is now: `;
  return (
    <div className="state-notice state-notice--info" role="status">
      <p className="state-notice__title">
        {text}
        {status !== "paid_mock" && !(decision === "decline" && status === "rejected") && <StatusBadge status={status} />}
      </p>
      <p className="sub">
        <Link className="inline-link" to={`/runs/${encodeURIComponent(response.run_id)}`}>
          View the run
        </Link>
      </p>
    </div>
  );
}

/** The selected invoice: current record, the actions the server allows, and history. */
function ReviewPanel({
  item,
  group,
  onQueueChanged,
}: {
  item: QueueItem;
  group: QueueGroup | null;
  onQueueChanged: () => void;
}) {
  const fetched = useInvoice(item.invoice_id);
  const [current, setCurrent] = useState<{ detail: InvoiceDetail | null; actions: ReviewAllowedActions | null } | null>(
    null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState<{ decision: Decision; response: ReviewActionResponse } | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { reload } = fetched;

  const detail = current?.detail ?? fetched.data;
  const actions = current?.actions ?? item.actions;

  // A 409: replace the panel with the current record; nothing is resubmitted.
  const onConflict = useCallback(
    (f: Conflict) => {
      setNotice(f.message);
      setCurrent({ detail: f.invoice, actions: f.actions });
      setShowCorrection(false);
      if (!f.invoice) reload();
      onQueueChanged();
      headingRef.current?.focus();
    },
    [reload, onQueueChanged],
  );

  const onDone = useCallback(
    (decision: Decision, response: ReviewActionResponse) => {
      setDone({ decision, response });
      setCurrent(null);
      reload();
      onQueueChanged();
    },
    [reload, onQueueChanged],
  );

  const status = detail?.status ?? actions.status;
  const allowed = new Set(actions.allowed);
  // The form remounts on a new version, so nothing typed for an old version is reused.
  const versionKey = `${item.invoice_id}:${detail?.current_version ?? "?"}`;

  return (
    <section className="panel review-panel" aria-labelledby="review-selected-title">
      <div className="panel__title">
        <h2 id="review-selected-title" ref={headingRef} tabIndex={-1}>
          {label(item)} · {item.vendor_name ?? "Vendor missing"}
        </h2>
        <StatusBadge status={status} />
      </div>
      {detail && <p className="sub">Showing version {detail.current_version}.</p>}

      {notice && (
        <div className="state-notice state-notice--warning" role="alert">
          <p className="state-notice__title">{notice}</p>
          <p className="sub">Nothing was submitted for the earlier version.</p>
        </div>
      )}

      {fetched.error && !detail && (
        <p className="field-error" role="alert">
          The invoice could not be loaded: {fetched.error.message}
        </p>
      )}
      {!detail && fetched.loading && <p className="sub">Loading invoice history…</p>}

      {done && <Outcome decision={done.decision} response={done.response} />}

      {detail && !done && (
        <div className="review-body" key={versionKey}>
          {status === "awaiting_human_approval" && (
            <>
              <ApprovalPanel detail={detail} actions={actions} onConflict={onConflict} onDone={onDone} />
              {allowed.has("correct") && (
                <div className="review-actions">
                  <button
                    type="button"
                    className="button button--ghost"
                    aria-expanded={showCorrection}
                    onClick={() => setShowCorrection((v) => !v)}
                  >
                    Correct an extracted value instead
                  </button>
                </div>
              )}
              {allowed.has("correct") && showCorrection && <CorrectionForm detail={detail} onConflict={onConflict} />}
            </>
          )}
          {status === "needs_review" && group !== "unresolved_blocker" && allowed.has("correct") && (
            <CorrectionForm detail={detail} onConflict={onConflict} />
          )}
          {status === "needs_review" && group === "unresolved_blocker" && (
            <BlockerExplanation item={item} detail={detail} />
          )}
          {status !== "awaiting_human_approval" && status !== "needs_review" && (
            <p className="sub">This invoice no longer needs review. Open it to see the current outcome.</p>
          )}
        </div>
      )}

      {detail && <ReviewHistory detail={detail} />}

      <div className="detail-actions">
        <Link to={`/invoices/${encodeURIComponent(item.invoice_id)}`} className="button button--secondary">
          View invoice
        </Link>
        <a
          className="button button--secondary"
          href={resultJsonUrl(item.invoice_id)}
          download={`${item.invoice_number ?? item.invoice_id}-result.json`}
        >
          <Icon name="download" />
          Download result JSON
        </a>
        {allowed.has("submit_corrected") && !done && (
          <Link to={`/add?corrects=${encodeURIComponent(item.invoice_id)}`} className="button button--secondary">
            Add corrected invoice
          </Link>
        )}
      </div>
    </section>
  );
}

/** Needs review (mockup screen 7): three queue groups and the selected invoice's panel. */
export function NeedsReviewView() {
  const queue = useApiQuery("review-queue", (s) => reviewApi.queue(s));
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("invoice");
  const lastSelected = useRef<{ item: QueueItem; group: QueueGroup | null } | null>(null);
  const { reload } = queue;

  let found: { item: QueueItem; group: QueueGroup | null } | null = null;
  if (selectedId && queue.data) {
    for (const g of QUEUE_GROUPS) {
      const item = queue.data.groups[g].find((i) => i.invoice_id === selectedId);
      if (item) found = { item, group: g };
    }
  }
  // An item that left the queue after an action stays open with its last known row.
  if (found) lastSelected.current = found;
  const selection =
    found ?? (selectedId && lastSelected.current?.item.invoice_id === selectedId ? lastSelected.current : null);

  const select = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("invoice", id);
    setParams(next, { replace: true });
  };

  return (
    <>
      <section className="page-head">
        <div>
          <h1>Needs review</h1>
          <p className="intro-text">
            Unresolved invoices. Correct extraction mistakes, approve or decline high-value payments,
            and see what stays blocked.
          </p>
        </div>
      </section>

      <div aria-live="polite" aria-busy={queue.loading}>
        {queue.error && (
          <div className="state-block" role="alert">
            <p className="strong">The review queue could not be loaded.</p>
            <p className="sub">{queue.error.message}</p>
            <button type="button" className="button button--secondary" onClick={reload}>
              Try again
            </button>
          </div>
        )}
        {!queue.data && queue.loading && <p className="sub">Loading the review queue…</p>}
      </div>

      {queue.data &&
        QUEUE_GROUPS.map((g) => (
          <QueueTable key={g} group={g} items={queue.data!.groups[g]} selected={selectedId} onSelect={select} />
        ))}

      {selection && (
        <ReviewPanel
          key={selection.item.invoice_id}
          item={selection.item}
          group={selection.group}
          onQueueChanged={reload}
        />
      )}
    </>
  );
}
