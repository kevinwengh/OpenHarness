/**
 * Render and coordinate the `TodoPanel` portion of the Ink terminal interface.
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

import React, {useState} from 'react';
import {Box, Text, useInput} from 'ink';

export type TodoItem = {
	text: string;
	checked: boolean;
};

/**
 * Parse todo items into the frontend's normalized representation.
 *
 * Integration: Owned by `TodoPanel.tsx` and collaborates with `split`, `match`, `push`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function parseTodoItems(markdown: string): TodoItem[] {
	const lines = markdown.split('\n');
	const items: TodoItem[] = [];
	for (const line of lines) {
		const m = line.match(/^\s*-\s+\[([ xX])\]\s+(.+)/);
		if (m) {
			items.push({checked: m[1].toLowerCase() === 'x', text: m[2].trim()});
		}
	}
	return items;
}

/**
 * Render the TodoPanelInner React component.
 *
 * Integration: Owned by `TodoPanel.tsx` and collaborates with `useState`, `parseTodoItems`,
 * `useInput`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function TodoPanelInner({
	markdown,
	compact: initialCompact = false,
}: {
	markdown: string;
	compact?: boolean;
}): React.JSX.Element | null {
	const [compact, setCompact] = useState(initialCompact);
	const items = parseTodoItems(markdown);

	useInput(/*
	 * useInput callback: uses setCompact; keep event-loop work bounded and preserve the callback's
	 * return contract.
	 */ (chunk, key) => {
		if (key.ctrl && chunk === 't') {
			setCompact(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (c) => !c);
		}
	});

	if (items.length === 0) {
		return null;
	}

	const done = items.filter(/*
	 * filter callback: computes its callback result; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ (i) => i.checked).length;
	const total = items.length;

	if (compact) {
		return (
			<Box>
				<Text color="yellow" bold>
					{'☑ '}
				</Text>
				<Text dimColor>
					Todos: {done}/{total} done
				</Text>
				<Text dimColor> [ctrl+t expand]</Text>
			</Box>
		);
	}

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1} marginTop={1}>
			<Box>
				<Text color="yellow" bold>
					{'☑ '}
				</Text>
				<Text bold>
					Todo List{' '}
				</Text>
				<Text dimColor>
					({done}/{total})
				</Text>
				<Text dimColor> [ctrl+t compact]</Text>
			</Box>
			{items.map(/*
			 * map callback: computes its callback result; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (item, i) => (
				<Box key={i}>
					<Text color={item.checked ? 'green' : 'white'}>
						{item.checked ? '  ☑ ' : '  ☐ '}
					</Text>
					<Text
						color={item.checked ? 'green' : undefined}
						dimColor={item.checked}
					>
						{item.text}
					</Text>
				</Box>
			))}
		</Box>
	);
}

export const TodoPanel = React.memo(TodoPanelInner);

export {parseTodoItems};
