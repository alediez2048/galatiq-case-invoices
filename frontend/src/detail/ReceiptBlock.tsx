import type { MockReceipt } from "../api/types";
import { formatDateTime, formatMoney } from "../format";

export function ReceiptBlock({ receipt, title = "Mock receipt" }: { receipt: MockReceipt; title?: string }) {
  return (
    <section className="receipt" aria-label={title}>
      <h3 className="receipt__title">{title}</h3>
      <dl className="facts">
        <div>
          <dt>Reference</dt>
          <dd className="mono">{receipt.receipt_id}</dd>
        </div>
        <div>
          <dt>Amount</dt>
          <dd className="num">{formatMoney(receipt.amount, receipt.currency)}</dd>
        </div>
        <div>
          <dt>Recorded</dt>
          <dd>{formatDateTime(receipt.paid_at)}</dd>
        </div>
      </dl>
      <p className="muted">No real funds transferred.</p>
    </section>
  );
}
