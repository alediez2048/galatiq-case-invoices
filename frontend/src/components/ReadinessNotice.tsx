import { Link } from "react-router-dom";
import { useWorkspace } from "../workspace";
import { Icon } from "./Icon";

/** Appears only when the operator can act on it (inventory missing, live selected but not ready). */
export function ReadinessNotice() {
  const { mode, readiness } = useWorkspace();
  const data = readiness.data;
  if (readiness.error) {
    return (
      <div className="notice notice--warning" role="status">
        <Icon name="warning" />
        <span>Cannot reach the local API: {readiness.error.message}</span>
      </div>
    );
  }
  if (!data) return null;

  const messages: string[] = [];
  if (!data.inventory_seeded) {
    messages.push("Inventory is not set up. Restart the local API to seed it.");
  }
  if (mode === "live" && !data.live_available) {
    messages.push(
      `Live model is selected but not configured${
        data.live_unavailable_reason ? `: ${data.live_unavailable_reason}` : "."
      }`,
    );
  }
  if (messages.length === 0) return null;

  return (
    <div className="notice notice--warning" role="status" aria-label="Setup required">
      <Icon name="warning" />
      <div>
        {messages.map((m) => (
          <p key={m}>{m}</p>
        ))}
        <Link to="/setup" className="inline-link">
          Open setup
        </Link>
      </div>
    </div>
  );
}
