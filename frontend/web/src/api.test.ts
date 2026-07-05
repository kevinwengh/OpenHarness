import { afterEach, expect, test, vi } from "vitest";

import { consumeLaunchToken, fetchResource, getLaunchToken, postAction } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

test("consumes the launch token from the fragment without leaving it in history", () => {
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/#token=fragment-secret");

  expect(consumeLaunchToken()).toBe("fragment-secret");
  expect(window.location.hash).toBe("");
  expect(window.location.href).not.toContain("fragment-secret");
  expect(getLaunchToken()).toBe("fragment-secret");
});

test("uses bearer auth for resource reads and JSON for allowlisted mutations", async () => {
  window.history.replaceState({}, "", "/#token=resource-secret");
  consumeLaunchToken();
  const fetchMock = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, area: "work", data: { tasks: [] } })))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ schema_version: 1, action: "cron.toggle", message: "updated" })),
    );

  await fetchResource("work");
  await postAction("cron.toggle", { name: "digest", enabled: false });

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "/api/work",
    expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer resource-secret" }) }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    "/api/actions/cron.toggle",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "digest", enabled: false }),
      headers: expect.objectContaining({
        Authorization: "Bearer resource-secret",
        "Content-Type": "application/json",
      }),
    }),
  );
});

test("reports a status-only fallback when an API error body is not JSON", async () => {
  window.history.replaceState({}, "", "/#token=resource-secret");
  consumeLaunchToken();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("unsafe html", { status: 502 }));

  await expect(fetchResource("knowledge")).rejects.toEqual(
    expect.objectContaining({ status: 502, message: "The local host returned 502." }),
  );
});
