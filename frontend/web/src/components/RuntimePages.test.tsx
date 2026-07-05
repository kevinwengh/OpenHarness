import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import { expectNoAccessibilityViolations } from "../test/accessibility";
import type { WebBootstrap } from "../types";
import type { WebSessionState } from "../useWebSession";
import { RuntimePage, SessionsPage } from "./RuntimePages";

const api = vi.hoisted(() => ({ fetchResource: vi.fn() }));
vi.mock("../api", () => api);

const session: WebSessionState = {
  connection: "ready",
  reconnected: false,
  busy: false,
  transcript: [],
  streamingText: "",
  runtime: { model: "local-model", provider: "anthropic", permission_mode: "Default" },
  tasks: [],
  commands: [],
  modal: null,
  selectRequest: null,
};

const runtime: WebBootstrap["runtime"] = {
  profile: "local",
  provider: "anthropic",
  model: "local-model",
  auth: { state: "configured", label: "local_token" },
  permission_mode: "default",
  sandbox_enabled: true,
  sandbox_backend: "docker",
  effort: "medium",
  max_turns: 200,
};

beforeEach(() => {
  api.fetchResource.mockResolvedValue({
    schema_version: 1,
    area: "sessions",
    data: {
      sessions: [{ id: "session-one", summary: "Review the release", message_count: 8, model: "local-model", created_at: 1_788_000_000 }],
      limits: { returned: 1, maximum: 20 },
    },
  });
});

test("sessions presents bounded project history and resumes through the runtime owner", async () => {
  const user = userEvent.setup();
  const onResume = vi.fn();
  render(<main><SessionsPage session={session} onBrowse={vi.fn()} onNew={vi.fn()} onResume={onResume} /></main>);

  expect(await screen.findByText("Review the release")).toBeVisible();
  expect(screen.getByText(/8 messages/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Resume" }));
  expect(onResume).toHaveBeenCalledWith("session-one");
  await expectNoAccessibilityViolations();
});

test("runtime exposes fixed sandbox policy and canonical selectors", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(<main><RuntimePage session={session} sandbox={runtime} onSelect={onSelect} /></main>);

  expect(screen.getByText("docker")).toBeVisible();
  expect(screen.getByText(/Sandbox policy is fixed/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: /Reasoning effort/ }));
  expect(onSelect).toHaveBeenCalledWith("effort");
  await expectNoAccessibilityViolations();
});
