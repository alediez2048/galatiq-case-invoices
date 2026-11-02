import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { readinessFixture } from "../test/fixtures";
import { json } from "../test/mockApi";
import { renderApp } from "../test/render";
import * as wire from "../test/wire";

const MiB = 1024 * 1024;

function file(name: string, size = 120, type = "text/plain") {
  const f = new File(["x".repeat(Math.min(size, 1024))], name, { type, lastModified: 1 });
  if (size > 1024) Object.defineProperty(f, "size", { value: size });
  return f;
}

const accepted = (run_id = "run-new") => ({
  run_id,
  status: "received",
  mode: "offline",
  idempotent_replay: false,
});

const pendingRun = { "GET /api/runs/:id": () => new Promise(() => {}) };

const posts = (calls: { method: string; url: string; headers: Record<string, string> }[]) =>
  calls.filter((c) => c.method === "POST");

const processButton = () => screen.getByRole("button", { name: "Process invoice" });

describe("Add invoice (P5-07, screen 2)", () => {
  it("shows the drop zone, formats, limit, mode copy and the auto-pay threshold", async () => {
    renderApp("/add");
    expect(await screen.findByRole("heading", { level: 1, name: "Add an invoice" })).toBeInTheDocument();
    expect(screen.getByText(/Drop an invoice here, or/)).toBeInTheDocument();
    expect(screen.getByText("PDF, TXT, CSV, JSON, XML · Up to 10 MiB")).toBeInTheDocument();
    expect(screen.getByText("Local checks and simulated agent decisions. No external model calls.")).toBeInTheDocument();
    expect(screen.getByText("Eligible invoices up to USD 10,000 can auto-pay. No real money moves.")).toBeInTheDocument();
    expect(processButton()).toBeDisabled();
    expect(screen.getByText("Choose a file or a sample first.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel processing|background/i })).not.toBeInTheDocument();
  });

  it("selecting a file or a sample never creates a run", async () => {
    const user = userEvent.setup();
    const { calls } = renderApp("/add?sample=invoice_1001.txt", { "POST /api/runs": () => accepted() });
    expect(await screen.findByText("invoice_1001.txt")).toBeInTheDocument();
    expect(await screen.findByText(/Clean invoice/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.upload(screen.getByLabelText("Invoice file"), file("invoice_1001.txt"));
    expect(screen.getByText("invoice_1001.txt")).toBeInTheDocument();
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file("other.json")] } });
    expect(screen.getByText("other.json")).toBeInTheDocument();
    await waitFor(() => expect(processButton()).toBeEnabled());
    expect(posts(calls)).toHaveLength(0);
  });

  it("pre-checks size and extension next to the drop zone; nothing is sent", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { calls } = renderApp("/add");
    const input = await screen.findByLabelText("Invoice file");
    await user.upload(input, file("big.pdf", 11 * MiB, "application/pdf"));
    expect(screen.getByRole("alert")).toHaveTextContent("File exceeds the 10 MiB limit.");
    expect(processButton()).toBeDisabled();
    await user.upload(input, file("photo.png", 100, "image/png"));
    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported file type.");
    await user.upload(input, file("empty.txt", 0));
    expect(screen.getByRole("alert")).toHaveTextContent("This file is empty.");
    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: { files: [file("a.txt"), file("b.txt")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose one invoice per submission.");
    expect(processButton()).toBeDisabled();
    expect(posts(calls)).toHaveLength(0);
  });

  it("double-clicking Process creates one run, with an idempotency key, then opens progress", async () => {
    const user = userEvent.setup();
    let resolve: (r: Response) => void = () => {};
    const { calls, router } = renderApp("/add?sample=invoice_1001.txt", {
      "POST /api/runs": () => new Promise<Response>((r) => (resolve = r)),
      ...pendingRun,
    });
    await waitFor(() => expect(processButton()).toBeEnabled());
    await user.dblClick(processButton());
    expect(processButton()).toBeDisabled();
    expect(screen.getByText("Submitting…")).toBeInTheDocument();
    resolve(json(accepted("run-1"), 202));
    await waitFor(() => expect(router.state.location.pathname).toBe("/runs/run-1"));
    const sent = posts(calls);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.url).toBe("/api/runs");
    expect(sent[0]?.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("posts a sample as JSON with the workspace mode", async () => {
    const user = userEvent.setup();
    const bodies: (BodyInit | null | undefined)[] = [];
    renderApp("/add?sample=invoice_1002.txt", {
      "POST /api/runs": (_url, init) => {
        bodies.push(init?.body);
        return json(accepted(), 202);
      },
      ...pendingRun,
    });
    await waitFor(() => expect(processButton()).toBeEnabled());
    await user.click(processButton());
    await screen.findByRole("heading", { name: /Processing/ });
    expect(JSON.parse(String(bodies[0]))).toEqual({ sample: "invoice_1002.txt", mode: "offline" });
  });

  it("posts an uploaded file as multipart with the mode", async () => {
    const user = userEvent.setup();
    const bodies: (BodyInit | null | undefined)[] = [];
    renderApp("/add", {
      "POST /api/runs": (_url, init) => {
        bodies.push(init?.body);
        return json(accepted(), 202);
      },
      ...pendingRun,
    });
    await user.upload(await screen.findByLabelText("Invoice file"), file("mine.csv"));
    await waitFor(() => expect(processButton()).toBeEnabled());
    await user.click(processButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    const form = bodies[0] as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("mode")).toBe("offline");
    expect((form.get("file") as File).name).toBe("mine.csv");
  });

  it("shows the server's refusal next to the action and allows a resend with the same key", async () => {
    const user = userEvent.setup();
    let n = 0;
    const { calls } = renderApp("/add?sample=invoice_1001.txt", {
      "POST /api/runs": () =>
        ++n === 1
          ? json({ code: "busy", message: "Another invoice is still processing." }, 503)
          : json(accepted(), 202),
      ...pendingRun,
    });
    await waitFor(() => expect(processButton()).toBeEnabled());
    await user.click(processButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("Another invoice is still processing. Try again shortly.");
    await user.click(processButton());
    await screen.findByRole("heading", { name: /Processing/ });
    const sent = posts(calls);
    expect(sent).toHaveLength(2);
    expect(sent[0]?.headers["Idempotency-Key"]).toBe(sent[1]?.headers["Idempotency-Key"]);
  });

  it("live mode: copy changes, and Process is disabled with the reason when live is not configured", async () => {
    window.localStorage.setItem("galatiq.workspaceMode", "live");
    renderApp("/add?sample=invoice_1001.txt");
    expect(
      await screen.findByText("Invoice content will be sent to the configured model provider. Payments remain simulated."),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Live mode is not configured: XAI_API_KEY is not set/)).toBeInTheDocument();
    expect(processButton()).toBeDisabled();
  });

  it("live mode configured: Process is enabled and posts mode live", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("galatiq.workspaceMode", "live");
    const bodies: string[] = [];
    renderApp("/add?sample=invoice_1001.txt", {
      "GET /api/settings/readiness": () =>
        wire.readiness({ ...readinessFixture, live_available: true, live_unavailable_reason: null }),
      "POST /api/runs": (_u, init) => {
        bodies.push(String(init?.body));
        return json({ ...accepted(), mode: "live" }, 202);
      },
      ...pendingRun,
    });
    await waitFor(() => expect(processButton()).toBeEnabled());
    await user.click(processButton());
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(JSON.parse(bodies[0]!).mode).toBe("live");
  });

  it("?mode=offline runs one submission offline as a separate simulation", async () => {
    window.localStorage.setItem("galatiq.workspaceMode", "live");
    renderApp("/add?sample=invoice_1001.txt&mode=offline");
    expect(await screen.findByText("This submission runs offline as a separate simulation.")).toBeInTheDocument();
    expect(screen.getByText("Local checks and simulated agent decisions. No external model calls.")).toBeInTheDocument();
    await waitFor(() => expect(processButton()).toBeEnabled());
  });

  it("disables Process while inventory is not set up", async () => {
    renderApp("/add?sample=invoice_1001.txt", {
      "GET /api/settings/readiness": () => wire.readiness({ ...readinessFixture, inventory_seeded: false }),
    });
    expect(await screen.findByText("Inventory is not set up. Restart the API to seed it.")).toBeInTheDocument();
    expect(processButton()).toBeDisabled();
  });
});
