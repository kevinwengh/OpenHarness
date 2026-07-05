import type { WebBootstrap } from "./types";

const TOKEN_KEY = "openharness.web.launch-token";

export class WebApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "WebApiError";
    this.status = status;
  }
}

export function consumeLaunchToken(): string | null {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const fragmentToken = fragment.get("token");
  if (fragmentToken) {
    window.sessionStorage.setItem(TOKEN_KEY, fragmentToken);
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    return fragmentToken;
  }
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function getLaunchToken(): string | null {
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export async function fetchBootstrap(signal?: AbortSignal): Promise<WebBootstrap> {
  const token = consumeLaunchToken();
  if (!token) {
    throw new WebApiError("This browser tab is missing its local launch token. Start it again with `oh web`.", 401);
  }

  const response = await fetch("/api/bootstrap", {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) {
    let message = `The local host returned ${response.status}.`;
    try {
      const payload = (await response.json()) as { error?: { message?: string } };
      message = payload.error?.message ?? message;
    } catch {
      // Retain the bounded status-only fallback; never display an arbitrary HTML body.
    }
    throw new WebApiError(message, response.status);
  }
  return (await response.json()) as WebBootstrap;
}
