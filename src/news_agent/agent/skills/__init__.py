# Main-process module — never import from worker.py
"""Skill loader for prompt-skill ``.md`` files in ``skills/*.md``."""

from __future__ import annotations

import re
from pathlib import Path

from news_agent.logging_setup import get_logger

logger = get_logger()
_SKILL_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _skills_dir() -> Path:
    """Return the directory containing this ``__init__.py``."""
    return Path(__file__).resolve().parent


def list_skills() -> list[dict]:
    """Scan the skills directory for ``*.md`` files (excluding README.md).

    Returns:
        List of ``{"name": str, "description": str, "path": str}`` dicts,
        sorted by name.  The description is the first paragraph (split on
        ``\\n\\n``) truncated to 200 characters.
    """
    result: list[dict] = []
    sd = _skills_dir()
    try:
        for fp in sorted(sd.glob("*.md")):
            if fp.name == "README.md":
                continue
            name = fp.stem
            desc = ""
            try:
                content = fp.read_text(encoding="utf-8")
                paragraphs = content.split("\n\n")
                if paragraphs:
                    desc = paragraphs[0].replace("\n", " ").strip()
                    if len(desc) > 200:
                        desc = desc[:200].rsplit(" ", 1)[0]
            except OSError:
                pass
            result.append({"name": name, "description": desc, "path": str(fp)})
    except OSError:
        pass
    return result


def load_skill_content(name: str) -> str | None:
    """Read the full content of ``skills/{name}.md``.

    Args:
        name: Skill name (filename without ``.md``).  Must match
            ``^[a-z0-9_]+$``; ``README`` is explicitly excluded.

    Returns:
        File content as a string, or ``None`` when the name is invalid,
        the file is missing, or an I/O error occurs.
    """
    if name == "README" or not _SKILL_NAME_RE.match(name):
        return None
    path = _skills_dir() / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load_active_skills_content() -> str:
    """Concatenate enabled skill ``.md`` contents from ``agent_config.json``.

    For each entry in ``skills_enabled`` whose value is ``True``, this function
    reads the corresponding ``skills/{name}.md`` file and joins them with
    ``"\\n\\n---\\n\\n"`` separators.

    Returns:
        The combined text of all active skills, or an empty string when no
        skills are enabled (or when every skill file is missing).
    """
    # Lazy import to avoid circular dependency with agent.config at module level
    from news_agent.agent.config import load_agent_config  # noqa: PLC0415

    cfg = load_agent_config()
    enabled = cfg.get("skills_enabled", {})
    parts: list[str] = []
    for name, active in enabled.items():
        if not active:
            continue
        content = load_skill_content(name)
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts)
