#!/usr/bin/env python3
"""Print a concise AI-facing summary of the Savant capability registry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


# scripts/registry/ -> scripts/ -> <skill-root>; data lives under references/.
SKILL_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_ROOT = SKILL_ROOT / "references" / "registry"
COMPONENTS_ROOT = SKILL_ROOT / "references" / "components"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def load_registry(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    index = read_json(root / "index.json")
    common_rel = (index.get("common") or {}).get("lookupOperators") if isinstance(index.get("common"), dict) else None
    common = read_json(root / common_rel) if isinstance(common_rel, str) else {}
    components = {
        component_type: read_json(root / rel_path)
        for component_type, rel_path in (index.get("components") or {}).items()
        if isinstance(component_type, str) and isinstance(rel_path, str)
    }
    return index, common, components


def keys(value: Any) -> list[str]:
    return sorted(value.keys()) if isinstance(value, dict) else []


def values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def render_list(items: list[Any], max_items: int = 24) -> str:
    rendered = [str(item) for item in items]
    if len(rendered) > max_items:
        return ", ".join(rendered[:max_items]) + f", ... ({len(rendered)} total)"
    return ", ".join(rendered)


def markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(.*)$", line)
        if match:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = match.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def first_sentence(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    compact = " ".join((paragraphs[0] if paragraphs else text).split())
    compact = re.sub(r"`([^`]+)`", r"\1", compact)
    compact = compact.replace("**", "").replace("*", "")
    match = re.search(r"(.+?[.!?])(\s|$)", compact)
    if match:
        return match.group(1)
    if compact.endswith(":"):
        return compact[:-1] + "."
    return compact


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        metadata[key.strip()] = value
    return metadata, text[end + len("\n---\n") :]


def component_summary(component_type: str, components_root: Path = COMPONENTS_ROOT) -> tuple[str, str]:
    path = components_root / f"{component_type}.md"
    if not path.exists():
        return "", ""
    metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    summary = metadata.get("registry_summary") or first_sentence(markdown_sections(body).get("Business purpose", ""))
    return summary, metadata.get("registry_details", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", type=Path, default=REGISTRY_ROOT)
    args = parser.parse_args()

    index, common, components = load_registry(args.registry_root)

    print("# Savant Capability Registry Summary")
    print()
    print(f"Components: {len(components)}")
    print(f"Unsupported node types: {render_list(values(index.get('unsupportedNodeTypes')))}")
    print()

    lookup_ops = keys(common.get("lookupOperators"))
    print(f"Expression lookup operators ({len(lookup_ops)}): {render_list(lookup_ops)}")
    print(f"Unsupported lookup operators: {render_list(values(common.get('unsupportedLookupOperators')))}")
    print()

    for component_type in sorted(components):
        summary, details = component_summary(component_type)
        detail = summary or "Schema-backed component."
        if details:
            detail += f" ({details})"
        print(f"- {component_type}: {detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
