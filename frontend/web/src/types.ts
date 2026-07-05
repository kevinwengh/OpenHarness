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
