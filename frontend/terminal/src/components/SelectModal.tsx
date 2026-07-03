/**
 * Render and coordinate the `SelectModal` portion of the Ink terminal interface.
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

export type SelectOption = {
	value: string;
	label: string;
	description?: string;
	active?: boolean;
};

/**
 * Render the SelectModal React component.
 *
 * Integration: Owned by `SelectModal.tsx` and collaborates with `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function SelectModal({
	title,
	options,
	selectedIndex,
}: {
	title: string;
	options: SelectOption[];
	selectedIndex: number;
}): React.JSX.Element {
	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginTop={1}>
			<Text bold color="cyan">{title}</Text>
			<Text> </Text>
			{options.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (opt, i) => {
				const isSelected = i === selectedIndex;
				const isCurrent = opt.active;
				return (
					<Box key={opt.value} flexDirection="row">
						<Text color={isSelected ? 'cyan' : undefined} bold={isSelected}>
							{isSelected ? '\u276F ' : '  '}
							<Text color={isSelected ? 'cyan' : undefined}>
								{opt.label}
							</Text>
						</Text>
						{isCurrent ? <Text color="green"> (current)</Text> : null}
						{opt.description ? <Text dimColor>  {opt.description}</Text> : null}
					</Box>
				);
			})}
			<Text> </Text>
			<Text dimColor>{'\u2191\u2193'} navigate{'  '}{'\u23CE'} select{'  '}esc cancel</Text>
		</Box>
	);
}
