/**
 * Render and coordinate the `SwarmPanel` portion of the Ink terminal interface.
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

export type SwarmTeammate = {
	name: string;
	status: 'running' | 'idle' | 'done' | 'error';
	duration?: number; // seconds
	task?: string;
};

export type SwarmNotification = {
	from: string;
	message: string;
	timestamp: number;
};

/**
 * Derive status icon from the current frontend state and inputs.
 *
 * Integration: Owned by `SwarmPanel.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function statusIcon(status: SwarmTeammate['status']): string {
	switch (status) {
		case 'running':
			return '🟢';
		case 'idle':
			return '🟡';
		case 'done':
			return '✅';
		case 'error':
			return '🔴';
	}
}

/**
 * Format duration for presentation.
 *
 * Integration: Owned by `SwarmPanel.tsx` and collaborates with `floor`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function formatDuration(seconds: number): string {
	if (seconds < 60) {
		return `${seconds}s`;
	}
	const m = Math.floor(seconds / 60);
	const s = seconds % 60;
	return `${m}m${s}s`;
}

/**
 * Render the SwarmPanelInner React component.
 *
 * Integration: Owned by `SwarmPanel.tsx` and collaborates with `useState`, `useInput`, `filter`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function SwarmPanelInner({
	teammates,
	notifications,
	collapsed: initialCollapsed = false,
}: {
	teammates: SwarmTeammate[];
	notifications: SwarmNotification[];
	collapsed?: boolean;
}): React.JSX.Element | null {
	const [collapsed, setCollapsed] = useState(initialCollapsed);

	useInput(/*
	 * useInput callback: uses setCollapsed; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ (chunk, key) => {
		if (key.ctrl && chunk === 'w') {
			setCollapsed(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (c) => !c);
		}
	});

	if (teammates.length === 0 && notifications.length === 0) {
		return null;
	}

	const activeCount = teammates.filter(/*
	 * filter callback: computes its callback result; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ (t) => t.status === 'running').length;

	if (collapsed) {
		return (
			<Box>
				<Text color="cyan" bold>
					{'⚡ '}
				</Text>
				<Text dimColor>
					Swarm: {teammates.length} agents ({activeCount} active)
				</Text>
				<Text dimColor> [ctrl+w expand]</Text>
			</Box>
		);
	}

	return (
		<Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginTop={1}>
			<Box>
				<Text color="cyan" bold>
					{'⚡ '}
				</Text>
				<Text bold>Swarm</Text>
				<Text dimColor>
					{' '}
					({activeCount}/{teammates.length} active) [ctrl+w collapse]
				</Text>
			</Box>

			{teammates.length > 0 && (
				<Box flexDirection="column" marginTop={1}>
					{teammates.map(/*
					 * map callback: uses statusIcon, formatDuration, slice; keep event-loop work bounded and
					 * preserve the callback's return contract.
					 */ (teammate) => (
						<Box key={teammate.name} flexDirection="row" marginBottom={0}>
							<Text>{statusIcon(teammate.status)} </Text>
							<Box flexDirection="column">
								<Box>
									<Text bold color={teammate.status === 'running' ? 'green' : teammate.status === 'error' ? 'red' : undefined}>
										{teammate.name}
									</Text>
									{teammate.duration !== undefined && (
										<Text dimColor> ({formatDuration(teammate.duration)})</Text>
									)}
								</Box>
								{teammate.task && (
									<Text dimColor>   {teammate.task.slice(0, 60)}{teammate.task.length > 60 ? '…' : ''}</Text>
								)}
							</Box>
						</Box>
					))}
				</Box>
			)}

			{notifications.length > 0 && (
				<Box flexDirection="column" marginTop={1}>
					<Text dimColor bold>Recent notifications:</Text>
					{notifications.slice(-3).map(/*
					 * map callback: uses slice; keep event-loop work bounded and preserve the callback's
					 * return contract.
					 */ (n, i) => (
						<Box key={i}>
							<Text dimColor>[{n.from}] </Text>
							<Text>{n.message.slice(0, 70)}{n.message.length > 70 ? '…' : ''}</Text>
						</Box>
					))}
				</Box>
			)}
		</Box>
	);
}

export const SwarmPanel = React.memo(SwarmPanelInner);
