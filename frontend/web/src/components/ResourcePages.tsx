import {
  Activity,
  Archive,
  Boxes,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  CircleSlash2,
  Clock3,
  Gauge,
  History,
  Link2,
  ListFilter,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  Plug,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Square,
  TerminalSquare,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { type FormEvent, type KeyboardEvent, type ReactNode, useMemo, useState } from "react";

import { useResource } from "../useResource";

interface CapabilityItem {
  name?: string;
  description?: string;
  source?: string;
  enabled?: boolean;
  user_invocable?: boolean;
  tool_count?: number;
  skill_count?: number;
  event?: string;
  count?: number;
  state?: string;
  transport?: string;
  detail?: string;
  resource_count?: number;
  label?: string;
  provider?: string;
  model?: string;
  configured?: boolean;
  auth_state?: string;
  active?: boolean;
}

interface CapabilitiesData {
  tools: CapabilityItem[];
  commands: CapabilityItem[];
  skills: CapabilityItem[];
  plugins: CapabilityItem[];
  hooks: CapabilityItem[];
  mcp: CapabilityItem[];
  providers: CapabilityItem[];
  trust: {
    project_plugins_allowed: boolean;
    blocked_project_plugin_directories: number;
  };
}

interface WorkTask {
  id: string;
  type: string;
  status: string;
  description: string;
  created_at?: string;
  started_at?: string;
  ended_at?: string;
  progress?: number | string | null;
  status_note?: string;
}

interface BridgeSession {
  session_id: string;
  status: string;
  pid?: number;
  workspace: string;
  started_at?: string;
}

interface CronJob {
  name: string;
  schedule: string;
  timezone: string;
  enabled: boolean;
  next_run?: string;
  last_run?: string;
  last_status?: string;
}

interface CronHistory {
  name: string;
  status: string;
  started_at?: string;
  ended_at?: string;
  returncode?: number;
}

interface WorkData {
  tasks: WorkTask[];
  bridges: BridgeSession[];
  cron: CronJob[];
  cron_history: CronHistory[];
  scheduler_running: boolean;
}

interface MemoryItem {
  id: string;
  title: string;
  description: string;
  preview: string;
  type?: string;
  category?: string;
  importance?: string | number;
  source?: string;
  tags: string[];
  modified_at?: string;
  disabled: boolean;
}

interface KnowledgeData {
  memories: MemoryItem[];
  limits: { returned: number; maximum: number };
}

interface AutopilotCard {
  id: string;
  title: string;
  body: string;
  source_kind: string;
  source_ref?: string;
  status: string;
  score?: number;
  labels: string[];
  updated_at?: string;
}

interface JournalEntry {
  timestamp?: string;
  kind: string;
  summary: string;
  task_id?: string;
}

interface AutopilotData {
  initialized: boolean;
  stats: Record<string, number | string>;
  cards: AutopilotCard[];
  journal: JournalEntry[];
}

type TabDefinition<T extends string> = { id: T; label: string; count: number; icon: LucideIcon };

function ResourceHeading({
  icon: Icon,
  eyebrow,
  title,
  description,
  loading,
  onRefresh,
}: {
  icon: LucideIcon;
  eyebrow: string;
  title: string;
  description: string;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="resource-heading">
      <div className="operational-hero">
        <div className="preview-icon"><Icon aria-hidden="true" /></div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <button className="button resource-refresh" onClick={onRefresh} disabled={loading}>
        <RefreshCw className={loading ? "spin" : undefined} aria-hidden="true" />
        {loading ? "Refreshing" : "Refresh"}
      </button>
    </div>
  );
}

function ResourceFeedback({ loading, error, notice, hasData }: { loading: boolean; error: string | null; notice: string | null; hasData: boolean }) {
  return (
    <div className="resource-feedback" aria-live="polite">
      {loading && !hasData ? <div className="resource-message"><LoaderCircle className="spin" /><span><strong>Loading local state</strong><small>Reading a bounded snapshot from the OpenHarness runtime.</small></span></div> : null}
      {error ? <div className="resource-message resource-message--error" role="alert"><XCircle /><span><strong>Could not refresh this area</strong><small>{error}</small></span></div> : null}
      {notice ? <div className="resource-message resource-message--success"><CheckCircle2 /><span><strong>Action completed</strong><small>{notice}</small></span></div> : null}
    </div>
  );
}

function ResourceTabs<T extends string>({ tabs, active, onChange, label }: { tabs: TabDefinition<T>[]; active: T; onChange: (tab: T) => void; label: string }) {
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const last = tabs.length - 1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? last : event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
    onChange(tabs[next].id);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role='tab']");
    buttons?.[next]?.focus();
  };
  return (
    <div className="resource-tabs" role="tablist" aria-label={label}>
      {tabs.map(({ id, label: tabLabel, count, icon: Icon }, index) => (
        <button
          key={id}
          role="tab"
          aria-selected={active === id}
          tabIndex={active === id ? 0 : -1}
          className={active === id ? "resource-tab resource-tab--active" : "resource-tab"}
          onClick={() => onChange(id)}
          onKeyDown={(event) => moveFocus(event, index)}
        >
          <Icon aria-hidden="true" /><span>{tabLabel}</span><small>{count}</small>
        </button>
      ))}
    </div>
  );
}

