import { createBrowserRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { AppFrame } from "./components/AppFrame";
import { AddInvoiceView } from "./views/AddInvoiceView";
import { InvoiceDetailView } from "./views/InvoiceDetailView";
import { InvoicesView, NeedsReviewView } from "./views/InvoicesView";
import { NotFoundView } from "./views/NotFoundView";
import { OverviewView } from "./views/OverviewView";
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
      { path: "setup", element: <SetupView /> },
      { path: "*", element: <NotFoundView /> },
    ],
  },
];

export const routerFuture = { v7_relativeSplatPath: true } as const;
export const providerFuture = { v7_startTransition: true } as const;

const router = createBrowserRouter(routes, { future: routerFuture });

export function App() {
  return (
    <WorkspaceProvider>
      <RouterProvider router={router} future={providerFuture} />
    </WorkspaceProvider>
  );
}
