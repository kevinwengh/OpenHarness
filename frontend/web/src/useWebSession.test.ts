import { act, renderHook } from "@testing-library/react";
import { vi } from "vitest";

import { useWebSession } from "./useWebSession";

type Listener = (event: Event & { data?: string; code?: number; reason?: string }) => void;

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readonly sent: string[] = [];
  readyState = 0;
  private listeners = new Map<string, Listener[]>();

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(name: string, listener: Listener) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  send(value: string) {
    this.sent.push(value);
  }

  close() {
    this.readyState = 3;
  }

  emit(name: string, detail: Record<string, unknown> = {}) {
    const event = { type: name, ...detail } as Event & { data?: string; code?: number; reason?: string };
    for (const listener of this.listeners.get(name) ?? []) listener(event);
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  window.sessionStorage.setItem("openharness.web.launch-token", "test-token");
  Object.defineProperty(window, "WebSocket", { configurable: true, value: FakeWebSocket });
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, value: FakeWebSocket });
});

test("authenticates, reduces streamed events, and submits typed requests", () => {
  const { result, unmount } = renderHook(() => useWebSession());
  const socket = FakeWebSocket.instances[0];

  act(() => {
    socket.readyState = FakeWebSocket.OPEN;
    socket.emit("open");
  });
  expect(JSON.parse(socket.sent[0])).toEqual({ type: "authenticate", token: "test-token" });

  act(() => {
    socket.emit("message", { data: JSON.stringify({ type: "authenticated", schema_version: 1, reconnected: false }) });
    socket.emit("message", { data: JSON.stringify({ type: "ready", state: { model: "test-model" }, tasks: [], commands: ["/help"] }) });
    socket.emit("message", { data: JSON.stringify({ type: "transcript_item", item: { role: "user", text: "hello" } }) });
    socket.emit("message", { data: JSON.stringify({ type: "assistant_delta", message: "hi " }) });
    socket.emit("message", { data: JSON.stringify({ type: "assistant_complete", message: "hi there" }) });
    socket.emit("message", { data: JSON.stringify({ type: "line_complete" }) });
  });

  expect(result.current.state.connection).toBe("ready");
  expect(result.current.state.runtime.model).toBe("test-model");
  expect(result.current.state.transcript).toEqual([
    { role: "user", text: "hello" },
    { role: "assistant", text: "hi there" },
  ]);
  let accepted = false;
  act(() => { accepted = result.current.submit("next"); });
  expect(accepted).toBe(true);
  expect(JSON.parse(socket.sent.at(-1)!)).toEqual({ type: "submit_line", line: "next", images: [] });
  expect(result.current.state.busy).toBe(true);
  unmount();
});

test("resolves permission prompts with correlated fail-closed replies", () => {
  const { result, unmount } = renderHook(() => useWebSession());
  const socket = FakeWebSocket.instances[0];
  act(() => {
    socket.readyState = FakeWebSocket.OPEN;
    socket.emit("open");
    socket.emit("message", { data: JSON.stringify({ type: "authenticated", schema_version: 1, reconnected: false }) });
    socket.emit("message", { data: JSON.stringify({ type: "modal_request", modal: { kind: "permission", request_id: "request-1", tool_name: "bash", reason: "run command" } }) });
  });

  expect(result.current.state.modal?.request_id).toBe("request-1");
  act(() => { result.current.respondPermission("request-1", "reject"); });
  expect(JSON.parse(socket.sent.at(-1)!)).toEqual({
    type: "permission_response",
    request_id: "request-1",
    allowed: false,
    permission_reply: "reject",
  });
  expect(result.current.state.modal).toBeNull();
  unmount();
});

test("does not restart a runtime that shut down without an explicit new-session request", () => {
  const { result, unmount } = renderHook(() => useWebSession());
  const socket = FakeWebSocket.instances[0];
  act(() => {
    socket.readyState = FakeWebSocket.OPEN;
    socket.emit("open");
    socket.emit("message", { data: JSON.stringify({ type: "authenticated", schema_version: 1, reconnected: false }) });
    socket.emit("message", { data: JSON.stringify({ type: "shutdown" }) });
    socket.emit("close", { code: 1000, reason: "complete" });
  });

  expect(result.current.state.connection).toBe("closed");
  expect(FakeWebSocket.instances).toHaveLength(1);
  unmount();
});

test("reconnects after shutdown only when a new session was explicitly requested", () => {
  vi.useFakeTimers();
  const { result, unmount } = renderHook(() => useWebSession());
  const socket = FakeWebSocket.instances[0];
  act(() => {
    socket.readyState = FakeWebSocket.OPEN;
    socket.emit("open");
    socket.emit("message", { data: JSON.stringify({ type: "authenticated", schema_version: 1, reconnected: false }) });
    result.current.newSession();
    socket.emit("message", { data: JSON.stringify({ type: "shutdown" }) });
    socket.emit("close", { code: 1000, reason: "new session" });
    vi.advanceTimersByTime(250);
  });

  expect(FakeWebSocket.instances).toHaveLength(2);
  unmount();
  vi.useRealTimers();
});
