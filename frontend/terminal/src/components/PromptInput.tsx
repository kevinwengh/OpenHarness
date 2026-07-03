/**
 * Render and coordinate the `PromptInput` portion of the Ink terminal interface.
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

import React, {useEffect, useRef, useState} from 'react';
import {Box, Text, useInput, useStdin} from 'ink';
import chalk from 'chalk';

import {useTheme} from '../theme/ThemeContext.js';
import {Spinner} from './Spinner.js';

/**
 * Derive noop from the current frontend state and inputs.
 *
 * Integration: Owned by `PromptInput.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
const noop = (): void => {};
const BACKSPACE_CONTROL_PATTERN = /^[\b\u007f]+$/;

/**
 * Return backspace delete count for the calling frontend path.
 *
 * Integration: Owned by `PromptInput.tsx` and collaborates with `test`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function getBackspaceDeleteCount(sequence: string): number {
	if (!sequence || !BACKSPACE_CONTROL_PATTERN.test(sequence)) {
		return 1;
	}

	return [...sequence].length;
}

/**
 * Render the MultilineTextInput React component.
 *
 * Integration: Owned by `PromptInput.tsx` and collaborates with `useState`, `useStdin`, `useRef`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function MultilineTextInput({
	value,
	onChange,
	onSubmit,
	focus = true,
	promptPrefix,
	promptColor,
}: {
	value: string;
	onChange: (value: string) => void;
	onSubmit?: (value: string) => void;
	focus?: boolean;
	promptPrefix: string;
	promptColor: string;
}): React.JSX.Element {
	const [cursorOffset, setCursorOffset] = useState(value.length);
	const {internal_eventEmitter} = useStdin();
	const lastSequenceRef = useRef('');
	// Tracks the last value this component produced via onChange. If the
	// incoming `value` prop diverges from this, the change came from outside
	// (tab completion, history recall, programmatic clear) and we should
	// move the cursor to the end — otherwise the cursor stays wherever the
	// user had it, which puts subsequent keystrokes in the middle of the
	// newly-completed text. See HKUDS/OpenHarness#183.
	const lastInternalValueRef = useRef<string>(value);

	useEffect(/*
	 * React effect: uses setCursorOffset after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		if (value === lastInternalValueRef.current) {
			// Self-authored update; cursor was already positioned by the
			// handler that called onChange.
			return;
		}
		lastInternalValueRef.current = value;
		setCursorOffset(value.length);
	}, [value]);

	 /**
  * Derive commit value from the current frontend state and inputs.
  *
  * Integration: Owned by `MultilineTextInput` and collaborates with `onChange`.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
  */
 const commitValue = (nextValue: string): void => {
		lastInternalValueRef.current = nextValue;
		onChange(nextValue);
	};

	useEffect(/*
	 * React effect: uses on after render; keep dependencies, asynchronous work, and returned
	 * cleanup synchronized.
	 */ () => {
		if (!focus) {
			return;
		}

		  /**
   * Handle raw input for the owning UI boundary.
   *
   * Integration: Owned by `useEffect callback 1` and collaborates with `isBuffer`, `toString`,
   * `String`.
   *
   * Event loop: Runs from an input or UI event; keep synchronous work bounded and order state
   * updates before asynchronous follow-up.
   *
   * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
   */
  const handleRawInput = (chunk: string | Buffer): void => {
			lastSequenceRef.current = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
		};

		internal_eventEmitter.on('input', handleRawInput);
		return /*
		 * Effect cleanup: uses removeListener; keep it paired with every resource acquired by the
		 * effect.
		 */ () => {
			internal_eventEmitter.removeListener('input', handleRawInput);
		};
	}, [focus, internal_eventEmitter]);

	useInput(
		/*
		 * useInput callback: uses slice, setCursorOffset, commitValue; keep event-loop work bounded
		 * and preserve the callback's return contract.
		 */ (input, key) => {
			if (!focus) {
				return;
			}

			if (
				key.upArrow ||
				key.downArrow ||
				key.tab ||
				(key.shift && key.tab) ||
				key.escape ||
				(key.ctrl && (input === 'c' || input === 'v'))
			) {
				return;
			}

			if (key.return) {
				if (key.shift) {
					const nextValue = value.slice(0, cursorOffset) + '\n' + value.slice(cursorOffset);
					setCursorOffset(cursorOffset + 1);
					commitValue(nextValue);
					return;
				}
				onSubmit?.(value);
				return;
			}

			if (key.leftArrow) {
				setCursorOffset(/*
				 * Functional state update: uses max from prior React state; keep the calculation pure and
				 * immutable.
				 */ (previous) => Math.max(0, previous - 1));
				return;
			}

			if (key.rightArrow) {
				setCursorOffset(/*
				 * Functional state update: uses min from prior React state; keep the calculation pure and
				 * immutable.
				 */ (previous) => Math.min(value.length, previous + 1));
				return;
			}

			if (key.backspace) {
				if (cursorOffset === 0) {
					return;
				}
				const deleteCount = Math.min(cursorOffset, getBackspaceDeleteCount(lastSequenceRef.current || input));
				const nextValue = value.slice(0, cursorOffset - deleteCount) + value.slice(cursorOffset);
				setCursorOffset(cursorOffset - deleteCount);
				commitValue(nextValue);
				return;
			}

			if (key.delete) {
				// Ink reports the common DEL byte (`0x7f`) as `delete`, even though
				// many terminals emit it for the Backspace key. Use the raw sequence
				// to distinguish that case from a true forward-delete escape sequence.
				if (
					lastSequenceRef.current === '\x7f' ||
					lastSequenceRef.current === '\x1b\x7f' ||
					BACKSPACE_CONTROL_PATTERN.test(lastSequenceRef.current)
				) {
					if (cursorOffset === 0) {
						return;
					}
					const deleteCount = Math.min(cursorOffset, getBackspaceDeleteCount(lastSequenceRef.current));
					const nextValue = value.slice(0, cursorOffset - deleteCount) + value.slice(cursorOffset);
					setCursorOffset(cursorOffset - deleteCount);
					commitValue(nextValue);
					return;
				}

				if (cursorOffset >= value.length) {
					return;
				}
				const nextValue = value.slice(0, cursorOffset) + value.slice(cursorOffset + 1);
				commitValue(nextValue);
				return;
			}

			if (!input) {
				return;
			}

			const nextValue = value.slice(0, cursorOffset) + input + value.slice(cursorOffset);
			setCursorOffset(cursorOffset + input.length);
			commitValue(nextValue);
		},
		{isActive: focus},
	);

	let renderedValue = value;
	if (focus) {
		if (value.length === 0) {
			renderedValue = chalk.inverse(' ');
		} else {
			renderedValue = '';
			let index = 0;
			for (const char of value) {
				if (index === cursorOffset) {
					renderedValue += chalk.inverse(char === '\n' ? ' ' : char);
				} else {
					renderedValue += char;
				}
				index += 1;
			}
			if (cursorOffset === value.length) {
				renderedValue += chalk.inverse(' ');
			}
		}
	}

	const lines = renderedValue.split('\n');
	const indent = ' '.repeat(promptPrefix.length);
	return (
		<Box flexDirection="column">
			{lines.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (line, index) => (
				<Box key={`${index}:${line}`}>
					<Text color={promptColor} bold>
						{index === 0 ? promptPrefix : indent}
					</Text>
					<Text>{line.length > 0 ? line : ' '}</Text>
				</Box>
			))}
		</Box>
	);
}

