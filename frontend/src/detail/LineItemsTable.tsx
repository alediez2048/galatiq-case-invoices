import type { DetailLineItem } from "../api/types";
import { formatMoney, formatQuantity } from "../format";
import { Icon } from "../components/Icon";

function result(line: DetailLineItem) {
  if (line.available === null || line.available === undefined) {
    return (
      <span className="check-result check-result--fail">
        <Icon name="cross" /> Not in inventory
      </span>
    );
  }
  if (line.shortfall) {
    return (
      <span className="check-result check-result--fail">
        <Icon name="cross" /> Exceeds stock by {formatQuantity(line.shortfall)}
      </span>
    );
  }
  return (
    <span className="check-result check-result--pass">
      <Icon name="check" /> Within stock
    </span>
  );
}

export function LineItemsTable({ lines, currency }: { lines: DetailLineItem[]; currency?: string | null }) {
  return (
    <section className="panel" aria-labelledby="lines-title">
      <div className="panel__title">
        <h2 id="lines-title">Line items</h2>
        <span className="eyebrow">Local inventory</span>
      </div>
      {lines.length === 0 ? (
        <p className="sub">No line items were extracted.</p>
      ) : (
        <div className="table-wrap table-wrap--scroll" tabIndex={0} aria-label="Line items, scrollable">
          <table>
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col" className="num">Requested</th>
                <th scope="col" className="num">Available</th>
                <th scope="col" className="num">Unit price</th>
                <th scope="col" className="num">Line total</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <tr key={`${line.item ?? "line"}-${i}`}>
                  <td className="strong">{line.item ?? "Item missing"}</td>
                  <td className="num">{formatQuantity(line.requested)}</td>
                  <td className="num">{formatQuantity(line.available)}</td>
                  <td className="num">{formatMoney(line.unit_price, currency)}</td>
                  <td className="num">{formatMoney(line.line_total, currency)}</td>
                  <td>{result(line)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
