"""Tests for beam/rollback.py — session-scoped rollback state."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from beam.rollback import RollbackEntry, RollbackSession


class TestRollbackEntry:
    def test_existed_remotely_true_when_bytes_present(self) -> None:
        entry = RollbackEntry(rel_path="src/main.py", original_bytes=b"print('hello')")
        assert entry.existed_remotely() is True

    def test_existed_remotely_false_when_none(self) -> None:
        entry = RollbackEntry(rel_path="new_file.py", original_bytes=None)
        assert entry.existed_remotely() is False

    def test_timestamp_set_automatically(self) -> None:
        before = datetime.now(timezone.utc)
        entry = RollbackEntry(rel_path="x.py", original_bytes=b"")
        after = datetime.now(timezone.utc)
        assert before <= entry.timestamp <= after


class TestRollbackSession:
    def test_initially_empty(self) -> None:
        session = RollbackSession()
        assert len(session) == 0
        assert session.list_entries() == []

    def test_snapshot_adds_entry(self) -> None:
        session = RollbackSession()
        entry = session.snapshot("app.py", b"original content")
        assert len(session) == 1
        assert entry.rel_path == "app.py"
        assert entry.original_bytes == b"original content"

    def test_snapshot_none_bytes_records_new_file(self) -> None:
        session = RollbackSession()
        entry = session.snapshot("brand_new.py", None)
        assert not entry.existed_remotely()

    def test_snapshot_replaces_existing_entry(self) -> None:
        session = RollbackSession()
        session.snapshot("app.py", b"version 1")
        session.snapshot("app.py", b"version 2")
        assert len(session) == 1
        entry = session.get_entry("app.py")
        assert entry is not None
        assert entry.original_bytes == b"version 2"

    def test_get_entry_returns_none_for_unknown(self) -> None:
        session = RollbackSession()
        assert session.get_entry("unknown.py") is None

    def test_has_entry(self) -> None:
        session = RollbackSession()
        session.snapshot("x.py", b"x")
        assert session.has_entry("x.py") is True
        assert session.has_entry("y.py") is False

    def test_list_entries_sorted_by_timestamp(self) -> None:
        session = RollbackSession()
        session.snapshot("a.py", b"a")
        session.snapshot("b.py", b"b")
        session.snapshot("c.py", b"c")
        entries = session.list_entries()
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps)

    def test_remove_existing_entry(self) -> None:
        session = RollbackSession()
        session.snapshot("a.py", b"a")
        result = session.remove("a.py")
        assert result is True
        assert not session.has_entry("a.py")

    def test_remove_nonexistent_returns_false(self) -> None:
        session = RollbackSession()
        assert session.remove("ghost.py") is False

    def test_clear_removes_all(self) -> None:
        session = RollbackSession()
        session.snapshot("a.py", b"a")
        session.snapshot("b.py", b"b")
        session.clear()
        assert len(session) == 0

    def test_multiple_files(self) -> None:
        session = RollbackSession()
        paths = ["src/a.py", "src/b.py", "lib/c.py"]
        for p in paths:
            session.snapshot(p, b"content")
        assert len(session) == 3
        for p in paths:
            assert session.has_entry(p)
