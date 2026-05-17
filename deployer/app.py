"""Deployer TUI Application.

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
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
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
# Workspace selection screen
# ---------------------------------------------------------------------------


class WorkspaceScreen(Screen):
    """Screen for listing and selecting a workspace."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("n", "new_workspace", "New workspace"),
        Binding("d", "delete_workspace", "Delete workspace"),
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
        margin: 0 2 1 2;
        color: $text-muted;
    }
    """

    def __init__(self, config: WorkspaceConfig, session: RollbackSession) -> None:
        super().__init__()
        self.config = config
        self.session = session

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Select a workspace — press [bold]Enter[/] to activate", id="workspace-hint")
        yield ListView(id="workspace-list")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv: ListView = self.query_one("#workspace-list")
        lv.clear()
        workspaces = self.config.list()
        if not workspaces:
            lv.append(ListItem(Label("  (no workspaces configured — press n to add)")))
            return
        for ws in workspaces:
            auth = f"key: {ws.key_path}" if ws.key_path else "password"
            lv.append(
                ListItem(
                    Label(
                        f"[bold]{ws.name}[/]  {ws.user}@{ws.host}:{ws.remote_root}"
                        f"  [{auth}]  local: {ws.local_root}"
                    )
                )
            )

    @on(ListView.Selected)
    def on_workspace_selected(self, event: ListView.Selected) -> None:
        workspaces = self.config.list()
        idx = event.list_view.index
        if idx is None or idx >= len(workspaces):
            return
        workspace = workspaces[idx]
        self.app.push_screen(FileSelectScreen(workspace, self.session))

    def action_new_workspace(self) -> None:
        self.app.push_screen(AddWorkspaceScreen(self.config))

    def action_delete_workspace(self) -> None:
        lv: ListView = self.query_one("#workspace-list")
        idx = lv.index
        workspaces = self.config.list()
        if idx is None or idx >= len(workspaces):
            return
        name = workspaces[idx].name
        self.config.delete(name)
        self._refresh_list()
        self.notify(f"Workspace '{name}' deleted.", severity="warning")


# ---------------------------------------------------------------------------
# Add workspace screen
# ---------------------------------------------------------------------------


class AddWorkspaceScreen(Screen):
    """Simple form to add a new workspace via the terminal (not full TUI form for MVP)."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Cancel")]

    CSS = """
    AddWorkspaceScreen {
        layout: vertical;
    }
    #form-container {
        margin: 2 4;
        height: auto;
    }
    """

    def __init__(self, config: WorkspaceConfig) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="form-container"):
            yield Static(
                "[bold yellow]Add Workspace[/]\n\n"
                "This MVP uses a pre-defined example workspace.\n"
                "Edit [italic]~/.deployer/workspaces.json[/] directly to add custom workspaces.\n\n"
                "Example entry:\n"
                '[dim]{ "name": "prod", "local_root": "/home/dev/myapp",\n'
                '  "host": "server.example.com", "user": "deploy",\n'
                '  "password": "secret", "remote_root": "/var/www/myapp",\n'
                '  "diff_threshold": 0.30 }[/]'
            )
            yield Button("Close", id="btn-close", variant="default")
        yield Footer()

    @on(Button.Pressed, "#btn-close")
    def on_close(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# File selection screen
# ---------------------------------------------------------------------------


class FileSelectScreen(Screen):
    """Screen showing local workspace files with multi-select for deployment."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("d", "deploy_selected", "Deploy selected"),
        Binding("r", "show_rollback", "Rollback"),
        Binding("space", "toggle_selection", "Toggle"),
    ]

    CSS = """
    FileSelectScreen {
        layout: vertical;
    }
    #info-bar {
        height: 3;
        margin: 0 1;
        padding: 0 1;
        background: $surface;
        border: round $primary-darken-2;
    }
    #file-list {
        height: 1fr;
        border: round $primary;
        margin: 0 1;
    }
    #action-bar {
        height: 3;
        layout: horizontal;
        margin: 0 1;
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
        with Horizontal(id="action-bar"):
            yield Button("Deploy selected [d]", id="btn-deploy", variant="primary")
            yield Button("Rollback [r]", id="btn-rollback", variant="warning")
            yield Button("Refresh [f5]", id="btn-refresh", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        self._connect_and_load()

    @work(thread=True)
    def _connect_and_load(self) -> None:
        """Connect to SFTP and load file list (runs in background thread)."""
        self.call_from_thread(
            self.notify, f"Connecting to {self.workspace.host}...", timeout=3
        )
        client = SFTPClient()
        try:
            client.connect(self.workspace)
        except SFTPError as exc:
            self.call_from_thread(
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
            self.call_from_thread(
                self.notify,
                f"[bold yellow]Directory diff warning:[/] {diff.summary()}\n"
                f"Mismatch exceeds {threshold_pct}% threshold. "
                "Review before deploying.",
                severity="warning",
                timeout=15,
            )

    def _load_file_list(self) -> None:
        """Populate the SelectionList with local workspace files."""
        local_root = Path(self.workspace.local_root).expanduser().resolve()
        local_paths = sorted(build_local_tree(local_root))

        selections = [
            Selection(rel_path, rel_path, initial_state=False)
            for rel_path in local_paths
        ]
        self.call_from_thread(self._update_file_list, selections)

    def _update_file_list(self, selections: list[Selection]) -> None:
        sl: SelectionList = self.query_one("#file-list")
        sl.clear_options()
        for sel in selections:
            sl.add_option(sel)

    @on(Button.Pressed, "#btn-deploy")
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

    @on(Button.Pressed, "#btn-rollback")
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

    @on(Button.Pressed, "#btn-refresh")
    def on_refresh(self) -> None:
        self._load_file_list()


# ---------------------------------------------------------------------------
# Deploy screen
# ---------------------------------------------------------------------------


class DeployScreen(Screen):
    """Shows deployment progress and results."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    CSS = """
    DeployScreen {
        layout: vertical;
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
        with Vertical():
            yield Label(
                f"Deploying [bold]{len(self.selected_paths)}[/] file(s) to "
                f"[bold]{self.workspace.host}:{self.workspace.remote_root}[/]"
            )
            yield Static(id="deploy-log")
        with Horizontal(id="deploy-actions"):
            yield Button("Done", id="btn-done", variant="success")
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
        self.call_from_thread(self._update_log, text)

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

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    CSS = """
    RollbackScreen {
        layout: vertical;
    }
    #rollback-list {
        height: 1fr;
        border: round $warning;
        margin: 1 2;
    }
    #rollback-actions {
        height: 3;
        margin: 0 2 1 2;
        layout: horizontal;
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
        yield Label("[bold yellow]Session Rollback[/] — Select files to restore")
        yield SelectionList(id="rollback-list")
        with Horizontal(id="rollback-actions"):
            yield Button("Rollback selected", id="btn-rollback", variant="error")
            yield Button("Cancel", id="btn-cancel", variant="default")
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

    @on(Button.Pressed, "#btn-rollback")
    def on_rollback(self) -> None:
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
        self.call_from_thread(self.notify, f"Rollback complete:\n{summary}", timeout=15)
        self.call_from_thread(self._load_entries)

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class DeployerApp(App):
    """Root application — initializes config and enters workspace selection."""

    TITLE = "Deployer"
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
    """Entry point for the deployer CLI."""
    app = DeployerApp()
    app.run()


if __name__ == "__main__":
    main()
