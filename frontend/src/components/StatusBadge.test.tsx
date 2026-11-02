import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Outcome } from "../api/types";
import { OUTCOME_SPEC, StatusBadge } from "./StatusBadge";

const OUTCOMES: [Outcome, string][] = [
  ["paid_mock", "Mock paid"],
  ["rejected", "Rejected"],
  ["needs_review", "Needs review"],
  ["awaiting_human_approval", "Awaiting approval"],
  ["failed", "Failed"],
  ["duplicate", "Duplicate"],
  ["processing", "Processing"],
];

describe("StatusBadge", () => {
  it.each(OUTCOMES)("%s shows visible text and an icon", (outcome, label) => {
    const { container } = render(<StatusBadge status={outcome} />);
    expect(screen.getByText(label)).toBeVisible();
    const icon = container.querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(container.firstElementChild).toHaveAttribute("data-outcome", outcome);
  });

  it("uses a distinct icon and label for every outcome", () => {
    const icons = Object.values(OUTCOME_SPEC).map((s) => s.icon);
    const labels = Object.values(OUTCOME_SPEC).map((s) => s.label);
    expect(new Set(icons).size).toBe(OUTCOMES.length);
    expect(new Set(labels).size).toBe(OUTCOMES.length);
  });

  it("renders non-terminal run statuses as processing", () => {
    render(<StatusBadge status="validated" />);
    expect(screen.getByText("Processing")).toBeInTheDocument();
  });
});
