import { createBrowserRouter, type RouteObject } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AppFrame } from "./components/AppFrame";
import { AddInvoiceView } from "./views/AddInvoiceView";
import { InvoiceDetailView } from "./views/InvoiceDetailView";
import { InvoicesView } from "./views/InvoicesView";
import { NeedsReviewView } from "./views/NeedsReviewView";
import { NotFoundView } from "./views/NotFoundView";
import { OverviewView } from "./views/OverviewView";
import { ProcessingView } from "./views/ProcessingView";
import { SetupView } from "./views/SetupView";
import { WorkspaceProvider } from "./workspace";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppFrame />,
    children: [
      { index: true, element: <OverviewView /> },
      { path: "invoices", element: <InvoicesView /> },
      { path: "invoices/:invoiceId", element: <InvoiceDetailView /> },
      { path: "review", element: <NeedsReviewView /> },
      { path: "add", element: <AddInvoiceView /> },
      { path: "runs/:runId", element: <ProcessingView /> },
      { path: "setup", element: <SetupView /> },
      { path: "*", element: <NotFoundView /> },
    ],
  },
];

const router = createBrowserRouter(routes);

export function App() {
  return (
    <WorkspaceProvider>
      <RouterProvider router={router} />
    </WorkspaceProvider>
  );
}
