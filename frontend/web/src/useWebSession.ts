import { useCallback, useEffect, useRef, useState } from "react";

import { getLaunchToken } from "./api";
import type {
  BackendEvent,
  FrontendImageAttachment,
  FrontendRequest,
  SelectRequest,
  SessionModal,
  TranscriptItem,
} from "./types";

export type ConnectionState = "starting" | "authenticating" | "ready" | "reconnecting" | "closed" | "error";

export interface WebSessionState {
  connection: ConnectionState;
  reconnected: boolean;
  busy: boolean;
  busyLabel?: string;
  transcript: TranscriptItem[];
  streamingText: string;
  runtime: Record<string, unknown>;
  tasks: Array<Record<string, unknown>>;
  commands: string[];
  modal: SessionModal | null;
  selectRequest: SelectRequest | null;
  todoMarkdown?: string;
  lastError?: string;
}

const initialState: WebSessionState = {
  connection: "starting",
  reconnected: false,
  busy: false,
  transcript: [],
  streamingText: "",
  runtime: {},
  tasks: [],
  commands: [],
  modal: null,
  selectRequest: null,
};

function sessionUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/session`;
}

export function useWebSession({ enabled = true }: { enabled?: boolean } = {}) {
  const [state, setState] = useState<WebSessionState>(initialState);
  const socketRef = useRef<WebSocket | null>(null);
  const disposedRef = useRef(false);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const authenticatedRef = useRef(false);
  const shutdownReceivedRef = useRef(false);
  const restartOnShutdownRef = useRef(false);
  const pendingDeltaRef = useRef("");
  const deltaTimerRef = useRef<number | null>(null);

  const flushDelta = useCallback(() => {
    if (deltaTimerRef.current !== null) {
      window.clearTimeout(deltaTimerRef.current);
      deltaTimerRef.current = null;
    }
    const pending = pendingDeltaRef.current;
    if (!pending) return;
    pendingDeltaRef.current = "";
    setState((current) => ({ ...current, streamingText: current.streamingText + pending }));
  }, []);

  const appendTranscript = useCallback((item: TranscriptItem) => {
    setState((current) => ({ ...current, transcript: [...current.transcript, item].slice(-1_000) }));
  }, []);

  const handleEvent = useCallback((event: BackendEvent) => {
    if (event.type === "ready") {
      setState((current) => ({
        ...current,
        connection: "ready",
        runtime: event.state ?? current.runtime,
        tasks: event.tasks ?? current.tasks,
        commands: event.commands ?? current.commands,
      }));
      return;
    }
    if (event.type === "state_snapshot") {
      setState((current) => ({ ...current, runtime: event.state ?? current.runtime }));
      return;
    }
    if (event.type === "tasks_snapshot") {
      setState((current) => ({ ...current, tasks: event.tasks ?? [] }));
      return;
    }
    if (event.type === "transcript_item" && event.item) {
      appendTranscript(event.item);
      return;
    }
    if (event.type === "assistant_delta" && event.message) {
      pendingDeltaRef.current += event.message;
      if (pendingDeltaRef.current.length >= 320) flushDelta();
      else if (deltaTimerRef.current === null) deltaTimerRef.current = window.setTimeout(flushDelta, 40);
      return;
    }
    if (event.type === "assistant_complete") {
      flushDelta();
      setState((current) => ({
        ...current,
        transcript: [
          ...current.transcript,
          { role: "assistant" as const, text: event.message ?? current.streamingText },
        ].slice(-1_000),
        streamingText: "",
        busyLabel: undefined,
      }));
      return;
    }
    if ((event.type === "tool_started" || event.type === "tool_completed") && event.item) {
      appendTranscript({
        ...event.item,
        tool_name: event.item.tool_name ?? event.tool_name,
        tool_input: event.item.tool_input ?? event.tool_input,
        is_error: event.item.is_error ?? event.is_error,
      });
      setState((current) => ({
        ...current,
        busy: true,
        busyLabel: event.type === "tool_started" ? `Running ${event.tool_name ?? "tool"}…` : "Processing…",
      }));
      return;
    }
    if (event.type === "line_complete") {
      flushDelta();
      setState((current) => ({ ...current, busy: false, busyLabel: undefined, streamingText: "" }));
      return;
    }
    if (event.type === "compact_progress") {
      setState((current) => ({ ...current, busyLabel: event.message ?? "Compacting conversation…" }));
      return;
    }
    if (event.type === "modal_request") {
      setState((current) => ({ ...current, modal: (event.modal as SessionModal | null) ?? null }));
      return;
    }
    if (event.type === "select_request") {
      const modal = (event.modal ?? {}) as Record<string, unknown>;
      setState((current) => ({
        ...current,
        selectRequest: {
          title: String(modal.title ?? "Select"),
          command: String(modal.command ?? ""),
          options: event.select_options ?? [],
        },
      }));
      return;
    }
    if (event.type === "clear_transcript") {
      pendingDeltaRef.current = "";
      setState((current) => ({ ...current, transcript: [], streamingText: "" }));
      return;
    }
    if (event.type === "todo_update") {
      setState((current) => ({ ...current, todoMarkdown: event.todo_markdown }));
      return;
    }
    if (event.type === "error") {
      const message = event.message ?? "Unknown runtime error";
      appendTranscript({ role: "system", text: message, is_error: true });
      setState((current) => ({ ...current, busy: false, busyLabel: undefined, lastError: message }));
      return;
    }
    if (event.type === "shutdown") {
      shutdownReceivedRef.current = true;
      setState((current) => ({ ...current, connection: "closed", busy: false }));
    }
  }, [appendTranscript, flushDelta]);

  useEffect(() => {
    if (!enabled) {
      setState((current) => ({ ...current, connection: "closed" }));
      return;
    }
    disposedRef.current = false;
    const token = getLaunchToken();
    if (!token) {
      setState((current) => ({ ...current, connection: "error", lastError: "Missing local launch token" }));
      return;
    }

    const connect = () => {
      if (disposedRef.current) return;
      const reconnecting = reconnectAttemptRef.current > 0;
      setState((current) => ({ ...current, connection: reconnecting ? "reconnecting" : "starting" }));
      const socket = new WebSocket(sessionUrl());
      socketRef.current = socket;
      authenticatedRef.current = false;
      shutdownReceivedRef.current = false;
      socket.addEventListener("open", () => {
        setState((current) => ({ ...current, connection: "authenticating" }));
        socket.send(JSON.stringify({ type: "authenticate", token }));
      });
      socket.addEventListener("message", (message) => {
        let event: BackendEvent & { reconnected?: boolean; schema_version?: number };
        try {
          event = JSON.parse(String(message.data)) as BackendEvent & { reconnected?: boolean; schema_version?: number };
        } catch {
          setState((current) => ({ ...current, lastError: "Received an invalid session event" }));
          return;
        }
        if (event.type === "authenticated") {
          authenticatedRef.current = true;
          reconnectAttemptRef.current = 0;
          setState((current) => ({ ...current, connection: "ready", reconnected: Boolean(event.reconnected), lastError: undefined }));
          return;
        }
        handleEvent(event);
      });
      socket.addEventListener("close", (close) => {
        if (socketRef.current === socket) socketRef.current = null;
        if (disposedRef.current) return;
        if (shutdownReceivedRef.current && !restartOnShutdownRef.current) {
          setState((current) => ({ ...current, connection: "closed", busy: false }));
          return;
        }
        if (restartOnShutdownRef.current) {
          restartOnShutdownRef.current = false;
          shutdownReceivedRef.current = false;
        }
        if (close.code === 4401 || close.code === 4409) {
          setState((current) => ({ ...current, connection: "error", busy: false, lastError: close.reason || "Session authorization failed" }));
          return;
        }
        reconnectAttemptRef.current += 1;
        if (reconnectAttemptRef.current > 5) {
          setState((current) => ({ ...current, connection: "closed", busy: false, lastError: "The local runtime disconnected" }));
          return;
        }
        setState((current) => ({ ...current, connection: "reconnecting" }));
        reconnectTimerRef.current = window.setTimeout(connect, Math.min(250 * reconnectAttemptRef.current, 1_000));
      });
      socket.addEventListener("error", () => {
        if (!authenticatedRef.current) setState((current) => ({ ...current, lastError: "Could not reach the local runtime" }));
      });
    };
    connect();
    return () => {
      disposedRef.current = true;
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
      if (deltaTimerRef.current !== null) window.clearTimeout(deltaTimerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [enabled, handleEvent]);

  const send = useCallback((request: FrontendRequest): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !authenticatedRef.current) return false;
    socket.send(JSON.stringify(request));
    return true;
  }, []);

  return {
    state,
    submit(line: string, images: FrontendImageAttachment[] = []) {
      const accepted = send({ type: "submit_line", line, images });
      if (accepted) setState((current) => ({ ...current, busy: true, busyLabel: "Thinking…", lastError: undefined }));
      return accepted;
    },
    interrupt: () => send({ type: "interrupt" }),
    newSession() {
      const accepted = send({ type: "shutdown" });
      restartOnShutdownRef.current = accepted;
      return accepted;
    },
    requestSelect: (command: string) => send({ type: "select_command", command }),
    applySelect(command: string, value: string) {
      const accepted = send({ type: "apply_select_command", command, value });
      if (accepted) setState((current) => ({ ...current, selectRequest: null, busy: true, busyLabel: `Applying ${command}…` }));
      return accepted;
    },
    dismissSelect: () => setState((current) => ({ ...current, selectRequest: null })),
    respondPermission(requestId: string, reply: "once" | "always" | "reject") {
      const accepted = send({ type: "permission_response", request_id: requestId, allowed: reply !== "reject", permission_reply: reply });
      if (accepted) setState((current) => ({ ...current, modal: null }));
      return accepted;
    },
    respondQuestion(requestId: string, answer: string) {
      const accepted = send({ type: "question_response", request_id: requestId, answer });
      if (accepted) setState((current) => ({ ...current, modal: null }));
      return accepted;
    },
  };
}
