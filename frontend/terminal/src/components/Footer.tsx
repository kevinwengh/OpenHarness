/**
 * Render and coordinate the `Footer` portion of the Ink terminal interface.
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
 * Render the Footer React component.
 *
 * Integration: Owned by `Footer.tsx` and collaborates with `String`, `Boolean`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function Footer({status, taskCount}: {status: Record<string, unknown>; taskCount: number}): React.JSX.Element {
	return (
		<Box marginTop={1}>
			<Text dimColor>
				model={String(status.model ?? 'unknown')} provider={String(status.provider ?? 'unknown')} auth=
				{String(status.auth_status ?? 'unknown')} permission={String(status.permission_mode ?? 'unknown')} tasks=
				{String(taskCount)} mcp={String(status.mcp_connected ?? 0)}/{String(status.mcp_failed ?? 0)} bridge=
				{String(status.bridge_sessions ?? 0)} vim={String(Boolean(status.vim_enabled))} voice=
				{String(Boolean(status.voice_enabled))} effort={String(status.effort ?? 'medium')} passes=
				{String(status.passes ?? 1)}
			</Text>
		</Box>
	);
}
