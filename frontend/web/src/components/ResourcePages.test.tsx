import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { AutopilotPage, CapabilitiesPage, KnowledgePage, WorkPage } from "./ResourcePages";
import { expectNoAccessibilityViolations } from "../test/accessibility";

const api = vi.hoisted(() => ({
  fetchResource: vi.fn(),
  postAction: vi.fn(),
}));

vi.mock("../api", () => api);

const snapshots = {
  capabilities: {
    schema_version: 1,
    area: "capabilities",
    data: {
      tools: [{ name: "read_file", description: "Read workspace files", source: "runtime" }],
      commands: [{ name: "/help", description: "Show help", source: "runtime" }],
      skills: [{ name: "review", description: "Review changes", source: "project", user_invocable: true }],
      plugins: [],
      hooks: [{ event: "pre_tool", count: 2 }],
      mcp: [{ name: "docs", state: "connected", transport: "stdio", tool_count: 3, resource_count: 1 }],
      providers: [{ name: "local", label: "Local", provider: "anthropic", model: "test-model", configured: true, active: true }],
      trust: { project_plugins_allowed: false, blocked_project_plugin_directories: 1 },
    },
  },
  work: {
    schema_version: 1,
    area: "work",
    data: {
      tasks: [{ id: "task-1", type: "agent", status: "running", description: "Review repository", created_at: "2026-07-05T12:00:00Z" }],
      bridges: [{ session_id: "bridge-1", status: "running", pid: 123, workspace: "demo", started_at: "2026-07-05T12:00:00Z" }],
      cron: [{ name: "digest", schedule: "0 */8 * * *", timezone: "UTC", enabled: true }],
      cron_history: [{ name: "digest", status: "completed", returncode: 0 }],
      scheduler_running: true,
    },
  },
  knowledge: {
    schema_version: 1,
    area: "knowledge",
    data: {
      memories: [
        { id: "one", title: "Python preference", description: "Use Python", preview: "", type: "project", category: "stack", source: "manual", tags: ["python"], disabled: false },
        { id: "two", title: "Retired note", description: "Old Java plan", preview: "", type: "project", category: "stack", source: "manual", tags: ["java"], disabled: true },
      ],
      limits: { returned: 2, maximum: 100 },
    },
  },
  autopilot: {
    schema_version: 1,
    area: "autopilot",
    data: {
      initialized: true,
      stats: { queued: 1, completed: 4 },
      cards: [{ id: "card-1", title: "Improve coverage", body: "Add browser tests", source_kind: "manual_idea", status: "queued", labels: ["quality"] }],
      journal: [{ timestamp: "2026-07-05T12:00:00Z", kind: "scan", summary: "Repository scanned" }],
    },
  },
} as const;

beforeEach(() => {
  api.fetchResource.mockImplementation(async (area: keyof typeof snapshots) => snapshots[area]);
  api.postAction.mockResolvedValue({ schema_version: 1, action: "test", message: "Action complete" });
});

test("capabilities exposes trust state, category counts, and searchable inventory", async () => {
  const user = userEvent.setup();
  render(<main><CapabilitiesPage /></main>);

  expect(await screen.findByRole("heading", { name: "Capabilities" })).toBeVisible();
  expect(screen.getByText(/1 project plugin directory is blocked/)).toBeVisible();
  expect(screen.getByText("read_file")).toBeVisible();

  await user.click(screen.getByRole("tab", { name: /MCP 1/ }));
  expect(screen.getByText("docs")).toBeVisible();
  expect(screen.getByText("connected")).toBeVisible();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: /Providers 1/ })).toHaveFocus();
  expect(screen.getByText("local")).toBeVisible();
  await user.click(screen.getByRole("tab", { name: /MCP 1/ }));
  await user.type(screen.getByRole("searchbox", { name: "Search capabilities" }), "missing");
  expect(screen.getByRole("heading", { name: "No matching capabilities" })).toBeVisible();
  await expectNoAccessibilityViolations();
});

test("work requires confirmation and sends only the selected allowlisted action", async () => {
  const user = userEvent.setup();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<main><WorkPage /></main>);
  await screen.findByRole("heading", { name: "Work" });

  await user.click(screen.getByRole("tab", { name: /Schedules 1/ }));
  const digest = screen.getByRole("article");
  await user.click(within(digest).getByRole("button", { name: "Run now" }));

  expect(confirm).toHaveBeenCalledWith("Run digest now? This executes the saved job immediately.");
  await waitFor(() => expect(api.postAction).toHaveBeenCalledWith("cron.run", { name: "digest" }));
  expect(await screen.findByText("Action complete")).toBeVisible();
  await expectNoAccessibilityViolations();
});

test("knowledge hides disabled memory by default and supports search", async () => {
  const user = userEvent.setup();
  render(<main><KnowledgePage /></main>);

  expect(await screen.findByText("Python preference")).toBeVisible();
  expect(screen.queryByText("Retired note")).not.toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: "Show disabled" }));
  expect(screen.getByText("Retired note")).toBeVisible();
  await user.type(screen.getByRole("searchbox", { name: "Search memory" }), "python");
  expect(screen.getByText("Python preference")).toBeVisible();
  expect(screen.queryByText("Retired note")).not.toBeInTheDocument();
  await expectNoAccessibilityViolations();
});

test("autopilot queues a bounded manual idea without starting a run", async () => {
  const user = userEvent.setup();
  api.postAction.mockResolvedValue({ schema_version: 1, action: "autopilot.enqueue", message: "Added card" });
  render(<main><AutopilotPage /></main>);
  await screen.findByRole("heading", { name: "Autopilot" });

  await user.type(screen.getByRole("textbox", { name: "Title" }), "Audit the API");
  await user.type(screen.getByRole("textbox", { name: /Context/ }), "Keep the transport bounded");
  await user.click(screen.getByRole("button", { name: "Add to Autopilot" }));

  await waitFor(() => expect(api.postAction).toHaveBeenCalledWith("autopilot.enqueue", {
    title: "Audit the API",
    body: "Keep the transport bounded",
  }));
  expect(await screen.findByText("Added card")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("");
  await expectNoAccessibilityViolations();
});

test("a resource failure is announced without rendering an unsafe response body", async () => {
  api.fetchResource.mockRejectedValue(new Error("Could not load capabilities"));
  render(<CapabilitiesPage />);

  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load capabilities");
  expect(screen.queryByRole("heading", { name: "Capability inventory" })).not.toBeInTheDocument();
});

test("refresh failure keeps the last successful snapshot visible", async () => {
  const user = userEvent.setup();
  render(<CapabilitiesPage />);
  expect(await screen.findByText("read_file")).toBeVisible();
  api.fetchResource.mockRejectedValueOnce(new Error("Refresh unavailable"));

  await user.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Refresh unavailable");
  expect(screen.getByText("read_file")).toBeVisible();
});

test("resource mutations are unavailable while the shared runtime is busy", async () => {
  const user = userEvent.setup();
  render(<WorkPage mutationsDisabled />);
  await screen.findByRole("heading", { name: "Work" });

  expect(screen.getByText("Actions paused during the active turn")).toBeVisible();
  await user.click(screen.getByRole("tab", { name: /Schedules 1/ }));
  expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
});
