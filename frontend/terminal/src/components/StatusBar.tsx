/**
 * Render and coordinate the `StatusBar` portion of the Ink terminal interface.
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
import {Box, Text} from 'ink';

import {useTheme} from '../theme/ThemeContext.js';
import type {TaskSnapshot} from '../types.js';

const SEP = ' \u2502 ';

const WRITE_TOOLS = new Set([
	'Write', 'Edit', 'MultiEdit', 'NotebookEdit',
	'Bash', 'computer', 'str_replace_editor',
]);

/**
 * Render the PlanModeIndicator React component.
 *
 * Integration: Owned by `StatusBar.tsx` and collaborates with `useState`, `useEffect`, `has`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function PlanModeIndicator({
	mode,
	activeToolName,
}: {
	mode: string;
	activeToolName?: string;
}): React.JSX.Element | null {
	const [flash, setFlash] = useState(false);
	const [prevMode, setPrevMode] = useState(mode);

	useEffect(/*
	 * React effect: uses setFlash, setTimeout, setPrevMode after render; keep dependencies,
	 * asynchronous work, and returned cleanup synchronized.
	 */ () => {
		if (prevMode === 'plan' && mode !== 'plan' && prevMode !== mode) {
			setFlash(true);
			const timer = setTimeout(/*
			 * Timer callback: uses setFlash on Node's event loop; keep work bounded and preserve
			 * matching cleanup.
			 */ () => setFlash(false), 800);
			setPrevMode(mode);
			return /*
			 * Effect cleanup: uses clearTimeout; keep it paired with every resource acquired by the
			 * effect.
			 */ () => clearTimeout(timer);
		}
		setPrevMode(mode);
	}, [mode]);

	if (mode !== 'plan' && mode !== 'Plan Mode') {
		if (flash) {
			return (
				<Text color="green" bold>
					{' PLAN MODE OFF '}
				</Text>
			);
		}
		return null;
	}

	const isBlockedTool = activeToolName != null && WRITE_TOOLS.has(activeToolName);

	return (
		<Text>
			<Text color="yellow" bold>{' [PLAN MODE] '}</Text>
			{isBlockedTool ? (
				<Text color="red">{'\uD83D\uDEAB '}{activeToolName} blocked</Text>
			) : null}
		</Text>
	);
}

/**
 * Render the StatusBarInner React component.
 *
 * Integration: Owned by `StatusBar.tsx` and collaborates with `useTheme`, `String`, `Number`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function StatusBarInner({
	status,
	tasks,
	activeToolName,
}: {
	status: Record<string, unknown>;
	tasks: TaskSnapshot[];
	activeToolName?: string;
}): React.JSX.Element {
	const {theme} = useTheme();
	const model = String(status.model ?? 'unknown');
	const mode = String(status.permission_mode ?? 'default');
	const taskCount = tasks.length;
	const mcpCount = Number(status.mcp_connected ?? 0);
	const inputTokens = Number(status.input_tokens ?? 0);
	const outputTokens = Number(status.output_tokens ?? 0);
	const isPlanMode = mode === 'plan' || mode === 'Plan Mode';

	return (
		<Box flexDirection="column">
			<Text dimColor>{'─'.repeat(60)}</Text>
			<Box flexDirection="row" alignItems="center">
				<Text>
					<Text color={theme.colors.primary} dimColor>model: {model}</Text>
					<Text dimColor>{SEP}</Text>
					{inputTokens > 0 || outputTokens > 0 ? (
						<>
							<Text dimColor>tokens: {formatNum(inputTokens)}{'\u2193'} {formatNum(outputTokens)}{'\u2191'}</Text>
							<Text dimColor>{SEP}</Text>
						</>
					) : null}
					{!isPlanMode ? (
						<Text dimColor>mode: {mode}</Text>
					) : null}
					{taskCount > 0 ? (
						<>
							<Text dimColor>{SEP}</Text>
							<Text dimColor>tasks: {taskCount}</Text>
						</>
					) : null}
					{mcpCount > 0 ? (
						<>
							<Text dimColor>{SEP}</Text>
							<Text dimColor>mcp: {mcpCount}</Text>
						</>
					) : null}
				</Text>
				{isPlanMode ? (
					<PlanModeIndicator mode={mode} activeToolName={activeToolName} />
				) : null}
			</Box>
		</Box>
	);
}

export const StatusBar = React.memo(StatusBarInner);

/**
 * Format num for presentation.
 *
 * Integration: Owned by `StatusBar.tsx` and collaborates with `toFixed`, `String`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function formatNum(n: number): string {
	if (n >= 1000) {
		return `${(n / 1000).toFixed(1)}k`;
	}
	return String(n);
}
