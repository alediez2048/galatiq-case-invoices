import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useOverview } from "../api/hooks";
import { MODE_LABEL } from "../format";
import { useWorkspace } from "../workspace";
import { Icon } from "./Icon";
import { ReadinessNotice } from "./ReadinessNotice";

export function ModeBadge() {
  const { mode } = useWorkspace();
  return (
    <span className="pill mode-badge" data-mode={mode} aria-label={`Workspace mode: ${MODE_LABEL[mode]}`}>
      <span className="pill__dot" aria-hidden="true" />
      {MODE_LABEL[mode]}
    </span>
  );
}

function NavCount({ value, label }: { value: number | undefined; label: string }) {
  if (value === undefined) return null;
  return (
    <span className="nav__count" aria-label={`${value} ${label}`}>
      {value}
    </span>
  );
}

export function AppFrame() {
  const location = useLocation();
  const overview = useOverview();
  const counts = overview.data?.counts;
  const reviewCount = counts ? counts.needs_review + counts.awaiting_human_approval : undefined;

  return (
    <div className="frame">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="header">
        <Link to="/" className="brand" aria-label="GALATIQ / Invoice Operations, overview">
          <span className="brand__wordmark">
            GALATIQ<span className="brand__dot">.</span>
          </span>
          <span className="brand__sep" aria-hidden="true">
            /
          </span>
          <span className="brand__product">Invoice Operations</span>
        </Link>
        <div className="header__right">
          <ModeBadge />
          <Link
            to="/setup"
            state={{ from: location.pathname + location.search }}
            className="button button--secondary"
          >
            <Icon name="settings" />
            Setup
          </Link>
        </div>
      </header>
      <div className="layout">
        <nav className="sidebar" aria-label="Primary">
          <div className="sidebar__label" aria-hidden="true">
            WORKSPACE
          </div>
          <NavLink to="/" end className="nav">
            <Icon name="overview" className="nav__icon" />
            Overview
          </NavLink>
          <NavLink to="/invoices" className="nav">
            <Icon name="list" className="nav__icon" />
            Invoices
            <NavCount value={counts?.unique_invoices} label="invoices" />
          </NavLink>
          <NavLink to="/review" className="nav">
            <Icon name="review" className="nav__icon" />
            Needs review
            <NavCount value={reviewCount} label="need review" />
          </NavLink>
          <div className="sidebar__bottom">
            <strong>
              <span className="brand__dot" aria-hidden="true">
                ●
              </span>{" "}
              Local workspace
            </strong>
            All payments are simulated.
          </div>
        </nav>
        <div className="workspace">
          <ReadinessNotice />
          <main id="main" tabIndex={-1} className="main">
            <Outlet />
          </main>
          <footer className="footer">
            Case-study prototype · Local workspace · All payments are simulated
          </footer>
        </div>
      </div>
    </div>
  );
}
