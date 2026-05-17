"""Beam TUI Application.

Interactive terminal UI built with textual.
Provides screens for workspace selection, file multi-select, deployment, and rollback.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from .config import Workspace, WorkspaceConfig
from .diff import build_local_tree, compute_diff
from .rollback import RollbackSession
from .sftp import SFTPClient, SFTPError


# ---------------------------------------------------------------------------
# Workspace Form Screen (Create + Edit)
# ---------------------------------------------------------------------------


class WorkspaceFormScreen(Screen):
    """Form screen for creating or editing a workspace.

    When *workspace* is None the form is in create mode (blank fields).
    When *workspace* is provided the form is in edit mode (pre-filled fields).
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
        Binding("ctrl+s", "submit", "Save"),
    ]

    CSS = """
    WorkspaceFormScreen {
        layout: vertical;
    }
    #form-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    #form-inner {
        margin: 1 4;
        height: auto;
    }
    .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    .required-label {
        margin-top: 1;
        color: $accent;
    }
    #form-error {
        margin: 0 4;
        color: $error;
        height: auto;
    }
    """

    def __init__(
        self,
        config: WorkspaceConfig,
        workspace: Optional[Workspace] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.workspace = workspace  # None = create mode, set = edit mode
        self._editing_name = workspace.name if workspace else None

    def compose(self) -> ComposeResult:
        ws = self.workspace
        mode = "Edit Workspace" if ws else "Add Workspace"
        yield Header()
        yield Label(f"[bold]{mode}[/]  — [dim]Ctrl+S to save, Esc to cancel[/]", id="form-title")
        yield Static("", id="form-error")
        with Container(id="form-scroll"):
            with Container(id="form-inner"):
                yield Label("Name *", classes="required-label")
                yield Input(
                    value=ws.name if ws else "",
                    placeholder="e.g. production",
                    id="inp-name",
                )
                yield Label("Local root *", classes="required-label")
                yield Input(
                    value=ws.local_root if ws else "",
                    placeholder="/home/me/myproject",
                    id="inp-local-root",
                )
                yield Label("Host *", classes="required-label")
                yield Input(
                    value=ws.host if ws else "",
                    placeholder="server.example.com",
                    id="inp-host",
                )
                yield Label("Port", classes="field-label")
                yield Input(
                    value=str(ws.port) if ws else "22",
                    placeholder="22",
                    id="inp-port",
                )
                yield Label("User *", classes="required-label")
                yield Input(
                    value=ws.user if ws else "",
                    placeholder="deploy",
                    id="inp-user",
                )
                yield Label(
                    "Password  [dim](leave blank if using key)[/]",
                    classes="field-label",
                )
                yield Input(
                    value=ws.password if (ws and ws.password) else "",
                    placeholder="••••••••",
                    password=True,
                    id="inp-password",
                )
                yield Label(
                    "Key path  [dim](leave blank if using password)[/]",
                    classes="field-label",
                )
                yield Input(
                    value=ws.key_path if (ws and ws.key_path) else "",
                    placeholder="~/.ssh/id_rsa",
                    id="inp-key-path",
                )
                yield Label("Remote root *", classes="required-label")
                yield Input(
                    value=ws.remote_root if ws else "",
                    placeholder="/var/www/myproject",
                    id="inp-remote-root",
                )
                yield Label(
                    "Diff threshold  [dim](0.0 – 1.0, default 0.30)[/]",
                    classes="field-label",
                )
                yield Input(
                    value=str(ws.diff_threshold) if ws else "0.30",
                    placeholder="0.30",
                    id="inp-diff-threshold",
                )
        yield Footer()

    def _show_error(self, msg: str) -> None:
        self.query_one("#form-error", Static).update(f"[bold red]Error:[/] {msg}")

    def _clear_error(self) -> None:
        self.query_one("#form-error", Static).update("")

    def _collect_and_validate(self) -> Optional[Workspace]:
        """Read form inputs, validate, and return a Workspace or None on error."""
        name = self.query_one("#inp-name", Input).value.strip()
        local_root = self.query_one("#inp-local-root", Input).value.strip()
        host = self.query_one("#inp-host", Input).value.strip()
        port_str = self.query_one("#inp-port", Input).value.strip()
        user = self.query_one("#inp-user", Input).value.strip()
        password = self.query_one("#inp-password", Input).value.strip() or None
        key_path = self.query_one("#inp-key-path", Input).value.strip() or None
        remote_root = self.query_one("#inp-remote-root", Input).value.strip()
        diff_str = self.query_one("#inp-diff-threshold", Input).value.strip()

        # Required field checks
        if not name:
            self._show_error("Name is required.")
            return None
        if not local_root:
            self._show_error("Local root is required.")
            return None
        if not host:
            self._show_error("Host is required.")
            return None
        if not user:
            self._show_error("User is required.")
            return None
        if not remote_root:
            self._show_error("Remote root is required.")
            return None

        # Auth check
        if not password and not key_path:
            self._show_error("Either password or key path must be provided.")
            return None

        # Port parsing
        try:
            port = int(port_str) if port_str else 22
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            self._show_error("Port must be an integer between 1 and 65535.")
            return None

        # Diff threshold parsing
        try:
            diff_threshold = float(diff_str) if diff_str else 0.30
            if not (0.0 <= diff_threshold <= 1.0):
                raise ValueError
        except ValueError:
            self._show_error("Diff threshold must be a float between 0.0 and 1.0.")
            return None

        # Duplicate name check (only in create mode, or if name was changed)
        if name != self._editing_name:
            existing = self.config.get(name)
            if existing is not None:
                self._show_error(f"A workspace named '{name}' already exists.")
                return None

        try:
            workspace = Workspace(
                name=name,
                local_root=local_root,
                host=host,
                user=user,
                remote_root=remote_root,
                port=port,
                password=password,
                key_path=key_path,
                diff_threshold=diff_threshold,
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return None

        return workspace

    def action_submit(self) -> None:
        """Triggered by Ctrl+S keybinding."""
        self._do_save()

    def _do_save(self) -> None:
        self._clear_error()
        workspace = self._collect_and_validate()
        if workspace is None:
            return

        # If editing and the name changed, remove the old entry first
        if self._editing_name and self._editing_name != workspace.name:
            self.config.delete(self._editing_name)

        self.config.add(workspace)  # add() calls save() internally
        mode = "updated" if self.workspace else "added"
        self.notify(f"Workspace '{workspace.name}' {mode}.", severity="information")
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Delete Confirm Screen
# ---------------------------------------------------------------------------


class DeleteConfirmScreen(Screen):
    """Confirmation dialog before deleting a workspace."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
        Binding("enter", "confirm_delete", "Yes — delete"),
    ]

    CSS = """
    DeleteConfirmScreen {
        layout: vertical;
        align: center middle;
    }
    #confirm-box {
        width: 60;
        height: auto;
        border: round $error;
        padding: 2 4;
        background: $surface;
    }
    """

    def __init__(self, config: WorkspaceConfig, workspace_name: str) -> None:
        super().__init__()
        self.config = config
        self.workspace_name = workspace_name

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="confirm-box"):
            yield Label(
                f"[bold red]Delete workspace?[/]\n\n"
                f"Workspace:  [bold]{self.workspace_name}[/]\n\n"
                f"This cannot be undone.\n\n"
                f"Press [bold]Enter[/] to delete  or  Esc to cancel.",
            )
        yield Footer()

    def action_confirm_delete(self) -> None:
        self._do_delete()

    def _do_delete(self) -> None:
        self.config.delete(self.workspace_name)
        self.notify(
            f"Workspace '{self.workspace_name}' deleted.",
            severity="warning",
        )
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Workspace selection screen
# ---------------------------------------------------------------------------


class WorkspaceScreen(Screen):
    """Screen for listing and selecting a workspace."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+n", "add_workspace", "Add"),
        Binding("ctrl+e", "edit_workspace", "Edit"),
        Binding("ctrl+d", "delete_workspace", "Delete"),
        Binding("enter", "select_workspace", "Open", show=False),
    ]

    CSS = """
    WorkspaceScreen {
        layout: vertical;
    }
    #workspace-list {
        height: 1fr;
        border: round $primary;
        margin: 1 2;
    }
    #workspace-hint {
        margin: 1 2 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, config: WorkspaceConfig, session: RollbackSession) -> None:
        super().__init__()
        self.config = config
        self.session = session

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Select a workspace and press Enter to open it.", id="workspace-hint")
        yield ListView(id="workspace-list")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv: ListView = self.query_one("#workspace-list")
        lv.clear()
        workspaces = self.config.list()
        if not workspaces:
            lv.append(ListItem(Label("  (no workspaces configured — press Ctrl+N to add)")))
            return
        for ws in workspaces:
            auth = f"key: {ws.key_path}" if ws.key_path else "password"
            port_info = f":{ws.port}" if ws.port != 22 else ""
            lv.append(
                ListItem(
                    Label(
                        f"[bold]{ws.name}[/]  "
                        f"{ws.user}@{ws.host}{port_info}:{ws.remote_root}"
                        f"  [{auth}]  local: {ws.local_root}"
                    )
                )
            )

    def on_screen_resume(self) -> None:
        """Refresh the list when returning from a form or delete screen."""
        self._refresh_list()

    @on(ListView.Selected)
    def on_workspace_selected(self, event: ListView.Selected) -> None:
        workspaces = self.config.list()
        idx = event.list_view.index
        if idx is None or idx >= len(workspaces):
            return
        workspace = workspaces[idx]
        self.app.push_screen(FileSelectScreen(workspace, self.session))

    def _get_selected_workspace(self) -> Optional[Workspace]:
        """Return the currently highlighted workspace, or None."""
        lv: ListView = self.query_one("#workspace-list")
        idx = lv.index
        workspaces = self.config.list()
        if idx is None or idx >= len(workspaces):
            return None
        return workspaces[idx]

    def action_select_workspace(self) -> None:
        ws = self._get_selected_workspace()
        if ws is None:
            return
        self.app.push_screen(FileSelectScreen(ws, self.session))

    def action_add_workspace(self) -> None:
        self.app.push_screen(WorkspaceFormScreen(self.config))

    def action_edit_workspace(self) -> None:
        ws = self._get_selected_workspace()
        if ws is None:
            self.notify("Select a workspace to edit.", severity="warning")
            return
        self.app.push_screen(WorkspaceFormScreen(self.config, workspace=ws))

    def action_delete_workspace(self) -> None:
        ws = self._get_selected_workspace()
        if ws is None:
            self.notify("Select a workspace to delete.", severity="warning")
            return
        self.app.push_screen(DeleteConfirmScreen(self.config, ws.name))


# ---------------------------------------------------------------------------
# File selection screen
# ---------------------------------------------------------------------------


class FileSelectScreen(Screen):
    """Screen showing local workspace files with multi-select for deployment."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+d", "deploy_selected", "Deploy"),
        Binding("ctrl+r", "show_rollback", "Rollback"),
        Binding("space", "toggle_selection", "Toggle", show=False),
        Binding("f5", "refresh_files", "Refresh"),
    ]

    CSS = """
    FileSelectScreen {
        layout: vertical;
    }
    #info-bar {
        height: 3;
        margin: 1 2 0 2;
        padding: 0 1;
        background: $surface;
        border: round $primary-darken-2;
    }
    #file-list {
        height: 1fr;
        border: round $primary;
        margin: 1 2;
    }
    """

    def __init__(self, workspace: Workspace, session: RollbackSession) -> None:
        super().__init__()
        self.workspace = workspace
        self.session = session
        self._sftp_client: Optional[SFTPClient] = None
        self._diff_checked = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="info-bar"):
            yield Label(
                f"[bold]{self.workspace.name}[/]  "
                f"{self.workspace.user}@{self.workspace.host}:{self.workspace.remote_root}  "
                f"→ local: {self.workspace.local_root}"
            )
        yield SelectionList(id="file-list")
        yield Footer()

    def on_mount(self) -> None:
        self._connect_and_load()

    @work(thread=True)
    def _connect_and_load(self) -> None:
        """Connect to SFTP and load file list (runs in background thread)."""
        self.app.call_from_thread(
            self.notify, f"Connecting to {self.workspace.host}...", timeout=3
        )
        client = SFTPClient()
        try:
            client.connect(self.workspace)
        except SFTPError as exc:
            self.app.call_from_thread(
                self.notify,
                f"Connection failed: {exc}",
                severity="error",
                timeout=10,
            )
            return

        self._sftp_client = client

        # Directory diff check
        if not self._diff_checked:
            self._diff_checked = True
            self._check_diff()

        self._load_file_list()

    def _check_diff(self) -> None:
        """Compare local vs remote trees; warn if threshold exceeded."""
        assert self._sftp_client is not None
        try:
            remote_paths = self._sftp_client.list_remote_tree(
                self.workspace.remote_root
            )
        except SFTPError:
            remote_paths = []

        local_paths = build_local_tree(self.workspace.local_root)
        diff = compute_diff(local_paths, remote_paths)

        if diff.exceeds_threshold(self.workspace.diff_threshold):
            threshold_pct = int(self.workspace.diff_threshold * 100)
            self.app.call_from_thread(
                self.notify,
                f"[bold yellow]Directory diff warning:[/] {diff.summary()}\n"
                f"Mismatch exceeds {threshold_pct}% threshold. "
                "Review before deploying.",
                severity="warning",
                timeout=15,
            )

    def _load_file_list(self) -> None:
        """Populate the SelectionList with merged local+remote workspace files.

        Each entry is labelled with an indicator:
          [B] — exists in both local and remote
          [L] — local only
          [R] — remote only

        Remote files are fetched via the already-open SFTP connection.
        Falls back to local-only listing when the SFTP client is unavailable.
        """
        local_root = Path(self.workspace.local_root).expanduser().resolve()
        local_set: frozenset[str] = build_local_tree(local_root)

        remote_set: frozenset[str] = frozenset()
        if self._sftp_client is not None:
            try:
                remote_list = self._sftp_client.list_remote_tree(
                    self.workspace.remote_root
                )
                remote_set = frozenset(remote_list)
            except SFTPError:
                pass  # remote listing failed — show local only

        all_paths = sorted(local_set | remote_set)

        selections: list[Selection] = []
        for rel_path in all_paths:
            in_local = rel_path in local_set
            in_remote = rel_path in remote_set
            if in_local and in_remote:
                label = f"[B] {rel_path}"
            elif in_local:
                label = f"[L] {rel_path}"
            else:
                label = f"[R] {rel_path}"
            selections.append(Selection(label, rel_path, initial_state=False))

        self.app.call_from_thread(self._update_file_list, selections)

    def _update_file_list(self, selections: list[Selection]) -> None:
        sl: SelectionList = self.query_one("#file-list")
        sl.clear_options()
        for sel in selections:
            sl.add_option(sel)

    def action_deploy_selected(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        sl: SelectionList = self.query_one("#file-list")
        selected = list(sl.selected)
        if not selected:
            self.notify("No files selected. Use Space to select files.", severity="warning")
            return
        self.app.push_screen(
            DeployScreen(
                workspace=self.workspace,
                sftp_client=self._sftp_client,
                session=self.session,
                selected_paths=selected,
            )
        )

    def action_show_rollback(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        if len(self.session) == 0:
            self.notify("No rollback entries in this session.", severity="information")
            return
        self.app.push_screen(
            RollbackScreen(
                workspace=self.workspace,
                sftp_client=self._sftp_client,
                session=self.session,
            )
        )

    def action_refresh_files(self) -> None:
        self._refresh_file_list_in_thread()

    @work(thread=True)
    def _refresh_file_list_in_thread(self) -> None:
        """Background worker that re-fetches the file list on F5."""
        self._load_file_list()


# ---------------------------------------------------------------------------
# Deploy screen
# ---------------------------------------------------------------------------


class DeployScreen(Screen):
    """Shows deployment progress and results."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back / Done"),
    ]

    CSS = """
    DeployScreen {
        layout: vertical;
    }
    #deploy-info {
        margin: 1 2 0 2;
        color: $text-muted;
    }
    #deploy-log {
        height: 1fr;
        border: round $primary;
        margin: 1 2;
        overflow-y: scroll;
    }
    #deploy-actions {
        height: 3;
        margin: 0 2 1 2;
    }
    """

    def __init__(
        self,
        workspace: Workspace,
        sftp_client: SFTPClient,
        session: RollbackSession,
        selected_paths: list[str],
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.sftp_client = sftp_client
        self.session = session
        self.selected_paths = selected_paths
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            f"Deploying [bold]{len(self.selected_paths)}[/] file(s) to "
            f"[bold]{self.workspace.host}:{self.workspace.remote_root}[/]",
            id="deploy-info",
        )
        yield Static(id="deploy-log")
        with Horizontal(id="deploy-actions"):
            yield Button("Done [esc]", id="btn-done", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self._deploy()

    @work(thread=True)
    def _deploy(self) -> None:
        local_root = Path(self.workspace.local_root).expanduser().resolve()

        for rel_path in self.selected_paths:
            local_abs = str(local_root / rel_path)
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"

            # Snapshot remote file before upload
            self._append_log(f"Snapshotting: {rel_path}")
            try:
                original = self.sftp_client.download_file(remote_abs)
                self.session.snapshot(rel_path, original)
            except SFTPError as exc:
                self._append_log(f"  [yellow]Snapshot warning:[/] {exc}")

            # Upload
            self._append_log(f"Uploading:   {rel_path}")
            try:
                bytes_written = self.sftp_client.upload_file(local_abs, remote_abs)
                self._append_log(f"  [green]OK[/] ({bytes_written} bytes)")
            except SFTPError as exc:
                self._append_log(f"  [red]FAILED:[/] {exc}")

        self._append_log("\n[bold green]Deployment complete.[/]")

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        text = "\n".join(self._log_lines)
        self.app.call_from_thread(self._update_log, text)

    def _update_log(self, text: str) -> None:
        log: Static = self.query_one("#deploy-log")
        log.update(text)

    @on(Button.Pressed, "#btn-done")
    def on_done(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Rollback screen
# ---------------------------------------------------------------------------


class RollbackScreen(Screen):
    """Shows session rollback entries for restoring deployed files."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
        Binding("ctrl+r", "do_rollback", "Rollback selected"),
        Binding("space", "toggle_selection", "Toggle", show=False),
    ]

    CSS = """
    RollbackScreen {
        layout: vertical;
    }
    #rollback-hint {
        margin: 1 2 0 2;
        color: $text-muted;
    }
    #rollback-list {
        height: 1fr;
        border: round $warning;
        margin: 1 2;
    }
    """

    def __init__(
        self,
        workspace: Workspace,
        sftp_client: SFTPClient,
        session: RollbackSession,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.sftp_client = sftp_client
        self.session = session

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            "[bold yellow]Session Rollback[/]  — Space to select, Ctrl+R to restore, Esc to cancel",
            id="rollback-hint",
        )
        yield SelectionList(id="rollback-list")
        yield Footer()

    def on_mount(self) -> None:
        self._load_entries()

    def _load_entries(self) -> None:
        sl: SelectionList = self.query_one("#rollback-list")
        sl.clear_options()
        for entry in self.session.list_entries():
            existed = "existed" if entry.existed_remotely() else "NEW (no prior content)"
            label = f"{entry.rel_path}  [{existed}]  @ {entry.timestamp.strftime('%H:%M:%S')}"
            sl.add_option(Selection(label, entry.rel_path, initial_state=False))

    def action_do_rollback(self) -> None:
        sl: SelectionList = self.query_one("#rollback-list")
        selected_paths = list(sl.selected)
        if not selected_paths:
            self.notify("No files selected for rollback.", severity="warning")
            return
        self._perform_rollback(selected_paths)

    @work(thread=True)
    def _perform_rollback(self, paths: list[str]) -> None:
        messages: list[str] = []
        for rel_path in paths:
            entry = self.session.get_entry(rel_path)
            if entry is None:
                messages.append(f"No snapshot for {rel_path}")
                continue

            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"
            if entry.existed_remotely():
                try:
                    assert entry.original_bytes is not None
                    self.sftp_client.upload_bytes(entry.original_bytes, remote_abs)
                    messages.append(f"Restored: {rel_path}")
                except SFTPError as exc:
                    messages.append(f"Failed {rel_path}: {exc}")
            else:
                # File was new — delete it to roll back
                try:
                    self.sftp_client.delete_remote_file(remote_abs)
                    messages.append(f"Deleted (rollback new file): {rel_path}")
                except SFTPError as exc:
                    messages.append(f"Failed to delete {rel_path}: {exc}")

        summary = "\n".join(messages)
        self.app.call_from_thread(self.notify, f"Rollback complete:\n{summary}", timeout=15)
        self.app.call_from_thread(self._load_entries)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class DeployerApp(App):
    """Root application — initializes config and enters workspace selection."""

    TITLE = "Beam"
    SUB_TITLE = "Terminal SFTP deployment tool"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, config_file: Optional[str] = None) -> None:
        super().__init__()
        from .config import CONFIG_FILE, WorkspaceConfig

        cf = Path(config_file) if config_file else CONFIG_FILE
        self._config = WorkspaceConfig(config_file=cf)
        self._session = RollbackSession()

    def on_mount(self) -> None:
        self.push_screen(WorkspaceScreen(self._config, self._session))


def main() -> None:
    """Entry point for the beam CLI."""
    app = DeployerApp()
    app.run()


if __name__ == "__main__":
    main()
