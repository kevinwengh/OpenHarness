/**
 * Render and coordinate the `TranscriptPane` portion of the Ink terminal interface.
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

import React from 'react';
import {Box, Text} from 'ink';

import type {TranscriptItem} from '../types.js';

/**
 * Render the TranscriptPane React component.
 *
 * Integration: Owned by `TranscriptPane.tsx` and collaborates with `slice`, `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function TranscriptPane({
	items,
	assistantBuffer,
}: {
	items: TranscriptItem[];
	assistantBuffer: string;
}): React.JSX.Element {
	const visible = items.slice(-24);
	return (
		<Box flexDirection="column" width="68%" paddingRight={1}>
			<Text bold>Transcript</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1} minHeight={24}>
				{visible.map(/*
				 * map callback: uses roleColor, labelFor; keep event-loop work bounded and preserve the
				 * callback's return contract.
				 */ (item, index) => (
					<Text key={`${index}-${item.role}`} color={roleColor(item.role)}>
						{labelFor(item.role)} {item.text}
					</Text>
				))}
				{assistantBuffer ? <Text color="green">assistant&gt; {assistantBuffer}</Text> : null}
			</Box>
		</Box>
	);
}

/**
 * Derive label for from the current frontend state and inputs.
 *
 * Integration: Owned by `TranscriptPane.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function labelFor(role: TranscriptItem['role']): string {
	switch (role) {
		case 'tool':
			return 'tool>';
		case 'tool_result':
			return 'tool_result>';
		default:
			return `${role}>`;
	}
}

/**
 * Derive role color from the current frontend state and inputs.
 *
 * Integration: Owned by `TranscriptPane.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function roleColor(role: TranscriptItem['role']): string | undefined {
	if (role === 'assistant') {
		return 'green';
	}
	if (role === 'tool') {
		return 'cyan';
	}
	if (role === 'tool_result') {
		return 'yellow';
	}
	if (role === 'system') {
		return 'magenta';
	}
	if (role === 'log') {
		return 'gray';
	}
	return undefined;
}
