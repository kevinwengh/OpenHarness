/**
 * Render and coordinate the `SidePanel` portion of the Ink terminal interface.
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

import type {BridgeSessionSnapshot, McpServerSnapshot, TaskSnapshot} from '../types.js';

/**
 * Render the SidePanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function SidePanel({
	status,
	tasks,
	commands,
	commandHints,
	mcpServers,
	bridgeSessions,
}: {
	status: Record<string, unknown>;
	tasks: TaskSnapshot[];
	commands: string[];
	commandHints: string[];
	mcpServers: McpServerSnapshot[];
	bridgeSessions: BridgeSessionSnapshot[];
}): React.JSX.Element {
	return (
		<Box flexDirection="column" width="32%">
			<StatusPanel status={status} />
			<TaskPanel tasks={tasks} />
			<McpPanel servers={mcpServers} />
			<BridgePanel sessions={bridgeSessions} />
			<CommandPanel commands={commands} hints={commandHints} />
		</Box>
	);
}

/**
 * Render the StatusPanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and collaborates with `String`, `Boolean`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function StatusPanel({status}: {status: Record<string, unknown>}): React.JSX.Element {
	return (
		<>
			<Text bold>Status</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1} marginBottom={1}>
				<Text>model: {String(status.model ?? 'unknown')}</Text>
				<Text>provider: {String(status.provider ?? 'unknown')}</Text>
				<Text>auth: {String(status.auth_status ?? 'unknown')}</Text>
				<Text>permission: {String(status.permission_mode ?? 'unknown')}</Text>
				<Text>cwd: {String(status.cwd ?? '.')}</Text>
				<Text>vim: {String(Boolean(status.vim_enabled))}</Text>
				<Text>voice: {String(Boolean(status.voice_enabled))}</Text>
				<Text>voice ready: {String(Boolean(status.voice_available))}</Text>
				<Text>fast: {String(Boolean(status.fast_mode))}</Text>
				<Text>effort: {String(status.effort ?? 'medium')}</Text>
				<Text>passes: {String(status.passes ?? 1)}</Text>
			</Box>
		</>
	);
}

/**
 * Render the TaskPanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and collaborates with `slice`, `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function TaskPanel({tasks}: {tasks: TaskSnapshot[]}): React.JSX.Element {
	const visible = tasks.slice(0, 6);
	return (
		<>
			<Text bold>Tasks</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1} marginBottom={1}>
				{visible.length === 0 ? (
					<Text>(none)</Text>
				) : (
					visible.map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (task) => (
						<Box key={task.id} flexDirection="column">
							<Text>
								{task.id} [{task.status}] {task.description}
							</Text>
							<Text dimColor>
								type={task.type} progress={task.metadata.progress ?? '-'} note={task.metadata.status_note ?? '-'}
							</Text>
						</Box>
					))
				)}
			</Box>
		</>
	);
}

/**
 * Render the McpPanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and collaborates with `map`, `slice`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function McpPanel({servers}: {servers: McpServerSnapshot[]}): React.JSX.Element {
	return (
		<>
			<Text bold>MCP</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1} marginBottom={1}>
				{servers.length === 0 ? (
					<Text>(none)</Text>
				) : (
					servers.slice(0, 5).map(/*
					 * map callback: uses String, Boolean; keep event-loop work bounded and preserve the
					 * callback's return contract.
					 */ (server) => (
						<Box key={server.name} flexDirection="column">
							<Text>
								{server.name} [{server.state}] {server.transport ?? 'unknown'}
							</Text>
							<Text dimColor>
								auth={String(Boolean(server.auth_configured))} tools={String(server.tool_count ?? 0)} resources=
								{String(server.resource_count ?? 0)}
							</Text>
							{server.detail ? <Text dimColor>{server.detail}</Text> : null}
						</Box>
					))
				)}
			</Box>
		</>
	);
}

/**
 * Render the BridgePanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and collaborates with `map`, `slice`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function BridgePanel({sessions}: {sessions: BridgeSessionSnapshot[]}): React.JSX.Element {
	return (
		<>
			<Text bold>Bridge</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1} marginBottom={1}>
				{sessions.length === 0 ? (
					<Text>(none)</Text>
				) : (
					sessions.slice(0, 4).map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (session) => (
						<Box key={session.session_id} flexDirection="column">
							<Text>
								{session.session_id} [{session.status}] pid={session.pid}
							</Text>
							<Text dimColor>{session.command}</Text>
						</Box>
					))
				)}
			</Box>
		</>
	);
}

/**
 * Render the CommandPanel React component.
 *
 * Integration: Owned by `SidePanel.tsx` and collaborates with `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function CommandPanel({
	commands,
	hints,
}: {
	commands: string[];
	hints: string[];
}): React.JSX.Element {
	return (
		<>
			<Text bold>Commands</Text>
			<Box flexDirection="column" borderStyle="round" paddingX={1}>
				{hints.length > 0 ? (
					hints.map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (command, index) => (
						<Text key={command} color={index === 0 ? 'cyan' : undefined}>
							{command}
							{index === 0 ? '  [tab]' : ''}
						</Text>
					))
				) : commands.length > 0 ? (
					<Text>type / for commands</Text>
				) : (
					<Text>(none)</Text>
				)}
			</Box>
		</>
	);
}
