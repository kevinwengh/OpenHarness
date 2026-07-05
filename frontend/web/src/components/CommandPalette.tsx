import { ArrowUpRight, Boxes, Clock3, Command, Search, TerminalSquare, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { fetchResource } from "../api";
import type { NavigationItem } from "../types";

interface SessionSummary {
  id: string;
  summary: string;
  message_count: number;
  model: string;
  created_at?: string | number;
}

interface SessionSearchData {
  sessions: SessionSummary[];
}

interface CapabilitySummary {
  name?: string;
  event?: string;
  description?: string;
  detail?: string;
  label?: string;
}

interface CapabilitySearchData {
  tools: CapabilitySummary[];
  commands: CapabilitySummary[];
  skills: CapabilitySummary[];
  plugins: CapabilitySummary[];
  mcp: CapabilitySummary[];
  providers: CapabilitySummary[];
}

interface PaletteItem {
  id: string;
  group: "Navigation" | "Sessions" | "Commands" | "Capabilities";
  label: string;
  detail: string;
  actionLabel: string;
  keywords: string;
  activate: () => boolean | void;
}

function formatSessionTime(value?: string | number) {
  if (value == null) return "Saved session";
  const timestamp = typeof value === "number" && value < 10_000_000_000 ? value * 1_000 : value;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? "Saved session" : parsed.toLocaleString();
}

export function CommandPalette({
  open,
  navigation,
  runtimeCommands,
  onClose,
  onNavigate,
  onPrepareCommand,
  onResume,
}: {
  open: boolean;
  navigation: NavigationItem[];
  runtimeCommands: string[];
  onClose: () => void;
  onNavigate: (item: NavigationItem) => void;
  onPrepareCommand: (command: string) => void;
  onResume: (sessionId: string) => boolean;
}) {
  const [query, setQuery] = useState("");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilitySearchData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setQuery("");
    setError(null);
    setLoading(true);
    window.requestAnimationFrame(() => inputRef.current?.focus());
    Promise.all([
      fetchResource<SessionSearchData>("sessions", controller.signal),
      fetchResource<CapabilitySearchData>("capabilities", controller.signal),
    ]).then(([sessionSnapshot, capabilitySnapshot]) => {
      setSessions(sessionSnapshot.data.sessions);
      setCapabilities(capabilitySnapshot.data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load local search data");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [open]);

  const items = useMemo(() => {
    const result: PaletteItem[] = [];
    const seen = new Set<string>();
    const push = (item: PaletteItem) => {
      if (seen.has(item.id)) return;
      seen.add(item.id);
      result.push(item);
    };
    navigation.forEach((item) => push({
      id: `nav:${item.id}`,
      group: "Navigation",
      label: item.label,
      detail: item.description,
      actionLabel: "Open area",
      keywords: `${item.label} ${item.description} ${item.depth}`,
      activate: () => onNavigate(item),
    }));
    sessions.forEach((session) => push({
      id: `session:${session.id}`,
      group: "Sessions",
      label: session.summary || "Untitled session",
      detail: `${formatSessionTime(session.created_at)} · ${session.message_count} messages${session.model ? ` · ${session.model}` : ""}`,
      actionLabel: "Resume session",
      keywords: `${session.id} ${session.summary} ${session.model}`,
      activate: () => onResume(session.id),
    }));
    const commandNames = [
      ...runtimeCommands,
      ...(capabilities?.commands ?? []).map((item) => item.name ?? ""),
    ];
    commandNames.filter(Boolean).forEach((command) => {
      const normalized = command.startsWith("/") ? command : `/${command}`;
      push({
        id: `command:${normalized}`,
        group: "Commands",
        label: normalized,
        detail: "Place this command in the Workbench composer for review.",
        actionLabel: "Prepare command",
        keywords: normalized,
        activate: () => onPrepareCommand(normalized),
      });
    });
    const capabilityGroups: Array<[string, CapabilitySummary[]]> = [
      ["tool", capabilities?.tools ?? []],
      ["skill", capabilities?.skills ?? []],
      ["plugin", capabilities?.plugins ?? []],
      ["MCP", capabilities?.mcp ?? []],
      ["provider", capabilities?.providers ?? []],
    ];
    const capabilityArea = navigation.find((item) => item.id === "capabilities");
    capabilityGroups.forEach(([kind, entries]) => entries.forEach((entry) => {
      const name = entry.name ?? entry.event;
      if (!name || !capabilityArea) return;
      push({
        id: `capability:${kind}:${name}`,
        group: "Capabilities",
        label: name,
        detail: entry.description || entry.detail || entry.label || `${kind} capability`,
        actionLabel: "Inspect capability",
        keywords: `${kind} ${name} ${entry.description ?? ""} ${entry.detail ?? ""}`,
        activate: () => onNavigate(capabilityArea),
      });
    }));
    const normalizedQuery = query.trim().toLowerCase();
    return result.filter((item) => !normalizedQuery || `${item.label} ${item.detail} ${item.keywords}`.toLowerCase().includes(normalizedQuery)).slice(0, 40);
  }, [capabilities, navigation, onNavigate, onPrepareCommand, onResume, query, runtimeCommands, sessions]);

  if (!open) return null;

  const activate = (item: PaletteItem) => {
    const accepted = item.activate();
    if (accepted === false) {
      setError("The local runtime is not ready for that action.");
      return;
    }
    onClose();
  };
  const moveResultFocus = (event: KeyboardEvent<HTMLElement>, offset: number) => {
    event.preventDefault();
    const buttons = Array.from(dialogRef.current?.querySelectorAll<HTMLButtonElement>(".palette-result") ?? []);
    if (buttons.length === 0) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(current + offset + buttons.length) % buttons.length].focus();
  };
  const onDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  const groups = ["Navigation", "Sessions", "Commands", "Capabilities"] as const;
  return (
    <div className="palette-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="command-palette" role="dialog" aria-modal="true" aria-labelledby="command-palette-title" onKeyDown={onDialogKeyDown}>
        <div className="palette-search">
          <Search aria-hidden="true" />
          <input ref={inputRef} type="search" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "ArrowDown") moveResultFocus(event, 1); }} placeholder="Search areas, sessions, commands, and capabilities" aria-label="Search OpenHarness" />
          <button onClick={onClose} aria-label="Close search"><X /></button>
        </div>
        <div className="palette-meta" aria-live="polite"><span id="command-palette-title">OpenHarness search</span><span>{loading ? "Indexing local state…" : `${items.length} results`} · Esc to close</span></div>
        {error ? <div className="palette-error" role="alert">{error} Navigation remains available.</div> : null}
        <div className="palette-results">
          {groups.map((group) => {
            const grouped = items.filter((item) => item.group === group);
            if (grouped.length === 0) return null;
            return <section key={group} aria-labelledby={`palette-${group.toLowerCase()}`}><h2 id={`palette-${group.toLowerCase()}`}>{group}</h2>{grouped.map((item) => <button className="palette-result" key={item.id} onClick={() => activate(item)} onKeyDown={(event) => { if (event.key === "ArrowDown") moveResultFocus(event, 1); else if (event.key === "ArrowUp") moveResultFocus(event, -1); }}><span className="palette-result-icon">{group === "Sessions" ? <Clock3 /> : group === "Commands" ? <TerminalSquare /> : group === "Capabilities" ? <Boxes /> : <Command />}</span><span className="palette-result-copy"><strong>{item.label}</strong><small>{item.detail}</small></span><span className="palette-result-action">{item.actionLabel}<ArrowUpRight /></span></button>)}</section>;
          })}
          {items.length === 0 && !loading ? <div className="palette-empty"><Search /><strong>No matching local results</strong><span>Try a shorter term or another capability name.</span></div> : null}
        </div>
      </div>
    </div>
  );
}
