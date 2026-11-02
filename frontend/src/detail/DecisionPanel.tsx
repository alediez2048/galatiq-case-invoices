import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { InvoiceDetail, Recommendation, GateOutcome } from "../api/types";
import { formatDateTime, MODE_LABEL } from "../format";
import { Icon } from "../components/Icon";
import { StatusBadge } from "../components/StatusBadge";
import { EvidenceRefs } from "./evidence";
import { CHECK_GROUPS, findingText, rankedFindings } from "./findingCopy";

const TABS = ["Decision", "Checks", "History"] as const;
type Tab = (typeof TABS)[number];

const RECOMMENDATION: Record<Recommendation, string> = {
  approve: "Approve",
  reject: "Reject",
  review: "Needs review",
};

const GATE: Record<GateOutcome, string> = {
  approved: "Approved for mock payment",
  rejected: "Rejected",
  needs_review: "Needs review",
  awaiting_human_approval: "Awaiting human approval",
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="check">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function DecisionTab({ detail }: { detail: InvoiceDetail }) {
  const d = detail.decision;
  const payment = detail.receipt
    ? detail.status === "paid_mock"
      ? "Simulated success"
      : "Mock paid on an earlier version"
    : "Not attempted";
  if (!d) {
    return (
      <dl className="checks">
        <Row label="Recommendation">No recommendation was recorded for this run.</Row>
        <Row label="Payment">{payment}</Row>
      </dl>
    );
  }
  const live = d.mode === "live";
  return (
    <>
      <dl className="checks">
        <Row label="Recommendation">
          {RECOMMENDATION[d.initial_recommendation]}
          {live ? "" : " (simulated)"}
        </Row>
        {d.revised_recommendation && d.revised_recommendation !== d.initial_recommendation && (
          <Row label="Revised after critique">{RECOMMENDATION[d.revised_recommendation]}</Row>
        )}
        <Row label="Critique">{d.critique_summary ?? "No critique summary recorded."}</Row>
        <Row label="Final policy result">{GATE[d.final_decision]}</Row>
        <Row label="Payment">{payment}</Row>
        <Row label="Mode">
          {MODE_LABEL[d.mode]}
          {live
            ? d.provider || d.model
              ? ` · ${[d.provider, d.model].filter(Boolean).join(" / ")}`
              : ""
            : " · simulated agent decisions"}
        </Row>
        <Row label="Policy version">{d.policy_version}</Row>
      </dl>
      {d.reasons.length > 0 && (
        <>
          <h3 className="eyebrow">Reasons</h3>
          <ul className="reasons">
            {d.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}
      <p className="sub">
        The critique checks the recommendation against policy. It cannot override a validation
        blocker.
      </p>
    </>
  );
}

function ChecksTab({ detail }: { detail: InvoiceDetail }) {
  const findings = rankedFindings(detail.findings);
  return (
    <>
      <dl className="checks" aria-label="Check summary">
        {CHECK_GROUPS.map((group) => {
          const hits = findings.filter(
            (f) => group.codes.includes(f.code) && (f.severity === "blocker" || f.severity === "review"),
          );
          const failed = hits.some((f) => f.severity === "blocker");
          return (
            <Row key={group.label} label={group.label}>
              {hits.length === 0 ? (
                <span className="check-result check-result--pass">
                  <Icon name="check" /> {group.label === "Currency" && detail.currency && detail.currency !== "USD" ? detail.currency : group.pass}
                </span>
              ) : (
                <span className={`check-result check-result--${failed ? "fail" : "review"}`}>
                  <Icon name={failed ? "cross" : "alert"} /> {failed ? "Failed" : "Needs review"}
                </span>
              )}
            </Row>
          );
        })}
      </dl>

      <h3 className="eyebrow">Findings</h3>
      {findings.length === 0 ? (
        <p className="sub">No findings.</p>
      ) : (
        <ul className="findings">
          {findings.map((f, i) => (
            <li key={`${f.code}-${i}`} className={`finding finding--${f.severity}`}>
              <div className="finding__head">
                <span className="finding__severity">{f.severity}</span>
                <span>{findingText(f.code)}</span>
              </div>
              {(f.item || f.field) && <p className="sub">{[f.item, f.field].filter(Boolean).join(" · ")}</p>}
              {(f.observed || f.expected) && (
                <dl className="observed">
                  <div>
                    <dt>Observed</dt>
                    <dd className="num">{f.observed ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Expected</dt>
                    <dd className="num">{f.expected ?? "—"}</dd>
                  </div>
                </dl>
              )}
              <EvidenceRefs refs={f.evidence} />
            </li>
          ))}
        </ul>
      )}

      <h3 className="eyebrow">Normalization</h3>
      {detail.normalization_events.length === 0 ? (
        <p className="sub">No values were normalized.</p>
      ) : (
        <ul className="findings" aria-label="Normalization events">
          {detail.normalization_events.map((e, i) => (
            <li key={`${e.field}-${i}`} className="finding">
              <div className="finding__head">
                <span className="strong">{e.field}</span>
              </div>
              <p className="normalization">
                <span className="mono">{e.raw_value ?? "∅"}</span>
                <Icon name="arrow-right" />
                <span className="mono">{e.normalized_value ?? "∅"}</span>
              </p>
              <p className="sub">Provenance: {e.provenance}</p>
              <EvidenceRefs refs={e.evidence} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function HistoryTab({ detail }: { detail: InvoiceDetail }) {
  return (
    <>
      <h3 className="eyebrow">Runs</h3>
      <ol className="history">
        {detail.runs.map((run) => (
          <li key={run.run_id} id={`run-${run.run_id}`} className="history__item">
            <div className="history__head">
              <StatusBadge status={run.status} />
              <span className="muted">
                {MODE_LABEL[run.mode]} · {formatDateTime(run.started_at)}
              </span>
            </div>
            <p className="sub">
              {run.original_name ?? "Source"} · run {run.run_id}
              {run.prior_run_id ? ` · follows run ${run.prior_run_id}` : ""}
            </p>
            {run.error_message && <p className="sub">{run.error_message}</p>}
            {run.events.length > 0 && (
              <ol className="events">
                {run.events.map((e) => (
                  <li key={e.sequence}>
                    <span className="mono">{e.stage}</span> {e.message ?? e.event.replace(/_/g, " ")}
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
      </ol>

      {detail.versions.length > 0 && (
        <>
          <h3 className="eyebrow">Versions</h3>
          <ol className="history">
            {detail.versions.map((v) => (
              <li key={v.version} className="history__item">
                <p>
                  Version {v.version}
                  {v.version === detail.current_version ? " (current)" : ""} · {v.original_name}
                  {v.revision ? ` · revision ${v.revision}` : ""}
                </p>
                <p className="sub">{formatDateTime(v.created_at)}</p>
              </li>
            ))}
          </ol>
        </>
      )}

      {detail.corrections.length > 0 && (
        <>
          <h3 className="eyebrow">Corrections</h3>
          <ol className="history">
            {detail.corrections.map((c, i) => (
              <li key={i} className="history__item">
                <p>
                  {c.field}: <span className="mono">{c.old_value ?? "∅"}</span> →{" "}
                  <span className="mono">{c.new_value ?? "∅"}</span> (version {c.version})
                </p>
                <p className="sub">
                  {c.reviewer} · {formatDateTime(c.created_at)} · {c.reason}
                </p>
              </li>
            ))}
          </ol>
        </>
      )}

      {detail.human_reviews.length > 0 && (
        <>
          <h3 className="eyebrow">Human reviews</h3>
          <ol className="history">
            {detail.human_reviews.map((r, i) => (
              <li key={i} className="history__item">
                <p>
                  {r.action === "approve" ? "Approved mock payment" : "Declined"} · version {r.version}
                </p>
                <p className="sub">
                  {r.reviewer} · {formatDateTime(r.created_at)} · {r.reason}
                </p>
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  );
}

export function DecisionPanel({ detail }: { detail: InvoiceDetail }) {
  const [tab, setTab] = useState<Tab>("Decision");
  const ids = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next =
      e.key === "ArrowRight" ? (index + 1) % TABS.length : e.key === "ArrowLeft" ? (index + TABS.length - 1) % TABS.length : -1;
    if (next < 0) return;
    e.preventDefault();
    setTab(TABS[next]!);
    tabRefs.current[next]?.focus();
  };

  return (
    <section className="panel decision-panel" aria-label="Decision, checks, and history">

      <div className="tabs" role="tablist" aria-label="Invoice evidence">
        {TABS.map((t, i) => (
          <button
            key={t}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${ids}-tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`${ids}-panel-${t}`}
            tabIndex={tab === t ? 0 : -1}
            className="tab"
            onClick={() => setTab(t)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${ids}-panel-${tab}`} aria-labelledby={`${ids}-tab-${tab}`} className="tabpanel">
        {tab === "Decision" && <DecisionTab detail={detail} />}
        {tab === "Checks" && <ChecksTab detail={detail} />}
        {tab === "History" && <HistoryTab detail={detail} />}
      </div>
    </section>
  );
}
