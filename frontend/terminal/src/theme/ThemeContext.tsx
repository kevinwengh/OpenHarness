/**
 * Own the terminal frontend's theme context boundary.
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

import React, {createContext, useContext, useState} from 'react';

import {type ThemeConfig, BUILTIN_THEMES, defaultTheme, getTheme} from './builtinThemes.js';

export type {ThemeConfig};

type ThemeContextValue = {
	theme: ThemeConfig;
	setThemeName: (name: string) => void;
};

const ThemeContext = createContext<ThemeContextValue>({
	theme: defaultTheme,
	 /**
  * Derive set theme name from the current frontend state and inputs.
  *
  * Integration: Owned by `ThemeContext.tsx` and invoked through its surrounding React or module
  * boundary.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
  */
 setThemeName: () => undefined,
});

/**
 * Render the ThemeProvider React component.
 *
 * Integration: Owned by `ThemeContext.tsx` and collaborates with `useState`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function ThemeProvider({
	children,
	initialTheme = 'default',
}: {
	children: React.ReactNode;
	initialTheme?: string;
}): React.JSX.Element {
	const [theme, setTheme] = useState<ThemeConfig>(/*
	 * useState callback: uses getTheme; keep event-loop work bounded and preserve the callback's
	 * return contract.
	 */ () => getTheme(initialTheme));

	 /**
  * Derive set theme name from the current frontend state and inputs.
  *
  * Integration: Owned by `ThemeProvider` and collaborates with `setTheme`.
  *
  * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
  * unless asynchronous ownership is explicit.
  *
  * Change safety: Preserve React state ownership, functional-update semantics, and render ordering;
  * review every dependent effect and component.
  */
 const setThemeName = (name: string): void => {
		const resolved = BUILTIN_THEMES[name] ?? defaultTheme;
		setTheme(resolved);
	};

	return (
		<ThemeContext.Provider value={{theme, setThemeName}}>
			{children}
		</ThemeContext.Provider>
	);
}

/**
 * Provide the theme React hook.
 *
 * Integration: Owned by `ThemeContext.tsx` and collaborates with `useContext`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function useTheme(): ThemeContextValue {
	return useContext(ThemeContext);
}
