/**
 * Render and coordinate the `WelcomeBanner` portion of the Ink terminal interface.
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

import {useTheme} from '../theme/ThemeContext.js';

const VERSION = '0.1.0';

// prettier-ignore
const LOGO = [
	' ██████╗ ██╗  ██╗    ███╗   ███╗██╗   ██╗    ██╗  ██╗ █████╗ ██████╗ ███╗   ██╗███████╗███████╗███████╗██╗',
	'██╔═══██╗██║  ██║    ████╗ ████║╚██╗ ██╔╝    ██║  ██║██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝██║',
	'██║   ██║███████║    ██╔████╔██║ ╚████╔╝     ███████║███████║██████╔╝██╔██╗ ██║█████╗  ███████╗███████╗██║',
	'██║   ██║██╔══██║    ██║╚██╔╝██║  ╚██╔╝      ██╔══██║██╔══██║██╔══██╗██║╚██╗██║██╔══╝  ╚════██║╚════██║╚═╝',
	'╚██████╔╝██║  ██║    ██║ ╚═╝ ██║   ██║       ██║  ██║██║  ██║██║  ██║██║ ╚████║███████╗███████║███████║██╗',
	' ╚═════╝ ╚═╝  ╚═╝    ╚═╝     ╚═╝   ╚═╝       ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝╚═╝',
];

/**
 * Render the WelcomeBanner React component.
 *
 * Integration: Owned by `WelcomeBanner.tsx` and collaborates with `useTheme`, `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function WelcomeBanner(): React.JSX.Element {
	const {theme} = useTheme();

	return (
		<Box flexDirection="column" marginBottom={1}>
			<Box flexDirection="column" paddingX={0}>
				{LOGO.map(/*
				 * map callback: computes its callback result; keep event-loop work bounded and preserve the
				 * callback's return contract.
				 */ (line, i) => (
					<Text key={i} color={theme.colors.primary} bold>{line}</Text>
				))}
				<Text> </Text>
				<Text>
					<Text dimColor> An AI-powered coding assistant</Text>
					<Text dimColor>{'  '}v{VERSION}</Text>
				</Text>
				<Text> </Text>
				<Text>
					<Text dimColor> </Text>
					<Text color={theme.colors.primary}>/help</Text>
					<Text dimColor> commands</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>/model</Text>
					<Text dimColor> switch</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>Ctrl+C</Text>
					<Text dimColor> exit</Text>
				</Text>
			</Box>
		</Box>
	);
}
