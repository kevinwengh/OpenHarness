/**
 * Own the terminal frontend's clipboard image boundary.
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

import {execFile} from 'node:child_process';
import {mkdtemp, readFile, rm, stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

export type ImageAttachment = {
	id: string;
	label: string;
	media_type: string;
	data: string;
	source_path?: string;
	size_bytes?: number;
};

const MAX_CLIPBOARD_IMAGE_BYTES = 15 * 1024 * 1024;
const EXEC_TIMEOUT_MS = 2500;

type ClipboardImageRead = {
	data: Buffer;
	mediaType: string;
	label: string;
};

/**
 * Derive read clipboard image from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `readClipboardImageData`, `now`,
 * `slice`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
export async function readClipboardImage(): Promise<ImageAttachment | null> {
	const image = await readClipboardImageData();
	if (!image) {
		return null;
	}
	return {
		id: `clipboard-${Date.now()}-${Math.random().toString(16).slice(2)}`,
		label: image.label,
		media_type: image.mediaType,
		data: image.data.toString('base64'),
		source_path: `clipboard:${image.label}`,
		size_bytes: image.data.length,
	};
}

/**
 * Derive read clipboard image data from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `readMacClipboardImage`,
 * `readWindowsClipboardImage`, `readLinuxClipboardImage`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function readClipboardImageData(): Promise<ClipboardImageRead | null> {
	if (process.platform === 'darwin') {
		return readMacClipboardImage();
	}
	if (process.platform === 'win32') {
		return readWindowsClipboardImage();
	}
	return readLinuxClipboardImage();
}

/**
 * Derive read mac clipboard image from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `mkdtemp`, `join`, `tmpdir`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function readMacClipboardImage(): Promise<ClipboardImageRead | null> {
	const tempDir = await mkdtemp(join(tmpdir(), 'openharness-clipboard-'));
	try {
		const pngPath = join(tempDir, 'clipboard.png');
		if (await runFileCommand('pngpaste', [pngPath])) {
			return await readImageFile(pngPath, 'image/png', 'clipboard.png');
		}
		if (await writeMacClipboardClass('PNGf', pngPath)) {
			return await readImageFile(pngPath, 'image/png', 'clipboard.png');
		}

		const tiffPath = join(tempDir, 'clipboard.tiff');
		if (await writeMacClipboardClass('TIFF', tiffPath)) {
			if (await runFileCommand('sips', ['-s', 'format', 'png', tiffPath, '--out', pngPath])) {
				return await readImageFile(pngPath, 'image/png', 'clipboard.png');
			}
			return await readImageFile(tiffPath, 'image/tiff', 'clipboard.tiff');
		}
		return null;
	} finally {
		await rm(tempDir, {recursive: true, force: true});
	}
}

/**
 * Derive write mac clipboard class from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `fromCharCode`, `replace`,
 * `runFileCommand`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function writeMacClipboardClass(classCode: 'PNGf' | 'TIFF', outputPath: string): Promise<boolean> {
	const appleClass = `${String.fromCharCode(0xab)}class ${classCode}${String.fromCharCode(0xbb)}`;
	const escapedPath = outputPath.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
	return runFileCommand('osascript', [
		'-e',
		`set clipboardData to the clipboard as ${appleClass}`,
		'-e',
		`set outFile to open for access POSIX file "${escapedPath}" with write permission`,
		'-e',
		'set eof outFile to 0',
		'-e',
		'write clipboardData to outFile',
		'-e',
		'close access outFile',
	]);
}

/**
 * Derive read windows clipboard image from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `mkdtemp`, `join`, `tmpdir`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function readWindowsClipboardImage(): Promise<ClipboardImageRead | null> {
	const tempDir = await mkdtemp(join(tmpdir(), 'openharness-clipboard-'));
	try {
		const pngPath = join(tempDir, 'clipboard.png');
		const escapedPath = pngPath.replace(/'/g, "''");
		const powershell = join(
			process.env.SystemRoot ?? 'C:\\Windows',
			'System32',
			'WindowsPowerShell',
			'v1.0',
			'powershell.exe',
		);
		const script = [
			'Add-Type -AssemblyName System.Windows.Forms',
			'Add-Type -AssemblyName System.Drawing',
			'if (-not [Windows.Forms.Clipboard]::ContainsImage()) { exit 2 }',
			'$image = [Windows.Forms.Clipboard]::GetImage()',
			`$image.Save('${escapedPath}', [Drawing.Imaging.ImageFormat]::Png)`,
		].join('; ');
		if (!(await runFileCommand(powershell, ['-NoProfile', '-STA', '-Command', script]))) {
			return null;
		}
		return await readImageFile(pngPath, 'image/png', 'clipboard.png');
	} finally {
		await rm(tempDir, {recursive: true, force: true});
	}
}

/**
 * Derive read linux clipboard image from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `runBufferCommand`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function readLinuxClipboardImage(): Promise<ClipboardImageRead | null> {
	const attempts: Array<[string, string[], string, string]> = [
		['wl-paste', ['--no-newline', '--type', 'image/png'], 'image/png', 'clipboard.png'],
		['wl-paste', ['--no-newline', '--type', 'image/jpeg'], 'image/jpeg', 'clipboard.jpg'],
		['xclip', ['-selection', 'clipboard', '-target', 'image/png', '-out'], 'image/png', 'clipboard.png'],
		['xclip', ['-selection', 'clipboard', '-target', 'image/jpeg', '-out'], 'image/jpeg', 'clipboard.jpg'],
		['xsel', ['--clipboard', '--output', '--mime-type', 'image/png'], 'image/png', 'clipboard.png'],
		['xsel', ['--clipboard', '--output', '--mime-type', 'image/jpeg'], 'image/jpeg', 'clipboard.jpg'],
	];
	for (const [command, args, mediaType, label] of attempts) {
		const data = await runBufferCommand(command, args);
		if (data && data.length > 0) {
			return {data, mediaType, label};
		}
	}
	return null;
}

/**
 * Derive read image file from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and collaborates with `catch`, `stat`, `readFile`.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function readImageFile(path: string, mediaType: string, label: string): Promise<ClipboardImageRead | null> {
	const fileStat = await stat(path).catch(/*
	 * catch callback: computes its callback result; keep event-loop work bounded and preserve the
	 * callback's return contract.
	 */ () => null);
	if (!fileStat || fileStat.size <= 0 || fileStat.size > MAX_CLIPBOARD_IMAGE_BYTES) {
		return null;
	}
	const data = await readFile(path);
	return {data, mediaType, label};
}

