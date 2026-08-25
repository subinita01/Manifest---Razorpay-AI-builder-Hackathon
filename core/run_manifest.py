"""Builds the RunManifest recorded with every run: seed, git SHA, config
hash, model string, library versions. Non-negotiable per CLAUDE.md rule 8.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from core.config import CONFIG_DIR
from core.models import RunManifest

TRACKED_PACKAGES = ("pydantic", "fastapi", "pandas", "rapidfuzz", "duckdb", "streamlit")


def _git_sha() -> str | None:
    """Gracefully degrades to None outside a git repo or if git isn't on PATH."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _config_hash() -> str:
    hasher = hashlib.sha256()
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


def _library_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for pkg in TRACKED_PACKAGES:
        try:
            versions[pkg] = version(pkg)
        except PackageNotFoundError:
            continue
    return versions


def build_run_manifest(run_id: str, seed: int = 0, model_string: str | None = None) -> RunManifest:
    """seed defaults to 0 for datasets with no seed concept (an uploaded
    dataset, as opposed to data/generator.py's synthetic demo data)."""
    return RunManifest(
        run_id=run_id,
        seed=seed,
        git_sha=_git_sha(),
        config_hash=_config_hash(),
        model_string=model_string,
        library_versions=_library_versions(),
        created_at=datetime.utcnow(),
    )
