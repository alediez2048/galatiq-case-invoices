import { Link } from "react-router-dom";
import type { InvoiceSummary } from "../api/types";
import { formatMoney, MODE_LABEL } from "../format";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

function invoiceLabel(i: InvoiceSummary) {
  return i.invoice_number ?? "No invoice number";
}

/**
 * Invoice rows as a table on wide screens and as summary cards at narrow widths
 * (CSS switches at 479px). Both carry the same fields so nothing is hidden permanently.
 */
export function InvoiceTable({
  invoices,
  caption,
  showMode = false,
}: {
  invoices: InvoiceSummary[];
  caption: string;
  showMode?: boolean;
}) {
  return (
    <>
      <div className="table-wrap invoice-table">
        <table>
          <caption className="visually-hidden">{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Invoice</th>
              <th scope="col">Vendor</th>
              <th scope="col" className="num">
                Total
              </th>
              <th scope="col">Outcome</th>
              {showMode && <th scope="col">Mode</th>}
              <th scope="col">
                <span className="visually-hidden">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((i) => (
              <tr key={i.invoice_id}>
                <td className="strong">{invoiceLabel(i)}</td>
                <td className="truncate" title={i.vendor ?? undefined}>
                  {i.vendor ?? "Vendor missing"}
                </td>
                <td className="num">{formatMoney(i.total, i.currency)}</td>
                <td>
                  <StatusBadge status={i.status} />
                </td>
                {showMode && <td className="muted">{MODE_LABEL[i.mode]}</td>}
                <td className="open-cell">
                  <Link
                    to={`/invoices/${encodeURIComponent(i.invoice_id)}`}
                    className="row-open"
                    aria-label={`Open ${invoiceLabel(i)}`}
                  >
                    <Icon name="arrow-right" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="invoice-cards" aria-label={caption}>
        {invoices.map((i) => (
          <li key={i.invoice_id} className="invoice-card">
            <Link to={`/invoices/${encodeURIComponent(i.invoice_id)}`} className="invoice-card__link">
              <span className="invoice-card__top">
                <span className="strong">{invoiceLabel(i)}</span>
                <StatusBadge status={i.status} />
              </span>
              <span className="invoice-card__vendor">{i.vendor ?? "Vendor missing"}</span>
              <span className="invoice-card__bottom">
                <span className="muted">{MODE_LABEL[i.mode]}</span>
                <span className="num">{formatMoney(i.total, i.currency)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
