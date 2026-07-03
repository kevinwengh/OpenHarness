/**
 * Own the terminal frontend's builtin themes boundary.
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

export type ThemeConfig = {
	name: string;
	colors: {
		primary: string;
		secondary: string;
		accent: string;
		foreground: string;
		background: string;
		muted: string;
		success: string;
		warning: string;
		error: string;
		info: string;
	};
	icons: {
		spinner: string[];
		tool: string;
		assistant: string;
		user: string;
		system: string;
		success: string;
		error: string;
	};
};

export const defaultTheme: ThemeConfig = {
	name: 'default',
	colors: {
		primary: 'cyan',
		secondary: 'white',
		accent: 'cyan',
		foreground: 'white',
		background: 'black',
		muted: 'gray',
		success: 'green',
		warning: 'yellow',
		error: 'red',
		info: 'blue',
	},
	icons: {
		spinner: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
		tool: '  ⏵ ',
		assistant: '⏺ ',
		user: '> ',
		system: 'ℹ ',
		success: '✓ ',
		error: '✗ ',
	},
};

export const darkTheme: ThemeConfig = {
	name: 'dark',
	colors: {
		primary: '#7aa2f7',
		secondary: '#c0caf5',
		accent: '#bb9af7',
		foreground: '#c0caf5',
		background: '#1a1b26',
		muted: '#565f89',
		success: '#9ece6a',
		warning: '#e0af68',
		error: '#f7768e',
		info: '#7dcfff',
	},
	icons: {
		spinner: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
		tool: '  ⏵ ',
		assistant: '⏺ ',
		user: '> ',
		system: 'ℹ ',
		success: '✓ ',
		error: '✗ ',
	},
};

export const minimalTheme: ThemeConfig = {
	name: 'minimal',
	colors: {
		primary: 'white',
		secondary: 'white',
		accent: 'white',
		foreground: 'white',
		background: 'black',
		muted: 'gray',
		success: 'white',
		warning: 'white',
		error: 'white',
		info: 'white',
	},
	icons: {
		spinner: ['-', '\\', '|', '/'],
		tool: '  > ',
		assistant: ': ',
		user: '> ',
		system: '# ',
		success: '+ ',
		error: '! ',
	},
};

export const cyberpunkTheme: ThemeConfig = {
	name: 'cyberpunk',
	colors: {
		primary: '#ff007c',
		secondary: '#00fff9',
		accent: '#ffe600',
		foreground: '#00fff9',
		background: '#0d0d0d',
		muted: '#444444',
		success: '#00ff41',
		warning: '#ffe600',
		error: '#ff003c',
		info: '#00fff9',
	},
	icons: {
		spinner: ['◐', '◓', '◑', '◒'],
		tool: '  ▶ ',
		assistant: '◆ ',
		user: '▸ ',
		system: '⚡ ',
		success: '✦ ',
		error: '✖ ',
	},
};

export const solarizedTheme: ThemeConfig = {
	name: 'solarized',
	colors: {
		primary: '#268bd2',
		secondary: '#839496',
		accent: '#2aa198',
		foreground: '#839496',
		background: '#002b36',
		muted: '#586e75',
		success: '#859900',
		warning: '#b58900',
		error: '#dc322f',
		info: '#268bd2',
	},
	icons: {
		spinner: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],
		tool: '  ⏵ ',
		assistant: '⏺ ',
		user: '> ',
		system: 'ℹ ',
		success: '✓ ',
		error: '✗ ',
	},
};

export const BUILTIN_THEMES: Record<string, ThemeConfig> = {
	default: defaultTheme,
	dark: darkTheme,
	minimal: minimalTheme,
	cyberpunk: cyberpunkTheme,
	solarized: solarizedTheme,
};

/**
 * Return theme for the calling frontend path.
 *
 * Integration: Owned by `builtinThemes.ts` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export function getTheme(name: string): ThemeConfig {
	return BUILTIN_THEMES[name] ?? defaultTheme;
}
