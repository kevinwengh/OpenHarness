/**
 * Render and coordinate the `MarkdownText` portion of the Ink terminal interface.
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
import {lexer, type Token, type Tokens} from 'marked';
import stringWidth from 'string-width';

import {useTheme} from '../theme/ThemeContext.js';
import type {ThemeConfig} from '../theme/builtinThemes.js';

/**
 * Return inline fallback text for the calling frontend path.
 *
 * Integration: Owned by `MarkdownText.tsx` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function getInlineFallbackText(token: Token): string {
	if ('text' in token && typeof token.text === 'string') {
		return token.text;
	}

	return token.raw;
}

/**
 * Return inline display text for the calling frontend path.
 *
 * Integration: Owned by `MarkdownText.tsx` and collaborates with `join`, `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function getInlineDisplayText(tokens: Token[] | undefined): string {
	if (!tokens || tokens.length === 0) {
		return '';
	}

	return tokens.map(/*
	 * map callback: uses getInlineDisplayText, getInlineFallbackText; keep event-loop work bounded
	 * and preserve the callback's return contract.
	 */ (token) => {
		switch (token.type) {
			case 'text': {
				const t = token as Tokens.Text;
				return t.tokens && t.tokens.length > 0 ? getInlineDisplayText(t.tokens) : t.text;
			}
			case 'strong':
			case 'em':
			case 'del':
				return getInlineDisplayText((token as Tokens.Strong | Tokens.Em | Tokens.Del).tokens);
			case 'codespan':
				return (token as Tokens.Codespan).text;
			case 'link': {
				const l = token as Tokens.Link;
				return l.text || l.href;
			}
			case 'image': {
				const image = token as Tokens.Image;
				return image.text || image.href;
			}
			case 'br':
				return '\n';
			case 'escape':
				return (token as Tokens.Escape).text;
			default:
				return getInlineFallbackText(token);
		}
	}).join('');
}

/**
 * Return table cell display text for the calling frontend path.
 *
 * Integration: Owned by `MarkdownText.tsx` and collaborates with `getInlineDisplayText`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function getTableCellDisplayText(cell: Tokens.TableCell): string {
	const displayText = getInlineDisplayText(cell.tokens);
	return displayText.length > 0 ? displayText : cell.text;
}

// Inline token renderer — returns an array of <Text> elements.
/**
 * Render inline for the current UI state.
 *
 * Integration: Owned by `MarkdownText.tsx` and collaborates with `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function renderInline(tokens: Token[] | undefined, theme: ThemeConfig): React.ReactNode {
	if (!tokens || tokens.length === 0) {
		return null;
	}
	return tokens.map(/*
	 * map callback: uses renderInline, getInlineFallbackText; keep event-loop work bounded and
	 * preserve the callback's return contract.
	 */ (token, i) => {
		switch (token.type) {
			case 'text': {
				const t = token as Tokens.Text;
				// Text tokens can themselves contain inline children, such as list items.
				if (t.tokens && t.tokens.length > 0) {
					return <React.Fragment key={i}>{renderInline(t.tokens, theme)}</React.Fragment>;
				}
				return <Text key={i}>{t.text}</Text>;
			}
			case 'strong': {
				const s = token as Tokens.Strong;
				return (
					<Text key={i} bold>
						{renderInline(s.tokens, theme)}
					</Text>
				);
			}
			case 'em': {
				const e = token as Tokens.Em;
				return (
					<Text key={i} italic>
						{renderInline(e.tokens, theme)}
					</Text>
				);
			}
			case 'del': {
				const d = token as Tokens.Del;
				return (
					<Text key={i} strikethrough>
						{renderInline(d.tokens, theme)}
					</Text>
				);
			}
			case 'codespan': {
				const c = token as Tokens.Codespan;
				return (
					<Text key={i} color={theme.colors.accent}>
						{c.text}
					</Text>
				);
			}
			case 'link': {
				const l = token as Tokens.Link;
				const label = l.text || l.href;
				return (
					<Text key={i} color={theme.colors.info}>
						{label}
					</Text>
				);
			}
			case 'image': {
				const image = token as Tokens.Image;
				return <Text key={i}>{image.text || image.href}</Text>;
			}
			case 'br':
				return <Text key={i}>{'\n'}</Text>;
			case 'escape': {
				const es = token as Tokens.Escape;
				return <Text key={i}>{es.text}</Text>;
			}
			default:
				return <Text key={i}>{getInlineFallbackText(token)}</Text>;
		}
	});
}

