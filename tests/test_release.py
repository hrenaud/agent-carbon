"""Tests du système de release (bump + changelog + validation).

Utilise un repo git temporisé via `monkeypatch` et un `_git` mocké
pour isoler les tests de la base réelle.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from agent_carbon.release import (
    ReleaseError,
    _check_clean_tree,
    _check_on_main,
    _check_tag_absent,
    _format_changelog,
    _parse_changelog,
    bump,
    changelog_range,
    last_tag,
    parse_version,
    run,
)


# ------------------------------------------------------------------- parse_version
def test_parse_version_finds_version():
    assert parse_version('version = "1.2.3"') == "1.2.3"


def test_parse_version_fails_on_missing():
    with pytest.raises(ReleaseError, match="Impossible de trouver version"):
        parse_version("pas de version ici")


# ------------------------------------------------------------------------ bump
@pytest.mark.parametrize(
    "version,part,new",
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.0", "minor", "0.2.0"),
        ("0.1.0", "major", "1.0.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
    ],
)
def test_bump_parties(version, part, new):
    assert bump(version, part) == new


def test_bump_invalid_part():
    with pytest.raises(ReleaseError, match="part invalide"):
        bump("0.1.0", "quux")


# ------------------------------------------------------------------- changelog
def test_parse_changelog_groups_by_type():
    raw = "feat(auth): login OAuth\nfix(core): null pointer\ndocs(readme): typo\n"
    parsed = _parse_changelog(raw)
    assert parsed["feat"] == ["(auth) — login OAuth"]
    assert parsed["fix"] == ["(core) — null pointer"]
    assert parsed["docs"] == ["(readme) — typo"]
    assert "other" not in parsed


def test_parse_changelog_with_scope():
    raw = "feat(auth): login OAuth"
    parsed = _parse_changelog(raw)
    assert parsed["feat"] == ["(auth) — login OAuth"]


def test_parse_changelog_without_scope():
    raw = "fix: correction note"
    parsed = _parse_changelog(raw)
    assert parsed["fix"] == ["correction note"]


def test_parse_changelog_falls_back_to_other():
    raw = "untyped line\nfix: oui\n"
    parsed = _parse_changelog(raw)
    assert parsed["other"] == ["untyped line"]
    assert parsed["fix"] == ["oui"]


def test_format_changelog_empty():
    assert _format_changelog({}) == ""


def test_format_changelog_orders_sections():
    parsed = {
        "feat": ["a"],
        "fix": ["b"],
        "other": ["c"],
    }
    out = _format_changelog(parsed)
    feat_idx = out.index("Features")
    fix_idx = out.index("Bug Fixes")
    other_idx = out.index("Autres")
    assert feat_idx < fix_idx < other_idx


def test_format_changelog_skips_empty_sections():
    parsed = {"feat": ["x"], "other": ["y"]}
    out = _format_changelog(parsed)
    assert "Bug Fixes" not in out
    assert "Features" in out
    assert "Autres" in out


# ------------------------------------------------------------ git helpers mocks
def _mock_git_side_effect(commands, output_map):
    """Retourne output_map[command tuple] ou lève CalledProcessError."""
    def side_effect(*args, **_):
        key = tuple(args)
        if key in output_map:
            class Result:
                stdout = output_map[key]
            return Result()
        # Tag inexistant → exit 128
        raise subprocess.CalledProcessError(128, args)
    return side_effect


def test_check_clean_tree_blocks_on_modification(tmp_path):
    """Si `git status --porcelain` renvoie autre chose que vide → bloquer."""
    def dirty(*_args, **_kwargs):
        return "M agent_carbon/foo.py"
    with patch("agent_carbon.release._git", side_effect=dirty):
        with pytest.raises(ReleaseError, match="sale"):
            _check_clean_tree()


def test_check_on_main_blocks_on_feature(tmp_path):
    """Si on est sur feature → bloquer avec le nom de branche."""
    def on_feature(*_args, **_kwargs):
        return "feature-x"
    with patch("agent_carbon.release._git", side_effect=on_feature):
        with pytest.raises(ReleaseError, match="feature-x"):
            _check_on_main()


def test_check_on_main_passes_on_main(tmp_path):
    def ok(*_args, **_kwargs):
        return "main"
    with patch("agent_carbon.release._git", side_effect=ok):
        _check_on_main()  # ne doit pas lever


def test_check_tag_absent_allows_missing_tag(tmp_path):
    """Pas de tag → pas d'erreur."""
    def missing(*_args, **_kwargs):
        raise subprocess.CalledProcessError(128, _args)
    with patch("agent_carbon.release._git", side_effect=missing):
        _check_tag_absent("9.9.9")  # ne doit pas lever


def test_check_tag_absent_blocks_existing_tag(tmp_path):
    """Tag existant → erreur."""
    def found(*_args, **_kwargs):
        return "v9.9.9"
    with patch("agent_carbon.release._git", side_effect=found):
        with pytest.raises(ReleaseError, match="existe déjà"):
            _check_tag_absent("9.9.9")


def test_last_tag_returns_none_when_no_tags(tmp_path):
    def no_tags(*_args, **_kwargs):
        raise subprocess.CalledProcessError(128, _args)
    with patch("agent_carbon.release._git", side_effect=no_tags):
        assert last_tag() is None


def test_last_tag_returns_tag(tmp_path):
    def has_tag(*_args, **_kwargs):
        return "v0.1.0"
    with patch("agent_carbon.release._git", side_effect=has_tag):
        assert last_tag() == "v0.1.0"


