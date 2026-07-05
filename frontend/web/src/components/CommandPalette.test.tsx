import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import type { NavigationItem } from "../types";
import { expectNoAccessibilityViolations } from "../test/accessibility";
import { CommandPalette } from "./CommandPalette";

const api = vi.hoisted(() => ({ fetchResource: vi.fn() }));
vi.mock("../api", () => api);

const navigation: NavigationItem[] = [
  { id: "overview", label: "Overview", description: "Runtime health", path: "/", depth: "inspect", availability: "available" },
  { id: "capabilities", label: "Capabilities", description: "Tools and skills", path: "/capabilities", depth: "inspect", availability: "available" },
];

beforeEach(() => {
  api.fetchResource.mockImplementation(async (area: string) => area === "sessions" ? {
    schema_version: 1,
    area,
    data: { sessions: [{ id: "session-1", summary: "Release planning", message_count: 12, model: "local-model", created_at: 1_788_000_000 }] },
  } : {
    schema_version: 1,
    area,
    data: {
      tools: [{ name: "read_file", description: "Read project files" }],
      commands: [{ name: "/memory", description: "Manage memory" }],
      skills: [{ name: "review", description: "Review a change" }],
      plugins: [],
      mcp: [],
      providers: [],
    },
  });
});

function renderPalette(overrides: Partial<Parameters<typeof CommandPalette>[0]> = {}) {
  const props = {
    open: true,
    navigation,
    runtimeCommands: ["/help"],
    onClose: vi.fn(),
    onNavigate: vi.fn(),
    onPrepareCommand: vi.fn(),
    onResume: vi.fn(() => true),
    ...overrides,
  };
  render(<CommandPalette {...props} />);
  return props;
}

test("searches bounded sessions and performs the explicitly labelled resume action", async () => {
  const user = userEvent.setup();
  const props = renderPalette();
  const search = screen.getByRole("searchbox", { name: "Search OpenHarness" });
  await waitFor(() => expect(search).toHaveFocus());
  await screen.findByText("Release planning");
  await user.type(search, "Release planning");

  const result = await screen.findByRole("button", { name: /Release planning.*Resume session/i });
  await expectNoAccessibilityViolations();
  await user.click(result);

  expect(props.onResume).toHaveBeenCalledWith("session-1");
  expect(props.onClose).toHaveBeenCalled();
});

test("prepares commands for review instead of executing them from search", async () => {
  const user = userEvent.setup();
  const props = renderPalette();
  const search = screen.getByRole("searchbox", { name: "Search OpenHarness" });
  await screen.findByText("/memory");
  await user.type(search, "/memory");
  await user.click(await screen.findByRole("button", { name: /\/memory.*Prepare command/i }));

  expect(props.onPrepareCommand).toHaveBeenCalledWith("/memory");
  expect(props.onResume).not.toHaveBeenCalled();
});

test("keeps navigation available when the optional local search index fails", async () => {
  api.fetchResource.mockRejectedValue(new Error("Index unavailable"));
  const user = userEvent.setup();
  const props = renderPalette();

  expect(await screen.findByRole("alert")).toHaveTextContent("Index unavailable");
  await user.click(screen.getByRole("button", { name: /Overview.*Open area/i }));
  expect(props.onNavigate).toHaveBeenCalledWith(navigation[0]);
});
