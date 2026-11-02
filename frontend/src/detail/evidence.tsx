import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { lineAnchor } from "../api/adapters";
import type { EvidenceRef } from "../api/types";

interface EvidenceState {
  active: ReadonlySet<string>;
  setActive: (refs: EvidenceRef[] | null) => void;
}

const EvidenceContext = createContext<EvidenceState>({ active: new Set(), setActive: () => {} });

/** Shares which evidence locations are highlighted between findings and the source panel. */
export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [active, setActiveState] = useState<ReadonlySet<string>>(new Set());
  const value = useMemo<EvidenceState>(
    () => ({
      active,
      setActive: (refs) => setActiveState(new Set((refs ?? []).map((r) => evidenceKey(r)))),
    }),
    [active],
  );
  return <EvidenceContext.Provider value={value}>{children}</EvidenceContext.Provider>;
}

export const useEvidence = () => useContext(EvidenceContext);

/** Keyed by the source line the location points at (CSV "row:3,col:Qty" -> "row:3"). */
export function evidenceKey(ref: { source_id: string; location: string }) {
  return `${ref.source_id}|${lineAnchor(ref.location)}`;
}

/**
 * Source references for one finding or event. Hovering or focusing highlights the
 * matching lines in the source panel.
 */
export function EvidenceRefs({ refs }: { refs: EvidenceRef[] }) {
  const { setActive } = useEvidence();
  if (refs.length === 0) return null;
  return (
    <span className="evidence-refs">
      {refs.map((ref) => (
        <button
          key={`${ref.source_id}|${ref.location}`}
          type="button"
          className="evidence-ref"
          onMouseEnter={() => setActive([ref])}
          onMouseLeave={() => setActive(null)}
          onFocus={() => setActive([ref])}
          onBlur={() => setActive(null)}
          aria-label={`Source ${ref.location}${ref.snippet ? `: ${ref.snippet}` : ""}`}
        >
          {ref.location}
        </button>
      ))}
    </span>
  );
}
