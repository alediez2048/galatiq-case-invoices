import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useReadiness, type QueryState } from "./api/hooks";
import type { ExecutionMode, Readiness } from "./api/types";

const STORAGE_KEY = "galatiq.workspaceMode";

interface Workspace {
  /** Mode new submissions will use. Never changes how historical runs are labelled. */
  mode: ExecutionMode;
  /** Live is selectable only when readiness reports it configured; returns false if refused. */
  selectMode: (mode: ExecutionMode) => boolean;
  readiness: QueryState<Readiness>;
}

const WorkspaceContext = createContext<Workspace | null>(null);

function storedMode(): ExecutionMode | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "offline" || value === "live" ? value : null;
  } catch {
    return null;
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const readiness = useReadiness();
  const [chosen, setChosen] = useState<ExecutionMode | null>(storedMode);

  // Offline unless the operator explicitly chose live (or the backend default is live)
  // and live is actually configured: live is never enabled silently.
  const preferred = chosen ?? readiness.data?.default_mode ?? "offline";
  const mode: ExecutionMode =
    preferred === "live" && readiness.data?.live_available !== true && chosen !== "live"
      ? "offline"
      : preferred;

  const selectMode = useCallback(
    (next: ExecutionMode) => {
      if (next === "live" && readiness.data?.live_available !== true) return false;
      setChosen(next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Storage unavailable: the choice lasts for this page only.
      }
      return true;
    },
    [readiness.data?.live_available],
  );

  const value = useMemo(() => ({ mode, selectMode, readiness }), [mode, selectMode, readiness]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}
