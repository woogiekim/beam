"""SFTP client wrapper built on top of paramiko.

Provides high-level operations: connect, upload, download, remote-tree listing,
and recursive remote directory creation.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import PurePosixPath
from typing import Optional

import paramiko


class SFTPError(Exception):
    """Raised when an SFTP operation fails."""


class SFTPClient:
    """Manages an authenticated SFTP session to a remote host.

    Usage::

        client = SFTPClient()
        client.connect(workspace)
        client.upload_file("/local/path/to/file.py", "/remote/path/to/file.py")
        data = client.download_file("/remote/path/to/file.py")
        client.disconnect()

    Or as a context manager::

        with SFTPClient() as client:
            client.connect(workspace)
            ...
    """

    def __init__(self) -> None:
        self._ssh: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, workspace) -> None:  # workspace: Workspace (avoid import cycle)
        """Open an SSH connection and start an SFTP session.

        Args:
            workspace: A `Workspace` instance (from config.py).

        Raises:
            SFTPError: On authentication failure or connection error.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs: dict = {
                "hostname": workspace.host,
                "port": getattr(workspace, "port", 22),
                "username": workspace.user,
                "timeout": 15,
            }
            if workspace.key_path:
                connect_kwargs["key_filename"] = workspace.key_path
            else:
                connect_kwargs["password"] = workspace.password

            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as exc:
            raise SFTPError(f"Authentication failed for {workspace.user}@{workspace.host}: {exc}") from exc
        except (paramiko.SSHException, OSError) as exc:
            raise SFTPError(f"Cannot connect to {workspace.host}: {exc}") from exc

        self._ssh = client
        try:
            self._sftp = client.open_sftp()
        except paramiko.SSHException as exc:
            client.close()
            raise SFTPError(f"Cannot open SFTP subsystem: {exc}") from exc

    def disconnect(self) -> None:
        """Close the SFTP session and underlying SSH connection."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None

    def is_connected(self) -> bool:
        return self._sftp is not None

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "SFTPClient":
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def _require_connected(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            raise SFTPError("Not connected. Call connect() first.")
        return self._sftp

    def upload_file(self, local_path: str, remote_path: str) -> int:
        """Upload a local file to remote_path, creating parent directories as needed.

        Returns:
            Number of bytes written.

        Raises:
            SFTPError: On upload failure.
        """
        sftp = self._require_connected()
        remote_dir = str(PurePosixPath(remote_path).parent)
        self.mkdir_p(remote_dir)
        try:
            sftp.put(local_path, remote_path)
            return os.path.getsize(local_path)
        except OSError as exc:
            raise SFTPError(f"Upload failed for {local_path} → {remote_path}: {exc}") from exc

    def download_file(self, remote_path: str) -> Optional[bytes]:
        """Download a remote file and return its content as bytes.

        Returns:
            File content, or None if the file does not exist on the remote.

        Raises:
            SFTPError: On I/O errors other than file-not-found.
        """
        sftp = self._require_connected()
        buf = io.BytesIO()
        try:
            sftp.getfo(remote_path, buf)
            return buf.getvalue()
        except IOError as exc:
            # errno 2 (ENOENT) → file does not exist
            if getattr(exc, "errno", None) == 2 or "No such file" in str(exc):
                return None
            raise SFTPError(f"Download failed for {remote_path}: {exc}") from exc

    def upload_bytes(self, data: bytes, remote_path: str) -> None:
        """Write bytes directly to a remote file (used for rollback restoration)."""
        sftp = self._require_connected()
        remote_dir = str(PurePosixPath(remote_path).parent)
        self.mkdir_p(remote_dir)
        buf = io.BytesIO(data)
        try:
            sftp.putfo(buf, remote_path)
        except OSError as exc:
            raise SFTPError(f"Write failed for {remote_path}: {exc}") from exc

    def delete_remote_file(self, remote_path: str) -> None:
        """Remove a remote file (used when rolling back a newly-created file)."""
        sftp = self._require_connected()
        try:
            sftp.remove(remote_path)
        except IOError:
            pass  # already gone — treat as success

    def mkdir_p(self, remote_dir: str) -> None:
        """Recursively create remote directories, like `mkdir -p`.

        Silently succeeds when the directory already exists.
        """
        sftp = self._require_connected()
        parts = PurePosixPath(remote_dir).parts
        current = ""
        for part in parts:
            current = str(PurePosixPath(current) / part) if current else part
            if current in ("", "/"):
                current = "/"
                continue
            try:
                sftp.stat(current)
            except IOError:
                try:
                    sftp.mkdir(current)
                except IOError:
                    pass  # race: another client created it

    def get_file_size(self, remote_path: str) -> Optional[int]:
        """Return the size in bytes of a remote file, or None on any error."""
        if self._sftp is None:
            return None
        try:
            return self._sftp.stat(remote_path).st_size
        except Exception:
            return None

    def list_remote_tree(self, remote_root: str, max_files: int = 500) -> list[str]:
        """Recursively list files under remote_root as POSIX-relative paths.

        Paths are relative to remote_root (e.g. "src/main.py").
        Hidden files and directories (names starting with ".") are skipped.
        Listing stops when max_files is reached.

        Returns:
            Sorted list of relative POSIX path strings.

        Raises:
            SFTPError: When remote_root does not exist or cannot be listed.
        """
        sftp = self._require_connected()
        results: list[str] = []
        self._walk_remote(sftp, remote_root, remote_root, results, max_files)
        return sorted(results)

    def _walk_remote(
        self,
        sftp: paramiko.SFTPClient,
        root: str,
        current: str,
        results: list[str],
        max_files: int,
    ) -> None:
        if len(results) >= max_files:
            return
        try:
            entries = sftp.listdir_attr(current)
        except IOError as exc:
            raise SFTPError(f"Cannot list remote directory {current}: {exc}") from exc

        for entry in entries:
            if entry.filename.startswith("."):
                continue
            full_path = f"{current}/{entry.filename}".replace("//", "/")
            if stat.S_ISDIR(entry.st_mode or 0):
                self._walk_remote(sftp, root, full_path, results, max_files)
            else:
                # Compute path relative to root
                rel = full_path[len(root):].lstrip("/")
                results.append(rel)
                if len(results) >= max_files:
                    return
