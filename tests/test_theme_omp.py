"""Tests for Oh My Posh prompt engine integration (Issue #138)."""
from __future__ import annotations

import os
import pytest

from agentdata import cli_theme
from agentdata import omp
from agentdata import theme


def test_generate_omp_config_structure():
    """generate_omp_config produces valid JSON structure with required blocks and symbols."""
    for t in theme.list_themes():
        if t.name == "none":
            continue
        cfg = omp.generate_omp_config(t)
        assert cfg["$schema"] == omp.SCHEMA_URL
        assert cfg["version"] == 2
        assert "transient_prompt" in cfg
        assert cfg["transient_prompt"]["foreground"] == (t.accent or "#3FB950")
        assert len(cfg["blocks"]) >= 1
        segments = cfg["blocks"][0]["segments"]
        types = [s["type"] for s in segments]
        assert "git" in types
        assert "status" in types


def test_write_theme_omp_creates_file(tmp_path):
    """write_theme_omp writes a valid JSON file to the designated path."""
    t = theme.GREENS
    target = tmp_path / "greens.omp.json"
    written = omp.write_theme_omp(t, out_path=str(target))
    assert os.path.isfile(written)
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "AGENTDATA_PROJECT" in content
    assert "AGENTDATA_TICKET" in content


def test_install_and_uninstall_roundtrip_is_byte_identical(tmp_path):
    """Install and uninstall on pwsh, bash, and cmd leaves startup files byte-identical."""
    omp_file = tmp_path / "greens.omp.json"
    omp.write_theme_omp(theme.GREENS, str(omp_file))

    for shell, fname in (("pwsh", "profile.ps1"), ("bash", ".bashrc"), ("cmd", "oh-my-posh.lua")):
        startup = tmp_path / fname
        initial_content = f"# existing user profile\nWrite-Host 'Hello from {shell}'\n"
        startup.write_text(initial_content, encoding="utf-8")

        # 1. Install
        res_inst = omp.install(shell, str(omp_file), path=str(startup))
        assert res_inst["changed"] is True
        assert res_inst["replaced"] is False
        assert startup.read_text(encoding="utf-8") != initial_content

        # 2. Idempotent install: second run does not duplicate line
        res_inst2 = omp.install(shell, str(omp_file), path=str(startup))
        assert res_inst2["replaced"] is True

        # 3. Uninstall
        res_uninst = omp.uninstall(shell, path=str(startup))
        assert res_uninst["removed"] is True

        # Assert byte-identical restoration
        restored = startup.read_text(encoding="utf-8")
        assert restored.strip() == initial_content.strip()


def test_detect_graceful_handling():
    """detect() returns expected structure without crashing."""
    res = omp.detect()
    assert "installed" in res
    assert "clink" in res
    assert "nerd_font" in res


def test_cli_theme_install_and_uninstall_prompt(tmp_path, monkeypatch, capsys):
    """ad-theme install --prompt omp and ad-theme uninstall --prompt work via CLI."""
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("# bashrc\n", encoding="utf-8")

    monkeypatch.setattr(omp, "startup_file", lambda sh: str(bashrc))

    # Install
    rc = cli_theme.main(["install", "--prompt", "omp", "--shell", "bash"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "installed" in out
    assert omp.MARKER in bashrc.read_text(encoding="utf-8")

    # Uninstall
    rc = cli_theme.main(["uninstall", "--prompt", "--shell", "bash"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "removed" in out
    assert omp.MARKER not in bashrc.read_text(encoding="utf-8")
