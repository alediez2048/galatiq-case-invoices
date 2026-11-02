import { useId } from "react";

/** Reviewer name and required reason, with errors next to each field. */
export function ReviewerAndReason({
  reviewer,
  onReviewer,
  reason,
  onReason,
  reasonLabel,
  errors,
  disabled,
}: {
  reviewer: string;
  onReviewer: (value: string) => void;
  reason: string;
  onReason: (value: string) => void;
  reasonLabel: string;
  errors: { reviewer?: string; reason?: string };
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <>
      <div className="form-field">
        <label htmlFor={`${id}-reviewer`}>Reviewer</label>
        <input
          id={`${id}-reviewer`}
          className="input"
          value={reviewer}
          maxLength={100}
          autoComplete="name"
          onChange={(e) => onReviewer(e.target.value)}
          aria-invalid={errors.reviewer ? true : undefined}
          aria-describedby={errors.reviewer ? `${id}-reviewer-error` : `${id}-reviewer-hint`}
          disabled={disabled}
        />
        {errors.reviewer ? (
          <p className="field-error" id={`${id}-reviewer-error`} role="alert">
            {errors.reviewer}
          </p>
        ) : (
          <p className="sub" id={`${id}-reviewer-hint`}>
            Recorded with the action for audit. Remembered in this browser only.
          </p>
        )}
      </div>
      <div className="form-field">
        <label htmlFor={`${id}-reason`}>
          {reasonLabel} <span className="muted">(required)</span>
        </label>
        <textarea
          id={`${id}-reason`}
          className="input textarea"
          value={reason}
          maxLength={1000}
          rows={3}
          required
          onChange={(e) => onReason(e.target.value)}
          aria-invalid={errors.reason ? true : undefined}
          aria-describedby={errors.reason ? `${id}-reason-error` : undefined}
          disabled={disabled}
        />
        {errors.reason && (
          <p className="field-error" id={`${id}-reason-error`} role="alert">
            {errors.reason}
          </p>
        )}
      </div>
    </>
  );
}
