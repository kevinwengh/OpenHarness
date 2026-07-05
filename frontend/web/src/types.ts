export type NavigationId =
  | "overview"
  | "workbench"
  | "sessions"
  | "runtime"
  | "capabilities"
  | "work"
  | "knowledge"
  | "autopilot";

export interface NavigationItem {
  id: NavigationId;
  label: string;
  description: string;
  path: string;
  depth: "operate" | "configure" | "inspect";
  availability: "available" | "coming_soon";
}

export interface WebBootstrap {
  schema_version: 1;
  app: {
    name: string;
    version: string;
  };
  workspace: {
    name: string;
    path: string;
  };
  runtime: {
    profile: string;
    provider: string;
    model: string;
    auth: {
      state: "configured" | "missing" | "unknown";
      label: string;
    };
    permission_mode: string;
    sandbox_enabled: boolean;
    sandbox_backend: string;
    effort: string;
    max_turns: number;
  };
  navigation: NavigationItem[];
}

export interface FrontendImageAttachment {
  media_type: string;
  data: string;
  source_path?: string;
}

export type FrontendRequest =
  | { type: "submit_line"; line: string; images?: FrontendImageAttachment[] }
  | { type: "permission_response"; request_id: string; allowed: boolean; permission_reply?: "once" | "always" | "reject" }
  | { type: "question_response"; request_id: string; answer: string }
  | { type: "list_sessions" }
  | { type: "select_command"; command: string }
  | { type: "apply_select_command"; command: string; value: string }
  | { type: "interrupt" }
  | { type: "shutdown" };

export interface TranscriptItem {
  role: "system" | "user" | "assistant" | "tool" | "tool_result" | "log" | "status";
  text: string;
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  is_error?: boolean;
}

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  active?: boolean;
}

export interface SelectRequest {
  title: string;
  command: string;
  options: SelectOption[];
}

export interface SessionModal {
  kind: "permission" | "edit_diff" | "question" | string;
  request_id: string;
  tool_name?: string;
  reason?: string;
  question?: string;
  path?: string;
  diff?: string;
  added?: number;
  removed?: number;
}

export interface BackendEvent {
  type: string;
  message?: string;
  item?: TranscriptItem;
  state?: Record<string, unknown>;
  tasks?: Array<Record<string, unknown>>;
  commands?: string[];
  modal?: SessionModal | null | Record<string, unknown>;
  select_options?: SelectOption[];
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  output?: string;
  is_error?: boolean;
  todo_markdown?: string;
}

export type ResourceArea = "sessions" | "capabilities" | "work" | "knowledge" | "autopilot";

export interface ResourceSnapshot<T = Record<string, unknown>> {
  schema_version: 1;
  area: ResourceArea;
  data: T;
}

export interface ActionResult {
  schema_version: 1;
  action: string;
  message: string;
  resource?: Record<string, unknown>;
}
