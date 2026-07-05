import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { WebSessionState } from "../useWebSession";
import { Workbench } from "./Workbench";

const session: WebSessionState = {
  connection: "ready",
  reconnected: false,
  busy: false,
  transcript: [{ role: "assistant", text: "**Done** [unsafe](javascript:alert(1))" }],
  streamingText: "",
  runtime: {},
  tasks: [],
  commands: [],
  modal: null,
  selectRequest: null,
};

test("renders final assistant Markdown safely and accepts a prepared command draft", () => {
  render(
    <Workbench
      session={session}
      onSubmit={vi.fn(() => true)}
      onInterrupt={vi.fn()}
      onRequestSelect={vi.fn()}
      draftRequest={{ id: 1, value: "/memory" }}
    />,
  );

  expect(screen.getByText("Done").tagName).toBe("STRONG");
  expect(screen.getByText("unsafe").closest("a")).toBeNull();
  expect(screen.getByRole("textbox", { name: "Message OpenHarness" })).toHaveValue("/memory");
});
