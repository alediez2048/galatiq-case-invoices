import { useId, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { RunInput } from "../api/client";
import { useSamples, useSubmitRun } from "../api/hooks";
import type { ExecutionMode } from "../api/types";
import { formatBytes, MODE_LABEL } from "../format";
import { useWorkspace } from "../workspace";
import { Icon } from "../components/Icon";

const MODE_COPY: Record<ExecutionMode, string> = {
  offline: "Local checks and simulated agent decisions. No external model calls.",
  live: "Invoice content will be sent to the configured model provider. Payments remain simulated.",
};

/** Client-side pre-check only; the server stays authoritative (P2-01 limits). */
export const MAX_BYTES = 10 * 1024 * 1024;
export const EXTENSIONS = ["pdf", "txt", "csv", "json", "xml"] as const;

export function precheckFile(file: File): string | null {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  if (!(EXTENSIONS as readonly string[]).includes(ext)) {
    return "Unsupported file type. Choose a PDF, TXT, CSV, JSON or XML file.";
  }
  if (file.size > MAX_BYTES) return "File exceeds the 10 MiB limit.";
  if (file.size === 0) return "This file is empty.";
  return null;
}

type Selection = { kind: "sample"; name: string } | { kind: "file"; file: File };

const selectionId = (s: Selection | null) =>
  s === null
    ? null
    : s.kind === "sample"
      ? `sample:${s.name}`
      : `file:${s.file.name}:${s.file.size}:${s.file.lastModified}`;

function submitErrorText(code: string, message: string): string {
  switch (code) {
    case "file_too_large":
      return "File exceeds the 10 MiB limit.";
    case "provider_unavailable":
      return `Live mode is not available: ${message} Choose offline in Setup.`;
    case "busy":
      return "Another invoice is still processing. Try again shortly.";
    case "network_error":
      return "Cannot reach the local API. Is the backend running?";
    default:
      return message;
  }
}

/**
 * Add-invoice panel (mockup screen 2). Selecting or previewing a file never starts
 * processing; Process posts once with an idempotency key and opens the processing view.
 */
export function AddInvoiceView() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { mode: workspaceMode, readiness } = useWorkspace();
  const corrects = params.get("corrects");
  // "Run offline as a separate simulation" links here with ?mode=offline: an explicit,
  // one-submission choice. Nothing else can change the mode on this screen.
  const forcedOffline = params.get("mode") === "offline";
  const mode: ExecutionMode = forcedOffline ? "offline" : workspaceMode;

  const initialSample = params.get("sample");
  const [selection, setSelection] = useState<Selection | null>(
    initialSample ? { kind: "sample", name: initialSample } : null,
  );
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const samples = useSamples(selection?.kind === "sample");
  const { submit, busy, error } = useSubmitRun(selectionId(selection));
  const reasonId = useId();
  const fileErrorId = useId();

  const choose = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    if (files.length > 1) {
      setFileError("Choose one invoice per submission.");
      return;
    }
    const file = files[0]!;
    const problem = precheckFile(file);
    setFileError(problem);
    if (problem === null) setSelection({ kind: "file", file });
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (!busy) choose(e.dataTransfer.files);
  };

  const remove = () => {
    setSelection(null);
    setFileError(null);
    if (input.current) input.current.value = "";
  };

  const r = readiness.data;
  const reason: string | null = busy
    ? "Submitting…"
    : selection === null
      ? "Choose a file or a sample first."
      : readiness.error && !r
        ? "Cannot reach the local API. Is the backend running?"
        : !r
          ? "Checking setup…"
          : !r.inventory_seeded
            ? "Inventory is not set up. Restart the API to seed it."
            : mode === "live" && !r.live_available
              ? `Live mode is not configured${r.live_unavailable_reason ? `: ${r.live_unavailable_reason}` : ""}. Choose offline in Setup.`
              : null;

  const process = async () => {
    if (reason !== null || selection === null) return;
    const runInput: RunInput =
      selection.kind === "sample"
        ? { kind: "sample", sample: selection.name, mode }
        : { kind: "file", file: selection.file, mode };
    const created = await submit(runInput);
    if (created) navigate(`/runs/${encodeURIComponent(created.run_id)}`);
  };

  const sampleInfo =
    selection?.kind === "sample" ? samples.data?.find((s) => s.name === selection.name) : undefined;

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
          Corrected invoice for {corrects}. It is submitted and checked like any other invoice; the
          earlier result stays on record.
        </p>
      )}

      <div
        className={`dropzone${dragging ? " is-dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="dropzone"
      >
        <p>
          Drop an invoice here, or{" "}
          <button
            type="button"
            className="button button--secondary"
            onClick={() => input.current?.click()}
            disabled={busy}
            aria-describedby={fileError ? fileErrorId : undefined}
          >
            Browse files
          </button>
        </p>
        <p className="sub">PDF, TXT, CSV, JSON, XML · Up to 10 MiB</p>
        <input
          ref={input}
          type="file"
          className="visually-hidden"
          accept=".pdf,.txt,.csv,.json,.xml"
          aria-label="Invoice file"
          tabIndex={-1}
          onChange={(e) => choose(e.target.files)}
        />
      </div>
      {fileError && (
        <p className="field-error" role="alert" id={fileErrorId}>
          {fileError}
        </p>
      )}

      {selection && (
        <div className="selected">
          <p>
            Selected:{" "}
            <span className="mono">
              {selection.kind === "sample" ? selection.name : selection.file.name}
            </span>
            {selection.kind === "file" && <span className="sub"> · {formatBytes(selection.file.size)}</span>}
            {sampleInfo && <span className="sub"> · {sampleInfo.label}</span>}
          </p>
          <button type="button" className="button button--ghost" onClick={remove} disabled={busy}>
            Remove
          </button>
        </div>
      )}

      <div className="mode-copy">
        <p>
          Mode: <span className="strong">{MODE_LABEL[mode]}</span>
          {!forcedOffline && (
            <>
              {" "}
              · <Link to="/setup" className="inline-link">Change in Setup</Link>
            </>
          )}
        </p>
        {forcedOffline && workspaceMode === "live" && (
          <p className="sub">This submission runs offline as a separate simulation.</p>
        )}
        <p className="sub">{MODE_COPY[mode]}</p>
        <p className="sub">Eligible invoices up to USD 10,000 can auto-pay. No real money moves.</p>
      </div>

      <div className="modal__actions">
        <Link to="/" className="button button--ghost">
          Cancel
        </Link>
        <span className="action-with-reason">
          {reason && (
            <span className="sub" id={reasonId}>
              {reason}
            </span>
          )}
          <button
            type="button"
            className="button button--primary"
            onClick={process}
            disabled={reason !== null}
            aria-describedby={reason ? reasonId : undefined}
          >
            Process invoice
          </button>
        </span>
      </div>
      {error && (
        <p className="field-error" role="alert">
          {submitErrorText(error.code, error.message)}
        </p>
      )}
    </section>
  );
}
