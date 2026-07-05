import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";
import { expectNoAccessibilityViolations } from "./test/accessibility";
import type { NavigationItem, WebBootstrap } from "./types";

const navigation: NavigationItem[] = [
  { id: "overview", label: "Overview", description: "Health", path: "/", depth: "inspect", availability: "available" },
  { id: "workbench", label: "Workbench", description: "Conversation", path: "/workbench", depth: "operate", availability: "coming_soon" },
  { id: "sessions", label: "Sessions", description: "History", path: "/sessions", depth: "operate", availability: "coming_soon" },
  { id: "runtime", label: "Runtime", description: "Controls", path: "/runtime", depth: "configure", availability: "coming_soon" },
  { id: "capabilities", label: "Capabilities", description: "Tools", path: "/capabilities", depth: "inspect", availability: "available" },
  { id: "work", label: "Work", description: "Tasks", path: "/work", depth: "operate", availability: "available" },
  { id: "knowledge", label: "Knowledge", description: "Memory", path: "/knowledge", depth: "inspect", availability: "available" },
  { id: "autopilot", label: "Autopilot", description: "Repository", path: "/autopilot", depth: "operate", availability: "available" },
];

const bootstrap: WebBootstrap = {
  schema_version: 1,
  app: { name: "OpenHarness", version: "0.1.9" },
  workspace: { name: "demo", path: "/work/demo" },
  runtime: {
    profile: "local",
    provider: "anthropic",
    model: "local-model",
    auth: { state: "configured", label: "local_token" },
    permission_mode: "default",
    sandbox_enabled: true,
    sandbox_backend: "docker",
    effort: "medium",
    max_turns: 200,
  },
  navigation,
};

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  window.localStorage.clear();
});

test("renders the redacted runtime overview after bootstrap", async () => {
  render(<App loadBootstrap={async () => bootstrap} connectSession={false} />);

  expect(screen.getByRole("status")).toHaveTextContent("Preparing your workspace");
  expect(await screen.findByRole("heading", { name: /Your agent workspace/i })).toBeVisible();
  expect(screen.getByText("local-model")).toBeVisible();
  expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
  expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expectNoAccessibilityViolations();
});

test("supports keyboard navigation to every staged product area", async () => {
  const user = userEvent.setup();
  render(<App loadBootstrap={async () => bootstrap} connectSession={false} />);

  const runtimeButtons = await screen.findAllByRole("button", { name: /Runtime/ });
  await user.click(runtimeButtons[0]);

  expect(await screen.findByRole("heading", { name: "Runtime" })).toBeVisible();
  expect(window.location.pathname).toBe("/runtime");
  expect(screen.getByText(/Tune this session/i)).toBeVisible();
});

test("shows an actionable error and retries bootstrap", async () => {
  const user = userEvent.setup();
  let calls = 0;
  const loader = async () => {
    calls += 1;
    if (calls === 1) throw new Error("Local host unavailable");
    return bootstrap;
  };
  render(<App loadBootstrap={loader} connectSession={false} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Local host unavailable");
  await user.click(screen.getByRole("button", { name: /Try again/ }));
  await waitFor(() => expect(screen.getByRole("heading", { name: /Your agent workspace/i })).toBeVisible());
  expect(calls).toBe(2);
});

test("opens and closes the complete mobile navigation drawer", async () => {
  const user = userEvent.setup();
  render(<App loadBootstrap={async () => bootstrap} connectSession={false} />);
  await screen.findByRole("heading", { name: /Your agent workspace/i });

  await user.click(screen.getByRole("button", { name: "Open navigation" }));
  expect(screen.getByRole("dialog", { name: "Navigate" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Close navigation" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "Navigate" })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "Open navigation" })).toHaveFocus());
});

test("opens global search from the top bar and restores focus on Escape", async () => {
  const user = userEvent.setup();
  render(<App loadBootstrap={async () => bootstrap} connectSession={false} />);
  await screen.findByRole("heading", { name: /Your agent workspace/i });
  const launcher = screen.getByRole("button", { name: /Search/ });

  await user.click(launcher);
  expect(screen.getByRole("dialog", { name: "OpenHarness search" })).toBeVisible();
  await waitFor(() => expect(screen.getByRole("searchbox", { name: "Search OpenHarness" })).toHaveFocus());
  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "OpenHarness search" })).not.toBeInTheDocument();
  await waitFor(() => expect(launcher).toHaveFocus());
});
