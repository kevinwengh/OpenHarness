import {
  Activity,
  Bot,
  BrainCircuit,
  Boxes,
  CalendarClock,
  ChevronRight,
  CircleHelp,
  Command,
  Gauge,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  Moon,
  Orbit,
  PanelLeftClose,
  RefreshCw,
  Search,
  ServerCog,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchBootstrap, type WebApiError } from "./api";
import { CommandPalette } from "./components/CommandPalette";
import { RuntimePage, SessionsPage } from "./components/RuntimePages";
import { AutopilotPage, CapabilitiesPage, KnowledgePage, WorkPage } from "./components/ResourcePages";
import { SessionDialogs } from "./components/SessionDialogs";
import { Workbench } from "./components/Workbench";
import type { NavigationId, NavigationItem, WebBootstrap } from "./types";
import { useWebSession } from "./useWebSession";

type BootstrapLoader = (signal?: AbortSignal) => Promise<WebBootstrap>;

interface AppProps {
  loadBootstrap?: BootstrapLoader;
  connectSession?: boolean;
}

const iconById: Record<NavigationId, LucideIcon> = {
  overview: LayoutDashboard,
  workbench: MessageSquareText,
  sessions: Orbit,
  runtime: Settings2,
  capabilities: Boxes,
  work: Workflow,
  knowledge: BrainCircuit,
  autopilot: Gauge,
};

const areaGroups: Array<{ label: string; ids: NavigationId[] }> = [
  { label: "Agent", ids: ["workbench", "sessions", "runtime"] },
  { label: "System", ids: ["capabilities", "work", "knowledge", "autopilot"] },
];

