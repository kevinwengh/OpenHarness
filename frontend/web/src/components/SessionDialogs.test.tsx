import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { SessionDialogs } from "./SessionDialogs";

test("focuses the safe permission action and Escape denies the request", async () => {
  const user = userEvent.setup();
  const onPermission = vi.fn();
  render(
    <SessionDialogs
      modal={{ kind: "permission", request_id: "permission-1", tool_name: "bash", reason: "Run a command" }}
      selectRequest={null}
      onPermission={onPermission}
      onQuestion={vi.fn()}
      onSelect={vi.fn()}
      onDismissSelect={vi.fn()}
    />,
  );

  expect(screen.getByRole("button", { name: /Deny/ })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(onPermission).toHaveBeenCalledWith("permission-1", "reject");
});

test("keeps a question open when an empty answer cannot be submitted", async () => {
  const onQuestion = vi.fn();
  render(
    <SessionDialogs
      modal={{ kind: "question", request_id: "question-1", question: "Which branch?" }}
      selectRequest={null}
      onPermission={vi.fn()}
      onQuestion={onQuestion}
      onSelect={vi.fn()}
      onDismissSelect={vi.fn()}
    />,
  );

  expect(screen.getByRole("button", { name: "Send answer" })).toBeDisabled();
  expect(onQuestion).not.toHaveBeenCalled();
});
