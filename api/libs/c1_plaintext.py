"""Extract readable plaintext from Thesys C1 responses.

Thesys generative-UI responses come wrapped in an XML envelope:

    <content thesys="true" version="1">  {JSON component tree}     </content>
    <content thesys="true" version="2">  ```openui-lang\n...\n```  </content>

`message.answer` stores the raw wrapper. Downstream consumers that want natural
language prose (TTS, workflow chaining into non-Thesys nodes, copy-to-clipboard,
cross-provider conversation history, etc.) materialize plaintext on demand via
`extract_plaintext(content)`.

The extractor is intentionally defensive:
- non-C1 content is returned unchanged
- malformed content degrades to empty string
- unknown components fall back to their string-literal args
- relies only on `json` + `re` + `html` from the stdlib
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterable
from typing import Any

_CONTENT_ENVELOPE = re.compile(r"<content\b([^>]*)>([\s\S]*?)</content>", re.IGNORECASE)
_VERSION_ATTR = re.compile(r"""\bversion\s*=\s*["'](\d+)["']""", re.IGNORECASE)
_OPENUI_FENCE = re.compile(r"```\s*openui-lang\s*\n([\s\S]*?)\n```", re.IGNORECASE)
_STATEMENT = re.compile(r"^\s*(\$?\w+)\s*=\s*(\w+)\s*\(([\s\S]*)\)\s*$")
_STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')

# Components whose visible output is their children — we skip them and let each
# child render on its own line.
_CONTAINER_COMPONENTS: frozenset[str] = frozenset(
    {
        "Card",
        "Section",
        "SectionBlock",
        "CompositeCardBlock",
        "CompositeCardItem",
        "ContextCardBlock",
        "Container",
        "Stack",
        "Row",
        "Column",
    }
)

# Components that are plumbing, never user-facing prose.
_SKIP_COMPONENTS: frozenset[str] = frozenset({"Query", "Mutation", "Icon"})

# JSON (v1) component prop names that typically hold user-facing prose.
_TEXT_JSON_KEYS: frozenset[str] = frozenset(
    {
        "title",
        "subtitle",
        "description",
        "label",
        "text",
        "heading",
        "caption",
        "markdown",
        "content",
        "body",
    }
)


def _format_default(strings: list[str]) -> str:
    return " ".join(s for s in strings if s)


def _format_header(strings: list[str]) -> str:
    if not strings:
        return ""
    out = f"# {strings[0]}"
    if len(strings) >= 2 and strings[1]:
        out += f"\n_{strings[1]}_"
    return out


def _format_inline_header(strings: list[str]) -> str:
    if not strings:
        return ""
    out = f"**{strings[0]}**"
    if len(strings) >= 2 and strings[1]:
        out += f" — {strings[1]}"
    return out


def _format_icon_text(strings: list[str]) -> str:
    # IconText(icon_ref, variant, size, title, description, ..., orientation)
    # The icon_ref at position 0 is a variable reference (not a string literal,
    # so it won't appear in `strings`). Remaining string literals start at
    # position 0 of `strings` with the variant, but user-visible text is title
    # (index ~1) and description (index ~2). Be tolerant to arity changes.
    if not strings:
        return ""
    title = strings[1] if len(strings) > 1 else strings[0]
    desc = strings[2] if len(strings) > 2 else ""
    parts = [f"**{title}**"] if title else []
    if desc:
        parts.append(f"— {desc}")
    return " ".join(parts)


def _format_text(strings: list[str]) -> str:
    # Text("type", "content") — take the content arg.
    if not strings:
        return ""
    return strings[1] if len(strings) > 1 else strings[0]


_FORMATTERS: dict[str, Callable[[list[str]], str]] = {
    "Header": _format_header,
    "InlineHeader": _format_inline_header,
    "TextContent": lambda s: s[0] if s else "",
    "Text": _format_text,
    "Button": lambda s: f"[button: {s[0]}]" if s else "",
    "IconButton": lambda s: f"[button: {s[0]}]" if s else "",
    "IconText": _format_icon_text,
    "FollowUpBlock": lambda s: "Follow-ups: " + " · ".join(x for x in s if x) if s else "",
    "Image": lambda s: f"[image: {s[1]}]" if len(s) > 1 and s[1] else "[image]",
    "BarChart": lambda s: "[bar chart]",
    "LineChart": lambda s: "[line chart]",
    "PieChart": lambda s: "[pie chart]",
    "AreaChart": lambda s: "[area chart]",
    "RadarChart": lambda s: "[radar chart]",
    "RadialChart": lambda s: "[radial chart]",
    "ScatterChart": lambda s: "[scatter chart]",
    "Table": lambda s: "[table]",
    "Slider": lambda s: f"[slider: {s[0]}]" if s else "[slider]",
    "Callout": lambda s: s[0] if s else "",
    "Alert": lambda s: s[0] if s else "",
}


def is_c1_content(content: str | None) -> bool:
    """Return True when the string contains a Thesys ``<content>`` envelope."""
    if not content:
        return False
    return bool(_CONTENT_ENVELOPE.search(content))


def extract_plaintext(content: str | None) -> str:
    """Return a readable plaintext rendering of a Thesys C1 response.

    Passes non-C1 content through unchanged. Empty / invalid inputs return ``""``.
    """
    if not content:
        return ""
    match = _CONTENT_ENVELOPE.search(content)
    if not match:
        return content.strip()

    attrs = match.group(1)
    inner = html.unescape(match.group(2)).strip()

    version_match = _VERSION_ATTR.search(attrs)
    version = int(version_match.group(1)) if version_match else 1

    if version >= 2:
        return _extract_from_openui_lang(inner)
    return _extract_from_json(inner)


def _extract_from_openui_lang(body: str) -> str:
    fence_match = _OPENUI_FENCE.search(body)
    if fence_match:
        body = fence_match.group(1).strip()

    segments: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        statement_match = _STATEMENT.match(line)
        if not statement_match:
            continue
        name, component, args = statement_match.groups()
        if name.startswith("$"):
            # State declaration — skip.
            continue
        if component in _CONTAINER_COMPONENTS or component in _SKIP_COMPONENTS:
            continue
        string_args = [m.group(1) for m in _STRING_LITERAL.finditer(args)]
        formatter = _FORMATTERS.get(component, _format_default)
        rendered = formatter(string_args).strip()
        if rendered:
            segments.append(rendered)

    return "\n\n".join(segments).strip()


def _extract_from_json(body: str) -> str:
    """Best-effort plaintext for the v1 JSON component tree."""
    try:
        tree = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        # Fall back to a coarse string-literal sweep; preserves behaviour for
        # partial / malformed v1 payloads rather than silently returning empty.
        strings = [m.group(1) for m in _STRING_LITERAL.finditer(body)]
        return " ".join(s for s in strings if s).strip()

    pieces: list[str] = []
    _collect_json_text(tree, pieces)
    return " ".join(p for p in pieces if p).strip()


def _collect_json_text(node: Any, out: list[str]) -> None:
    if node is None:
        return
    if isinstance(node, str):
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _TEXT_JSON_KEYS and isinstance(value, str):
                out.append(value)
            elif isinstance(value, (dict, list)):
                _collect_json_text(value, out)
        return
    if isinstance(node, Iterable) and not isinstance(node, (bytes, bytearray)):
        for item in node:
            _collect_json_text(item, out)
