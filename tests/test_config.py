"""Tests for beam/config.py — workspace configuration management."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from beam.config import Workspace, WorkspaceConfig


# ---------------------------------------------------------------------------
# Workspace dataclass
# ---------------------------------------------------------------------------


class TestWorkspace:
    def test_password_auth_ok(self) -> None:
        ws = Workspace(
            name="dev",
            local_root="/tmp/dev",
            host="dev.example.com",
            user="alice",
            remote_root="/var/www",
            password="secret",
        )
        assert ws.auth_type() == "password"

    def test_key_auth_ok(self) -> None:
        ws = Workspace(
            name="prod",
            local_root="/tmp/prod",
            host="prod.example.com",
            user="deploy",
            remote_root="/srv/app",
            key_path="/home/deploy/.ssh/id_rsa",
        )
        assert ws.auth_type() == "key"

    def test_no_auth_raises(self) -> None:
        with pytest.raises(ValueError, match="password or key_path"):
            Workspace(
                name="bad",
                local_root="/tmp",
                host="host",
                user="u",
                remote_root="/r",
            )

    def test_default_threshold(self) -> None:
        ws = Workspace(
            name="x", local_root="/x", host="h", user="u",
            remote_root="/r", password="p"
        )
        assert ws.diff_threshold == pytest.approx(0.30)

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        ws = Workspace(
            name="roundtrip",
            local_root="/tmp/rt",
            host="rt.example.com",
            user="bob",
            remote_root="/data",
            password="pass123",
            diff_threshold=0.20,
        )
        d = ws.to_dict()
        ws2 = Workspace.from_dict(d)
        assert ws2.name == ws.name
        assert ws2.host == ws.host
        assert ws2.diff_threshold == pytest.approx(0.20)

    def test_local_path_expands_home(self) -> None:
        ws = Workspace(
            name="home", local_root="~/myapp", host="h", user="u",
            remote_root="/r", password="p"
        )
        assert not str(ws.local_path()).startswith("~")


# ---------------------------------------------------------------------------
# WorkspaceConfig persistence
# ---------------------------------------------------------------------------


class TestWorkspaceConfig:
    def _tmp_config(self, tmp_path: Path) -> WorkspaceConfig:
        config_file = tmp_path / "workspaces.json"
        return WorkspaceConfig(config_file=config_file)

    def _sample_ws(self, name: str = "dev") -> Workspace:
        return Workspace(
            name=name,
            local_root="/tmp/dev",
            host="dev.example.com",
            user="alice",
            remote_root="/var/www",
            password="secret",
        )

    def test_empty_config_returns_empty_list(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        assert cfg.list() == []

    def test_add_and_get(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        ws = self._sample_ws()
        cfg.add(ws)
        fetched = cfg.get("dev")
        assert fetched is not None
        assert fetched.name == "dev"
        assert fetched.host == "dev.example.com"

    def test_add_persists_to_disk(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        cfg.add(self._sample_ws())
        # Load a fresh config from the same file
        cfg2 = WorkspaceConfig(config_file=cfg.config_file)
        assert len(cfg2.list()) == 1
        assert cfg2.get("dev") is not None

    def test_delete_existing(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        cfg.add(self._sample_ws())
        result = cfg.delete("dev")
        assert result is True
        assert cfg.get("dev") is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        assert cfg.delete("ghost") is False

    def test_multiple_workspaces(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        cfg.add(self._sample_ws("dev"))
        cfg.add(self._sample_ws("staging"))
        cfg.add(self._sample_ws("prod"))
        assert len(cfg.list()) == 3
        assert cfg.names() == ["dev", "staging", "prod"]

    def test_add_replaces_existing_name(self, tmp_path: Path) -> None:
        cfg = self._tmp_config(tmp_path)
        cfg.add(self._sample_ws("dev"))
        updated = Workspace(
            name="dev",
            local_root="/NEW",
            host="new.example.com",
            user="bob",
            remote_root="/NEW/remote",
            password="newpass",
        )
        cfg.add(updated)
        assert len(cfg.list()) == 1
        assert cfg.get("dev").host == "new.example.com"

    def test_missing_file_loads_empty(self, tmp_path: Path) -> None:
        cfg = WorkspaceConfig(config_file=tmp_path / "nonexistent.json")
        assert cfg.list() == []

    def test_corrupted_json_loads_empty(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "workspaces.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")
        cfg = WorkspaceConfig(config_file=bad_file)
        assert cfg.list() == []
