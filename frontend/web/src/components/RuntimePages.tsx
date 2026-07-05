import { History, Plus, RefreshCw, Settings2, ShieldCheck, Sparkles } from "lucide-react";

import type { WebSessionState } from "../useWebSession";

export function SessionsPage({
  session,
  onBrowse,
  onNew,
}: {
  session: WebSessionState;
  onBrowse: () => void;
  onNew: () => void;
}) {
  return (
    <div className="page operational-page">
      <div className="operational-hero"><div className="preview-icon"><History /></div><p className="eyebrow">Conversation continuity</p><h1>Sessions</h1><p>Resume durable project history or start with a clean runtime while keeping the browser workspace in place.</p></div>
      <div className="action-grid">
        <button onClick={onBrowse} disabled={session.connection !== "ready" || session.busy}><History /><span><strong>Resume a session</strong><small>Browse recent project conversations and restore one through the canonical runtime command.</small></span></button>
        <button onClick={onNew} disabled={session.connection !== "ready" || session.busy}><Plus /><span><strong>Start a new session</strong><small>Close the current runtime cleanly; the local host will establish a fresh controller.</small></span></button>
      </div>
      <div className="operational-note"><RefreshCw /><span><strong>Current connection: {session.connection}</strong><small>{session.transcript.length} presentation events in this browser tab. Durable history remains owned by the session backend.</small></span></div>
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

export function RuntimePage({ session, onSelect }: { session: WebSessionState; onSelect: (command: string) => void }) {
  return (
    <div className="page operational-page">
      <div className="operational-hero"><div className="preview-icon"><Settings2 /></div><p className="eyebrow">Live session policy</p><h1>Runtime</h1><p>Inspect and change the active model, profile, reasoning, output, and permission controls through the same command handlers as the terminal.</p></div>
      <section className="runtime-summary" aria-label="Live runtime summary">
        <div><Sparkles /><span><small>Model</small><strong>{String(session.runtime.model ?? "Starting…")}</strong></span></div>
        <div><ShieldCheck /><span><small>Permission</small><strong>{String(session.runtime.permission_mode ?? "—")}</strong></span></div>
        <div><Settings2 /><span><small>Provider</small><strong>{String(session.runtime.provider ?? "—")}</strong></span></div>
      </section>
      <section className="control-list" aria-labelledby="runtime-controls-title">
        <div className="section-heading"><div><p className="eyebrow">Controls</p><h2 id="runtime-controls-title">Tune this session</h2></div><p>Changes are validated and applied by existing runtime command owners.</p></div>
        {controls.map(([command, label, description]) => <button key={command} onClick={() => onSelect(command)} disabled={session.connection !== "ready" || session.busy}><span><strong>{label}</strong><small>{description}</small></span><span className="control-value">Configure</span></button>)}
      </section>
    </div>
  );
}
