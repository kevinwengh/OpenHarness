/**
 * Own the terminal frontend's app boundary.
 *
 * Integration: Connects the Ink application to shared TypeScript types and the Python backend
 * protocol.
 *
 * Event loop: Process I/O, React effects, input events, and buffered rendering coexist on Node's
 * event loop; preserve cleanup and backpressure.
 *
 * Change safety: Coordinate protocol, process lifecycle, terminal restoration, and packaging
 * changes with the Python host and UI tests.
 */

import React, {useDeferredValue, useEffect, useMemo, useRef, useState} from 'react';
import {Box, Text, useApp, useInput} from 'ink';

import {readClipboardImage, type ImageAttachment} from './clipboardImage.js';
import {CommandPicker} from './components/CommandPicker.js';
import {ConversationView} from './components/ConversationView.js';
import {ModalHost} from './components/ModalHost.js';
import {PromptInput} from './components/PromptInput.js';
import {SelectModal, type SelectOption} from './components/SelectModal.js';
import {StatusBar} from './components/StatusBar.js';
import {SwarmPanel} from './components/SwarmPanel.js';
import {TodoPanel} from './components/TodoPanel.js';
import {useBackendSession} from './hooks/useBackendSession.js';
import {ThemeProvider, useTheme} from './theme/ThemeContext.js';
import type {FrontendConfig, ImageAttachmentPayload} from './types.js';

const rawReturnSubmit = process.env.OPENHARNESS_FRONTEND_RAW_RETURN === '1';
const scriptedSteps = (/*
 * callback at line 18: uses parse, isArray, filter; keep event-loop work bounded and preserve
 * surrounding control flow.
 */ () => {
	const raw = process.env.OPENHARNESS_FRONTEND_SCRIPT;
	if (!raw) {
		return [] as string[];
	}
	try {
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed.filter(/*
		 * filter callback: computes its callback result; keep event-loop work bounded and preserve
		 * the callback's return contract.
		 */ (item): item is string => typeof item === 'string') : [];
	} catch {
		return [];
	}
})();

const SELECTABLE_COMMANDS = new Set([
	'/provider',
	'/model',
	'/theme',
	'/output-style',
	'/permissions',
	'/resume',
	'/effort',
	'/passes',
	'/turns',
	'/fast',
	'/vim',
	'/voice',
]);

type SelectModalState = {
	title: string;
	options: SelectOption[];
	onSelect: (value: string) => void;
} | null;

