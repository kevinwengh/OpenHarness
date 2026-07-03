/**
 * Render and coordinate the `ModalHost` portion of the Ink terminal interface.
 *
 * Integration: Consumed by the terminal component tree; Python remains authoritative for runtime
 * and persisted conversation state.
 *
 * Event loop: React render and input callbacks share Node's event loop with backend-protocol
 * processing, so rendering work must remain bounded.
 *
 * Change safety: Preserve props, keyboard/focus behavior, accessibility text, and transcript/event
 * ordering expected by parent components.
 */

import React, {useEffect, useState} from 'react';
import {Box, Text, useInput} from 'ink';
import TextInput from 'ink-text-input';

const WAIT_FRAMES = [
	'Agent is waiting for your input   ',
	'Agent is waiting for your input.  ',
	'Agent is waiting for your input.. ',
	'Agent is waiting for your input...',
];
const MAX_DIFF_LINES = 40;

/**
 * Render the WaitingAnimation React component.
 *
 * Integration: Owned by `ModalHost.tsx` and collaborates with `useState`, `useEffect`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function WaitingAnimation(): React.JSX.Element {
	const [frame, setFrame] = useState(0);
	useEffect(/*
	 * React effect: uses setInterval after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		const timer = setInterval(/*
		 * Timer callback: uses setFrame on Node's event loop; keep work bounded and preserve matching
		 * cleanup.
		 */ () => setFrame(/*
		 * Functional state update: computes its callback result from prior React state; keep the
		 * calculation pure and immutable.
		 */ (f) => (f + 1) % WAIT_FRAMES.length), 500);
		return /*
		 * Effect cleanup: uses clearInterval; keep it paired with every resource acquired by the
		 * effect.
		 */ () => clearInterval(timer);
	}, []);
	return (
		<Text color="magenta" dimColor>
			{WAIT_FRAMES[frame]}
		</Text>
	);
}

/**
 * Render the QuestionModal React component.
 *
 * Integration: Owned by `ModalHost.tsx` and collaborates with `useState`, `useInput`, `String`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function QuestionModal({
	modal,
	modalInput,
	setModalInput,
	onSubmit,
}: {
	modal: Record<string, unknown>;
	modalInput: string;
	setModalInput: (value: string) => void;
	onSubmit: (value: string) => void;
}): React.JSX.Element {
	const [extraLines, setExtraLines] = useState<string[]>([]);

	useInput(/*
	 * useInput callback: uses setExtraLines, setModalInput; keep event-loop work bounded and
	 * preserve the callback's return contract.
	 */ (_chunk, key) => {
		if (key.shift && key.return) {
			setExtraLines(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (lines) => [...lines, modalInput]);
			setModalInput('');
		}
	});

	 /**
  * Handle submit for the owning UI boundary.
  *
  * Integration: Owned by `QuestionModal` and collaborates with `setExtraLines`, `onSubmit`, `join`.
  *
  * Event loop: Runs from an input or UI event; keep synchronous work bounded and order state
  * updates before asynchronous follow-up.
  *
  * Change safety: Preserve React state ownership, functional-update semantics, and render ordering;
  * review every dependent effect and component.
  */
 const handleSubmit = (value: string): void => {
		const allLines = [...extraLines, value];
		setExtraLines([]);
		onSubmit(allLines.join('\n'));
	};

	const toolName = modal.tool_name ? String(modal.tool_name) : null;
	const reason = modal.reason ? String(modal.reason) : null;
	const question = String(modal.question ?? 'Question');

	return (
		<Box flexDirection="column" marginTop={1} borderStyle="double" borderColor="magenta" paddingX={1}>
			<WaitingAnimation />
			<Box marginTop={1}>
				<Text color="magenta" bold>{'\u2753 '}</Text>
				<Text bold>{question}</Text>
			</Box>
			{toolName ? (
				<Text dimColor>
					{'  '}Tool: <Text color="cyan">{toolName}</Text>
				</Text>
			) : null}
			{reason ? (
				<Text dimColor>{'  '}Reason: {reason}</Text>
			) : null}
			{extraLines.length > 0 && (
				<Box flexDirection="column" marginTop={1} marginLeft={2}>
					{extraLines.map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (line, i) => (
						<Text key={i} dimColor>
							{line}
						</Text>
					))}
				</Box>
			)}
			<Box marginTop={1}>
				<Text color="cyan">{'> '}</Text>
				<TextInput value={modalInput} onChange={setModalInput} onSubmit={handleSubmit} />
			</Box>
			<Text dimColor>{'  '}shift+enter: newline | enter: submit</Text>
		</Box>
	);
}

type DiffLineKind = 'add' | 'del' | 'hunk' | 'context';

type ParsedDiffLine = {
	kind: DiffLineKind;
	content: string;
};

