import { Link, useParams } from "react-router";
import { resultJsonUrl } from "../api/client";
import { useInvoice } from "../api/hooks";
import type { InvoiceDetail } from "../api/types";
import { formatDate, formatMoney, isOverdue, MODE_LABEL } from "../format";
import { Icon, type IconName } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import { DecisionPanel } from "../detail/DecisionPanel";
import { EvidenceProvider } from "../detail/evidence";
import { LineItemsTable } from "../detail/LineItemsTable";
import { ReceiptBlock } from "../detail/ReceiptBlock";
import { SourcePanel } from "../detail/SourcePanel";
import { StateNotices } from "../detail/StateNotices";
import { decisionHeadline, hasFinding, stageStrip, type StageState } from "../detail/states";

const STAGE_ICON: Record<StageState, IconName> = {
  complete: "check",
  active: "hourglass",
  pending: "pending",
  failed: "cross",
  skipped: "skipped",
  attention: "alert",
};

const STAGE_WORD: Record<StageState, string> = {
  complete: "complete",
  active: "in progress",
  pending: "pending",
  failed: "failed",
  skipped: "skipped",
  attention: "needs review",
};

function StageStrip({ detail }: { detail: InvoiceDetail }) {
  return (
    <ol className="stage-strip" aria-label="Workflow stages">
      {stageStrip(detail).map((stage) => (
        <li key={stage.key} className={`stage stage--${stage.state}`} data-state={stage.state}>
          <Icon name={STAGE_ICON[stage.state]} />
          <span>{stage.label}</span>
          <span className="visually-hidden">: {STAGE_WORD[stage.state]}</span>
        </li>
      ))}
    </ol>
  );
}

function DetailHeader({ detail }: { detail: InvoiceDetail }) {
  const title = [detail.invoice_number ?? "No invoice number", detail.vendor ?? "Vendor missing"].join(" · ");
  const meta = [
    formatMoney(detail.total, detail.currency),
    detail.due_date ? `Due ${formatDate(detail.due_date)}` : "Due date missing",
    MODE_LABEL[detail.mode],
  ];
  return (
    <div className="detail-top">
      <div>
        <h1>{title}</h1>
        <p className="detail-meta">
          {meta.map((m, i) => (
            <span key={m} className={i === 0 ? "num" : undefined}>
              {i > 0 && " · "}
              {m}
            </span>
          ))}
        </p>
        {isOverdue(detail.due_date, detail.evaluation_date) && (
          <p className="overdue">
            <Icon name="warning" /> Overdue — due {formatDate(detail.due_date)}, evaluated{" "}
            {formatDate(detail.evaluation_date)}.
          </p>
        )}
      </div>
      <StatusBadge status={detail.status} />
    </div>
  );
}

/** Outcome and primary reason first, before the source (mockup screens 5, 6 and narrow layout). */
function Outcome({ detail }: { detail: InvoiceDetail }) {
  const headline = decisionHeadline(detail);
  return (
    <section className="outcome" aria-labelledby="outcome-title">
      <h2 id="outcome-title" className="decision-message">
        {headline.title}
      </h2>
      {headline.sub && <p className="decision-sub">{headline.sub}</p>}
    </section>
  );
}

function Detail({ detail, reload }: { detail: InvoiceDetail; reload: () => void }) {
  const showReceipt = detail.receipt && !hasFinding(detail, "revision_after_payment");
  return (
    <EvidenceProvider>
      <DetailHeader detail={detail} />
      <StageStrip detail={detail} />
      <Outcome detail={detail} />
      <StateNotices detail={detail} onChanged={reload} />
      <div className="detail-grid">
        {detail.source ? (
          <SourcePanel source={detail.source} />
        ) : (
          <section className="panel source-panel" aria-label="Source">
            <p className="sub">No source document is recorded for this invoice.</p>
          </section>
        )}
        <DecisionPanel detail={detail} />
      </div>
      <LineItemsTable lines={detail.line_items} currency={detail.currency} />
      {showReceipt && detail.receipt && <ReceiptBlock receipt={detail.receipt} />}
      {!detail.receipt && <p className="sub">Payment: Not attempted.</p>}
      <div className="detail-actions">
        <a
          className="button button--secondary"
          href={resultJsonUrl(detail.invoice_id)}
          download={`${detail.invoice_number ?? detail.invoice_id}-result.json`}
        >
          <Icon name="download" />
          Download result JSON
        </a>
        {detail.status === "rejected" && detail.allowed_actions.add_corrected_invoice && (
          <Link
            to={`/add?corrects=${encodeURIComponent(detail.invoice_id)}`}
            className="button button--primary"
          >
            Add corrected invoice
          </Link>
        )}
      </div>
      {detail.status === "rejected" && (
        <p className="sub">
          A corrected invoice is submitted as a new version and checked again. This result stays
          on record.
        </p>
      )}
    </EvidenceProvider>
  );
}

export function InvoiceDetailView() {
  const { invoiceId } = useParams();
  const invoice = useInvoice(invoiceId);
  return (
    <>
      <Link to="/invoices" className="back">
        <Icon name="arrow-left" /> Invoices
      </Link>
      {invoice.error && !invoice.data && (
        <div className="state-block" role="alert">
          <p className="strong">
            {"status" in invoice.error && invoice.error.status === 404
              ? "This invoice was not found."
              : "The invoice could not be loaded."}
          </p>
          <p className="sub">{invoice.error.message}</p>
        </div>
      )}
      {!invoice.data && invoice.loading && <p className="sub">Loading invoice history…</p>}
      {invoice.data && <Detail detail={invoice.data} reload={invoice.reload} />}
    </>
  );
}
