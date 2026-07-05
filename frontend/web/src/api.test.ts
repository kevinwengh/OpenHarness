import { consumeLaunchToken, getLaunchToken } from "./api";

test("consumes the launch token from the fragment without leaving it in history", () => {
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/#token=fragment-secret");

  expect(consumeLaunchToken()).toBe("fragment-secret");
  expect(window.location.hash).toBe("");
  expect(window.location.href).not.toContain("fragment-secret");
  expect(getLaunchToken()).toBe("fragment-secret");
});