/**
 * Parse diff lines into the frontend's normalized representation.
 *
 * Integration: Owned by `ModalHost.tsx` and collaborates with `flatMap`, `split`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function parseDiffLines(diffText: string): ParsedDiffLine[] {
	return diffText
		.split('\n')
		.flatMap(/*
		 * flatMap callback: uses startsWith, slice; keep event-loop work bounded and preserve the
		 * callback's return contract.
		 */ (raw): ParsedDiffLine[] => {
			if (!raw || raw.startsWith('+++') || raw.startsWith('---')) {
				return [];
			}
			if (raw.startsWith('@@')) {
				return [{kind: 'hunk', content: raw}];
			}
			if (raw.startsWith('+')) {
				return [{kind: 'add', content: raw.slice(1)}];
			}
			if (raw.startsWith('-')) {
				return [{kind: 'del', content: raw.slice(1)}];
			}
			return [{kind: 'context', content: raw.startsWith(' ') ? raw.slice(1) : raw}];
		});
}

/**
 * Render the EditDiffModal React component.
 *
 * Integration: Owned by `ModalHost.tsx` and collaborates with `String`, `Number`, `parseDiffLines`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function EditDiffModal({modal}: {modal: Record<string, unknown>}): React.JSX.Element {
	const path = String(modal.path ?? '');
	const added = Number(modal.added ?? 0);
	const removed = Number(modal.removed ?? 0);
	const lines = parseDiffLines(String(modal.diff ?? ''));
	const visibleLines = lines.slice(0, MAX_DIFF_LINES);
	const hiddenCount = lines.length - visibleLines.length;

	return (
		<Box flexDirection="column" marginTop={1}>
			<Text>
				<Text color="yellow" bold>{'\u250C '}</Text>
				<Text bold>Edit </Text>
				<Text color="cyan" bold>{path}</Text>
				<Text>{'  '}</Text>
				<Text color="green">{`+${added}`}</Text>
				<Text>{' '}</Text>
				<Text color="red">{`-${removed}`}</Text>
			</Text>
			{visibleLines.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (line, index) => {
				if (line.kind === 'hunk') {
					return (
						<Text key={index}>
							<Text color="yellow">{'\u2502 '}</Text>
							<Text color="cyan" dimColor>{line.content}</Text>
						</Text>
					);
				}
				if (line.kind === 'add') {
					return (
						<Text key={index}>
							<Text color="yellow">{'\u2502 '}</Text>
							<Text color="green">+</Text>
							<Text color="green">{line.content}</Text>
						</Text>
					);
				}
				if (line.kind === 'del') {
					return (
						<Text key={index}>
							<Text color="yellow">{'\u2502 '}</Text>
							<Text color="red">-</Text>
							<Text color="red">{line.content}</Text>
						</Text>
					);
				}
				return (
					<Text key={index}>
						<Text color="yellow">{'\u2502 '}</Text>
						<Text dimColor>{' '}{line.content}</Text>
					</Text>
				);
			})}
			{hiddenCount > 0 ? (
				<Text>
					<Text color="yellow">{'\u2502 '}</Text>
					<Text dimColor>... {hiddenCount} more lines hidden</Text>
				</Text>
			) : null}
			<Text>
				<Text color="yellow">{'\u2514 '}</Text>
				<Text color="green">[y] Once</Text>
				<Text>{'  '}</Text>
				<Text color="green">[a] Always</Text>
				<Text>{'  '}</Text>
				<Text color="red">[n] Deny</Text>
			</Text>
		</Box>
	);
}

/**
 * Render the ModalHostInner React component.
 *
 * Integration: Owned by `ModalHost.tsx` and collaborates with `String`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function ModalHostInner({
	modal,
	modalInput,
	setModalInput,
	onSubmit,
}: {
	modal: Record<string, unknown> | null;
	modalInput: string;
	setModalInput: (value: string) => void;
	onSubmit: (value: string) => void;
}): React.JSX.Element | null {
	if (modal?.kind === 'permission') {
		return (
			<Box flexDirection="column" marginTop={1}>
				<Text>
					<Text color="yellow" bold>{'\u250C '}</Text>
					<Text bold>Allow </Text>
					<Text color="cyan" bold>{String(modal.tool_name ?? 'tool')}</Text>
					<Text bold>?</Text>
				</Text>
				{modal.reason ? (
					<Text>
						<Text color="yellow">{'\u2502 '}</Text>
						<Text dimColor>{String(modal.reason)}</Text>
					</Text>
				) : null}
				<Text>
					<Text color="yellow">{'\u2514 '}</Text>
					<Text color="green">[y] Allow</Text>
					<Text>{'  '}</Text>
					<Text color="red">[n] Deny</Text>
				</Text>
			</Box>
		);
	}
	if (modal?.kind === 'edit_diff') {
		return <EditDiffModal modal={modal} />;
	}
	if (modal?.kind === 'question') {
		return (
			<QuestionModal
				modal={modal}
				modalInput={modalInput}
				setModalInput={setModalInput}
				onSubmit={onSubmit}
			/>
		);
	}
	if (modal?.kind === 'mcp_auth') {
		return (
			<Box flexDirection="column" marginTop={1}>
				<Text>
					<Text color="yellow" bold>{'\u{1F511} '}</Text>
					<Text bold>MCP Authentication</Text>
				</Text>
				<Text dimColor>{String(modal.prompt ?? 'Provide auth details')}</Text>
				<Box>
					<Text color="cyan">{'> '}</Text>
					<TextInput value={modalInput} onChange={setModalInput} onSubmit={onSubmit} />
				</Box>
			</Box>
		);
	}
	return null;
}

export const ModalHost = React.memo(ModalHostInner);
