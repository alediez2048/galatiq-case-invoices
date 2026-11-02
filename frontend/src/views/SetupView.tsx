import { useEffect, useRef } from "react";
import { Link, useLocation } from "react-router";
import type { ExecutionMode } from "../api/types";
import { MODE_LABEL } from "../format";
import { useWorkspace } from "../workspace";
import { Icon } from "../components/Icon";

const MODE_COPY: Record<ExecutionMode, string> = {
  offline: "Local checks and simulated agent decisions. No external model calls.",
  live: "Invoice content will be sent to the configured model provider. Payments remain simulated.",
};

export function SetupView() {
  const { mode, selectMode, readiness } = useWorkspace();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const data = readiness.data;

  return (
    <section className="panel setup" aria-labelledby="setup-title">
      <div className="panel__title">
        <h1 id="setup-title" ref={heading} tabIndex={-1}>
          Setup
        </h1>
        <Link to={from} className="button button--secondary" aria-label="Close setup">
          <Icon name="close" />
          Close
        </Link>
      </div>

      <fieldset className="mode-select">
        <legend>Execution mode for new invoices</legend>
        {(["offline", "live"] as const).map((m) => {
          const disabled = m === "live" && data?.live_available !== true;
          return (
            <label key={m} className={`choice${disabled ? " choice--disabled" : ""}`}>
              <input
                type="radio"
                name="mode"
                value={m}
                checked={mode === m}
                disabled={disabled}
                onChange={() => selectMode(m)}
              />
              <span>
                <span className="choice__title">{MODE_LABEL[m]}</span>
                <small>{MODE_COPY[m]}</small>
                {disabled && (
                  <small className="choice__reason">
                    Unavailable
                    {data?.live_unavailable_reason ? `: ${data.live_unavailable_reason}` : "."}
                  </small>
                )}
              </span>
            </label>
          );
        })}
        <p className="sub">
          Changing the mode affects new submissions only. Earlier runs keep their original mode.
        </p>
      </fieldset>

      <h2 className="section-title">Readiness</h2>
      {readiness.loading && !data && <p className="sub">Checking the local workspace…</p>}
      {readiness.error && <p className="sub">Cannot reach the local API: {readiness.error.message}</p>}
      {data && (
        <dl className="facts">
          <div>
            <dt>Inventory</dt>
            <dd>{data.inventory_seeded ? "Seeded" : "Not set up"}</dd>
          </div>
          <div>
            <dt>Offline simulation</dt>
            <dd>{data.offline_available ? "Available" : "Unavailable"}</dd>
          </div>
          <div>
            <dt>Live model</dt>
            <dd>
              {data.live_available
                ? "Configured"
                : data.live_settings_present
                  ? "Settings present but unavailable"
                  : "Not configured"}
            </dd>
          </div>
          <div>
            <dt>Database</dt>
            <dd className="mono">{data.db_path}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
