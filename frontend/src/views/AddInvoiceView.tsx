import { Link, useSearchParams } from "react-router";
import { MODE_LABEL } from "../format";
import { useWorkspace } from "../workspace";
import { Icon } from "../components/Icon";

const MODE_COPY = {
  offline: "Local checks and simulated agent decisions. No external model calls.",
  live: "Invoice content will be sent to the configured model provider. Payments remain simulated.",
} as const;

/**
 * Add-invoice panel shell. Selecting a sample or file never starts processing; the
 * submission and progress flow (drop zone, pre-checks, Process, stage events) is P5-07.
 */
export function AddInvoiceView() {
  const [params] = useSearchParams();
  const { mode } = useWorkspace();
  const sample = params.get("sample");
  const corrects = params.get("corrects");

  return (
    <section className="panel add-invoice" aria-labelledby="add-title">
      <div className="panel__title">
        <h1 id="add-title">Add an invoice</h1>
        <Link to="/" className="button button--secondary">
          <Icon name="close" />
          Close
        </Link>
      </div>
      {corrects && (
        <p className="notice notice--muted">
          Corrected invoice for {corrects}. It is checked as a new version; the earlier result stays
          on record.
        </p>
      )}
      <div className="dropzone">
        <p>Drop an invoice here, or browse files</p>
        <p className="sub">PDF, TXT, CSV, JSON, XML · Up to 10 MiB</p>
      </div>
      {sample && (
        <p className="selected">
          Selected: <span className="mono">{sample}</span>
        </p>
      )}
      <p>Mode: {MODE_LABEL[mode]}</p>
      <p className="sub">{MODE_COPY[mode]}</p>
      <p className="sub">Eligible invoices up to USD 10,000 can auto-pay. No real money moves.</p>
      <div className="modal__actions">
        <Link to="/" className="button button--ghost">
          Cancel
        </Link>
        <span className="action-with-reason">
          <span className="sub" id="process-reason">
            Submitting from the browser is not available yet (P5-07).
          </span>
          <button type="button" className="button button--primary" disabled aria-describedby="process-reason">
            Process invoice
          </button>
        </span>
      </div>
    </section>
  );
}
