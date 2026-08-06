from __future__ import annotations

import subprocess
from pathlib import Path


def list_changed_files(
    repo: Path,
    *,
    base: str,
    head: str = "HEAD",
    merge_base: bool = True,
) -> list[str]:
    """Return paths changed between base and head (repo-relative).

    Uses three-dot ``base...head`` (merge-base) by default, which is what you
    want for PR CI. Set ``merge_base=False`` for two-dot ``base head``.
    """
    repo = repo.resolve()
    if merge_base:
        args = ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"]
    else:
        args = ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head]

    try:
        out = subprocess.check_output(args, cwd=repo, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "").strip() or str(exc)
        raise RuntimeError(f"git diff failed: {err}") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("git executable not found") from exc

    return [line.strip() for line in out.splitlines() if line.strip()]


def read_changed_files_from_lines(lines: list[str]) -> list[str]:
    """Normalize a list of path lines (e.g. from stdin)."""
    files: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        files.append(line)
    return files
