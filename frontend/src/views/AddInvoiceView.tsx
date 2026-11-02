import { useCallback, useId, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { RunInput } from "../api/client";
import { useInvoice, useSamples, useSubmitRun } from "../api/hooks";
import { refusalMessage, reviewApi, type ReviewFailure } from "../api/review";
import type { ExecutionMode } from "../api/types";
import { ReviewerAndReason } from "../review/ReviewerAndReason";
import { useReviewerName } from "../review/reviewer";
import { useReviewAction } from "../review/useReviewAction";
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
  const { submit, busy, error } = useSubmitRun(selectionId(selection), mode);
  const reasonId = useId();
  const fileErrorId = useId();

  // ?corrects=<invoice id>: a corrected invoice from the vendor, sent to
  // POST /api/invoices/{id}/corrected-submission, bound to the version shown here.
  const target = useInvoice(corrects ?? undefined);
  const reloadTarget = target.reload;
  const { reviewer, setReviewer, remember } = useReviewerName();
  const [note, setNote] = useState("");
  const [noteErrors, setNoteErrors] = useState<{ reason?: string; reviewer?: string }>({});
  const [conflict, setConflict] = useState<string | null>(null);
  const onConflict = useCallback(
    (f: Extract<ReviewFailure, { kind: "conflict" }>) => {
      setConflict(f.message);
      reloadTarget(); // show the current version; nothing was submitted
    },
    [reloadTarget],
  );
  const corrected = useReviewAction(onConflict);
  const busyAny = busy || corrected.busy;
  const original = target.data;
  const correctedRefusal =
    original && !original.review_actions?.allowed.includes("submit_corrected")
      ? refusalMessage(original.review_actions?.refused.submit_corrected ?? "action_not_allowed")
      : null;

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
    if (!busyAny) choose(e.dataTransfer.files);
  };

  const remove = () => {
    setSelection(null);
    setFileError(null);
    if (input.current) input.current.value = "";
  };

  const r = readiness.data;
  const correctsReason: string | null = !corrects
    ? null
    : target.error && !original
      ? "The invoice to correct could not be loaded."
      : !original
        ? "Loading the invoice to correct…"
        : correctedRefusal
          ? `A corrected invoice cannot be added: ${correctedRefusal}`
          : selection?.kind === "sample"
            ? "Choose the corrected file from the vendor."
            : null;
  const reason: string | null = busyAny
    ? "Submitting…"
    : correctsReason
      ? correctsReason
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

  const submitCorrected = async (file: File) => {
    if (!corrects || !original) return;
    const next: typeof noteErrors = {};
    if (!note.trim()) next.reason = "Enter why this corrected invoice replaces the earlier one.";
    if (!reviewer.trim()) next.reviewer = "Enter your name.";
    setNoteErrors(next);
    if (Object.keys(next).length > 0) return;
    setConflict(null);
    const input = {
      file,
      expected_version: original.current_version,
      reason: note.trim(),
      reviewer: reviewer.trim(),
      mode,
    };
    const signature = `corrected:${corrects}:${selectionId(selection)}:${JSON.stringify({ ...input, file: undefined })}`;
    const out = await corrected.send(signature, (key) => reviewApi.correctedSubmission(corrects, input, key));
    if (out) {
      remember(input.reviewer);
      navigate(`/runs/${encodeURIComponent(out.run_id)}`);
    }
  };

  const process = async () => {
    if (reason !== null || selection === null) return;
    if (corrects) {
      if (selection.kind === "file") await submitCorrected(selection.file);
      return;
    }
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
          Corrected invoice for {original?.invoice_number ?? corrects}
          {original ? ` · replaces version ${original.current_version}` : ""}. It is checked like any
          other invoice and, once processed, supersedes the earlier versions; their results stay on
          record.
        </p>
      )}
      {conflict && (
        <div className="state-notice state-notice--warning" role="alert">
          <p className="state-notice__title">{conflict}</p>
          <p className="sub">Nothing was submitted for the earlier version.</p>
        </div>
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
            disabled={busyAny}
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
          <button type="button" className="button button--ghost" onClick={remove} disabled={busyAny}>
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

      {corrects && (
        <div className="review-form">
          <ReviewerAndReason
            reviewer={reviewer}
            onReviewer={setReviewer}
            reason={note}
            onReason={setNote}
            reasonLabel="Reason for the corrected invoice"
            errors={noteErrors}
            disabled={busyAny}
          />
        </div>
      )}

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
            {corrects ? "Process corrected invoice" : "Process invoice"}
          </button>
        </span>
      </div>
      {error && (
        <p className="field-error" role="alert">
          {submitErrorText(error.code, error.message)}
        </p>
      )}
      {corrected.failure && (
        <p className="field-error" role="alert">
          {submitErrorText(corrected.failure.code, corrected.failure.message)}
        </p>
      )}
    </section>
  );
}
