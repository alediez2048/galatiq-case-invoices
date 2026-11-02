import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useRetryRun } from "../api/hooks";
import type { InvoiceDetail } from "../api/types";
import { formatMoney, MODE_LABEL } from "../format";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import { ReceiptBlock } from "./ReceiptBlock";
import {
  failureInfo,
  hasFinding,
  latestRun,
  missingFieldsMessage,
  priorReceipt,
  totalsMessage,
} from "./states";

function Notice({
  tone,
  title,
  children,
  label,
}: {
  tone: "warning" | "danger" | "info";
  title: string;
  children?: ReactNode;
  label: string;
}) {
  return (
    <section className={`state-notice state-notice--${tone}`} aria-label={label}>
      <p className="state-notice__title">
        <Icon name={tone === "danger" ? "warning" : tone === "warning" ? "alert" : "copy"} />
        {title}
      </p>
      {children}
    </section>
  );
}

function RetryButton({ runId, onDone }: { runId: string; onDone: () => void }) {
  const { retry, busy, error } = useRetryRun(runId, onDone);
  return (
    <>
      <button type="button" className="button button--primary" onClick={retry} disabled={busy}>
        {busy ? "Retrying…" : "Retry"}
      </button>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/**
 * The "Other essential states" from docs/mockup.md, derived from persisted data:
 * duplicate submission, version conflict, revision after payment, unreadable / OCR /
 * oversized input, missing fields, contradictory totals, provider failure, processing failure.
 */
export function StateNotices({ detail, onChanged }: { detail: InvoiceDetail; onChanged: () => void }) {
  const notices: JSX.Element[] = [];
  const run = latestRun(detail);

  if (run?.status === "duplicate") {
    const original = detail.runs.find((r) => r.run_id === run.prior_run_id);
    notices.push(
      <Notice key="duplicate" tone="info" title="Already processed. No additional payment." label="Duplicate submission">
        <dl className="compare">
          <div>
            <dt>This submission</dt>
            <dd>
              {run.original_name ?? "Source"} · <StatusBadge status="duplicate" />
            </dd>
          </div>
          <div>
            <dt>Original outcome</dt>
            <dd>
              {original?.original_name ?? detail.source.original_name} · <StatusBadge status={detail.status} />
            </dd>
          </div>
        </dl>
        {run.prior_run_id && (
          <a className="inline-link" href={`#run-${run.prior_run_id}`}>
            Open original result
          </a>
        )}
      </Notice>,
    );
  }

  if (hasFinding(detail, "version_conflict")) {
    notices.push(
      <Notice key="version" tone="warning" title="Invoice versions differ. Review required." label="Version conflict">
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">Compared versions</caption>
            <thead>
              <tr>
                <th scope="col">Version</th>
                <th scope="col">Source</th>
                <th scope="col" className="num">Total</th>
                <th scope="col">Lines</th>
                <th scope="col">Payment</th>
              </tr>
            </thead>
            <tbody>
              {detail.versions.map((v) => (
                <tr key={v.version}>
                  <td>
                    {v.version}
                    {v.version === detail.current_version ? " (this)" : ""}
                  </td>
                  <td>{v.original_name}</td>
                  <td className="num">{formatMoney(v.total, v.currency)}</td>
                  <td>{v.lines.map((l) => `${l.item ?? "?"} × ${l.quantity ?? "?"}`).join(", ")}</td>
                  <td>{v.receipt ? `Mock paid ${formatMoney(v.receipt.amount, v.receipt.currency)}` : "Not paid"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sub">No automatic replacement. The earlier version stays as recorded.</p>
      </Notice>,
    );
  }

  if (hasFinding(detail, "revision_after_payment")) {
    const receipt = priorReceipt(detail);
    notices.push(
      <Notice
        key="revision"
        tone="warning"
        title="Earlier version already mock paid. Revised version blocked from additional payment."
        label="Revision after payment"
      >
        {receipt && <ReceiptBlock receipt={receipt} title="Prior mock receipt" />}
      </Notice>,
    );
  }

  const failure = failureInfo(detail);
  if (failure) {
    notices.push(
      <Notice key="failure" tone="danger" title={failure.headline} label="Processing failure">
        {failure.detail && <p className="sub">{failure.detail}</p>}
        {failure.code && <p className="sub mono">Code: {failure.code}</p>}
        <div className="actions">
          {failure.kind === "provider" && (
            <>
              {detail.allowed_actions.retry && failure.run && (
                <RetryButton runId={failure.run.run_id} onDone={onChanged} />
              )}
              <Link to="/add?mode=offline" className="button button--secondary">
                Run offline as a separate simulation
              </Link>
            </>
          )}
          {failure.kind === "processing" && detail.allowed_actions.retry && failure.run && (
            <RetryButton runId={failure.run.run_id} onDone={onChanged} />
          )}
          {(failure.kind === "unreadable" || failure.kind === "ocr" || failure.kind === "oversized") && (
            <Link to="/add" className="button button--secondary">
              Replace file
            </Link>
          )}
        </div>
        {failure.kind === "processing" && detail.receipt && (
          <p className="sub">A mock payment was already recorded for this invoice; retrying never pays twice.</p>
        )}
        {failure.run && <p className="sub">Mode of this run: {MODE_LABEL[failure.run.mode]}</p>}
      </Notice>,
    );
  }

  const missing = missingFieldsMessage(detail.findings);
  if (missing) {
    notices.push(
      <Notice key="missing" tone="warning" title={missing} label="Missing required fields">
        <p className="sub">No values were invented and no payment was made.</p>
      </Notice>,
    );
  }

  const totals = totalsMessage(detail);
  if (totals) {
    const rows: [string, string | null | undefined, string | null | undefined][] = [
      ["Subtotal", detail.stated.subtotal, detail.computed?.subtotal],
      ["Tax", detail.stated.tax, detail.computed?.tax],
      ["Shipping", detail.stated.shipping, detail.computed?.shipping],
      ["Total", detail.stated.total, detail.computed?.total],
    ];
    notices.push(
      <Notice key="totals" tone="danger" title={totals} label="Contradictory totals">
        <div className="table-wrap">
          <table>
            <caption className="visually-hidden">Stated and calculated totals</caption>
            <thead>
              <tr>
                <th scope="col">Amount</th>
                <th scope="col" className="num">Stated</th>
                <th scope="col" className="num">Calculated</th>
              </tr>
            </thead>
            <tbody>
              {rows
                .filter(([, s, c]) => s || c)
                .map(([label, s, c]) => (
                  <tr key={label}>
                    <td>{label}</td>
                    <td className="num">{formatMoney(s, detail.currency)}</td>
                    <td className="num">{formatMoney(c, detail.currency)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="sub">Payment is blocked until the totals agree.</p>
      </Notice>,
    );
  }

  if (notices.length === 0) return null;
  return <div className="state-notices">{notices}</div>;
}
