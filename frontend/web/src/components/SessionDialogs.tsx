import { Check, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { SelectRequest, SessionModal } from "../types";

interface SessionDialogsProps {
  modal: SessionModal | null;
  selectRequest: SelectRequest | null;
  onPermission: (requestId: string, reply: "once" | "always" | "reject") => void;
  onQuestion: (requestId: string, answer: string) => void;
  onSelect: (command: string, value: string) => void;
  onDismissSelect: () => void;
}

function DialogFrame({ title, children }: { title: string; children: React.ReactNode }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.querySelector<HTMLElement>("[data-initial-focus]")?.focus();
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
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
    document.addEventListener("keydown", trapFocus);
    return () => {
      document.removeEventListener("keydown", trapFocus);
      window.requestAnimationFrame(() => returnFocus?.focus());
    };
  }, []);
  return (
    <div className="decision-backdrop">
      <div ref={dialogRef} className="decision-dialog" role="dialog" aria-modal="true" aria-labelledby="decision-title">
        <h2 id="decision-title">{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function SessionDialogs({
  modal,
  selectRequest,
  onPermission,
  onQuestion,
  onSelect,
  onDismissSelect,
}: SessionDialogsProps) {
  const [answer, setAnswer] = useState("");

  useEffect(() => setAnswer(""), [modal?.request_id]);

  useEffect(() => {
    if (!modal && !selectRequest) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      if (modal?.kind === "question") onQuestion(modal.request_id, "");
      else if (modal) onPermission(modal.request_id, "reject");
      else onDismissSelect();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [modal, onDismissSelect, onPermission, onQuestion, selectRequest]);

  if (modal?.kind === "question") {
    return (
      <DialogFrame title="The agent needs your input">
        <p className="dialog-copy">{modal.question}</p>
        <label className="field-label" htmlFor="agent-answer">Your answer</label>
        <textarea id="agent-answer" data-initial-focus value={answer} onChange={(event) => setAnswer(event.target.value)} rows={4} />
        <div className="dialog-actions">
          <button className="button" onClick={() => onQuestion(modal.request_id, "")}>Cancel</button>
          <button className="button button--primary" disabled={!answer.trim()} onClick={() => onQuestion(modal.request_id, answer.trim())}>Send answer</button>
        </div>
      </DialogFrame>
    );
  }

  if (modal?.kind === "edit_diff") {
    return (
      <DialogFrame title="Review proposed edit">
        <div className="decision-summary"><ShieldAlert aria-hidden="true" /><span><strong>{modal.path}</strong><small>+{modal.added ?? 0} / −{modal.removed ?? 0} lines</small></span></div>
        <pre className="diff-preview" tabIndex={0}>{modal.diff || "No diff preview supplied."}</pre>
        <div className="dialog-actions dialog-actions--spread">
          <button data-initial-focus className="button button--danger" onClick={() => onPermission(modal.request_id, "reject")}><X /> Reject</button>
          <span className="dialog-action-group">
            <button className="button" onClick={() => onPermission(modal.request_id, "once")}>Apply once</button>
            <button className="button button--primary" onClick={() => onPermission(modal.request_id, "always")}><Check /> Apply for session</button>
          </span>
        </div>
      </DialogFrame>
    );
  }

  if (modal) {
    return (
      <DialogFrame title="Permission required">
        <div className="decision-summary"><ShieldAlert aria-hidden="true" /><span><strong>{modal.tool_name || "Tool action"}</strong><small>{modal.reason || "This action can change local state."}</small></span></div>
        <p className="dialog-copy">Review the requested action before allowing it. Deny is selected first for keyboard safety.</p>
        <div className="dialog-actions">
          <button data-initial-focus className="button button--danger" onClick={() => onPermission(modal.request_id, "reject")}><X /> Deny</button>
          <button className="button button--primary" onClick={() => onPermission(modal.request_id, "once")}><Check /> Allow once</button>
        </div>
      </DialogFrame>
    );
  }

  if (selectRequest) {
    return (
      <DialogFrame title={selectRequest.title}>
        <div className="select-options" role="listbox" aria-label={selectRequest.title}>
          {selectRequest.options.length ? selectRequest.options.map((option, index) => (
            <button
              key={option.value}
              data-initial-focus={index === 0 ? "true" : undefined}
              className={`select-option${option.active ? " select-option--active" : ""}`}
              onClick={() => onSelect(selectRequest.command, option.value)}
              role="option"
              aria-selected={Boolean(option.active)}
            >
              <span><strong>{option.label}</strong>{option.description ? <small>{option.description}</small> : null}</span>
              {option.active ? <Check aria-label="Current" /> : null}
            </button>
          )) : <p className="dialog-copy">No options are available for this command.</p>}
        </div>
        <div className="dialog-actions"><button className="button" onClick={onDismissSelect}>Close</button></div>
      </DialogFrame>
    );
  }

  return null;
}
