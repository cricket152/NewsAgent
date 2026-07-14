"""Tests for user-imported skills and MCP connection probing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_agent.agent.config import load_agent_config, save_agent_config
from news_agent.agent.conversation import _effective_system_prompt
from news_agent.agent.mcp_config import probe_mcp_server
from news_agent.agent.skills import (
    delete_skill,
    import_skill,
    list_skills,
    load_skill_content,
)


def test_import_skill_to_user_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = import_skill("My Research Skill.md", "Use concise evidence.\n")

    assert result["name"] == "my_research_skill"
    assert Path(result["path"]).is_file()
    assert load_skill_content("my_research_skill") == "Use concise evidence."
    assert any(item["name"] == "my_research_skill" for item in list_skills())


def test_import_skill_rejects_non_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(ValueError, match="only .md"):
        import_skill("skill.txt", "content")


def test_import_skill_uses_frontmatter_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    content = "---\nname: grill-me\ndescription: Sharpen a plan.\n---\n\nRun a grilling session."

    result = import_skill("SKILL.md", content)
    item = next(skill for skill in list_skills() if skill["name"] == "grill_me")

    assert result["display_name"] == "grill-me"
    assert item["display_name"] == "grill-me"
    assert item["description"] == "Sharpen a plan."
    assert load_skill_content("grill_me") == "Run a grilling session."
    assert delete_skill("grill_me") is True
    assert load_skill_content("grill_me") is None


def test_probe_http_mcp_initialize_success() -> None:
    response = MagicMock()
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"serverInfo": {"name": "test-mcp", "version": "1.0"}},
    }

    with patch("news_agent.agent.mcp_config.httpx.post", return_value=response) as post:
        result = probe_mcp_server(
            {"name": "test", "transport": "http", "command_or_url": "http://localhost/mcp"}
        )

    assert result["ok"] is True
    assert result["server_info"]["name"] == "test-mcp"
    assert post.call_args.kwargs["json"]["method"] == "initialize"


def test_probe_mcp_rejects_empty_target() -> None:
    result = probe_mcp_server({"name": "bad", "transport": "http", "command_or_url": ""})
    assert result == {"ok": False, "message": "command or URL is empty"}


def test_system_prompt_defaults_empty_and_combines_enabled_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert load_agent_config()["system_prompt"] == ""
    imported = import_skill("Focus.md", "Always focus on evidence.")
    save_agent_config(
        {
            "skills_enabled": {imported["name"]: True},
            "mcp_servers": [],
            "system_prompt": "Answer in Chinese.",
        }
    )

    assert _effective_system_prompt() == "Always focus on evidence.\n\nAnswer in Chinese."
