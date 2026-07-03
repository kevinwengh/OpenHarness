"""Authentication flows for various provider types.

Each flow is a self-contained class with a single ``run()`` method that
performs the interactive authentication and returns the obtained credential.

Integration: This module participates in credential discovery, subscription login, and provider
authentication.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve credential-store permissions, token refresh, source precedence,
redaction, and noninteractive failure guidance.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class AuthFlow(ABC):
    """Abstract base for all auth flows.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    @abstractmethod
    def run(self) -> str:
        """Execute the flow and return the obtained credential value.

        Integration: Exposed as a public entrypoint for this subsystem.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """


# ---------------------------------------------------------------------------
# ApiKeyFlow — directly prompt for and store an API key
# ---------------------------------------------------------------------------


class ApiKeyFlow(AuthFlow):
    """Prompt the user for an API key and persist it via :mod:`openharness.auth.storage`.

    Integration: Constructed or referenced by ``_ensure_profile_auth``, ``_login_provider``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, provider: str, prompt_text: str | None = None) -> None:
        """Initialize ``ApiKeyFlow`` and bind its runtime dependencies.

        Integration: Exposed through ``ApiKeyFlow``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.provider = provider
        self.prompt_text = prompt_text or f"Enter your {provider} API key"

    def run(self) -> str:
        """Run one API key flow lifecycle.

        Integration: Exposed through ``ApiKeyFlow`` and collaborates with ``ValueError``,
        ``getpass.getpass``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        import getpass

        key = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key


# ---------------------------------------------------------------------------
# DeviceCodeFlow — GitHub OAuth device-code flow (refactored from copilot_auth)
# ---------------------------------------------------------------------------


class DeviceCodeFlow(AuthFlow):
    """GitHub OAuth device-code flow.

    This is a refactored version of the logic previously inlined in
    ``cli.py`` (``auth_copilot_login``).  It can be used for any GitHub
    OAuth app that supports the device-code grant.

    Integration: Constructed or referenced by ``_run_copilot_login``.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(
        self,
        client_id: str | None = None,
        github_domain: str = "github.com",
        enterprise_url: str | None = None,
        *,
        progress_callback: Any | None = None,
    ) -> None:
        """Initialize ``DeviceCodeFlow`` and bind its runtime dependencies.

        Integration: Exposed through ``DeviceCodeFlow``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        from openharness.api.copilot_auth import COPILOT_CLIENT_ID

        self.client_id = client_id or COPILOT_CLIENT_ID
        self.enterprise_url = enterprise_url
        self.github_domain = github_domain if not enterprise_url else enterprise_url
        self.progress_callback = progress_callback

    @staticmethod
    def _try_open_browser(url: str) -> bool:
        """Attempt to open *url* in the default browser; return True if likely succeeded.

        Integration: Called by ``DeviceCodeFlow.run``, ``BrowserFlow.run`` and collaborates with
        ``platform.system``, ``subprocess.Popen``, ``urlparse``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve argv boundaries, timeouts, and child cleanup; preserve exception
        and fallback behavior expected by callers.
        """
        # Only http(s) URLs are valid here. ShellExecute / xdg-open / `open`
        # all resolve unrecognised tokens (e.g. ``file:``, ``javascript:``, a
        # bare executable name) against the registry or PATH, so refusing
        # everything else removes a class of unintended-action footguns.
        if urlparse(url).scheme not in {"http", "https"}:
            return False
        try:
            plat = platform.system()
            if plat == "Darwin":
                subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if plat == "Windows":
                # ShellExecute via os.startfile — does NOT route through
                # cmd.exe, so ``&`` / ``|`` / ``^`` in the URL cannot be
                # interpreted as command separators.  Replaces the prior
                # ``subprocess.Popen([...], shell=True)`` form, which would
                # execute appended commands when a hostile or compromised
                # device-flow endpoint returned a URL like
                # ``https://x.com&calc.exe``.
                os.startfile(url)  # type: ignore[attr-defined]
                return True
            # Linux / WSL
            proc = subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                proc.wait(timeout=2)
                return proc.returncode == 0
            except subprocess.TimeoutExpired:
                return True
        except Exception:
            return False
        return False

    def run(self) -> str:
        """Run one device code flow lifecycle.

        Integration: Exposed through ``DeviceCodeFlow`` and collaborates with
        ``request_device_code``, ``_try_open_browser``, ``poll_for_access_token``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        from openharness.api.copilot_auth import poll_for_access_token, request_device_code

        print("Starting GitHub device flow...", flush=True)
        dc = request_device_code(client_id=self.client_id, github_domain=self.github_domain)

        print(flush=True)
        print(f"  Open: {dc.verification_uri}", flush=True)
        print(f"  Code: {dc.user_code}", flush=True)
        print(flush=True)

        opened = self._try_open_browser(dc.verification_uri)
        if opened:
            print("(Browser opened — enter the code shown above.)", flush=True)
        else:
            print("Open the URL above in your browser and enter the code.", flush=True)
        print(flush=True)

        if self.progress_callback is None:

            def _default_progress(poll_num: int, elapsed: float) -> None:
                """Apply default progress to the enclosing subsystem state.

                Integration: Used as an internal helper or callback at this module boundary.

                Concurrency: This is synchronous; preserve deterministic behavior for its direct
                callers.

                Change safety: Preserve the signature, return value, and side-effect contract
                expected by callers.
                """
                mins = int(elapsed) // 60
                secs = int(elapsed) % 60
                print(f"\r  Polling... ({mins}m {secs:02d}s elapsed)", end="", flush=True)

            self.progress_callback = _default_progress

        print("Waiting for authorisation...", flush=True)
        try:
            token = poll_for_access_token(
                dc.device_code,
                dc.interval,
                client_id=self.client_id,
                github_domain=self.github_domain,
                progress_callback=self.progress_callback,
            )
        except RuntimeError as exc:
            print(flush=True)
            print(f"Error: {exc}", file=sys.stderr, flush=True)
            raise

        print(flush=True)
        return token