/**
 * Render the App React component.
 *
 * Integration: Owned by `App.tsx` and collaborates with `String`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function App({config}: {config: FrontendConfig}): React.JSX.Element {
	const initialTheme = String((config as Record<string, unknown>).theme ?? 'default');
	return (
		<ThemeProvider initialTheme={initialTheme}>
			<AppInner config={config} />
		</ThemeProvider>
	);
}

/**
 * Render the AppInner React component.
 *
 * Integration: Owned by `App.tsx` and collaborates with `useApp`, `useTheme`, `useState`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function AppInner({config}: {config: FrontendConfig}): React.JSX.Element {
	const {exit} = useApp();
	const {theme, setThemeName} = useTheme();
	const [input, setInput] = useState('');
	const [modalInput, setModalInput] = useState('');
	const [history, setHistory] = useState<string[]>([]);
	const [historyIndex, setHistoryIndex] = useState(-1);
	const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([]);
	const [clipboardStatus, setClipboardStatus] = useState<string | null>(null);
	const [lastEscapeAt, setLastEscapeAt] = useState(0);
	const [scriptIndex, setScriptIndex] = useState(0);
	const [pickerIndex, setPickerIndex] = useState(0);
	const [selectModal, setSelectModal] = useState<SelectModalState>(null);
	const [selectIndex, setSelectIndex] = useState(0);
	const session = useBackendSession(config, /*
	 * useBackendSession callback: uses exit; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ () => exit());
	const deferredTranscript = useDeferredValue(session.transcript);
	const deferredAssistantBuffer = useDeferredValue(session.assistantBuffer);
	const deferredStatus = useDeferredValue(session.status);
	const deferredTasks = useDeferredValue(session.tasks);
	const deferredTodoMarkdown = useDeferredValue(session.todoMarkdown);
	const deferredSwarmTeammates = useDeferredValue(session.swarmTeammates);
	const deferredSwarmNotifications = useDeferredValue(session.swarmNotifications);
	const clipboardStatusTimerRef = useRef<NodeJS.Timeout | null>(null);

	useEffect(/*
	 * React effect: uses setThemeName after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		const nextTheme = session.status.theme;
		if (typeof nextTheme === 'string' && nextTheme) {
			setThemeName(nextTheme);
		}
	}, [session.status.theme, setThemeName]);

	useEffect(/*
	 * React effect: computes its callback result after render; keep dependencies, asynchronous
	 * work, and returned cleanup synchronized.
	 */ () => {
		return /*
		 * Effect cleanup: uses clearTimeout; keep it paired with every resource acquired by the
		 * effect.
		 */ () => {
			if (clipboardStatusTimerRef.current) {
				clearTimeout(clipboardStatusTimerRef.current);
			}
		};
	}, []);

	 /**
  * Derive set temporary clipboard status from the current frontend state and inputs.
  *
  * Integration: Owned by `AppInner` and collaborates with `setClipboardStatus`, `clearTimeout`,
  * `setTimeout`.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve React state ownership, functional-update semantics, and render ordering;
  * review every dependent effect and component.
  */
 const setTemporaryClipboardStatus = (message: string): void => {
		setClipboardStatus(message);
		if (clipboardStatusTimerRef.current) {
			clearTimeout(clipboardStatusTimerRef.current);
		}
		clipboardStatusTimerRef.current = setTimeout(/*
		 * Timer callback: uses setClipboardStatus on Node's event loop; keep work bounded and
		 * preserve matching cleanup.
		 */ () => {
			setClipboardStatus(null);
			clipboardStatusTimerRef.current = null;
		}, 2500);
	};

	 /**
  * Derive attach clipboard image from the current frontend state and inputs.
  *
  * Integration: Owned by `AppInner` and collaborates with `catch`.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
  */
 const attachClipboardImage = (): void => {
		void (/*
		 * callback at line 112: uses readClipboardImage, setTemporaryClipboardStatus,
		 * setImageAttachments; keep event-loop work bounded and preserve surrounding control flow.
		 */ async () => {
			const image = await readClipboardImage();
			if (!image) {
				setTemporaryClipboardStatus('No image found in clipboard');
				return;
			}
			setImageAttachments(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (items) => [...items, image]);
			setTemporaryClipboardStatus(`Attached ${image.label}`);
		})().catch(/*
		 * catch callback: uses String, setTemporaryClipboardStatus; keep event-loop work bounded and
		 * preserve the callback's return contract.
		 */ (error: unknown) => {
			const message = error instanceof Error ? error.message : String(error);
			setTemporaryClipboardStatus(`Clipboard image unavailable: ${message}`);
		});
	};

	 /**
  * Derive image payloads from the current frontend state and inputs.
  *
  * Integration: Owned by `AppInner` and collaborates with `map`.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
  */
 const imagePayloads = (): ImageAttachmentPayload[] =>
		imageAttachments.map(/*
		 * map callback: computes its callback result; keep event-loop work bounded and preserve the
		 * callback's return contract.
		 */ (image) => ({
			media_type: image.media_type,
			data: image.data,
			source_path: image.source_path,
		}));

	// Current tool name for spinner
	const currentToolName = useMemo(/*
	 * React useMemo callback: computes its callback result; keep dependencies synchronized with
	 * captured values and preserve purity.
	 */ () => {
		for (let i = deferredTranscript.length - 1; i >= 0; i--) {
			const item = deferredTranscript[i];
			if (item.role === 'tool') {
				return item.tool_name ?? 'tool';
			}
			if (item.role === 'tool_result' || item.role === 'assistant') {
				break;
			}
		}
		return undefined;
	}, [deferredTranscript]);

	// Command hints
	const commandHints = useMemo(/*
	 * React useMemo callback: uses trim, startsWith, slice; keep dependencies synchronized with
	 * captured values and preserve purity.
	 */ () => {
		const value = input.trim();
		if (!value.startsWith('/')) {
			return [] as string[];
		}
		return session.commands.filter(/*
		 * filter callback: uses startsWith; keep event-loop work bounded and preserve the callback's
		 * return contract.
		 */ (cmd) => cmd.startsWith(value)).slice(0, 10);
	}, [session.commands, input]);

	const showPicker = commandHints.length > 0 && !session.busy && !session.modal && !selectModal;
	const outputStyle = String(session.status.output_style ?? 'default');

	useEffect(/*
	 * React effect: uses setPickerIndex after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		setPickerIndex(0);
	}, [commandHints.length, input]);

	// Handle backend-initiated select requests (e.g. /resume session list)
	useEffect(/*
	 * React effect: uses setSelectRequest, findIndex, setSelectIndex after render; keep
	 * dependencies, asynchronous work, and returned cleanup synchronized.
	 */ () => {
		if (!session.selectRequest) {
			return;
		}
		const req = session.selectRequest;
		if (req.options.length === 0) {
			session.setSelectRequest(null);
			return;
		}
		const initialIndex = req.options.findIndex(/*
		 * findIndex callback: computes its callback result; keep event-loop work bounded and preserve
		 * the callback's return contract.
		 */ (option) => option.active);
		setSelectIndex(initialIndex >= 0 ? initialIndex : 0);
		setSelectModal({
			title: req.title,
			options: req.options.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (o) => ({value: o.value, label: o.label, description: o.description, active: o.active})),
			   /**
    * Handle select for the owning UI boundary.
    *
    * Integration: Owned by `useEffect callback 1` and collaborates with `sendRequest`, `setBusy`,
    * `setSelectModal`.
    *
    * Event loop: Runs from an input or UI event; keep synchronous work bounded and order state
    * updates before asynchronous follow-up.
    *
    * Change safety: Preserve React state ownership, functional-update semantics, and render
    * ordering; review every dependent effect and component.
    */
   onSelect: (value) => {
				session.sendRequest({type: 'apply_select_command', command: req.command, value});
				session.setBusy(true);
				setSelectModal(null);
			},
		});
		session.setSelectRequest(null);
	}, [session.selectRequest]);

	// Intercept special commands that need interactive UI
	 /**
  * Handle command for the owning UI boundary.
  *
  * Integration: Owned by `AppInner` and collaborates with `trim`, `has`, `sendRequest`.
  *
  * Event loop: Runs from an input or UI event; keep synchronous work bounded and order state
  * updates before asynchronous follow-up.
  *
  * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
  */
 const handleCommand = (cmd: string): boolean => {
		const trimmed = cmd.trim();

		if (SELECTABLE_COMMANDS.has(trimmed)) {
			session.sendRequest({type: 'select_command', command: trimmed.slice(1)});
			return true;
		}

		// /permissions → show mode picker
		if (trimmed === '/permissions' || trimmed === '/permissions show') {
			session.sendRequest({type: 'select_command', command: 'permissions'});
			return true;
		}

		// /plan → toggle plan mode
		if (trimmed === '/plan') {
			const currentMode = String(session.status.permission_mode ?? 'default');
			if (currentMode === 'plan') {
				session.sendRequest({type: 'submit_line', line: '/plan off'});
			} else {
				session.sendRequest({type: 'submit_line', line: '/plan on'});
			}
			session.setBusy(true);
			return true;
		}

		// /resume → request session list from backend (will trigger select_request)
		if (trimmed === '/resume') {
			session.sendRequest({type: 'select_command', command: 'resume'});
			return true;
		}

		return false;
	};

	useInput(/*
	 * useInput callback: uses sendRequest, setBusyLabel, exit; keep event-loop work bounded and
	 * preserve the callback's return contract.
	 */ (chunk, key) => {
		const isPaste = chunk.length > 1 && !key.ctrl && !key.meta;
		const isEscape = key.escape || chunk === '\u001B';

		// Ctrl+C interrupts a running turn; when idle it exits the TUI.
		if (key.ctrl && chunk === 'c') {
			if (session.busy) {
				session.sendRequest({type: 'interrupt'});
				session.setBusyLabel('Stopping current operation...');
				return;
			}
			session.sendRequest({type: 'shutdown'});
			exit();
			return;
		}

		if (!session.busy && key.ctrl && chunk === 'v') {
			attachClipboardImage();
			return;
		}

		// Let ink-text-input handle pasted text directly.
		if (isPaste) {
			return;
		}

		// --- Select modal (permissions picker etc.) ---
		if (selectModal) {
			if (key.upArrow) {
				setSelectIndex(/*
				 * Functional state update: uses max from prior React state; keep the calculation pure and
				 * immutable.
				 */ (i) => Math.max(0, i - 1));
				return;
			}
			if (key.downArrow) {
				setSelectIndex(/*
				 * Functional state update: uses min from prior React state; keep the calculation pure and
				 * immutable.
				 */ (i) => Math.min(selectModal.options.length - 1, i + 1));
				return;
			}
			if (key.return) {
				const selected = selectModal.options[selectIndex];
				if (selected) {
					selectModal.onSelect(selected.value);
				}
				return;
			}
			if (key.escape) {
				setSelectModal(null);
				return;
			}
			// Number keys for quick selection
			const num = parseInt(chunk, 10);
			if (num >= 1 && num <= selectModal.options.length) {
				const selected = selectModal.options[num - 1];
				if (selected) {
					selectModal.onSelect(selected.value);
				}
				return;
			}
			return;
		}

		// --- Scripted raw return ---
		if (rawReturnSubmit && key.return) {
			if (session.modal?.kind === 'question') {
				session.sendRequest({
					type: 'question_response',
					request_id: session.modal.request_id,
					answer: modalInput,
				});
				session.setModal(null);
				setModalInput('');
				return;
			}
			if (!session.modal && !session.busy && input.trim()) {
				onSubmit(input);
				return;
			}
		}

		// --- Permission modal (MUST be before busy check — modal appears while busy) ---
		if (session.modal?.kind === 'permission') {
			if (chunk.toLowerCase() === 'y') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
				});
				session.setModal(null);
				return;
			}
			if (chunk.toLowerCase() === 'n' || isEscape) {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: false,
				});
				session.setModal(null);
				return;
			}
			return;
		}

		// --- Edit diff modal (also appears while busy) ---
		if (session.modal?.kind === 'edit_diff') {
			if (chunk.toLowerCase() === 'y') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
					permission_reply: 'once',
				});
				session.setModal(null);
				return;
			}
			if (chunk.toLowerCase() === 'a') {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: true,
					permission_reply: 'always',
				});
				session.setModal(null);
				return;
			}
			if (chunk.toLowerCase() === 'n' || isEscape) {
				session.sendRequest({
					type: 'permission_response',
					request_id: session.modal.request_id,
					allowed: false,
					permission_reply: 'reject',
				});
				session.setModal(null);
				return;
			}
			return;
		}

		// --- Question modal (also appears while busy) ---
		if (session.modal?.kind === 'question') {
			return; // Let TextInput in ModalHost handle input
		}

		if (session.busy && isEscape) {
			session.sendRequest({type: 'interrupt'});
			session.setBusyLabel('Stopping current operation...');
			return;
		}

		// --- Ignore input while busy ---
		if (session.busy) {
			return;
		}

		// Empty-input Tab opens the permission mode picker. This makes leaving
		// plan mode explicit without requiring users to remember /permissions.
		if (!showPicker && key.tab && input.trim() === '') {
			session.sendRequest({type: 'select_command', command: 'permissions'});
			return;
		}

		// --- Command picker ---
		if (showPicker) {
			if (key.upArrow) {
				setPickerIndex(/*
				 * Functional state update: uses max from prior React state; keep the calculation pure and
				 * immutable.
				 */ (i) => Math.max(0, i - 1));
				return;
			}
			if (key.downArrow) {
				setPickerIndex(/*
				 * Functional state update: uses min from prior React state; keep the calculation pure and
				 * immutable.
				 */ (i) => Math.min(commandHints.length - 1, i + 1));
				return;
			}
			if (key.return) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					setInput('');
					if (!handleCommand(selected)) {
						onSubmit(selected);
					}
				}
				return;
			}
			if (key.tab) {
				const selected = commandHints[pickerIndex];
				if (selected) {
					// Complete to the selected command with no trailing space —
					// the user can hit Enter immediately to run it, or keep
					// typing to add args. The trailing space made it look like
					// Tab was "committing" with a token, which broke the flow.
					setInput(selected);
				}
				return;
			}
			if (isEscape) {
				setInput('');
				return;
			}
		}

		if (isEscape) {
			const now = Date.now();
			if ((input || imageAttachments.length > 0) && now - lastEscapeAt < 500) {
				setInput('');
				setImageAttachments([]);
				setHistoryIndex(-1);
				setLastEscapeAt(0);
				return;
			}
			setLastEscapeAt(now);
			return;
		}

		// --- History navigation ---
		if (!showPicker && key.upArrow) {
			const nextIndex = Math.min(history.length - 1, historyIndex + 1);
			if (nextIndex >= 0) {
				setHistoryIndex(nextIndex);
				setInput(history[history.length - 1 - nextIndex] ?? '');
			}
			return;
		}
		if (!showPicker && key.downArrow) {
			const nextIndex = Math.max(-1, historyIndex - 1);
			setHistoryIndex(nextIndex);
			setInput(nextIndex === -1 ? '' : (history[history.length - 1 - nextIndex] ?? ''));
			return;
		}

		// Note: normal Enter submission is handled by TextInput's onSubmit in
		// PromptInput.  Do NOT duplicate it here — that causes double requests.
	});

	 /**
  * Handle submit for the owning UI boundary.
  *
  * Integration: Owned by `AppInner` and collaborates with `sendRequest`, `setModal`,
  * `setModalInput`.
  *
  * Event loop: Runs from an input or UI event; keep synchronous work bounded and order state
  * updates before asynchronous follow-up.
  *
  * Change safety: Preserve React state ownership, functional-update semantics, and render ordering;
  * review every dependent effect and component.
  */
 const onSubmit = (value: string): void => {
		if (session.modal?.kind === 'question') {
			session.sendRequest({
				type: 'question_response',
				request_id: session.modal.request_id,
				answer: value,
			});
			session.setModal(null);
			setModalInput('');
			return;
		}
		if ((!value.trim() && imageAttachments.length === 0) || session.busy || !session.ready) {
			if (session.busy && value.trim() === '/stop') {
				session.sendRequest({type: 'interrupt'});
				session.setBusyLabel('Stopping current operation...');
				setInput('');
			}
			return;
		}
		// Check if it's an interactive command
		if (imageAttachments.length === 0 && handleCommand(value)) {
			setHistory(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (items) => [...items, value]);
			setHistoryIndex(-1);
			setInput('');
			return;
		}
		session.sendRequest({type: 'submit_line', line: value, images: imagePayloads()});
		if (value.trim()) {
			setHistory(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (items) => [...items, value]);
		}
		setHistoryIndex(-1);
		setInput('');
		setImageAttachments([]);
		session.setBusy(true);
	};

	// Scripted automation
	useEffect(/*
	 * React effect: uses setTimeout after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		if (scriptIndex >= scriptedSteps.length) {
			return;
		}
		if (session.busy || session.modal || selectModal) {
			return;
		}
		const step = scriptedSteps[scriptIndex];
		const timer = setTimeout(/*
		 * Timer callback: uses onSubmit, setScriptIndex on Node's event loop; keep work bounded and
		 * preserve matching cleanup.
		 */ () => {
			onSubmit(step);
			setScriptIndex(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (index) => index + 1);
		}, 200);
		return /*
		 * Effect cleanup: uses clearTimeout; keep it paired with every resource acquired by the
		 * effect.
		 */ () => clearTimeout(timer);
	}, [scriptIndex, session.busy, session.modal, selectModal]);

	return (
		<Box flexDirection="column" paddingX={1} height="100%">
			{/* Conversation area */}
			<Box flexDirection="column" flexGrow={1}>
				<ConversationView
					items={deferredTranscript}
					assistantBuffer={deferredAssistantBuffer}
					showWelcome={session.ready && outputStyle !== 'codex'}
					outputStyle={outputStyle}
				/>
			</Box>

			{/* Backend modal (permission confirm, question, mcp auth) */}
			{session.modal ? (
				<ModalHost
					modal={session.modal}
					modalInput={modalInput}
					setModalInput={setModalInput}
					onSubmit={onSubmit}
				/>
			) : null}

			{/* Frontend select modal (permissions picker, etc.) */}
			{selectModal ? (
				<SelectModal
					title={selectModal.title}
					options={selectModal.options}
					selectedIndex={selectIndex}
				/>
			) : null}

			{/* Command picker */}
			{showPicker ? (
				<CommandPicker hints={commandHints} selectedIndex={pickerIndex} />
			) : null}

			{/* Todo panel */}
			{session.ready && deferredTodoMarkdown ? (
				<TodoPanel markdown={deferredTodoMarkdown} />
			) : null}

			{/* Swarm panel */}
			{session.ready && (deferredSwarmTeammates.length > 0 || deferredSwarmNotifications.length > 0) ? (
				<SwarmPanel teammates={deferredSwarmTeammates} notifications={deferredSwarmNotifications} />
			) : null}

			{/* Status bar (only after backend is ready) */}
			{session.ready ? (
				<StatusBar status={deferredStatus} tasks={deferredTasks} activeToolName={session.busy ? currentToolName : undefined} />
			) : null}

			{/* Input — show loading indicator until backend is ready */}
			{!session.ready ? (
				<Box>
					<Text color={theme.colors.warning}>Connecting to backend...</Text>
				</Box>
			) : session.modal || selectModal ? null : (
				<PromptInput
					busy={session.busy}
					input={input}
					setInput={setInput}
					onSubmit={onSubmit}
					toolName={session.busy ? currentToolName : undefined}
					statusLabel={session.busy ? (session.busyLabel ?? (currentToolName ? `Running ${currentToolName}...` : 'Running agent loop...')) : undefined}
					suppressSubmit={showPicker}
					imageAttachmentLabels={imageAttachments.map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (image) => image.label)}
					clipboardStatus={clipboardStatus}
				/>
			)}

			{/* Keyboard hints (only after backend is ready) */}
			{session.ready && !session.modal && !selectModal ? (
				<Box>
					<Text dimColor>
						<Text color={theme.colors.primary}>shift+enter</Text> newline{'  '}
						<Text color={theme.colors.primary}>enter</Text> send{'  '}
						<Text color={theme.colors.primary}>/</Text> commands{'  '}
						<Text color={theme.colors.primary}>tab</Text> mode{'  '}
						<Text color={theme.colors.primary}>{'\u2191\u2193'}</Text> history{'  '}
						<Text color={theme.colors.primary}>{session.busy ? '/stop' : 'esc'}</Text> stop{'  '}
						<Text color={theme.colors.primary}>ctrl+c</Text> {session.busy ? 'stop' : 'exit'}
					</Text>
				</Box>
			) : null}
		</Box>
	);
}
