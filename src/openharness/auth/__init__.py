"""Unified authentication management for OpenHarness.

Integration: This module participates in credential discovery, subscription login, and provider
authentication.

Concurrency: This module is synchronous unless collaborators document otherwise; async callers
execute its helpers inline, so filesystem, process, parsing, and serialization work must remain
bounded.

Change safety: Preserve credential-store permissions, token refresh, source precedence,
redaction, and noninteractive failure guidance.
"""

from openharness.auth.flows import ApiKeyFlow, BrowserFlow, DeviceCodeFlow
from openharness.auth.manager import AuthManager
from openharness.auth.storage import (
    clear_provider_credentials,
    decrypt,
    encrypt,
    load_credential,
    load_external_binding,
    store_credential,
    store_external_binding,
)

__all__ = [
    "AuthManager",
    "ApiKeyFlow",
    "BrowserFlow",
    "DeviceCodeFlow",
    "store_credential",
    "load_credential",
    "store_external_binding",
    "load_external_binding",
    "clear_provider_credentials",
    # Deprecated — use _obfuscate/_deobfuscate directly if needed.
    # Kept for backward compatibility; will be removed in a future version.
    "encrypt",
    "decrypt",
]
