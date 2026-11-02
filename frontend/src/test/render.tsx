import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import { providerFuture, routerFuture, routes } from "../App";
import { WorkspaceProvider } from "../workspace";
import { createFetch, defaultRoutes, type Routes } from "./mockApi";

/** Renders the real routes at `path` against a fixture fetch; returns recorded calls. */
export function renderApp(path: string, routes_: Routes = {}) {
  const { fetchStub, calls } = createFetch({ ...defaultRoutes, ...routes_ });
  vi.stubGlobal("fetch", fetchStub);
  const router = createMemoryRouter(routes, { initialEntries: [path], future: routerFuture });
  const utils = render(
    <WorkspaceProvider>
      <RouterProvider router={router} future={providerFuture} />
    </WorkspaceProvider>,
  );
  return { ...utils, router, calls };
}
