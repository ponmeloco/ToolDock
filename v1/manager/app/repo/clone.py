from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def repo_cache_path(base_dir: Path, repo_url: str) -> Path:
    digest = hashlib.sha256(repo_url.encode("utf-8")).hexdigest()[:16]
    return base_dir / digest


def ensure_cloned(base_dir: Path, repo_url: str) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = repo_cache_path(base_dir, repo_url)
    if path.exists() and (path / ".git").exists():
        return path

    if path.exists():
        subprocess.run(["rm", "-rf", str(path)], check=True)

    subprocess.run(["git", "clone", "--depth", "1", repo_url, str(path)], check=True)
    return path
