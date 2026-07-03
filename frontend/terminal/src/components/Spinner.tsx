/**
 * Render and coordinate the `Spinner` portion of the Ink terminal interface.
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

import React, {useEffect, useState} from 'react';
import {Text} from 'ink';

import {useTheme} from '../theme/ThemeContext.js';

const VERBS = [
	'Thinking',
	'Processing',
	'Analyzing',
	'Reasoning',
	'Working',
	'Computing',
	'Evaluating',
	'Considering',
];

const WINDOWS_SAFE_FRAMES = ['-', '\\', '|', '/'];

/**
 * Render the Spinner React component.
 *
 * Integration: Owned by `Spinner.tsx` and collaborates with `useTheme`, `useState`, `useEffect`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function Spinner({label}: {label?: string}): React.JSX.Element {
	const {theme} = useTheme();
	const frames = process.platform === 'win32' ? WINDOWS_SAFE_FRAMES : theme.icons.spinner;
	const [frame, setFrame] = useState(0);
	const [verbIndex, setVerbIndex] = useState(0);

	useEffect(/*
	 * React effect: uses setInterval after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		const timer = setInterval(/*
		 * Timer callback: uses setFrame on Node's event loop; keep work bounded and preserve matching
		 * cleanup.
		 */ () => {
			setFrame(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (f) => (f + 1) % frames.length);
		}, 100);
		return /*
		 * Effect cleanup: uses clearInterval; keep it paired with every resource acquired by the
		 * effect.
		 */ () => clearInterval(timer);
	}, [frames.length]);

	useEffect(/*
	 * React effect: uses setInterval after render; keep dependencies, asynchronous work, and
	 * returned cleanup synchronized.
	 */ () => {
		const timer = setInterval(/*
		 * Timer callback: uses setVerbIndex on Node's event loop; keep work bounded and preserve
		 * matching cleanup.
		 */ () => {
			setVerbIndex(/*
			 * Functional state update: computes its callback result from prior React state; keep the
			 * calculation pure and immutable.
			 */ (v) => (v + 1) % VERBS.length);
		}, 3000);
		return /*
		 * Effect cleanup: uses clearInterval; keep it paired with every resource acquired by the
		 * effect.
		 */ () => clearInterval(timer);
	}, []);

	const verb = label ?? `${VERBS[verbIndex]}...`;

	return (
		<Text>
			<Text color={theme.colors.primary}>{frames[frame]}</Text>
			<Text dimColor> {verb}</Text>
		</Text>
	);
}
