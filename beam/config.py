"""Workspace configuration management.

Stores multiple named workspaces in ~/.beam/workspaces.json.
Each workspace defines a local root directory and a remote SSH/SFTP connection.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".beam"
CONFIG_FILE = CONFIG_DIR / "workspaces.json"


@dataclass
class Workspace:
    """A named workspace mapping a local root to a remote SSH/SFTP endpoint."""

    name: str
    local_root: str
    host: str
    user: str
    remote_root: str
    port: int = 22
    password: Optional[str] = None
    key_path: Optional[str] = None
    diff_threshold: float = 0.30

    def __post_init__(self) -> None:
        if not self.password and not self.key_path:
            raise ValueError(
                f"Workspace '{self.name}' must have either password or key_path set."
            )
        if not self.remote_root.startswith("/"):
            raise ValueError(
                f"Workspace '{self.name}': remote_root must be an absolute path "
                f"(must start with '/'), got: {self.remote_root!r}"
            )

    def auth_type(self) -> str:
        """Return 'key' when using an SSH key, 'password' otherwise."""
        if self.key_path:
            return "key"
        return "password"

    def local_path(self) -> Path:
        return Path(self.local_root).expanduser().resolve()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        return cls(
            name=data["name"],
            local_root=data["local_root"],
            host=data["host"],
            user=data["user"],
            remote_root=data["remote_root"],
            port=int(data.get("port", 22)),
            password=data.get("password"),
            key_path=data.get("key_path"),
            diff_threshold=data.get("diff_threshold", 0.30),
        )


@dataclass
class WorkspaceConfig:
    """Manages persistence of workspace definitions in a JSON config file."""

    config_file: Path = field(default_factory=lambda: CONFIG_FILE)
    _workspaces: dict[str, Workspace] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.config_file = Path(self.config_file)
        self._load()

    def _load(self) -> None:
        """Load workspaces from the config file, silently ignore if missing."""
        if not self.config_file.exists():
            self._workspaces = {}
            return
        try:
            raw = json.loads(self.config_file.read_text(encoding="utf-8"))
            self._workspaces = {
                entry["name"]: Workspace.from_dict(entry)
                for entry in raw.get("workspaces", [])
            }
        except (json.JSONDecodeError, KeyError, ValueError):
            self._workspaces = {}

    def save(self) -> None:
        """Persist workspaces to disk, creating the config directory if needed."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "workspaces": [ws.to_dict() for ws in self._workspaces.values()]
        }
        self.config_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, workspace: Workspace) -> None:
        """Add or replace a workspace by name."""
        self._workspaces[workspace.name] = workspace
        self.save()

    def get(self, name: str) -> Optional[Workspace]:
        """Return the workspace with the given name, or None."""
        return self._workspaces.get(name)

    def list(self) -> list[Workspace]:
        """Return all workspaces in insertion order."""
        return list(self._workspaces.values())

    def delete(self, name: str) -> bool:
        """Remove the workspace by name. Return True when deleted, False if not found."""
        if name not in self._workspaces:
            return False
        del self._workspaces[name]
        self.save()
        return True

    def names(self) -> list[str]:
        return list(self._workspaces.keys())
