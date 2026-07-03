/**
 * Own the terminal frontend's index boundary.
 *
 * Integration: Connects the Ink application to shared TypeScript types and the Python backend
 * protocol.
 *
 * Event loop: Process I/O, React effects, input events, and buffered rendering coexist on Node's
 * event loop; preserve cleanup and backpressure.
 *
 * Change safety: Coordinate protocol, process lifecycle, terminal restoration, and packaging
 * changes with the Python host and UI tests.
 */

import React from 'react';
import {render} from 'ink';
import fs from 'node:fs';
import tty from 'node:tty';

import {App} from './App.js';
import type {FrontendConfig} from './types.js';

// Guard against EIO crashes in both stdin reads and setRawMode calls.
// Ink's React reconciler calls setRawMode during mount/unmount which can
// throw EIO in certain terminal environments (SSH, tmux, Docker).
process.stdin.on('error', /*
 * on callback: uses exit; keep event-loop work bounded and preserve the callback's return
 * contract.
 */ (err: NodeJS.ErrnoException) => {
	if (err.code === 'EIO' || err.code === 'EAGAIN') {
		process.exit(1);
	}
	throw err;
});

if (process.stdin.isTTY && typeof process.stdin.setRawMode === 'function') {
	const origSetRawMode = process.stdin.setRawMode.bind(process.stdin);
	process.stdin.setRawMode = /*
	 * callback at line 21: uses origSetRawMode, exit; keep event-loop work bounded and preserve
	 * surrounding control flow.
	 */ (mode: boolean) => {
		try {
			return origSetRawMode(mode);
		} catch (err: any) {
			if (err?.code === 'EIO' || err?.code === 'EAGAIN') {
				process.exit(1);
			}
			throw err;
		}
	};
}

process.on('uncaughtException', /*
 * on callback: uses exit; keep event-loop work bounded and preserve the callback's return
 * contract.
 */ (err: NodeJS.ErrnoException) => {
	if (err.code === 'EIO' || err.code === 'EAGAIN') {
		process.exit(1);
	}
	throw err;
});

const config = JSON.parse(process.env.OPENHARNESS_FRONTEND_CONFIG ?? '{}') as FrontendConfig;

// Restore terminal cursor visibility on exit (Ink hides it by default).
// Also write a newline so the shell prompt starts on a fresh line and does
// not run into the last line of the TUI output.
/**
 * Derive restore terminal from the current frontend state and inputs.
 *
 * Integration: Owned by `index.tsx` and collaborates with `write`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
const restoreTerminal = (): void => {
	process.stdout.write('\x1B[?25h\n');
};
process.on('exit', restoreTerminal);
process.on('SIGINT', /*
 * on callback: uses restoreTerminal, exit; keep event-loop work bounded and preserve the
 * callback's return contract.
 */ () => {
	restoreTerminal();
	process.exit(130);
});
process.on('SIGTERM', /*
 * on callback: uses restoreTerminal, exit; keep event-loop work bounded and preserve the
 * callback's return contract.
 */ () => {
	restoreTerminal();
	process.exit(143);
});

// On WSL / Windows the process-spawning chain (npm exec → tsx → node) can
// lose the TTY on stdin, which prevents Ink's useInput from enabling raw mode.
// When that happens, open /dev/tty directly to get a real TTY stream.
let stdinStream: NodeJS.ReadStream & {fd: 0} = process.stdin;
let ttyFd: number | undefined;

if (!process.stdin.isTTY) {
	try {
		ttyFd = fs.openSync('/dev/tty', 'r');
		const ttyStream = new tty.ReadStream(ttyFd);
		// Cast is safe — tty.ReadStream is a full readable TTY stream
		stdinStream = ttyStream as unknown as NodeJS.ReadStream & {fd: 0};
	} catch {
		// /dev/tty unavailable (e.g. non-interactive CI) — fall back to process.stdin
	}
}

process.on('exit', /*
 * on callback: uses closeSync; keep event-loop work bounded and preserve the callback's return
 * contract.
 */ () => {
	if (ttyFd !== undefined) {
		try { fs.closeSync(ttyFd); } catch { /* ignore */ }
	}
});

render(<App config={config} />, {stdin: stdinStream});
