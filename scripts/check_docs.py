"""Validate structural documentation contracts without network access.

The check deliberately stays dependency-free. It validates local Markdown links, repository-root
paths written in code spans, SVG XML, fenced-block balance, and source-derived registry counts.
It does not claim to validate prose semantics or fully parse Mermaid syntax.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
GENERATED_DOC_ROOTS = {ROOT / "docs" / "autopilot"}
ROOT_PATH_PREFIXES = (
    ".github/",
    "autopilot-dashboard/",
    "docs/",
    "frontend/",
    "ohmo/",
    "scripts/",
    "src/",
    "tests/",
)
ROOT_FILES = {
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "pyproject.toml",
}
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
HTML_LINK_RE = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']", re.IGNORECASE)
CODE_SPAN_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")


def maintained_markdown_files() -> list[Path]:
    """Return hand-maintained Markdown files in deterministic order."""
    roots = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        ROOT / "CHANGELOG.md",
    ]
    roots.extend((ROOT / "docs").rglob("*.md"))
    return sorted(
        path
        for path in roots
        if path.is_file()
        and not any(path == generated or generated in path.parents for generated in GENERATED_DOC_ROOTS)
    )


def content_outside_fences(text: str, path: Path, errors: list[str]) -> str:
    """Blank fenced content so examples are not mistaken for live links or paths."""
    outside: list[str] = []
    fence: str | None = None
    fence_line = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        match = re.match(r"^\s*(```+|~~~+)", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0]
                fence_line = line_number
            elif marker[0] == fence:
                fence = None
            outside.append("\n" if line.endswith("\n") else "")
            continue
        outside.append(line if fence is None else ("\n" if line.endswith("\n") else ""))
    if fence is not None:
        errors.append(f"{path.relative_to(ROOT)}:{fence_line}: unclosed fenced block")
    return "".join(outside)


def normalize_local_target(raw_target: str) -> str | None:
    """Return a local path portion, or None for remote/anchor/template targets."""
    target = unquote(raw_target.strip().strip("<>"))
    if not target or target.startswith("#"):
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
        return None
    if target.startswith("//") or "${" in target or "{{" in target:
        return None
    return target.split("#", 1)[0].split("?", 1)[0]


def check_local_links(path: Path, text: str, errors: list[str]) -> None:
    """Check Markdown and HTML links that resolve within the repository."""
    targets = [match.group(1) for match in MARKDOWN_LINK_RE.finditer(text)]
    targets.extend(match.group(1) for match in HTML_LINK_RE.finditer(text))
    for raw_target in targets:
        target = normalize_local_target(raw_target)
        if target is None:
            continue
        resolved = ROOT / target.lstrip("/") if target.startswith("/") else path.parent / target
        if not resolved.resolve().exists():
            try:
                display_path: Path = resolved.resolve().relative_to(ROOT)
            except ValueError:
                display_path = resolved.resolve()
            errors.append(
                f"{path.relative_to(ROOT)}: missing local link {raw_target!r} "
                f"(resolved as {display_path})"
            )


def check_root_path_spans(path: Path, text: str, errors: list[str]) -> None:
    """Check unambiguous repository-root paths written as inline code."""
    for match in CODE_SPAN_RE.finditer(text):
        value = match.group(1).strip()
        candidate = value.split("::", 1)[0].split("#", 1)[0]
        candidate = re.sub(r":\d+(?:-\d+)?$", "", candidate)
        candidate = candidate.rstrip(".,:;)")
        if "*" in candidate or "<" in candidate or "{" in candidate:
            continue
        if candidate not in ROOT_FILES and not candidate.startswith(ROOT_PATH_PREFIXES):
            continue
        if not (ROOT / candidate).exists():
            line = text.count("\n", 0, match.start()) + 1
            errors.append(f"{path.relative_to(ROOT)}:{line}: missing repository path {candidate!r}")


def check_svgs(errors: list[str]) -> None:
    """Require every checked-in SVG to be well-formed XML with accessible title text."""
    for path in sorted((ROOT / "docs").rglob("*.svg")):
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid SVG XML: {exc}")
            continue
        root = tree.getroot()
        title = root.find("{http://www.w3.org/2000/svg}title")
        if title is None or not (title.text or "").strip():
            errors.append(f"{path.relative_to(ROOT)}: SVG must contain a non-empty <title>")


def check_registry_counts(errors: list[str]) -> None:
    """Keep checked-in capability counts synchronized with their actual registries."""
    from openharness.commands.registry import create_default_command_registry
    from openharness.tools import create_default_tool_registry

    tool_count = len(create_default_tool_registry().list_tools())
    command_count = len(create_default_command_registry().list_commands())
    expected_fragments = {
        ROOT / "README.md": [
            f"{tool_count} built-in tools",
            f"{command_count} built-in slash commands",
        ],
        ROOT / "docs" / "reference" / "TOOLS_AND_COMMANDS.md": [
            f"contains {tool_count}",
            f"and {command_count}",
        ],
    }
    for path, fragments in expected_fragments.items():
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                errors.append(
                    f"{path.relative_to(ROOT)}: expected source-derived text fragment {fragment!r}"
                )


def main() -> int:
    """Run checks and return a conventional process status."""
    errors: list[str] = []
    files = maintained_markdown_files()
    for path in files:
        text = content_outside_fences(path.read_text(encoding="utf-8"), path, errors)
        check_local_links(path, text, errors)
        check_root_path_spans(path, text, errors)
    check_svgs(errors)
    check_registry_counts(errors)

    if errors:
        print("Documentation integrity check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Documentation integrity check passed ({len(files)} Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
