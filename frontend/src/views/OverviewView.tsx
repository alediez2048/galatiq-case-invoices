import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useOverview } from "../api/hooks";
import type { Overview } from "../api/types";
import { formatMoney } from "../format";
import { Icon } from "../components/Icon";
import { InvoiceTable } from "../components/InvoiceTable";
import { SamplePanel } from "../components/SamplePanel";
import { WaveMesh } from "../components/WaveMesh";
import { OUTCOME_SPEC } from "../components/StatusBadge";

export function EmptyWorkspace() {
  const [samplesOpen, setSamplesOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => {
    setSamplesOpen(false);
    trigger.current?.focus();
  };

  return (
    <>
      <section className="intro" aria-labelledby="intro-title">
        <WaveMesh />
        <div className="intro__copy">
          <h1 id="intro-title">
            From invoice to decision.
            <br />
            Every check visible.
          </h1>
          <p className="intro__lead">
            Extract details. Check inventory. Review the decision. Simulate the payment.
          </p>
          <div className="intro__actions">
            <Link to="/add" className="button button--primary">
              <Icon name="plus" />
              Upload invoice
            </Link>
            <button
              type="button"
              ref={trigger}
              className="button button--secondary"
              onClick={() => setSamplesOpen(true)}
            >
              Try a sample
            </button>
          </div>
        </div>
      </section>
      <div className="empty-note">
        <p className="strong">No invoices processed yet.</p>
        <p className="sub">Start with a sample to explore the workflow.</p>
      </div>
      {samplesOpen && <SamplePanel onClose={close} />}
    </>
  );
}

interface Card {
  key: string;
  label: string;
  value: number;
  accent?: boolean;
  foot?: string;
}

function metricCards(o: Overview): Card[] {
  const c = o.counts;
  const cards: Card[] = [
    {
      key: "unique",
      label: "Unique invoices",
      value: c.unique_invoices,
      foot: `${c.documents} ${c.documents === 1 ? "document" : "documents"} · ${c.runs} ${
        c.runs === 1 ? "run" : "runs"
      }`,
    },
    { key: "paid_mock", label: OUTCOME_SPEC.paid_mock.label, value: c.paid_mock, accent: true },
    { key: "needs_review", label: OUTCOME_SPEC.needs_review.label, value: c.needs_review },
    { key: "rejected", label: OUTCOME_SPEC.rejected.label, value: c.rejected },
  ];
  // Shown whenever non-zero; never hidden to preserve the four-card arrangement.
  if (c.awaiting_human_approval > 0) {
    cards.push({
      key: "awaiting_human_approval",
      label: OUTCOME_SPEC.awaiting_human_approval.label,
      value: c.awaiting_human_approval,
    });
  }
  if (c.failed > 0) cards.push({ key: "failed", label: OUTCOME_SPEC.failed.label, value: c.failed });
  if (c.processing > 0) {
    cards.push({ key: "processing", label: OUTCOME_SPEC.processing.label, value: c.processing });
  }
  return cards;
}

function OverviewWithResults({ overview }: { overview: Overview }) {
  const cards = metricCards(overview);
  const totals = Object.entries(overview.mock_paid_totals).sort(([a], [b]) => a.localeCompare(b));
  const { duplicates } = overview.counts;

  return (
    <>
      <section className="page-head">
        <div>
          <h1>Invoice overview</h1>
          <p className="intro-text">A clear view of every decision.</p>
        </div>
        <Link to="/add" className="button button--primary">
          <Icon name="plus" />
          Add invoice
        </Link>
      </section>

      <ul className="metrics" aria-label="Invoice counts" data-count={cards.length}>
        {cards.map((card) => (
          <li key={card.key} className="metric" data-metric={card.key}>
            <span className={`metric__number${card.accent ? " metric__number--accent" : ""}`}>
              {card.value}
            </span>
            <span className="metric__label">{card.label}</span>
            {card.foot && <span className="metric__foot">{card.foot}</span>}
          </li>
        ))}
      </ul>

      <div className="paid-totals" aria-label="Mock-paid totals">
        <p>
          {totals.length === 0
            ? "Mock paid: none yet"
            : totals.map(([currency, amount], index) => (
                <span key={currency} className="num">
                  {index === 0 ? "Mock paid: " : " · "}
                  {formatMoney(amount, currency)}
                </span>
              ))}
        </p>
        <p className="muted">No real funds transferred.</p>
      </div>
      {duplicates > 0 && (
        <p className="sub">
          {duplicates} duplicate {duplicates === 1 ? "submission" : "submissions"} recorded in run
          history; duplicates never add to these counts.
        </p>
      )}

      <section aria-labelledby="recent-title">
        <div className="section-head">
          <h2 id="recent-title">Recent invoices</h2>
        </div>
        {overview.recent_invoices.length > 0 ? (
          <InvoiceTable invoices={overview.recent_invoices} caption="Recent invoices" />
        ) : (
          <p className="sub">No recent invoices.</p>
        )}
        <div className="section-foot">
          <Link to="/invoices" className="button button--secondary">
            View all invoices
          </Link>
        </div>
      </section>
    </>
  );
}

export function OverviewView() {
  const overview = useOverview();
  if (overview.error && !overview.data) {
    return (
      <div className="state-block" role="alert">
        <p className="strong">The overview could not be loaded.</p>
        <p className="sub">{overview.error.message}</p>
        <button type="button" className="button button--secondary" onClick={overview.reload}>
          Try again
        </button>
      </div>
    );
  }
  if (!overview.data) {
    return (
      <p className="sub" role="status">
        Loading invoice history…
      </p>
    );
  }
  const c = overview.data.counts;
  if (c.unique_invoices === 0 && c.documents === 0 && c.runs === 0) return <EmptyWorkspace />;
  return <OverviewWithResults overview={overview.data} />;
}
