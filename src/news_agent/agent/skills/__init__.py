# Main-process module — never import from worker.py
"""Skill loader for prompt-skill ``.md`` files in ``skills/*.md``."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from news_agent.logging_setup import get_logger

logger = get_logger()
_SKILL_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _skills_dir() -> Path:
    """Return the directory containing this ``__init__.py``."""
    return Path(__file__).resolve().parent


def _user_skills_dir() -> Path:
    """Return the writable directory used for imported skills."""
    base = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return base / "news-agent" / "skills"


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def _parse_skill(path: Path, builtin: bool, content: str | None = None) -> dict:
    if content is None:
        content = path.read_text(encoding="utf-8")
    body = content
    metadata: dict = {}
    if content.startswith("---"):
        match = re.search(r"\r?\n---\s*(?:\r?\n|$)", content[3:])
        if match:
            header_end = 3 + match.start()
            body_start = 3 + match.end()
            parsed = yaml.safe_load(content[3:header_end])
            if isinstance(parsed, dict):
                metadata = parsed
            body = content[body_start:].lstrip()
    display_name = str(metadata.get("name") or path.stem).strip()
    name = _normalise_name(display_name)
    if not name:
        name = _normalise_name(path.stem)
    description = str(metadata.get("description") or "").strip()
    if not description:
        description = body.split("\n\n", 1)[0].replace("\n", " ").strip()
    return {
        "name": name,
        "display_name": display_name,
        "description": description[:200],
        "path": str(path),
        "builtin": builtin,
        "content": body.strip(),
    }


def _skill_records() -> dict[str, dict]:
    records: dict[str, dict] = {}
    for directory, builtin in ((_skills_dir(), True), (_user_skills_dir(), False)):
        try:
            for path in directory.glob("*.md"):
                if path.name == "README.md":
                    continue
                record = _parse_skill(path, builtin)
                if record["name"]:
                    records[record["name"]] = record
        except (OSError, yaml.YAMLError):
            logger.warning("could not scan skills in %s", directory, exc_info=True)
    return records


def list_skills() -> list[dict]:
    """Scan the skills directory for ``*.md`` files (excluding README.md).

    Returns:
        List of ``{"name": str, "description": str, "path": str}`` dicts,
        sorted by name.  The description is the first paragraph (split on
        ``\\n\\n``) truncated to 200 characters.
    """
    return [
        {key: value for key, value in record.items() if key != "content"}
        for _, record in sorted(_skill_records().items())
    ]


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
    record = _skill_records().get(name)
    return str(record["content"]) if record else None


def import_skill(filename: str, content: str) -> dict:
    """Validate and persist an uploaded Markdown prompt skill."""
    if Path(filename).suffix.lower() != ".md":
        raise ValueError("only .md skill files are supported")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("skill file is empty")
    if len(content.encode("utf-8")) > 512 * 1024:
        raise ValueError("skill file exceeds 512 KB")
    parsed = _parse_skill(Path(filename), builtin=False, content=content)
    name = parsed["name"]
    if not name or not _SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        raise ValueError("skill filename must contain letters, numbers, or underscores")
    path = _user_skills_dir() / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "name": name,
        "display_name": parsed["display_name"],
        "path": str(path),
        "size": len(content.encode("utf-8")),
    }


def delete_skill(name: str) -> bool:
    """Delete an imported skill; built-in skills cannot be removed."""
    record = _skill_records().get(name)
    if not record or record["builtin"]:
        return False
    path = Path(record["path"])
    path.unlink()
    return True


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