function initialTheme(): "light" | "dark" {
  const saved = window.localStorage.getItem("openharness.web.theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function searchShortcutLabel() {
  return /Mac|iPhone|iPad/.test(window.navigator.platform) ? "⌘ K" : "Ctrl K";
}

function routeId(navigation: NavigationItem[]): NavigationId {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  return navigation.find((item) => item.path === path)?.id ?? "overview";
}

function LoadingScreen() {
  return (
    <div className="launch-state" role="status" aria-live="polite">
      <div className="brand-mark brand-mark--large" aria-hidden="true"><Sparkles /></div>
      <p className="eyebrow">OpenHarness / local</p>
      <h1>Preparing your workspace</h1>
      <p>Reading the redacted runtime snapshot from the local host.</p>
      <div className="loading-track"><span /></div>
    </div>
  );
}

function ErrorScreen({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const status = (error as WebApiError).status;
  return (
    <div className="launch-state launch-state--error" role="alert">
      <div className="brand-mark brand-mark--large brand-mark--warning" aria-hidden="true"><CircleHelp /></div>
      <p className="eyebrow">Local connection unavailable</p>
      <h1>We couldn’t open this workspace</h1>
      <p>{error.message}</p>
      <div className="launch-actions">
        <button className="button button--primary" onClick={onRetry}><RefreshCw /> Try again</button>
        <code>{status === 401 ? "oh web" : "oh web --no-open"}</code>
      </div>
    </div>
  );
}

function StatusPill({ state }: { state: WebBootstrap["runtime"]["auth"]["state"] }) {
  const label = state === "configured" ? "Ready" : state === "missing" ? "Needs auth" : "Check auth";
  return <span className={`status-pill status-pill--${state}`}><span aria-hidden="true" />{label}</span>;
}

function NavigationButton({
  item,
  active,
  compact = false,
  onSelect,
}: {
  item: NavigationItem;
  active: boolean;
  compact?: boolean;
  onSelect: (item: NavigationItem) => void;
}) {
  const Icon = iconById[item.id];
  return (
    <button
      className={`nav-item${active ? " nav-item--active" : ""}${compact ? " nav-item--compact" : ""}`}
      onClick={() => onSelect(item)}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      title={compact ? item.label : undefined}
    >
      <Icon aria-hidden="true" />
      <span>{item.label}</span>
      {item.availability === "coming_soon" && !compact ? <span className="nav-dot" title="Planned" /> : null}
    </button>
  );
}

function DesktopRail({
  navigation,
  activeId,
  collapsed,
  onToggle,
  onSelect,
}: {
  navigation: NavigationItem[];
  activeId: NavigationId;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (item: NavigationItem) => void;
}) {
  const overview = navigation.find((item) => item.id === "overview");
  return (
    <aside className={`rail${collapsed ? " rail--collapsed" : ""}`}>
      <div className="rail-brand">
        <div className="brand-mark" aria-hidden="true"><Sparkles /></div>
        <div className="rail-brand-copy"><strong>OpenHarness</strong><span>Local workspace</span></div>
      </div>
      <nav aria-label="Primary navigation">
        {overview ? <NavigationButton item={overview} active={activeId === "overview"} compact={collapsed} onSelect={onSelect} /> : null}
        {areaGroups.map((group) => (
          <div className="nav-group" key={group.label}>
            <p>{group.label}</p>
            {group.ids.map((id) => {
              const item = navigation.find((candidate) => candidate.id === id);
              return item ? <NavigationButton key={id} item={item} active={activeId === id} compact={collapsed} onSelect={onSelect} /> : null;
            })}
          </div>
        ))}
      </nav>
      <button className="rail-toggle" onClick={onToggle} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
        <PanelLeftClose aria-hidden="true" />
        <span>{collapsed ? "Expand" : "Collapse"}</span>
      </button>
    </aside>
  );
}

function Topbar({
  bootstrap,
  theme,
  onTheme,
  onMenu,
  onSearch,
}: {
  bootstrap: WebBootstrap;
  theme: "light" | "dark";
  onTheme: () => void;
  onMenu: () => void;
  onSearch: () => void;
}) {
  return (
    <header className="topbar">
      <button className="icon-button mobile-only" onClick={onMenu} aria-label="Open navigation"><Menu /></button>
      <div className="topbar-context">
        <span className="workspace-name">{bootstrap.workspace.name}</span>
        <span className="workspace-path">{bootstrap.workspace.path}</span>
      </div>
      <div className="topbar-actions">
        <button className="search-launch" onClick={onSearch}><Search aria-hidden="true" /><span>Search</span><kbd>{searchShortcutLabel()}</kbd></button>
        <StatusPill state={bootstrap.runtime.auth.state} />
        <button className="icon-button" onClick={onTheme} aria-label={`Use ${theme === "dark" ? "light" : "dark"} theme`}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>
      </div>
    </header>
  );
}

function Metric({ icon: Icon, label, value, detail }: { icon: LucideIcon; label: string; value: string; detail: string }) {
  return (
    <div className="metric">
      <div className="metric-icon"><Icon aria-hidden="true" /></div>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </div>
  );
}

function Overview({ bootstrap, onSelect }: { bootstrap: WebBootstrap; onSelect: (item: NavigationItem) => void }) {
  const runtime = bootstrap.runtime;
  const workbench = bootstrap.navigation.find((item) => item.id === "workbench");
  const authReady = runtime.auth.state === "configured";
  return (
    <div className="page page--overview">
      <section className="hero" aria-labelledby="overview-title">
        <div className="hero-copy">
          <p className="eyebrow"><Activity aria-hidden="true" /> Runtime overview</p>
          <h1 id="overview-title">Your agent workspace,<br /><span>clear at a glance.</span></h1>
          <p>One local surface for conversations, runtime controls, capabilities, scheduled work, memory, and repository autopilot.</p>
          <div className="hero-actions">
            {workbench ? <button className="button button--primary" onClick={() => onSelect(workbench)}>Open workbench <ChevronRight /></button> : null}
            <span className="stage-label">Local workspace online</span>
          </div>
        </div>
        <div className="runtime-orbit" aria-label={`Runtime ${authReady ? "ready" : "needs attention"}`}>
          <div className="orbit-ring orbit-ring--outer" />
          <div className="orbit-ring orbit-ring--inner" />
          <div className="orbit-core"><Bot aria-hidden="true" /><strong>{authReady ? "Ready" : "Review"}</strong><span>{runtime.profile}</span></div>
          <span className="orbit-node orbit-node--one"><ShieldCheck /><small>Policy</small></span>
          <span className="orbit-node orbit-node--two"><ServerCog /><small>Runtime</small></span>
          <span className="orbit-node orbit-node--three"><Command /><small>Tools</small></span>
        </div>
      </section>

      <section className="metrics" aria-label="Runtime status">
        <Metric icon={ServerCog} label="Provider" value={runtime.provider} detail={runtime.profile} />
        <Metric icon={Sparkles} label="Model" value={runtime.model} detail={`${runtime.effort} effort`} />
        <Metric icon={ShieldCheck} label="Permissions" value={runtime.permission_mode} detail={runtime.sandbox_enabled ? `${runtime.sandbox_backend} sandbox` : "host execution"} />
        <Metric icon={Activity} label="Authentication" value={runtime.auth.state} detail={runtime.auth.label} />
      </section>

      <section className="surface-section" aria-labelledby="areas-title">
        <div className="section-heading">
          <div><p className="eyebrow">Product map</p><h2 id="areas-title">Everything has a place</h2></div>
          <p>Each area grows through an explicit operate, configure, or inspect contract.</p>
        </div>
        <div className="area-list">
          {bootstrap.navigation.filter((item) => item.id !== "overview").map((item, index) => {
            const Icon = iconById[item.id];
            return (
              <button className="area-row" key={item.id} onClick={() => onSelect(item)}>
                <span className="area-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="area-icon"><Icon aria-hidden="true" /></span>
                <span className="area-copy"><strong>{item.label}</strong><small>{item.description}</small></span>
                <span className={`depth-tag depth-tag--${item.depth}`}>{item.depth}</span>
                <ChevronRight aria-hidden="true" />
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function MobileNavigation({
  navigation,
  activeId,
  onSelect,
  onMore,
}: {
  navigation: NavigationItem[];
  activeId: NavigationId;
  onSelect: (item: NavigationItem) => void;
  onMore: () => void;
}) {
  const primaryIds: NavigationId[] = ["overview", "workbench", "sessions"];
  return (
    <nav className="mobile-nav" aria-label="Mobile navigation">
      {primaryIds.map((id) => {
        const item = navigation.find((candidate) => candidate.id === id);
        return item ? <NavigationButton key={id} item={item} active={activeId === id} compact onSelect={onSelect} /> : null;
      })}
      <button className="nav-item nav-item--compact" onClick={onMore}><Menu aria-hidden="true" /><span>More</span></button>
    </nav>
  );
}

function NavigationDrawer({
  open,
  navigation,
  activeId,
  onClose,
  onSelect,
}: {
  open: boolean;
  navigation: NavigationItem[];
  activeId: NavigationId;
  onClose: () => void;
  onSelect: (item: NavigationItem) => void;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])"),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside ref={drawerRef} className="nav-drawer" role="dialog" aria-modal="true" aria-labelledby="nav-drawer-title">
        <div className="drawer-heading"><div><p className="eyebrow">OpenHarness</p><h2 id="nav-drawer-title">Navigate</h2></div><button ref={closeRef} className="icon-button" onClick={onClose} aria-label="Close navigation"><X /></button></div>
        <nav aria-label="All product areas">
          {navigation.map((item) => <NavigationButton key={item.id} item={item} active={activeId === item.id} onSelect={onSelect} />)}
        </nav>
      </aside>
    </div>
  );
}

export function App({ loadBootstrap = fetchBootstrap, connectSession = true }: AppProps) {
  const [bootstrap, setBootstrap] = useState<WebBootstrap | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [activeId, setActiveId] = useState<NavigationId>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [draftRequest, setDraftRequest] = useState<{ id: number; value: string } | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);
  const drawerReturnFocus = useRef<HTMLElement | null>(null);
  const paletteReturnFocus = useRef<HTMLElement | null>(null);
  const webSession = useWebSession({ enabled: connectSession && bootstrap !== null });

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    loadBootstrap(controller.signal).then((value) => {
      setBootstrap(value);
      setActiveId(routeId(value.navigation));
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason : new Error("Unknown bootstrap error"));
    });
    return () => controller.abort();
  }, [attempt, loadBootstrap]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("openharness.web.theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!bootstrap) return;
    const onPopState = () => setActiveId(routeId(bootstrap.navigation));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [bootstrap]);

  const select = useCallback((item: NavigationItem) => {
    setActiveId(item.id);
    setDrawerOpen(false);
    if (window.location.pathname !== item.path) window.history.pushState({}, "", item.path);
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  }, []);

  const openDrawer = useCallback(() => {
    drawerReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setDrawerOpen(true);
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    window.requestAnimationFrame(() => drawerReturnFocus.current?.focus());
  }, []);

  const openPalette = useCallback(() => {
    paletteReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPaletteOpen(true);
  }, []);

  const closePalette = useCallback(() => {
    setPaletteOpen(false);
    window.requestAnimationFrame(() => paletteReturnFocus.current?.focus());
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (paletteOpen) closePalette(); else openPalette();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closePalette, openPalette, paletteOpen]);

  const selectFromDrawer = useCallback((item: NavigationItem) => {
    select(item);
    window.requestAnimationFrame(() => document.getElementById("main-content")?.focus());
  }, [select]);

  const activeItem = useMemo(() => bootstrap?.navigation.find((item) => item.id === activeId), [activeId, bootstrap]);

  if (error) return <ErrorScreen error={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!bootstrap) return <LoadingScreen />;

  const content = activeId === "overview" ? (
    <Overview bootstrap={bootstrap} onSelect={select} />
  ) : activeId === "workbench" ? (
    <Workbench
      session={webSession.state}
      onSubmit={webSession.submit}
      onInterrupt={webSession.interrupt}
      onRequestSelect={webSession.requestSelect}
      draftRequest={draftRequest}
    />
  ) : activeId === "sessions" ? (
    <SessionsPage
      session={webSession.state}
      onBrowse={() => webSession.requestSelect("resume")}
      onResume={(sessionId) => { webSession.applySelect("resume", sessionId); }}
      onNew={() => { if (window.confirm("Start a new runtime session? The current active turn must be idle.")) webSession.newSession(); }}
    />
  ) : activeId === "runtime" ? (
    <RuntimePage session={webSession.state} sandbox={bootstrap.runtime} onSelect={webSession.requestSelect} />
  ) : activeId === "capabilities" ? (
    <CapabilitiesPage />
  ) : activeId === "work" ? (
    <WorkPage mutationsDisabled={webSession.state.busy} />
  ) : activeId === "knowledge" ? (
    <KnowledgePage />
  ) : activeId === "autopilot" ? (
    <AutopilotPage mutationsDisabled={webSession.state.busy} />
  ) : null;

  return (
    <div className={`app-shell${collapsed ? " app-shell--collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <DesktopRail navigation={bootstrap.navigation} activeId={activeId} collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)} onSelect={select} />
      <div className="workspace-shell">
        <Topbar bootstrap={bootstrap} theme={theme} onTheme={() => setTheme((value) => value === "dark" ? "light" : "dark")} onMenu={openDrawer} onSearch={openPalette} />
        <main id="main-content" tabIndex={-1}>
          {content}
        </main>
        <footer className="app-footer"><span>Local-only · launch-token protected</span><span>OpenHarness {bootstrap.app.version}</span></footer>
      </div>
      <MobileNavigation navigation={bootstrap.navigation} activeId={activeId} onSelect={select} onMore={openDrawer} />
      <NavigationDrawer open={drawerOpen} navigation={bootstrap.navigation} activeId={activeId} onClose={closeDrawer} onSelect={selectFromDrawer} />
      <CommandPalette
        open={paletteOpen}
        navigation={bootstrap.navigation}
        runtimeCommands={webSession.state.commands}
        onClose={closePalette}
        onNavigate={select}
        onPrepareCommand={(command) => {
          const workbench = bootstrap.navigation.find((item) => item.id === "workbench");
          setDraftRequest((current) => ({ id: (current?.id ?? 0) + 1, value: command }));
          if (workbench) select(workbench);
        }}
        onResume={(sessionId) => {
          const accepted = webSession.applySelect("resume", sessionId);
          const workbench = bootstrap.navigation.find((item) => item.id === "workbench");
          if (accepted && workbench) select(workbench);
          return accepted;
        }}
      />
      <SessionDialogs
        modal={webSession.state.modal}
        selectRequest={webSession.state.selectRequest}
        onPermission={webSession.respondPermission}
        onQuestion={webSession.respondQuestion}
        onSelect={webSession.applySelect}
        onDismissSelect={webSession.dismissSelect}
      />
      <div className="sr-only" aria-live="polite">Viewing {activeItem?.label ?? "Overview"}</div>
    </div>
  );
}
