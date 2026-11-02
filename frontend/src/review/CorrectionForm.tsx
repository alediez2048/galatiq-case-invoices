import { useId, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { reviewApi, type ReviewFailure } from "../api/review";
import type { InvoiceDetail } from "../api/types";
import { SourcePanel } from "../detail/SourcePanel";
import { findingText } from "../detail/findingCopy";
import { correctableFields } from "./fields";
import { ReviewerAndReason } from "./ReviewerAndReason";
import { useReviewerName } from "./reviewer";
import { useReviewAction } from "./useReviewAction";

type Conflict = Extract<ReviewFailure, { kind: "conflict" }>;

interface Errors {
  value?: string;
  evidence?: string;
  reason?: string;
  reviewer?: string;
}

/**
 * Correct one extracted value with source evidence (mockup screen 7, "Correct extraction").
 * Bound to the displayed version; a successful save opens the revalidation run.
 */
export function CorrectionForm({ detail, onConflict }: { detail: InvoiceDetail; onConflict: (f: Conflict) => void }) {
  const navigate = useNavigate();
  const id = useId();
  const options = useMemo(() => correctableFields(detail), [detail]);
  const [field, setField] = useState(options[0]?.field ?? "");
  const option = options.find((o) => o.field === field) ?? options[0];
  const [value, setValue] = useState("");
  const [evidence, setEvidence] = useState<{ location: string; text: string | null } | null>(
    option?.evidence[0] ? { location: option.evidence[0].location, text: option.evidence[0].snippet ?? null } : null,
  );
  const [reason, setReason] = useState("");
  const { reviewer, setReviewer, remember } = useReviewerName();
  const [errors, setErrors] = useState<Errors>({});
  const { send, busy, failure } = useReviewAction(onConflict);
  const version = detail.current_version;

  const pickField = (next: string) => {
    setField(next);
    const first = options.find((o) => o.field === next)?.evidence[0];
    setEvidence(first ? { location: first.location, text: first.snippet ?? null } : null);
    setErrors({});
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!option) return;
    const next: Errors = {};
    const newValue = value.trim();
    if (!newValue) next.value = "Enter the corrected value.";
    else if (newValue === (option.extracted ?? "").trim())
      next.value = "The corrected value is the same as the extracted value.";
    if (!evidence?.location.trim()) next.evidence = "Select the source line that shows this value.";
    if (!reason.trim()) next.reason = "Enter a reason for this correction.";
    if (!reviewer.trim()) next.reviewer = "Enter your name.";
    setErrors(next);
    if (Object.keys(next).length > 0 || !evidence) return;

    const body = {
      expected_version: version,
      changes: [{ field: option.field, new_value: newValue, evidence_location: evidence.location.trim() }],
      reason: reason.trim(),
      reviewer: reviewer.trim(),
    };
    const out = await send(`correct:${detail.invoice_id}:${JSON.stringify(body)}`, (key) =>
      reviewApi.correct(detail.invoice_id, body, key),
    );
    if (out) {
      remember(body.reviewer);
      navigate(`/runs/${encodeURIComponent(out.run_id)}`);
    }
  };

  if (!option) return <p className="sub">This invoice has no correctable fields.</p>;

  return (
    <div className="detail-grid review-correct">
      {detail.source ? (
        <SourcePanel
          source={detail.source}
          picker={{
            selected: evidence?.location ?? null,
            onSelect: (location, text) => {
              setEvidence({ location, text });
              setErrors((x) => ({ ...x, evidence: undefined }));
            },
          }}
        />
      ) : (
        <section className="panel source-panel" aria-label="Source">
          <p className="sub">No source document is recorded for this invoice.</p>
        </section>
      )}

      <form className="panel review-form" onSubmit={submit} aria-labelledby={`${id}-title`} noValidate>
        <h3 id={`${id}-title`} className="eyebrow">
          Correct extraction · version {version}
        </h3>

        <div className="form-field">
          <label htmlFor={`${id}-field`}>Field</label>
          <select id={`${id}-field`} className="select" value={option.field} onChange={(e) => pickField(e.target.value)}>
            {options.map((o) => (
              <option key={o.field} value={o.field}>
                {o.label}
                {o.finding ? ` — ${findingText(o.finding).replace(/\.$/, "")}` : ""}
              </option>
            ))}
          </select>
        </div>

        <dl className="checks" aria-label="Before and after">
          <div className="check">
            <dt>Original source</dt>
            <dd className="mono">{evidence?.text?.trim() || (evidence ? evidence.location : "Select a source line")}</dd>
          </div>
          <div className="check">
            <dt>Evidence</dt>
            <dd className="mono">{evidence?.location ?? "None selected"}</dd>
          </div>
          <div className="check">
            <dt>Extracted value</dt>
            <dd className="mono">{option.extracted ?? "∅"}</dd>
          </div>
          <div className="check">
            <dt>Corrected value</dt>
            <dd className="mono">{value.trim() || "—"}</dd>
          </div>
        </dl>

        <div className="form-field">
          <label htmlFor={`${id}-evidence`}>Evidence location</label>
          <input
            id={`${id}-evidence`}
            className="input mono"
            value={evidence?.location ?? ""}
            maxLength={200}
            placeholder="line:13, row:3, $.total"
            onChange={(e) => setEvidence({ location: e.target.value, text: null })}
            aria-invalid={errors.evidence ? true : undefined}
            aria-describedby={errors.evidence ? `${id}-evidence-error` : `${id}-evidence-hint`}
            disabled={busy}
          />
          {errors.evidence ? (
            <p className="field-error" id={`${id}-evidence-error`} role="alert">
              {errors.evidence}
            </p>
          ) : (
            <p className="sub" id={`${id}-evidence-hint`}>
              Select the line in the source that states this field.
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor={`${id}-value`}>Corrected value</label>
          <input
            id={`${id}-value`}
            className="input mono"
            value={value}
            maxLength={200}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={errors.value ? true : undefined}
            aria-describedby={errors.value ? `${id}-value-error` : undefined}
            disabled={busy}
          />
          {errors.value && (
            <p className="field-error" id={`${id}-value-error`} role="alert">
              {errors.value}
            </p>
          )}
        </div>

        <ReviewerAndReason
          reviewer={reviewer}
          onReviewer={setReviewer}
          reason={reason}
          onReason={setReason}
          reasonLabel="Reason"
          errors={errors}
          disabled={busy}
        />

        <div className="review-actions">
          <button type="submit" className="button button--primary" disabled={busy} aria-describedby={`${id}-note`}>
            {busy ? "Saving…" : "Save correction and revalidate"}
          </button>
        </div>
        <p className="sub" id={`${id}-note`}>
          Saving invalidates prior approval; an eligible invoice up to USD 10,000 may auto-pay.
        </p>
        <p className="sub">
          The original file and every earlier value stay on record. An error in the vendor&apos;s
          invoice itself needs a corrected invoice from the vendor.
        </p>
        {failure && (
          <p className="field-error" role="alert">
            {failure.message}
          </p>
        )}
      </form>
    </div>
  );
}
