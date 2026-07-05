import { History, Plus, RefreshCw, Settings2, ShieldCheck, Sparkles } from "lucide-react";

import type { WebBootstrap } from "../types";
import { useResource } from "../useResource";
import type { WebSessionState } from "../useWebSession";

interface SessionSummary {
  id: string;
  summary: string;
  message_count: number;
  model: string;
  created_at?: string | number;
}

interface SessionResourceData {
  sessions: SessionSummary[];
  limits: { returned: number; maximum: number };
}

function formatSessionTime(value?: string | number) {
  if (value == null) return "Unknown time";
  const timestamp = typeof value === "number" && value < 10_000_000_000 ? value * 1_000 : value;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? "Unknown time" : parsed.toLocaleString();
}

export function SessionsPage({
  session,
  onBrowse,
  onNew,
  onResume,
}: {
  session: WebSessionState;
  onBrowse: () => void;
  onNew: () => void;
  onResume: (sessionId: string) => void;
}) {
  const resource = useResource<SessionResourceData>("sessions");
  return (
    <div className="page operational-page">
      <div className="operational-hero"><div className="preview-icon"><History /></div><p className="eyebrow">Conversation continuity</p><h1>Sessions</h1><p>Resume durable project history or start with a clean runtime while keeping the browser workspace in place.</p></div>
      <div className="action-grid">
        <button onClick={onBrowse} disabled={session.connection !== "ready" || session.busy}><History /><span><strong>Resume a session</strong><small>Browse recent project conversations and restore one through the canonical runtime command.</small></span></button>
        <button onClick={onNew} disabled={session.connection !== "ready" || session.busy}><Plus /><span><strong>Start a new session</strong><small>Close the current runtime cleanly; the local host will establish a fresh controller.</small></span></button>
      </div>
      <div className="operational-note"><RefreshCw /><span><strong>Current connection: {session.connection}</strong><small>{session.transcript.length} presentation events in this browser tab. Durable history remains owned by the session backend.</small></span></div>
      <section className="resource-surface" aria-labelledby="recent-sessions-title">
        <div className="resource-surface-heading"><div><p className="eyebrow">Project history</p><h2 id="recent-sessions-title">Recent sessions</h2>{resource.data ? <small>{resource.data.limits.returned} of at most {resource.data.limits.maximum} bounded summaries</small> : null}</div><button className="button" onClick={resource.refresh} disabled={resource.loading}><RefreshCw className={resource.loading ? "spin" : undefined} /> Refresh</button></div>
        {resource.error ? <div className="resource-message resource-message--error" role="alert"><span><strong>Could not refresh sessions</strong><small>{resource.error}</small></span></div> : null}
        {resource.loading && !resource.data ? <div className="resource-message"><RefreshCw className="spin" /><span><strong>Loading project history</strong><small>Reading bounded session summaries.</small></span></div> : null}
        {resource.data ? <div className="resource-list">{resource.data.sessions.map((item) => <article className="resource-row" key={item.id}><div className="resource-row-main"><strong>{item.summary}</strong><p>{item.model || "Unknown model"}</p><small>{formatSessionTime(item.created_at)} · {item.message_count} messages · {item.id}</small></div><button className="row-action" disabled={session.connection !== "ready" || session.busy} onClick={() => onResume(item.id)}>Resume</button></article>)}{resource.data.sessions.length === 0 ? <div className="resource-empty"><History /><h2>No saved sessions</h2><p>Complete a Workbench turn to create durable project history.</p></div> : null}</div> : null}
      </section>
    </div>
  );
}

const controls = [
  ["provider", "Provider profile", "Choose the configured provider and auth workflow."],
  ["model", "Model", "Select an allowed or provider-compatible model."],
  ["permissions", "Permission mode", "Default, Plan Mode, or Auto policy."],
  ["effort", "Reasoning effort", "Balance latency and depth for this session."],
  ["turns", "Turn limit", "Bound or uncap agentic turns."],
  ["fast", "Fast mode", "Prefer shorter, faster responses."],
  ["passes", "Reasoning passes", "Choose the configured multi-pass count."],
  ["output-style", "Output style", "Adjust how completed responses are presented."],
] as const;

export function RuntimePage({ session, sandbox, onSelect }: { session: WebSessionState; sandbox: WebBootstrap["runtime"]; onSelect: (command: string) => void }) {
  return (
    <div className="page operational-page">
      <div className="operational-hero"><div className="preview-icon"><Settings2 /></div><p className="eyebrow">Live session policy</p><h1>Runtime</h1><p>Inspect and change the active model, profile, reasoning, output, and permission controls through the same command handlers as the terminal.</p></div>
      <section className="runtime-summary" aria-label="Live runtime summary">
        <div><Sparkles /><span><small>Model</small><strong>{String(session.runtime.model ?? "Starting…")}</strong></span></div>
        <div><ShieldCheck /><span><small>Permission</small><strong>{String(session.runtime.permission_mode ?? "—")}</strong></span></div>
        <div><Settings2 /><span><small>Provider</small><strong>{String(session.runtime.provider ?? "—")}</strong></span></div>
        <div><ShieldCheck /><span><small>Sandbox</small><strong>{sandbox.sandbox_enabled ? sandbox.sandbox_backend : "Disabled"}</strong></span></div>
      </section>
      <div className="operational-note"><ShieldCheck /><span><strong>Sandbox lifecycle</strong><small>Sandbox policy is fixed when this runtime starts. Change settings from the canonical CLI and start a new runtime to apply it safely.</small></span></div>
      <section className="control-list" aria-labelledby="runtime-controls-title">
        <div className="section-heading"><div><p className="eyebrow">Controls</p><h2 id="runtime-controls-title">Tune this session</h2></div><p>Changes are validated and applied by existing runtime command owners.</p></div>
        {controls.map(([command, label, description]) => <button key={command} onClick={() => onSelect(command)} disabled={session.connection !== "ready" || session.busy}><span><strong>{label}</strong><small>{description}</small></span><span className="control-value">Configure</span></button>)}
      </section>
    </div>
  );
}
