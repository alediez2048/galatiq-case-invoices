import type { InvoiceDetail } from "../api/types";
import { formatDateTime } from "../format";

/** Version history: who changed what, when and why (corrections and human reviews). */
export function ReviewHistory({ detail }: { detail: InvoiceDetail }) {
  const empty = detail.corrections.length === 0 && detail.human_reviews.length === 0;
  return (
    <section className="review-history" aria-label="Version history">
      <h3 className="eyebrow">Version history</h3>
      {detail.versions.length > 0 && (
        <ol className="history" aria-label="Versions">
          {detail.versions.map((v) => (
            <li key={v.version} className="history__item">
              <p>
                Version {v.version}
                {v.version === detail.current_version ? " (current)" : ""}
                {v.original_name ? ` · ${v.original_name}` : ""}
              </p>
              <p className="sub">{formatDateTime(v.created_at)}</p>
            </li>
          ))}
        </ol>
      )}
      {empty ? (
        <p className="sub">No corrections or human reviews yet.</p>
      ) : (
        <ol className="history" aria-label="Changes">
          {detail.corrections.map((c, i) => (
            <li key={`c-${i}`} className="history__item">
              <p>
                {c.field}: <span className="mono">{c.old_value ?? "∅"}</span> →{" "}
                <span className="mono">{c.new_value ?? "∅"}</span> · version {c.version}
              </p>
              <p className="sub">
                {c.reviewer} · {formatDateTime(c.created_at)} · {c.reason} · evidence {c.evidence_location}
              </p>
            </li>
          ))}
          {detail.human_reviews.map((r, i) => (
            <li key={`r-${i}`} className="history__item">
              <p>
                {r.action === "approve" ? "Approved mock payment" : "Declined"} · version {r.version}
              </p>
              <p className="sub">
                {r.reviewer} · {formatDateTime(r.created_at)} · {r.reason}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
