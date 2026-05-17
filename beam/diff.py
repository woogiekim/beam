"""Directory structure diff detection.

Compares the set of relative paths in local and remote trees.
Computes a mismatch ratio and determines whether it exceeds a configurable threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class DiffResult:
    """Result of comparing local and remote directory trees."""

    local_paths: frozenset[str]
    remote_paths: frozenset[str]

    @property
    def only_local(self) -> frozenset[str]:
        return self.local_paths - self.remote_paths

    @property
    def only_remote(self) -> frozenset[str]:
        return self.remote_paths - self.local_paths

    @property
    def common(self) -> frozenset[str]:
        return self.local_paths & self.remote_paths

    @property
    def mismatch_ratio(self) -> float:
        """Fraction of paths that exist only on one side.

        Computed as: mismatched / max(local_count, remote_count).
        Returns 0.0 when both trees are empty.
        """
        total = max(len(self.local_paths), len(self.remote_paths))
        if total == 0:
            return 0.0
        mismatched = len(self.only_local) + len(self.only_remote)
        return mismatched / total

    def exceeds_threshold(self, threshold: float) -> bool:
        """Return True when the mismatch ratio is strictly greater than threshold."""
        return self.mismatch_ratio > threshold

    def summary(self) -> str:
        """Human-readable one-line summary."""
        ratio_pct = self.mismatch_ratio * 100
        return (
            f"Mismatch: {ratio_pct:.1f}%  "
            f"(local-only: {len(self.only_local)}, "
            f"remote-only: {len(self.only_remote)}, "
            f"common: {len(self.common)})"
        )

    def format_diff(self, max_lines: int = 20) -> str:
        """Return a detailed diff block capped at max_lines entries per side."""
        lines: list[str] = [self.summary()]
        if self.only_local:
            lines.append("\nOnly in LOCAL:")
            for p in sorted(self.only_local)[:max_lines]:
                lines.append(f"  + {p}")
            if len(self.only_local) > max_lines:
                lines.append(f"  ... and {len(self.only_local) - max_lines} more")
        if self.only_remote:
            lines.append("\nOnly in REMOTE:")
            for p in sorted(self.only_remote)[:max_lines]:
                lines.append(f"  - {p}")
            if len(self.only_remote) > max_lines:
                lines.append(f"  ... and {len(self.only_remote) - max_lines} more")
        return "\n".join(lines)


def build_local_tree(local_root: str | Path) -> frozenset[str]:
    """Recursively collect relative paths from local_root.

    Returns POSIX-style relative paths (e.g. "src/main.py").
    Symlinks are followed; permission errors are silently skipped.
    """
    root = Path(local_root).expanduser().resolve()
    paths: list[str] = []
    for dirpath, dirnames, filenames in Path(root).walk():
        # Skip hidden directories (e.g. .git)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            full = Path(dirpath) / fname
            try:
                rel = full.relative_to(root)
                paths.append(rel.as_posix())
            except ValueError:
                pass
    return frozenset(paths)


def compute_diff(
    local_paths: frozenset[str] | Sequence[str],
    remote_paths: frozenset[str] | Sequence[str],
) -> DiffResult:
    """Compute the diff between local and remote path sets."""
    return DiffResult(
        local_paths=frozenset(local_paths),
        remote_paths=frozenset(remote_paths),
    )
