import axe from "axe-core";
import { expect } from "vitest";

export async function expectNoAccessibilityViolations(root: HTMLElement = document.body) {
  const results = await axe.run(root, {
    rules: {
      // jsdom has no layout/paint engine, so contrast needs rendered-browser review.
      "color-contrast": { enabled: false },
    },
  });
  expect(
    results.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      nodes: violation.nodes.map((node) => node.target.join(" ")),
    })),
  ).toEqual([]);
}
