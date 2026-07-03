/**
 * Render and coordinate the `CommandPicker` portion of the Ink terminal interface.
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

/**
 * Render the CommandPickerInner React component.
 *
 * Integration: Owned by `CommandPicker.tsx` and collaborates with `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function CommandPickerInner({
	hints,
	selectedIndex,
}: {
	hints: string[];
	selectedIndex: number;
}): React.JSX.Element | null {
	if (hints.length === 0) {
		return null;
	}

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginBottom={0}>
			<Text dimColor bold> Commands</Text>
			{hints.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (hint, i) => {
				const isSelected = i === selectedIndex;
				return (
					<Box key={hint}>
						<Text color={isSelected ? 'cyan' : undefined} bold={isSelected}>
							{isSelected ? '\u276F ' : '  '}
							{hint}
						</Text>
						{isSelected ? <Text dimColor> [enter]</Text> : null}
					</Box>
				);
			})}
			<Text dimColor> {'\u2191\u2193'} navigate{'  '}{'\u23CE'} select{'  '}esc dismiss</Text>
		</Box>
	);
}

export const CommandPicker = React.memo(CommandPickerInner);