/**
 * Render blocks for the current UI state.
 *
 * Integration: Owned by `MarkdownText.tsx` and collaborates with `map`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function renderBlocks(tokens: Token[] | undefined, theme: ThemeConfig): React.ReactNode {
	if (!tokens || tokens.length === 0) {
		return null;
	}

	return tokens.map(/*
	 * map callback: computes its callback result; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ (token, i) => (
		<MarkdownBlock key={i} token={token} theme={theme} />
	));
}

/**
 * Render the MarkdownBlock React component.
 *
 * Integration: Owned by `MarkdownText.tsx` and collaborates with `renderInline`, `repeat`, `split`.
 *
 * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded unless
 * asynchronous ownership is explicit.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
function MarkdownBlock({
	token,
	theme,
}: {
	token: Token;
	theme: ThemeConfig;
}): React.JSX.Element | null {
	switch (token.type) {
		case 'heading': {
			const h = token as Tokens.Heading;
			const headingColors: string[] = [
				theme.colors.primary,
				theme.colors.secondary,
				theme.colors.accent,
				theme.colors.info,
				theme.colors.muted,
				theme.colors.muted,
			];
			const color = headingColors[h.depth - 1] ?? theme.colors.primary;
			const isMajor = h.depth <= 2;
			return (
				<Box marginTop={1} flexDirection="column">
					<Text color={color} bold={isMajor} underline={h.depth === 1}>
						{renderInline(h.tokens, theme)}
					</Text>
					{h.depth === 1 ? <Text color={color} dimColor>{'━'.repeat(32)}</Text> : null}
				</Box>
			);
		}

		case 'paragraph': {
			const p = token as Tokens.Paragraph;
			return (
				<Box marginTop={0} flexWrap="wrap">
					<Text>{renderInline(p.tokens, theme)}</Text>
				</Box>
			);
		}

		case 'code': {
			const c = token as Tokens.Code;
			const lines = c.text.split('\n');
			return (
				<Box flexDirection="column" marginTop={1} marginLeft={2} borderStyle="round" paddingX={1} borderColor={theme.colors.muted}>
					{c.lang ? (
						<Text dimColor>{c.lang}</Text>
					) : null}
					{lines.map(/*
					 * map callback: computes its callback result; keep event-loop work bounded and preserve
					 * the callback's return contract.
					 */ (line, i) => (
						<Text key={i} color={theme.colors.accent}>
							{line}
						</Text>
					))}
				</Box>
			);
		}

		case 'blockquote': {
			const bq = token as Tokens.Blockquote;
			return (
				<Box flexDirection="column" marginTop={0} marginLeft={0}>
					{bq.tokens.map(/*
					 * map callback: uses renderBlocks; keep event-loop work bounded and preserve the
					 * callback's return contract.
					 */ (t, i) => (
						<Box key={i} flexDirection="row">
							<Text color={theme.colors.muted}>{'│ '}</Text>
							<Box flexDirection="column" flexGrow={1}>
								{renderBlocks([t], theme)}
							</Box>
						</Box>
					))}
				</Box>
			);
		}

		case 'list': {
			const l = token as Tokens.List;
			return (
				<Box flexDirection="column" marginTop={0} marginLeft={2}>
					{l.items.map(/*
					 * map callback: uses flatMap, Number, renderInline; keep event-loop work bounded and
					 * preserve the callback's return contract.
					 */ (item, i) => {
						// For tight lists, item.tokens = [{type:'text', tokens:[...inline]}]
						// For loose lists, item.tokens = [{type:'paragraph', tokens:[...inline]}]
						const inlineTokens: Token[] = item.tokens.flatMap(/*
						 * flatMap callback: computes its callback result; keep event-loop work bounded and
						 * preserve the callback's return contract.
						 */ (t) =>
							'tokens' in t && t.tokens ? (t.tokens as Token[]) : [],
						);
						const bullet = l.ordered ? `${(Number(l.start) || 1) + i}. ` : '• ';
						return (
							<Box key={i} flexDirection="row">
								<Text color={theme.colors.primary}>{bullet}</Text>
								<Box flexGrow={1}>
									<Text>
										{inlineTokens.length > 0
											? renderInline(inlineTokens, theme)
											: item.text}
									</Text>
								</Box>
							</Box>
						);
					})}
				</Box>
			);
		}

		case 'hr':
			return (
				<Box marginTop={1}>
					<Text dimColor>{'─'.repeat(48)}</Text>
				</Box>
			);

		case 'space':
			return null;

		case 'table': {
			const t = token as Tokens.Table;
			const headerTexts = t.header.map(getTableCellDisplayText);
			const rowTexts = t.rows.map(/*
			 * map callback: uses map; keep event-loop work bounded and preserve the callback's return
			 * contract.
			 */ (row) => row.map(getTableCellDisplayText));
			// Use stringWidth for correct CJK and wide-char column widths.
			const colCount = t.header.length;
			const colWidths: number[] = headerTexts.map(/*
			 * map callback: uses stringWidth; keep event-loop work bounded and preserve the callback's
			 * return contract.
			 */ (cellText) => stringWidth(cellText));
			for (const row of rowTexts) {
				for (let c = 0; c < colCount; c++) {
					colWidths[c] = Math.max(colWidths[c] ?? 0, stringWidth(row[c] ?? ''));
				}
			}
			   /**
    * Derive trailing from the current frontend state and inputs.
    *
    * Integration: Owned by `MarkdownBlock` and collaborates with `repeat`, `max`, `stringWidth`.
    *
    * Event loop: Runs synchronously during render or callback dispatch; keep it pure or bounded
    * unless asynchronous ownership is explicit.
    *
    * Change safety: Preserve parameters, return shape, state ownership, and caller-visible
    * ordering.
    */
   const trailing = (cellText: string, c: number): string =>
				' '.repeat(Math.max(0, (colWidths[c] ?? 0) - stringWidth(cellText)));
			const top = '┌' + colWidths.map(/*
			 * map callback: uses repeat; keep event-loop work bounded and preserve the callback's return
			 * contract.
			 */ (w) => '─'.repeat(w + 2)).join('┬') + '┐';
			const mid = '├' + colWidths.map(/*
			 * map callback: uses repeat; keep event-loop work bounded and preserve the callback's return
			 * contract.
			 */ (w) => '─'.repeat(w + 2)).join('┼') + '┤';
			const bot = '└' + colWidths.map(/*
			 * map callback: uses repeat; keep event-loop work bounded and preserve the callback's return
			 * contract.
			 */ (w) => '─'.repeat(w + 2)).join('┴') + '┘';
			return (
				<Box flexDirection="column" marginTop={1} marginLeft={1}>
					<Text color={theme.colors.muted}>{top}</Text>
					<Text>
						<Text color={theme.colors.muted}>{'│'}</Text>
						{t.header.map(/*
						 * map callback: uses renderInline, trailing; keep event-loop work bounded and preserve
						 * the callback's return contract.
						 */ (cell, c) => (
							<React.Fragment key={c}>
								<Text color={theme.colors.primary} bold>
									{' '}{renderInline(cell.tokens, theme)}{trailing(headerTexts[c] ?? '', c)}{' '}
								</Text>
								<Text color={theme.colors.muted}>{'│'}</Text>
							</React.Fragment>
						))}
					</Text>
					<Text color={theme.colors.muted}>{mid}</Text>
					{t.rows.map(/*
					 * map callback: uses map; keep event-loop work bounded and preserve the callback's return
					 * contract.
					 */ (row, i) => (
						<Text key={i}>
							<Text color={theme.colors.muted}>{'│'}</Text>
							{row.map(/*
							 * map callback: uses renderInline, trailing; keep event-loop work bounded and preserve
							 * the callback's return contract.
							 */ (cell, c) => (
								<React.Fragment key={c}>
									<Text>
										{' '}{renderInline(cell.tokens, theme)}{trailing(rowTexts[i]?.[c] ?? '', c)}{' '}
									</Text>
									<Text color={theme.colors.muted}>{'│'}</Text>
								</React.Fragment>
							))}
						</Text>
					))}
					<Text color={theme.colors.muted}>{bot}</Text>
				</Box>
			);
		}

		default:
			if ((token as Token).raw) {
				return <Text>{(token as Token).raw}</Text>;
			}
			return null;
	}
}

export const MarkdownText = React.memo(/*
 * memo callback: uses useTheme, useMemo, renderBlocks; keep event-loop work bounded and
 * preserve the callback's return contract.
 */ function MarkdownText({content}: {content: string}): React.JSX.Element {
	const {theme} = useTheme();
	const tokens = React.useMemo(/*
	 * React useMemo callback: uses lexer; keep dependencies synchronized with captured values and
	 * preserve purity.
	 */ () => lexer(content), [content]);
	return (
		<Box flexDirection="column">
			{renderBlocks(tokens, theme)}
		</Box>
	);
});
