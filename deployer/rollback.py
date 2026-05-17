"""Session-scoped rollback state.

Maintains an in-memory log of pre-deploy remote file snapshots.
State is discarded when the program exits — no persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RollbackEntry:
    """A snapshot of a remote file captured immediately before deployment."""

    rel_path: str
    original_bytes: Optional[bytes]  # None when the file did not exist remotely
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def existed_remotely(self) -> bool:
        """Return True when the remote file existed before deployment."""
        return self.original_bytes is not None


class RollbackSession:
    """In-memory rollback log for the current program session.

    Each deploy action should call `snapshot()` before uploading.
    After deployment, call `rollback_file()` to restore the original state.
    """

    def __init__(self) -> None:
        # Keyed by rel_path; stores the MOST RECENT pre-deploy snapshot per path.
        self._entries: dict[str, RollbackEntry] = {}

    def snapshot(self, rel_path: str, original_bytes: Optional[bytes]) -> RollbackEntry:
        """Record the pre-deploy state of a file.

        Args:
            rel_path: Relative path (POSIX) within the workspace.
            original_bytes: Content of the remote file before deployment.
                            Pass None when the file did not previously exist.

        Returns:
            The newly created RollbackEntry.
        """
        entry = RollbackEntry(rel_path=rel_path, original_bytes=original_bytes)
        self._entries[rel_path] = entry
        return entry

    def get_entry(self, rel_path: str) -> Optional[RollbackEntry]:
        """Return the snapshot for rel_path, or None if not snapshotted."""
        return self._entries.get(rel_path)

    def list_entries(self) -> list[RollbackEntry]:
        """Return all entries in chronological order (oldest first)."""
        return sorted(self._entries.values(), key=lambda e: e.timestamp)

    def has_entry(self, rel_path: str) -> bool:
        return rel_path in self._entries

    def clear(self) -> None:
        """Clear all rollback entries (e.g. after a fresh workspace switch)."""
        self._entries.clear()

    def remove(self, rel_path: str) -> bool:
        """Remove a single entry. Return True when removed, False if absent."""
        if rel_path in self._entries:
            del self._entries[rel_path]
            return True
        return False

    def __len__(self) -> int:
        return len(self._entries)
