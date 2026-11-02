import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/app.css";

async function start() {
  // Dev-only fixture API (VITE_MOCK_API=1 npm run dev). import.meta.env.DEV is a build-time
  // constant, so this branch and the fixtures it imports are removed from production builds.
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK_API === "1") {
    const { installMockApi } = await import("./test/mockApi");
    installMockApi();
  }
  const root = document.getElementById("root");
  if (!root) throw new Error("missing #root");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
