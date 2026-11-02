import { useState } from "react";
import { useSourceContent } from "../api/hooks";
import type { SourceSummary } from "../api/types";
import { evidenceKey, useEvidence } from "./evidence";

export function SourcePanel({ source }: { source: SourceSummary }) {
  const content = useSourceContent(source.source_id);
  const { active } = useEvidence();
  const [showPdf, setShowPdf] = useState(true);
  const data = content.data;
  const isPdf = source.format === "pdf";

  return (
    <section className="panel source-panel" aria-labelledby="source-title">
      <div className="panel__title">
        <h2 id="source-title">Source</h2>
        <span className="eyebrow">{source.format.toUpperCase()}</span>
      </div>
      <p className="sub source-name">{source.original_name}</p>

      {content.loading && !data && <p className="sub">Loading source…</p>}
      {content.error && (
        <p className="sub" role="alert">
          The source could not be loaded: {content.error.message}
        </p>
      )}

      {data && isPdf && data.original_url && showPdf && (
        <object
          className="pdf-preview"
          data={data.original_url}
          type="application/pdf"
          aria-label={`Page preview of ${source.original_name}`}
          onError={() => setShowPdf(false)}
        >
          <p className="sub">This browser cannot preview the PDF. Extracted text is shown below.</p>
        </object>
      )}
      {data?.preview_limitation && <p className="notice notice--muted">{data.preview_limitation}</p>}
      {data && isPdf && <p className="eyebrow source-subhead">Extracted text</p>}

      {data && (
        <ol className="source" aria-label={`Contents of ${source.original_name}`}>
          {data.lines.map((line) => {
            const highlighted = active.has(
              evidenceKey({ source_id: source.source_id, location: line.location }),
            );
            return (
              <li
                key={line.location}
                className={`source__line${highlighted ? " is-highlighted" : ""}`}
                data-location={line.location}
                data-highlighted={highlighted || undefined}
              >
                <span className="source__loc" aria-hidden="true">
                  {line.location.replace(/^(line|row):/, "")}
                </span>
                <span className="source__text">{line.text || " "}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
