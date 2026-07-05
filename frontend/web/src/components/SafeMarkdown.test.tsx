import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { SafeMarkdown } from "./SafeMarkdown";

test("renders useful GFM without enabling raw HTML", () => {
  const { container } = render(
    <SafeMarkdown>{"**Ready**\n\n- one\n- two\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n<img src=x onerror=alert(1)>"}</SafeMarkdown>,
  );

  expect(screen.getByText("Ready").tagName).toBe("STRONG");
  expect(screen.getByRole("list")).toBeVisible();
  expect(screen.getByRole("table")).toBeVisible();
  expect(container.querySelector("img")).not.toBeInTheDocument();
  expect(container.innerHTML).not.toContain("onerror");
});

test("allows bounded web and relative links while removing unsafe protocols", () => {
  render(
    <SafeMarkdown>{"[docs](https://example.com/docs) [local](/knowledge) [unsafe](javascript:alert(1)) [data](data:text/html,bad)"}</SafeMarkdown>,
  );

  expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("href", "https://example.com/docs");
  expect(screen.getByRole("link", { name: "docs" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.getByRole("link", { name: "local" })).toHaveAttribute("href", "/knowledge");
  expect(screen.getByText("unsafe").closest("a")).toBeNull();
  expect(screen.getByText("data").closest("a")).toBeNull();
});

test("does not load model-authored remote images", () => {
  const { container } = render(<SafeMarkdown>{"![tracking pixel](https://example.com/pixel.gif)"}</SafeMarkdown>);

  expect(screen.getByText("[Image omitted: tracking pixel]")).toBeVisible();
  expect(container.querySelector("img")).not.toBeInTheDocument();
});
