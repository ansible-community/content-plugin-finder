from __future__ import annotations

from pathlib import Path

import yaml


def read_collection_fqcn(collection_root: Path) -> str:
    galaxy = collection_root / "galaxy.yml"
    if not galaxy.is_file():
        raise FileNotFoundError(f"galaxy.yml not found in {collection_root}")
    data = yaml.safe_load(galaxy.read_text(encoding="utf-8")) or {}
    namespace = data.get("namespace")
    name = data.get("name")
    if not namespace or not name:
        raise ValueError(f"galaxy.yml missing namespace/name: {galaxy}")
    return f"{namespace}.{name}"
