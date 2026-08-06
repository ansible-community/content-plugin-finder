from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

YAML_SUFFIXES = {".yml", ".yaml"}


@dataclass(frozen=True, slots=True)
class YamlScalar:
    path: Path
    line: int | None
    text: str


@dataclass
class CrawlContext:
    root: Path
    acc_result: Any | None = None
    yaml_scalars: list[YamlScalar] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def iter_yaml_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in YAML_SUFFIXES:
            continue
        # Skip obvious non-content noise
        if any(part.startswith(".") for part in path.parts):
            continue
        files.append(path)
    return files


def _walk_scalars(node: Any, path: Path, out: list[YamlScalar], line: int | None = None) -> None:
    if isinstance(node, str):
        if node.strip():
            out.append(YamlScalar(path=path, line=line, text=node))
        return
    if isinstance(node, dict):
        for value in node.values():
            _walk_scalars(value, path, out, line=line)
        return
    if isinstance(node, list):
        for item in node:
            _walk_scalars(item, path, out, line=line)


def build_yaml_scalar_index(root: Path) -> tuple[list[YamlScalar], list[str]]:
    scalars: list[YamlScalar] = []
    errors: list[str] = []
    for path in iter_yaml_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        try:
            documents = list(yaml.safe_load_all(text))
        except yaml.YAMLError as exc:
            errors.append(f"{path}: YAML parse error: {exc}")
            continue
        for doc in documents:
            if doc is not None:
                _walk_scalars(doc, path, scalars)
    return scalars, errors


def build_acc_result(root: Path) -> tuple[Any | None, list[str]]:
    errors: list[str] = []
    try:
        from ansible_content_capture.scanner import AnsibleScanner
    except Exception as exc:  # pragma: no cover - import failure is environmental
        return None, [f"failed to import ansible_content_capture: {exc}"]

    try:
        scanner = AnsibleScanner()
        result = scanner.run(target_dir=str(root.resolve()))
        return result, errors
    except Exception as exc:
        return None, [f"ansible-content-capture scan failed for {root}: {exc}"]


def build_context(
    root: Path,
    *,
    need_acc: bool = True,
    need_yaml: bool = True,
) -> CrawlContext:
    root = root.resolve()
    errors: list[str] = []
    acc_result = None
    yaml_scalars: list[YamlScalar] = []

    if need_acc:
        acc_result, acc_errors = build_acc_result(root)
        errors.extend(acc_errors)
    if need_yaml:
        yaml_scalars, yaml_errors = build_yaml_scalar_index(root)
        errors.extend(yaml_errors)

    return CrawlContext(
        root=root,
        acc_result=acc_result,
        yaml_scalars=yaml_scalars,
        errors=errors,
    )
