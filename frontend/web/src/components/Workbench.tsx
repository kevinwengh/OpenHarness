import {
  Bot,
  CircleStop,
  FileImage,
  Paperclip,
  Send,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  User,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { FrontendImageAttachment, TranscriptItem } from "../types";
import type { WebSessionState } from "../useWebSession";

interface PendingImage extends FrontendImageAttachment {
  name: string;
}

const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const MAX_TURN_IMAGE_BYTES = 6 * 1024 * 1024;

interface WorkbenchProps {
  session: WebSessionState;
  onSubmit: (line: string, images: FrontendImageAttachment[]) => boolean;
  onInterrupt: () => void;
  onRequestSelect: (command: string) => void;
}

function TranscriptRow({ item }: { item: TranscriptItem }) {
  if (item.role === "tool" || item.role === "tool_result") {
    return (
      <details className={`tool-event${item.is_error ? " tool-event--error" : ""}`}>
        <summary><TerminalSquare aria-hidden="true" /><span><strong>{item.tool_name || "Tool"}</strong><small>{item.role === "tool" ? "started" : item.is_error ? "failed" : "completed"}</small></span></summary>
        {item.tool_input ? <pre>{JSON.stringify(item.tool_input, null, 2)}</pre> : null}
        {item.text ? <pre>{item.text}</pre> : null}
      </details>
    );
  }
  const assistant = item.role === "assistant";
  const user = item.role === "user";
  return (
    <article className={`message message--${item.role}${item.is_error ? " message--error" : ""}`}>
      <div className="message-avatar" aria-hidden="true">{assistant ? <Bot /> : user ? <User /> : <Sparkles />}</div>
      <div className="message-body"><p className="message-role">{assistant ? "OpenHarness" : user ? "You" : item.role}</p><div className="message-text">{item.text}</div></div>
    </article>
  );
}

async function readImage(file: File): Promise<PendingImage> {
  if (!file.type.startsWith("image/")) throw new Error(`${file.name} is not an image.`);
  if (file.size > MAX_IMAGE_BYTES) throw new Error(`${file.name} is larger than 2 MB.`);
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
  return { name: file.name, media_type: file.type, data: dataUrl.split(",", 2)[1] ?? "" };
}

export function Workbench({ session, onSubmit, onInterrupt, onRequestSelect }: WorkbenchProps) {
  const [draft, setDraft] = useState("");
  const [images, setImages] = useState<PendingImage[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const connected = session.connection === "ready";

  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [session.transcript, session.streamingText]);

  const submit = () => {
    const text = draft.trim();
    if ((!text && images.length === 0) || session.busy || !connected) return;
    if (onSubmit(text, images)) {
      setDraft("");
      setImages([]);
      inputRef.current?.focus();
    }
  };

  const attach = async (files: FileList | null) => {
    if (!files) return;
    setAttachmentError(null);
    try {
      const room = Math.max(0, 4 - images.length);
      const selected = Array.from(files).slice(0, room);
      const existingBytes = images.reduce((total, image) => total + Math.ceil(image.data.length * 0.75), 0);
      const selectedBytes = selected.reduce((total, file) => total + file.size, 0);
      if (existingBytes + selectedBytes > MAX_TURN_IMAGE_BYTES) throw new Error("Images in one turn must total 6 MB or less.");
      const next = await Promise.all(selected.map(readImage));
      setImages((current) => [...current, ...next]);
      if (files.length > room) setAttachmentError("A turn can include up to four images.");
    } catch (error) {
      setAttachmentError(error instanceof Error ? error.message : "Could not attach that image.");
    }
  };

  return (
    <div className="workbench-layout">
      <section className="conversation" aria-label="Conversation workbench">
        <header className="conversation-heading">
          <div><p className="eyebrow"><Sparkles /> Active runtime</p><h1>Workbench</h1></div>
          <span className={`connection-chip connection-chip--${session.connection}`}><span />{session.connection}</span>
        </header>
        <div className="transcript" aria-live="polite" aria-busy={session.busy}>
          {session.transcript.length === 0 && !session.streamingText ? (
            <div className="conversation-empty"><div className="preview-icon"><Bot /></div><h2>What should we work on?</h2><p>Ask about this project, request a change, or attach an image. Tool calls and decisions stay visible as the turn unfolds.</p></div>
          ) : session.transcript.map((item, index) => <TranscriptRow key={`${index}-${item.role}`} item={item} />)}
          {session.streamingText ? <article className="message message--assistant message--streaming"><div className="message-avatar"><Bot /></div><div className="message-body"><p className="message-role">OpenHarness</p><div className="message-text">{session.streamingText}<span className="stream-cursor" /></div></div></article> : null}
          {session.busyLabel ? <div className="turn-status" role="status"><span className="status-spinner" />{session.busyLabel}</div> : null}
          <div ref={endRef} />
        </div>
        <div className="composer-wrap">
          {images.length ? <div className="attachment-list">{images.map((image, index) => <span className="attachment-chip" key={`${image.name}-${index}`}><FileImage />{image.name}<button aria-label={`Remove ${image.name}`} onClick={() => setImages((current) => current.filter((_, itemIndex) => itemIndex !== index))}><X /></button></span>)}</div> : null}
          {attachmentError ? <p className="composer-error" role="alert">{attachmentError}</p> : null}
          <div className="composer">
            <label className="attach-button" title="Attach images"><Paperclip /><span className="sr-only">Attach images</span><input type="file" accept="image/*" multiple onChange={(event) => { void attach(event.target.files); event.target.value = ""; }} /></label>
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }}
              placeholder={connected ? "Ask OpenHarness…" : "Waiting for local runtime…"}
              aria-label="Message OpenHarness"
              disabled={!connected || session.busy}
              rows={1}
            />
            {session.busy ? <button className="composer-action composer-action--stop" onClick={onInterrupt} aria-label="Stop active turn"><CircleStop /></button> : <button className="composer-action" onClick={submit} disabled={!connected || (!draft.trim() && images.length === 0)} aria-label="Send message"><Send /></button>}
          </div>
          <p className="composer-hint">Enter to send · Shift+Enter for a new line · images stay local until submitted</p>
        </div>
      </section>
      <aside className="runtime-panel" aria-label="Runtime controls">
        <div className="runtime-panel-heading"><p className="eyebrow">Session context</p><h2>How the agent runs</h2></div>
        <dl className="runtime-facts">
          <div><dt>Model</dt><dd>{String(session.runtime.model ?? "Starting…")}</dd></div>
          <div><dt>Provider</dt><dd>{String(session.runtime.provider ?? "—")}</dd></div>
          <div><dt>Permission</dt><dd><ShieldCheck />{String(session.runtime.permission_mode ?? "—")}</dd></div>
          <div><dt>Effort</dt><dd>{String(session.runtime.effort ?? "—")}</dd></div>
        </dl>
        <div className="quick-controls">
          <p>Quick controls</p>
          {[ ["model", "Model"], ["provider", "Provider"], ["permissions", "Permissions"], ["effort", "Effort"], ["turns", "Turn limit"] ].map(([command, label]) => <button key={command} onClick={() => onRequestSelect(command)} disabled={!connected || session.busy}>{label}<span>Change</span></button>)}
        </div>
        {session.todoMarkdown ? <div className="todo-panel"><p>Current plan</p><pre>{session.todoMarkdown}</pre></div> : null}
      </aside>
    </div>
  );
}
