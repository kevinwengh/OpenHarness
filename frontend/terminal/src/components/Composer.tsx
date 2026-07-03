/**
 * Render and coordinate the `Composer` portion of the Ink terminal interface.
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
import TextInput from 'ink-text-input';

/**
 * Render the Composer React component.
 *
 * Integration: Owned by `Composer.tsx` and collaborates with `String`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function Composer({
	busy,
	input,
	setInput,
	onSubmit,
	historyIndex,
}: {
	busy: boolean;
	input: string;
	setInput: (value: string) => void;
	onSubmit: (value: string) => void;
	historyIndex: number;
}): React.JSX.Element {
	return (
		<Box flexDirection="column" marginTop={1}>
			<Box borderStyle="round" paddingX={1}>
				<Text color={busy ? 'yellow' : 'green'}>{busy ? 'busy' : 'ready'}</Text>
				<Text> </Text>
				<TextInput value={input} onChange={setInput} onSubmit={onSubmit} />
			</Box>
			<Box marginTop={1}>
				<Text dimColor>
					shift+enter=newline enter=submit tab=complete ctrl-p/ctrl-n=history history_index={String(historyIndex)}
				</Text>
			</Box>
		</Box>
	);
}