/**
 * Derive run file command from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function runFileCommand(command: string, args: string[]): Promise<boolean> {
	return new Promise(/*
	 * callback at line 146: uses execFile; keep event-loop work bounded and preserve surrounding
	 * control flow.
	 */ (resolve) => {
		execFile(command, args, {timeout: EXEC_TIMEOUT_MS, windowsHide: true}, /*
		 * execFile callback: uses resolve; keep event-loop work bounded and preserve the callback's
		 * return contract.
		 */ (error) => {
			resolve(!error);
		});
	});
}

/**
 * Derive run buffer command from the current frontend state and inputs.
 *
 * Integration: Owned by `clipboardImage.ts` and invoked through its surrounding React or module
 * boundary.
 *
 * Event loop: Awaits asynchronous work on the JavaScript event loop; preserve rejection,
 * cancellation, and completion ordering, and avoid blocking terminal rendering.
 *
 * Change safety: Preserve parameters, return shape, state ownership, and caller-visible ordering.
 */
async function runBufferCommand(command: string, args: string[]): Promise<Buffer | null> {
	return new Promise(/*
	 * callback at line 154: uses execFile; keep event-loop work bounded and preserve surrounding
	 * control flow.
	 */ (resolve) => {
		execFile(
			command,
			args,
			{
				encoding: 'buffer',
				maxBuffer: MAX_CLIPBOARD_IMAGE_BYTES + 1024,
				timeout: EXEC_TIMEOUT_MS,
				windowsHide: true,
			},
			/*
			 * execFile callback: uses isBuffer, resolve; keep event-loop work bounded and preserve the
			 * callback's return contract.
			 */ (error, stdout) => {
				if (error || !Buffer.isBuffer(stdout) || stdout.length > MAX_CLIPBOARD_IMAGE_BYTES) {
					resolve(null);
					return;
				}
				resolve(stdout);
			},
		);
	});
}
