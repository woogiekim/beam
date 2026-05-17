"""Tests for deployer/diff.py — directory structure diff detection."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deployer.diff import DiffResult, build_local_tree, compute_diff


class TestDiffResult:
    def _make(self, local, remote) -> DiffResult:
        return DiffResult(
            local_paths=frozenset(local),
            remote_paths=frozenset(remote),
        )

    def test_only_local(self) -> None:
        d = self._make(["a.py", "b.py"], ["b.py"])
        assert d.only_local == frozenset({"a.py"})
        assert d.only_remote == frozenset()
        assert d.common == frozenset({"b.py"})

    def test_only_remote(self) -> None:
        d = self._make(["a.py"], ["a.py", "c.py"])
        assert d.only_remote == frozenset({"c.py"})

    def test_mismatch_ratio_identical(self) -> None:
        d = self._make(["a.py", "b.py"], ["a.py", "b.py"])
        assert d.mismatch_ratio == pytest.approx(0.0)

    def test_mismatch_ratio_completely_different(self) -> None:
        d = self._make(["x.py"], ["y.py"])
        # 2 mismatched / max(1, 1)=1 → 2.0 capped... wait, formula:
        # mismatched = len(only_local) + len(only_remote) = 1+1=2
        # total = max(1, 1) = 1
        # ratio = 2/1 = 2.0 — but this represents 100% different (two sets of 1)
        # In practice caller should treat >1.0 as fully different; threshold 0.30 still works.
        assert d.mismatch_ratio == pytest.approx(2.0)

    def test_mismatch_ratio_partial(self) -> None:
        # local: 3, remote: 3, 2 common, 1 only_local, 1 only_remote → 2/3
        d = self._make(["a", "b", "c"], ["b", "c", "d"])
        assert d.mismatch_ratio == pytest.approx(2 / 3)

    def test_both_empty_ratio_zero(self) -> None:
        d = self._make([], [])
        assert d.mismatch_ratio == pytest.approx(0.0)

    def test_exceeds_threshold_true(self) -> None:
        d = self._make(["a", "b", "c"], ["x", "y", "z"])  # 6/3 = 2.0
        assert d.exceeds_threshold(0.30) is True

    def test_exceeds_threshold_false(self) -> None:
        # 2 common, 0 mismatched → 0.0 ratio
        d = self._make(["a", "b"], ["a", "b"])
        assert d.exceeds_threshold(0.30) is False

    def test_exceeds_threshold_at_boundary(self) -> None:
        # 3 local, 3 remote, 2 common, 1 each side → ratio = 2/3 ≈ 0.667
        d = self._make(["a", "b", "c"], ["b", "c", "d"])
        # 0.667 > 0.30 → True
        assert d.exceeds_threshold(0.30) is True
        # 0.667 < 0.80 → False
        assert d.exceeds_threshold(0.80) is False

    def test_summary_contains_ratio(self) -> None:
        d = self._make(["a.py"], ["b.py"])
        summary = d.summary()
        assert "Mismatch:" in summary

    def test_format_diff_contains_local_and_remote(self) -> None:
        d = self._make(["only-local.py"], ["only-remote.py"])
        text = d.format_diff()
        assert "LOCAL" in text
        assert "only-local.py" in text
        assert "REMOTE" in text
        assert "only-remote.py" in text

    def test_format_diff_caps_lines(self) -> None:
        many_local = [f"file_{i}.py" for i in range(50)]
        d = self._make(many_local, [])
        text = d.format_diff(max_lines=10)
        assert "more" in text


class TestComputeDiff:
    def test_returns_diff_result(self) -> None:
        result = compute_diff({"a.py"}, {"a.py", "b.py"})
        assert isinstance(result, DiffResult)
        assert "b.py" in result.only_remote

    def test_accepts_lists(self) -> None:
        result = compute_diff(["a", "b"], ["b", "c"])
        assert result.only_local == frozenset({"a"})
        assert result.only_remote == frozenset({"c"})


class TestBuildLocalTree:
    def test_returns_relative_posix_paths(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x")
        (tmp_path / "README.md").write_text("r")

        paths = build_local_tree(tmp_path)
        assert "src/main.py" in paths
        assert "README.md" in paths

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").write_text("h")
        (tmp_path / "visible.py").write_text("v")

        paths = build_local_tree(tmp_path)
        assert "visible.py" in paths
        assert ".hidden" not in paths

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("git config")
        (tmp_path / "app.py").write_text("app")

        paths = build_local_tree(tmp_path)
        assert "app.py" in paths
        assert not any(".git" in p for p in paths)

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        assert build_local_tree(tmp_path) == frozenset()

    def test_nested_structure(self, tmp_path: Path) -> None:
        (tmp_path / "a" / "b" / "c").mkdir(parents=True)
        (tmp_path / "a" / "b" / "c" / "deep.py").write_text("d")
        paths = build_local_tree(tmp_path)
        assert "a/b/c/deep.py" in paths