# ---------------------------------------------------------------------------
# BrowserFlow — open a URL and wait for the user to complete auth
# ---------------------------------------------------------------------------


class BrowserFlow(AuthFlow):
    """Open a browser URL and wait for the user to complete authentication.

    After the user completes the browser flow they are expected to paste
    back a token/code — this simple implementation prompts for that value.

    Integration: Owned by the enclosing module and consumed through its public methods.

    Concurrency: The class is synchronous unless a collaborator documents otherwise; keep
    methods bounded when async callers use them inline.

    Change safety: Preserve constructor invariants, public method contracts, state ownership,
    and cleanup expectations used by collaborators.
    """

    def __init__(self, auth_url: str, prompt_text: str = "Paste the token from your browser") -> None:
        """Initialize ``BrowserFlow`` and bind its runtime dependencies.

        Integration: Exposed through ``BrowserFlow``.

        Concurrency: This is synchronous; preserve deterministic behavior for its direct
        callers.

        Change safety: Preserve the signature, return value, and side-effect contract expected
        by callers.
        """
        self.auth_url = auth_url
        self.prompt_text = prompt_text

    def run(self) -> str:
        """Run one browser flow lifecycle.

        Integration: Exposed through ``BrowserFlow`` and collaborates with
        ``DeviceCodeFlow._try_open_browser``, ``ValueError``, ``getpass.getpass``.

        Event loop: Async callers invoke this synchronous helper inline, so keep its work
        bounded and non-blocking.

        Change safety: Preserve exception and fallback behavior expected by callers.
        """
        import getpass

        print(f"Opening browser for authentication: {self.auth_url}", flush=True)
        opened = DeviceCodeFlow._try_open_browser(self.auth_url)
        if not opened:
            print(f"Could not open browser automatically. Visit: {self.auth_url}", flush=True)

        token = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not token:
            raise ValueError("No token provided.")
        return token