def test_changelog_range_no_last_tag(tmp_path):
    """Sans dernier tag : tous les commits."""
    def log_all(*args, **_):
        return "feat:A\nfix:B\n"
    with patch("agent_carbon.release._git", side_effect=log_all):
        assert changelog_range(None) == "feat:A\nfix:B\n"


def test_changelog_range_with_last_tag(tmp_path):
    """Avec tag : `v0.1.0..HEAD`."""
    calls = []

    def log_between(*args, **_):
        calls.append(tuple(args))
        return "fix:C\n"

    with patch("agent_carbon.release._git", side_effect=log_between):
        changelog_range("v0.1.0")

    # L'ordre des args est : ("log", range, "--pretty=format:%s")
    assert calls[0][0] == "log"
    assert calls[0][1] == "v0.1.0..HEAD"
    assert "--pretty=format:%s" in calls[0]


# ----------------------------------------------------------- full run mocked
def _make_git_map(*, clean=True, branch="main", tags=None):
    """Retourne un callable qui simule les appels _git avec des strings."""
    tags = tags or []

    def handler(*args, **_):
        cmd = tuple(args)
        if cmd == ("status", "--porcelain"):
            return "" if clean else "M x"
        if cmd == ("rev-parse", "--abbrev-ref", "HEAD"):
            return branch
        if cmd[0] == "rev-parse" and len(cmd) > 1 and cmd[1].startswith("v"):
            # Vérification d'un tag existant : si le tag est dans la liste, réussit
            tag_name = cmd[1]
            if tag_name in tags:
                return tag_name
            # Sinon, échoue (tag inexistant)
            raise subprocess.CalledProcessError(128, cmd)
        if cmd == ("describe", "--tags", "--abbrev=0"):
            if tags:
                return tags[-1]
            raise subprocess.CalledProcessError(128, cmd)
        if cmd[:2] == ("log", "--pretty=format:%s"):
            return "feat:x\nfix:y\n"
        if cmd[0] == "log" and any("..HEAD" in a for a in cmd):
            return "feat:x\nfix:y\n"
        # add / commit / tag / push : succès silencieux (quel que soit les fichiers)
        if cmd[0] in ("add", "commit", "tag", "push"):
            return ""
        raise NotImplementedError(f"mock non couvert : {cmd}")

    return handler

def test_run_bumps_patch_successfully(tmp_path, monkeypatch):
    """Cycle complet : bump patch, tag créé, pas de push."""
    # Monkeypatch BASE_DIR, PYPROJECT, INIT_FILE, CHANGELOG vers tmp_path
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=True, tags=[])
    with patch("agent_carbon.release._git", side_effect=git_handler):
        new = run("patch")

        assert new == "0.1.1"
        # Vérifie que les fichiers ont été bumpés
        assert (fake_base / "pyproject.toml").read_text().startswith('version = "0.1.1"')
        assert (fake_base / "agent_carbon" / "__init__.py").read_text().startswith('__version__ = "0.1.1"')
        # Le CHANGELOG contient le nouveau bloc
        changelog_content = (fake_base / "CHANGELOG.md").read_text()
        assert "## [0.1.1]" in changelog_content


def test_run_blocks_dirty_tree(tmp_path, monkeypatch):
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=False, tags=[])
    with patch("agent_carbon.release._git", side_effect=git_handler):
        with pytest.raises(ReleaseError, match="sale"):
            run("patch")


def test_run_blocks_on_non_main(tmp_path, monkeypatch):
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=True, branch="feature-x", tags=[])
    with patch("agent_carbon.release._git", side_effect=git_handler):
        with pytest.raises(ReleaseError, match="feature-x"):
            run("patch")


def test_run_blocks_on_existing_tag(tmp_path, monkeypatch):
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=True, tags=["v0.1.1"])
    with patch("agent_carbon.release._git", side_effect=git_handler):
        with pytest.raises(ReleaseError, match="existe déjà"):
            run("patch")


def test_run_with_push_calls_git_push(tmp_path, monkeypatch):
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=True, tags=[])
    calls = []

    def tracking_handler(*args, **_):
        calls.append(tuple(args))
        return git_handler(*args, **_)

    with patch("agent_carbon.release._git", side_effect=tracking_handler):
        run("patch", push=True)

    # Le dernier appel doit être le push
    push_call = calls[-1]
    assert push_call[:2] == ("push", "origin")
    assert "main" in push_call
    assert "--tags" in push_call


def test_run_without_push_does_not_push(tmp_path, monkeypatch):
    import agent_carbon.release as rel

    fake_base = tmp_path / "repo"
    fake_base.mkdir()
    (fake_base / "pyproject.toml").write_text('version = "0.1.0"\n')
    (fake_base / "agent_carbon").mkdir()
    (fake_base / "agent_carbon" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (fake_base / "CHANGELOG.md").write_text("# Changelog\n")

    monkeypatch.setattr(rel, "BASE_DIR", fake_base)
    monkeypatch.setattr(rel, "PYPROJECT", fake_base / "pyproject.toml")
    monkeypatch.setattr(rel, "INIT_FILE", fake_base / "agent_carbon" / "__init__.py")
    monkeypatch.setattr(rel, "CHANGELOG", fake_base / "CHANGELOG.md")

    git_handler = _make_git_map(clean=True, tags=[])
    calls = []

    def tracking_handler(*args, **_):
        calls.append(tuple(args))
        return git_handler(*args, **_)

    with patch("agent_carbon.release._git", side_effect=tracking_handler):
        run("patch")

    push_calls = [c for c in calls if c[0] == "push"]
    assert push_calls == []
