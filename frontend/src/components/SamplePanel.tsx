import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSamples } from "../api/hooks";
import { Icon } from "./Icon";

/**
 * Sample selection. Choosing a sample opens the add-invoice flow with it preselected;
 * it never starts processing.
 */
export function SamplePanel({ onClose }: { onClose: () => void }) {
  const samples = useSamples(true);
  const [selected, setSelected] = useState<string>("");
  const navigate = useNavigate();
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && dialog.current) {
        const focusable = [
          ...dialog.current.querySelectorAll<HTMLElement>("button, input, a[href]"),
        ].filter((el) => !el.hasAttribute("disabled"));
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const choose = () => {
    if (selected) navigate(`/add?sample=${encodeURIComponent(selected)}`);
  };

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialog}>
        <div className="modal__header">
          <h2 id={titleId}>Try a sample</h2>
          <button type="button" className="button button--icon" onClick={onClose} aria-label="Close sample selection" data-autofocus>
            <Icon name="close" />
          </button>
        </div>
        <p className="sub">
          Pick a supplied example. You will review it before anything is processed.
        </p>
        {samples.loading && !samples.data && <p className="sub">Loading samples…</p>}
        {samples.error && (
          <p className="field-error" role="alert">
            Samples could not be loaded: {samples.error.message}
          </p>
        )}
        {samples.data && samples.data.length === 0 && (
          <p className="sub">No sample files were found in data/invoices/.</p>
        )}
        {samples.data && samples.data.length > 0 && (
          <fieldset className="samples">
            <legend className="visually-hidden">Samples</legend>
            {samples.data.map((s) => (
              <label key={s.name} className="choice">
                <input
                  type="radio"
                  name="sample"
                  value={s.name}
                  checked={selected === s.name}
                  onChange={() => setSelected(s.name)}
                />
                <span>
                  <span className="choice__title">{s.label}</span>
                  <small>
                    {[s.invoice_number, s.name].filter(Boolean).join(" · ")}
                  </small>
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="button button--primary" onClick={choose} disabled={!selected}>
            Continue
            <Icon name="arrow-right" />
          </button>
        </div>
      </div>
    </div>
  );
}
