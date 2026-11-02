import { Link } from "react-router-dom";

export function NotFoundView() {
  return (
    <div className="state-block">
      <h1>Page not found.</h1>
      <Link to="/" className="button button--secondary">
        Back to overview
      </Link>
    </div>
  );
}
