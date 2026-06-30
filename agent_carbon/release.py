"""Système de release : bump sémantique + génération CHANGELOG + commit + tag.

Usage CLI : `agent-carbon release bump <patch|minor|major> [--push]`.

Flux :
  1. Vérifie tree propre, branche main, pas de tag existant.
  2. Lit la version courante, calcule la nouvelle.
  3. Génère le CHANGELOG entre le dernier tag et HEAD.
  4. Bump pyproject.toml + __init__.py.
  5. Prepend le nouveau bloc dans CHANGELOG.md.
  6. Commit `chore(release): vX.Y.Z` + tag `vX.Y.Z`.
  7. (optionnel) git push origin main --tags.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

VERSION_RE = re.compile(r'version = "(\d+\.\d+\.\d+)"')
INIT_RE = re.compile(r'__version__ = "[^"]*"')

BASE_DIR = Path(__file__).resolve().parent.parent
PYPROJECT = BASE_DIR / "pyproject.toml"
INIT_FILE = BASE_DIR / "agent_carbon" / "__init__.py"
CHANGELOG = BASE_DIR / "CHANGELOG.md"


# --------------------------------------------------------------------- exceptions
class ReleaseError(Exception):
    """Erreur bloquante lors d'un release."""


# ------------------------------------------------------------------- helpers
def _git(*args: str) -> str:
    """Exécute `git …` et renvoie stdout stripé. Lève subprocess.CalledProcessError."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _check_clean_tree() -> None:
    status = _git("status", "--porcelain")
    if status:
        raise ReleaseError(
            "Arbre de travail sale — commit ou annule tes modifications avant release."
        )


def _check_on_main() -> None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise ReleaseError(
            f"Release uniquement depuis `main` (tu es sur `{branch}`)."
        )


def _check_tag_absent(version: str) -> None:
    try:
        _git("rev-parse", f"v{version}")
    except subprocess.CalledProcessError:
        return
    raise ReleaseError(f"Le tag `v{version}` existe déjà.")


def parse_version(text: str) -> str:
    """Extrait `X.Y.Z` du contenu brut d'un fichier de version."""
    m = VERSION_RE.search(text)
    if m is None:
        raise ReleaseError("Impossible de trouver version = « X.Y.Z » dans pyproject.toml.")
    return m.group(1)


def bump(version: str, part: str) -> str:
    """Retourne la version après bump de `part` (patch, minor ou major)."""
    if part not in {"patch", "minor", "major"}:
        raise ReleaseError(f"part invalide : {part!r} (choisir patch, minor ou major)")
    parts = list(map(int, version.split(".")))
    if part == "major":
        parts = [parts[0] + 1, 0, 0]
    elif part == "minor":
        parts[1] += 1
        parts[2] = 0
    else:
        parts[2] += 1
    return ".".join(map(str, parts))


def last_tag() -> str | None:
    """Renvoie le dernier tag annoté, ou None s'il n'y en a pas."""
    try:
        return _git("describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        return None


def changelog_range(last: str | None) -> str:
    """Retourne le log des messages de commit entre `last` (exclue) et HEAD.

    Format conventionnel : `type(scope)?: description`.
    """
    args = ["log", "--pretty=format:%s"]
    if last:
        args.insert(1, f"{last}..HEAD")
    try:
        return _git(*args)
    except subprocess.CalledProcessError:
        return ""


def _parse_changelog(text: str) -> dict[str, list[str]]:
    """Parse les commits conventionnels en rubriques {type: [descriptions]}.

    Les descriptions sont nettoyées (suppression du préfixe `type(scope): `).
    Les entries sans type conventionnel vont dans `other`.
    """
    sections: dict[str, list[str]] = {}
    type_order = ["feat", "fix", "docs", "chore", "refactor", "perf", "test", "ci", "other"]
    for line in text.splitlines():
        m = re.match(r"^(feat|fix|docs|chore|refactor|perf|test|ci)(\(.+?\))?:\s*(.+)", line)
        if m:
            key = m.group(1)
            scope = m.group(2)
            desc = m.group(3).strip()
            label = f"{scope} — {desc}" if scope else desc
            sections.setdefault(key, []).append(label)
        else:
            sections.setdefault("other", []).append(line)
    return {k: v for k, v in sections.items() if v}


def _format_changelog(parsed: dict[str, list[str]]) -> str:
    labels = {
        "feat": "Features",
        "fix": "Bug Fixes",
        "docs": "Documentation",
        "chore": "Chores",
        "refactor": "Refactoring",
        "perf": "Performance",
        "test": "Tests",
        "ci": "CI",
        "other": "Autres",
    }
    lines: list[str] = []
    for key in ["feat", "fix", "docs", "chore", "refactor", "perf", "test", "ci", "other"]:
        items = parsed.get(key)
        if not items:
            continue
        lines.append(f"### {labels[key]}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _prepend_changelog(new_block: str) -> None:
    """Prepend un bloc dans CHANGELOG.md (créé si inexistant)."""
    header = "# Changelog\n\nRecent Changes\n"
    if not CHANGELOG.exists():
        CHANGELOG.write_text(f"{header}\n{new_block}\n")
        return
    content = CHANGELOG.read_text()
    # Insère après le header (h1 + saut de ligne).
    m = re.match(r"^#\s+.+?\n\n", content)
    if m:
        pos = m.end()
        CHANGELOG.write_text(content[:pos] + new_block + "\n" + content[pos:])
    else:
        CHANGELOG.write_text(f"{header}\n{new_block}\n{content}")


def _update_pyproject(version: str) -> None:
    content = PYPROJECT.read_text()
    PYPROJECT.write_text(VERSION_RE.sub(f'version = "{version}"', content))


def _update_init(version: str) -> None:
    content = INIT_FILE.read_text()
    INIT_FILE.write_text(INIT_RE.sub(f'__version__ = "{version}"', content))


def run(part: str, *, push: bool = False) -> str:
    """Exécute le cycle de release complet.

    Args:
        part: patch, minor ou major.
        push: si True, push main + tags après le commit.

    Returns:
        La nouvelle version (ex. "0.2.0").

    Lève ReleaseError en cas d'échec d'une des validations.
    """
    # 1. Validations
    _check_clean_tree()
    _check_on_main()

    # 2. Lecture + calcul
    current = parse_version(PYPROJECT.read_text())
    new = bump(current, part)
    _check_tag_absent(new)

    # 3. Changelog
    last = last_tag()
    raw = changelog_range(last)
    body = _format_changelog(_parse_changelog(raw)) if raw.strip() else "(aucun changelog généré — premier release)"
    date = datetime.now().strftime("%Y-%m-%d")
    block = f"## [{new}] — {date}\n\n{body}"

    # 4. Bump fichiers
    _update_pyproject(new)
    _update_init(new)
    _prepend_changelog(block)

    # 5. Commit + tag
    tag = f"v{new}"
    _git("add", str(PYPROJECT), str(INIT_FILE), str(CHANGELOG))
    _git("commit", "-m", f"chore(release): {new}", "-m", tag)
    _git("tag", tag)

    if push:
        _git("push", "origin", "main", "--tags")

    return new