function SearchField({ value, onChange, label, placeholder }: { value: string; onChange: (value: string) => void; label: string; placeholder: string }) {
  return (
    <label className="resource-search">
      <Search aria-hidden="true" />
      <span className="sr-only">{label}</span>
      <input type="search" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function EmptyResource({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <div className="resource-empty">
      <Icon aria-hidden="true" /><h2>{title}</h2><p>{children}</p>
    </div>
  );
}

function StatusBadge({ value, positive = false }: { value: string; positive?: boolean }) {
  const normalized = value.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return <span className={`resource-badge resource-badge--${positive ? "positive" : normalized}`}>{value}</span>;
}

function formatWhen(value?: string) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

const capabilityTabs: Array<{ id: keyof Omit<CapabilitiesData, "trust">; label: string; icon: LucideIcon }> = [
  { id: "tools", label: "Tools", icon: Wrench },
  { id: "commands", label: "Commands", icon: TerminalSquare },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "plugins", label: "Plugins", icon: Boxes },
  { id: "mcp", label: "MCP", icon: Plug },
  { id: "providers", label: "Providers", icon: Activity },
  { id: "hooks", label: "Hooks", icon: Link2 },
];

function capabilitySecondary(tab: keyof Omit<CapabilitiesData, "trust">, item: CapabilityItem) {
  if (tab === "plugins") return `${item.source ?? "unknown"} · ${item.tool_count ?? 0} tools · ${item.skill_count ?? 0} skills`;
  if (tab === "mcp") return `${item.transport ?? "unknown"} · ${item.tool_count ?? 0} tools · ${item.resource_count ?? 0} resources`;
  if (tab === "providers") return [item.provider, item.model].filter(Boolean).join(" · ");
  if (tab === "hooks") return `${item.count ?? 0} registered handlers`;
  return item.source ?? "runtime";
}

export function CapabilitiesPage() {
  const resource = useResource<CapabilitiesData>("capabilities");
  const [active, setActive] = useState<keyof Omit<CapabilitiesData, "trust">>("tools");
  const [query, setQuery] = useState("");
  const data = resource.data;
  const tabs = capabilityTabs.map((tab) => ({ ...tab, count: data?.[tab.id]?.length ?? 0 }));
  const items = useMemo(() => {
    const lowered = query.trim().toLowerCase();
    const current = data?.[active] ?? [];
    if (!lowered) return current;
    return current.filter((item) => JSON.stringify(item).toLowerCase().includes(lowered));
  }, [active, data, query]);

  return (
    <div className="page resource-page">
      <ResourceHeading icon={Boxes} eyebrow="Runtime inventory" title="Capabilities" description="Inspect the tools, commands, extensions, providers, and connection surfaces available to this local agent runtime." loading={resource.loading} onRefresh={resource.refresh} />
      <ResourceFeedback {...resource} hasData={data !== null} />
      {data?.trust.blocked_project_plugin_directories ? (
        <div className="trust-banner"><ShieldAlert /><span><strong>{data.trust.blocked_project_plugin_directories} project plugin {data.trust.blocked_project_plugin_directories === 1 ? "directory is" : "directories are"} blocked</strong><small>Project plugins stay unexecuted until explicitly allowed in settings.</small></span></div>
      ) : null}
      {data ? (
        <section className="resource-surface" aria-labelledby="capability-inventory-title">
          <div className="resource-surface-heading"><div><p className="eyebrow">Available now</p><h2 id="capability-inventory-title">Capability inventory</h2></div><SearchField value={query} onChange={setQuery} label="Search capabilities" placeholder={`Search ${active}`} /></div>
          <ResourceTabs tabs={tabs} active={active} onChange={(tab) => { setActive(tab); setQuery(""); }} label="Capability categories" />
          <div className="resource-list" role="tabpanel">
            {items.map((item, index) => {
              const title = item.name ?? item.event ?? `Item ${index + 1}`;
              const state = active === "providers" ? (item.active ? "active" : item.configured ? "configured" : item.auth_state === "unknown" ? "unknown" : "needs auth") : active === "mcp" ? item.state : item.enabled === false ? "disabled" : undefined;
              return (
                <article className="resource-row" key={`${title}-${index}`}>
                  <div className="resource-row-main"><strong>{title}</strong><p>{item.description || item.detail || capabilitySecondary(active, item)}</p><small>{capabilitySecondary(active, item)}</small></div>
                  {state ? <StatusBadge value={state} positive={state === "active" || state === "connected" || state === "configured"} /> : null}
                </article>
              );
            })}
            {items.length === 0 ? <EmptyResource icon={Search} title={query ? "No matching capabilities" : `No ${active} configured`}>{query ? "Try a broader search or choose another category." : "Use oh setup for providers, or the documented skill, plugin, hook, and MCP configuration paths for extensions."}</EmptyResource> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

type WorkTab = "tasks" | "cron" | "bridges" | "history";

const terminalTaskStates = new Set(["completed", "failed", "cancelled", "canceled", "stopped"]);

export function WorkPage({ mutationsDisabled = false }: { mutationsDisabled?: boolean }) {
  const resource = useResource<WorkData>("work");
  const [active, setActive] = useState<WorkTab>("tasks");
  const data = resource.data;
  const tabs: TabDefinition<WorkTab>[] = [
    { id: "tasks", label: "Tasks", count: data?.tasks.length ?? 0, icon: Activity },
    { id: "cron", label: "Schedules", count: data?.cron.length ?? 0, icon: CalendarClock },
    { id: "bridges", label: "Bridges", count: data?.bridges.length ?? 0, icon: Link2 },
    { id: "history", label: "Run history", count: data?.cron_history.length ?? 0, icon: History },
  ];
  const confirmAction = async (message: string, action: string, payload: Record<string, unknown>) => {
    if (window.confirm(message)) await resource.action(action, payload);
  };

  return (
    <div className="page resource-page">
      <ResourceHeading icon={CalendarClock} eyebrow="Background operations" title="Work" description="Monitor tasks, bridge sessions, recurring schedules, and recent scheduled runs without exposing their prompts or command bodies." loading={resource.loading} onRefresh={resource.refresh} />
      <ResourceFeedback {...resource} hasData={data !== null} />
      {mutationsDisabled ? <div className="operation-lock"><Pause /><span><strong>Actions paused during the active turn</strong><small>Wait for the Workbench to become idle or stop the current turn before changing background work.</small></span></div> : null}
      {data ? (
        <section className="resource-surface" aria-labelledby="work-queue-title">
          <div className="resource-surface-heading"><div><p className="eyebrow">Operational state</p><h2 id="work-queue-title">Work queue</h2></div><span className="scheduler-state"><span className={data.scheduler_running ? "dot dot--online" : "dot"} /> Scheduler {data.scheduler_running ? "running" : "stopped"}</span></div>
          <ResourceTabs tabs={tabs} active={active} onChange={setActive} label="Work categories" />
          <div className="resource-list" role="tabpanel">
            {active === "tasks" ? data.tasks.map((task) => (
              <article className="resource-row" key={task.id}>
                <div className="resource-row-main"><strong>{task.description || task.id}</strong><p>{task.status_note || `${task.type} task`}</p><small>{task.id} · created {formatWhen(task.created_at)}{task.progress != null ? ` · ${task.progress}%` : ""}</small></div>
                <div className="resource-row-actions"><StatusBadge value={task.status} positive={task.status === "running" || task.status === "completed"} />{!terminalTaskStates.has(task.status.toLowerCase()) ? <button className="row-action row-action--danger" disabled={mutationsDisabled || resource.pendingAction !== null} onClick={() => void confirmAction(`Stop task ${task.id}? Its active work will be interrupted.`, "task.stop", { task_id: task.id })}><Square /> Stop</button> : null}</div>
              </article>
            )) : null}
            {active === "cron" ? data.cron.map((job) => (
              <article className="resource-row" key={job.name}>
                <div className="resource-row-main"><strong>{job.name}</strong><p><code>{job.schedule}</code> · {job.timezone}</p><small>Next {formatWhen(job.next_run)} · Last {formatWhen(job.last_run)}{job.last_status ? ` · ${job.last_status}` : ""}</small></div>
                <div className="resource-row-actions"><StatusBadge value={job.enabled ? "enabled" : "disabled"} positive={job.enabled} /><button className="row-action" disabled={mutationsDisabled || resource.pendingAction !== null} onClick={() => void confirmAction(`${job.enabled ? "Disable" : "Enable"} schedule ${job.name}?`, "cron.toggle", { name: job.name, enabled: !job.enabled })}>{job.enabled ? <Pause /> : <Play />} {job.enabled ? "Disable" : "Enable"}</button><button className="row-action" disabled={mutationsDisabled || resource.pendingAction !== null} onClick={() => void confirmAction(`Run ${job.name} now? This executes the saved job immediately.`, "cron.run", { name: job.name })}><Play /> Run now</button></div>
              </article>
            )) : null}
            {active === "bridges" ? data.bridges.map((bridge) => (
              <article className="resource-row" key={bridge.session_id}>
                <div className="resource-row-main"><strong>{bridge.workspace || bridge.session_id}</strong><p>Bridge session {bridge.session_id}</p><small>PID {bridge.pid ?? "—"} · started {formatWhen(bridge.started_at)}</small></div>
                <div className="resource-row-actions"><StatusBadge value={bridge.status} positive={bridge.status === "running"} />{bridge.status.toLowerCase() !== "stopped" ? <button className="row-action row-action--danger" disabled={mutationsDisabled || resource.pendingAction !== null} onClick={() => void confirmAction(`Stop bridge ${bridge.session_id}? Connected work in that bridge will end.`, "bridge.stop", { session_id: bridge.session_id })}><Square /> Stop</button> : null}</div>
              </article>
            )) : null}
            {active === "history" ? data.cron_history.map((entry, index) => (
              <article className="resource-row" key={`${entry.name}-${entry.started_at}-${index}`}><div className="resource-row-main"><strong>{entry.name}</strong><p>Started {formatWhen(entry.started_at)}</p><small>Ended {formatWhen(entry.ended_at)} · return code {entry.returncode ?? "—"}</small></div><StatusBadge value={entry.status || "unknown"} positive={entry.status === "completed" || entry.status === "success"} /></article>
            )) : null}
            {((active === "tasks" && data.tasks.length === 0) || (active === "cron" && data.cron.length === 0) || (active === "bridges" && data.bridges.length === 0) || (active === "history" && data.cron_history.length === 0)) ? <EmptyResource icon={CircleSlash2} title={`No ${tabs.find((tab) => tab.id === active)?.label.toLowerCase()}`}>{active === "cron" ? "Ask the Workbench to create a scheduled job, then use oh cron start when you want the scheduler daemon running." : active === "bridges" ? "Use /bridge spawn in the Workbench when a child command needs a managed bridge session." : active === "history" ? "Run a saved schedule to create the first bounded history entry." : "Delegate background work from the Workbench to populate this queue."}</EmptyResource> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function KnowledgePage() {
  const resource = useResource<KnowledgeData>("knowledge");
  const [query, setQuery] = useState("");
  const [showDisabled, setShowDisabled] = useState(false);
  const memories = useMemo(() => {
    const lowered = query.trim().toLowerCase();
    return (resource.data?.memories ?? []).filter((memory) => {
      if (!showDisabled && memory.disabled) return false;
      if (!lowered) return true;
      return [memory.title, memory.description, memory.preview, memory.category, memory.source, ...memory.tags].join(" ").toLowerCase().includes(lowered);
    });
  }, [query, resource.data, showDisabled]);

  return (
    <div className="page resource-page">
      <ResourceHeading icon={BrainCircuit} eyebrow="Local context" title="Knowledge" description="Review bounded project memory metadata and previews used to carry durable context across agent sessions." loading={resource.loading} onRefresh={resource.refresh} />
      <ResourceFeedback {...resource} hasData={resource.data !== null} />
      {resource.data ? (
        <section className="resource-surface" aria-labelledby="memory-library-title">
          <div className="resource-surface-heading"><div><p className="eyebrow">Memory index</p><h2 id="memory-library-title">Knowledge library</h2><small>{resource.data.limits.returned} of at most {resource.data.limits.maximum} entries in this snapshot</small></div><div className="resource-filter-group"><SearchField value={query} onChange={setQuery} label="Search memory" placeholder="Search memory" /><label className="toggle-field"><input type="checkbox" checked={showDisabled} onChange={(event) => setShowDisabled(event.target.checked)} /><span>Show disabled</span></label></div></div>
          <div className="knowledge-grid">
            {memories.map((memory) => (
              <article className={`memory-entry${memory.disabled ? " memory-entry--disabled" : ""}`} key={memory.id}>
                <div className="memory-entry-heading"><div className="memory-icon"><Archive /></div><div><h3>{memory.title || "Untitled memory"}</h3><small>{[memory.type, memory.category, memory.source].filter(Boolean).join(" · ") || "local memory"}</small></div>{memory.disabled ? <StatusBadge value="disabled" /> : null}</div>
                <p>{memory.description || memory.preview || "No preview is available for this memory."}</p>
                {memory.description && memory.preview ? <blockquote>{memory.preview}</blockquote> : null}
                <div className="tag-list">{memory.tags.map((tag) => <span key={tag}>{tag}</span>)}{memory.modified_at ? <time dateTime={memory.modified_at}>Updated {formatWhen(memory.modified_at)}</time> : null}</div>
              </article>
            ))}
            {memories.length === 0 ? <EmptyResource icon={Search} title={query ? "No matching memory" : "No visible memory"}>{query ? "Try different terms or include disabled entries." : "Use /memory add in the Workbench to create durable project context, or include disabled entries to inspect them."}</EmptyResource> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

type AutopilotTab = "cards" | "journal";

function statLabel(value: string) {
  return value.replaceAll("_", " ");
}

export function AutopilotPage({ mutationsDisabled = false }: { mutationsDisabled?: boolean }) {
  const resource = useResource<AutopilotData>("autopilot");
  const [active, setActive] = useState<AutopilotTab>("cards");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const data = resource.data;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const created = await resource.action("autopilot.enqueue", { title: title.trim(), body: body.trim() });
    if (created) { setTitle(""); setBody(""); }
  };
  const tabs: TabDefinition<AutopilotTab>[] = [
    { id: "cards", label: "Work intake", count: data?.cards.length ?? 0, icon: ListFilter },
    { id: "journal", label: "Journal", count: data?.journal.length ?? 0, icon: History },
  ];

  return (
    <div className="page resource-page">
      <ResourceHeading icon={Gauge} eyebrow="Repository operations" title="Autopilot" description="Inspect repository work intake and run history, or add a bounded manual idea to the existing Autopilot registry." loading={resource.loading} onRefresh={resource.refresh} />
      <ResourceFeedback {...resource} hasData={data !== null} />
      {mutationsDisabled ? <div className="operation-lock"><Pause /><span><strong>Intake paused during the active turn</strong><small>Wait for the Workbench to become idle or stop the current turn before changing repository work intake.</small></span></div> : null}
      {data ? (
        <>
          <section className="autopilot-overview" aria-label="Autopilot status">
            <div className="stat-strip">
              {Object.entries(data.stats).slice(0, 6).map(([label, value]) => <div key={label}><small>{statLabel(label)}</small><strong>{String(value)}</strong></div>)}
              {Object.keys(data.stats).length === 0 ? <div><small>Registry</small><strong>{data.initialized ? "Ready" : "Not initialized"}</strong></div> : null}
            </div>
            <form className="intake-form" onSubmit={(event) => void submit(event)}>
              <div><p className="eyebrow"><Plus /> Manual intake</p><h2>Add an idea</h2><p>Queue a repository-scoped idea without starting an agent run.</p></div>
              <label><span>Title</span><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required placeholder="Describe the outcome" /></label>
              <label><span>Context <small>optional</small></span><textarea value={body} onChange={(event) => setBody(event.target.value)} maxLength={20_000} rows={4} placeholder="Add constraints, evidence, or acceptance notes" /></label>
              <button className="button button--primary" type="submit" disabled={mutationsDisabled || !title.trim() || resource.pendingAction !== null}>{resource.pendingAction === "autopilot.enqueue" ? <LoaderCircle className="spin" /> : <Plus />} Add to Autopilot</button>
            </form>
          </section>
          <section className="resource-surface" aria-labelledby="autopilot-activity-title">
            <div className="resource-surface-heading"><div><p className="eyebrow">Registry</p><h2 id="autopilot-activity-title">Autopilot activity</h2></div>{!data.initialized ? <span className="scheduler-state"><span className="dot" /> Initializes on first intake</span> : null}</div>
            <ResourceTabs tabs={tabs} active={active} onChange={setActive} label="Autopilot categories" />
            <div className="resource-list" role="tabpanel">
              {active === "cards" ? data.cards.map((card) => <article className="resource-row" key={card.id}><div className="resource-row-main"><strong>{card.title}</strong><p>{card.body || "No additional context."}</p><small>{card.source_kind}{card.source_ref ? ` · ${card.source_ref}` : ""} · updated {formatWhen(card.updated_at)}</small><div className="tag-list">{card.labels.map((label) => <span key={label}>{label}</span>)}</div></div><div className="resource-row-actions"><StatusBadge value={card.status} positive={card.status === "queued" || card.status === "completed"} />{card.score != null ? <span className="score">Score {card.score}</span> : null}</div></article>) : null}
              {active === "journal" ? data.journal.map((entry, index) => <article className="resource-row" key={`${entry.timestamp}-${entry.kind}-${index}`}><div className="resource-row-main"><strong>{entry.kind}</strong><p>{entry.summary}</p><small>{formatWhen(entry.timestamp)}{entry.task_id ? ` · task ${entry.task_id}` : ""}</small></div><Clock3 /></article>) : null}
              {((active === "cards" && data.cards.length === 0) || (active === "journal" && data.journal.length === 0)) ? <EmptyResource icon={active === "cards" ? ListFilter : History} title={active === "cards" ? "No work intake yet" : "No journal activity yet"}>{active === "cards" ? "Use the manual intake form to create the first queued idea." : "Journal events appear after Autopilot processes repository work."}</EmptyResource> : null}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