/**
 * Render the PromptInput React component.
 *
 * Integration: Owned by `PromptInput.tsx` and collaborates with `useTheme`, `join`, `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function PromptInput({
	busy,
	input,
	setInput,
	onSubmit,
	toolName,
	suppressSubmit,
	statusLabel,
	imageAttachmentLabels = [],
	clipboardStatus,
}: {
	busy: boolean;
	input: string;
	setInput: (value: string) => void;
	onSubmit: (value: string) => void;
	toolName?: string;
	suppressSubmit?: boolean;
	statusLabel?: string;
	imageAttachmentLabels?: string[];
	clipboardStatus?: string | null;
}): React.JSX.Element {
	const {theme} = useTheme();
	const promptPrefix = busy ? '… ' : '> ';

	return (
		<Box flexDirection="column">
			{busy ? (
				<Box flexDirection="column" marginBottom={0}>
					<Box>
						<Spinner label={statusLabel ?? (toolName ? `Running ${toolName}...` : 'Running...')} />
					</Box>
				</Box>
			) : null}
			{imageAttachmentLabels.length > 0 ? (
				<Box>
					<Text color={theme.colors.accent}>
						{imageAttachmentLabels.map(/*
						 * map callback: computes its callback result; keep event-loop work bounded and preserve
						 * the callback's return contract.
						 */ (label, index) => `[image ${index + 1}: ${label}]`).join(' ')}
					</Text>
				</Box>
			) : null}
			{clipboardStatus ? (
				<Box>
					<Text color={theme.colors.muted}>{clipboardStatus}</Text>
				</Box>
			) : null}
			<MultilineTextInput
				value={input}
				onChange={setInput}
				onSubmit={suppressSubmit ? noop : onSubmit}
				focus
				promptPrefix={promptPrefix}
				promptColor={theme.colors.primary}
			/>
		</Box>
	);
}
