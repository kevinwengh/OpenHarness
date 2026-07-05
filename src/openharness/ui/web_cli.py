"""Typer adapter for the local OpenHarness web UI host."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer


def web_cmd(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Loopback address for the local web UI",
    ),
    port: int = typer.Option(
        0,
        "--port",
        min=0,
        max=65535,
        help="Local port (0 selects an available port)",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Print the launch URL without opening a browser",
    ),
    cwd: str = typer.Option(
        str(Path.cwd()),
        "--cwd",
        help="Working directory for the web session",
    ),
) -> None:
    """Start the secure local OpenHarness browser interface."""

    from openharness.ui.web_server import (
        WebServerConfig,
        WebServerConfigurationError,
        run_web_ui,
    )

    try:
        asyncio.run(
            run_web_ui(
                WebServerConfig(
                    cwd=Path(cwd),
                    host=host,
                    port=port,
                    open_browser=not no_open,
                )
            )
        )
    except WebServerConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise typer.Exit(2)
