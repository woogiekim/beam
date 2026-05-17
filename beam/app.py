"""Beam TUI Application.

Interactive terminal UI built with textual.
Provides screens for workspace selection, file multi-select, deployment, and rollback.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Callable, Optional


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size:>6} B  "
    if size < 1024 * 1024:
        return f"{size/1024:>5.1f} KB "
    return f"{size/1024/1024:>5.1f} MB "


def _fmt_date(mtime: float) -> str:
    if not mtime:
        return "           "
    return datetime.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")


from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from .config import Workspace, WorkspaceConfig
from .diff import build_local_tree, compute_diff
from .rollback import RollbackSession
from .sftp import SFTPClient, SFTPError


# ---------------------------------------------------------------------------
# Shared color tokens
# ---------------------------------------------------------------------------
#
#  Background layers
#    VOID      #020207   deepest background — space black
#    SURFACE   #07070f   panel / widget surface
#    RAISED    #0d0d1c   slightly raised surface (input fields, inner boxes)
#
#  Accent palette
#    CYAN      #00ffff   primary accent — pure electric cyan
#    MAGENTA   #ff00ff   secondary accent — hot magenta
#    GREEN     #39ff14   success / neon green
#    AMBER     #ff9500   warning / warm amber
#    RED       #ff0040   danger / hot red
#
#  Text
#    TEXT_HI   #d0e8f8   primary text (cool white-blue)
#    TEXT_MID  #6080a0   secondary / muted text
#    TEXT_LO   #2a3a4a   very dim (disabled, placeholders)
#
# ---------------------------------------------------------------------------


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
        Binding("ctrl+s", "submit", "Save", priority=True),
    ]

    CSS = """
    WorkspaceFormScreen {
        layout: vertical;
        background: #020207;
    }
    #form-title {
        margin: 1 2 0 2;
        color: #00ffff;
    }
    #form-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    #form-inner {
        margin: 1 4;
        height: auto;
        background: #07070f;
        border: heavy #00ffff;
        border-title-color: #00ffff;
        border-title-style: bold;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
        color: #6080a0;
    }
    .required-label {
        margin-top: 1;
        color: #00ffff;
    }
    #form-error {
        margin: 0 4;
        color: #ff0040;
        height: auto;
    }
    Input {
        background: #0d0d1c;
        border: round #2a3a4a;
        color: #d0e8f8;
    }
    Input:focus {
        border: round #00ffff;
        color: #ffffff;
    }
    Input.-invalid {
        border: round #ff0040;
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
        yield Label(
            f"[bold bright_cyan]{mode}[/]  [dim]Ctrl+S save  ·  Esc cancel[/]",
            id="form-title",
        )
        yield Static("", id="form-error")
        with Container(id="form-scroll"):
            with Container(id="form-inner"):
                yield Label("Name [bold bright_cyan]*[/]", classes="required-label")
                yield Input(
                    value=ws.name if ws else "",
                    placeholder="e.g. production",
                    id="inp-name",
                )
                yield Label("Local root [bold bright_cyan]*[/]", classes="required-label")
                yield Input(
                    value=ws.local_root if ws else "",
                    placeholder="/home/me/myproject",
                    id="inp-local-root",
                )
                yield Label("Host [bold bright_cyan]*[/]", classes="required-label")
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
                yield Label("User [bold bright_cyan]*[/]", classes="required-label")
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
                yield Label("Remote root [bold bright_cyan]*[/]", classes="required-label")
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
        self.query_one("#form-error", Static).update(
            f"[bold bright_red]  ERROR:[/] {msg}"
        )

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
        self.notify(
            f"Workspace [bold bright_cyan]{workspace.name}[/] {mode}.",
            severity="information",
        )
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Delete Confirm Screen
# ---------------------------------------------------------------------------


class DeleteConfirmScreen(Screen):
    """Confirmation dialog before deleting a workspace."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
        Binding("enter", "confirm_delete", "Yes — delete", priority=True),
    ]

    CSS = """
    DeleteConfirmScreen {
        layout: vertical;
        align: center middle;
        background: #020207;
    }
    #confirm-box {
        width: 64;
        height: auto;
        border: heavy #ff0040;
        border-title-color: #ff0040;
        border-title-style: bold;
        padding: 2 4;
        background: #0d0007;
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
                f"[bold bright_red]  DELETE WORKSPACE[/]\n\n"
                f"  Name:  [bold bright_cyan]{self.workspace_name}[/]\n\n"
                f"  [dim]This action cannot be undone.[/]\n\n"
                f"  [bold]Enter[/] to confirm  ·  [bold]Esc[/] to cancel",
            )
        yield Footer()

    def action_confirm_delete(self) -> None:
        self._do_delete()

    def _do_delete(self) -> None:
        self.config.delete(self.workspace_name)
        self.notify(
            f"Workspace [bold]{self.workspace_name}[/] deleted.",
            severity="warning",
        )
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Generic remote-action confirmation screen
# ---------------------------------------------------------------------------


class ConfirmScreen(Screen):
    """Generic confirmation dialog before executing a remote-affecting action.

    Shows a title and a body message, then waits for Enter (confirm) or Esc
    (cancel).  On confirmation the *on_confirm* callable is invoked and the
    screen is dismissed.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "confirm", "Confirm", priority=True),
    ]

    CSS = """
    ConfirmScreen {
        layout: vertical;
        align: center middle;
        background: #0a0a0f;
    }
    #remote-confirm-box {
        width: 70;
        height: auto;
        border: round #ff3355;
        padding: 2 4;
        background: #0f0f1a;
    }
    #remote-confirm-title {
        color: #ff3355;
        text-style: bold;
        margin-bottom: 1;
    }
    #remote-confirm-body {
        color: #c8d8e8;
        margin-bottom: 1;
    }
    #remote-confirm-hint {
        color: #4a5a6a;
    }
    """

    def __init__(self, title: str, message: str, on_confirm: "Callable[[], None]") -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="remote-confirm-box"):
            yield Label(self._title, id="remote-confirm-title")
            yield Label(self._message, id="remote-confirm-body")
            yield Label(
                "Press [bold]Enter[/] to confirm  or  [bold]Esc[/] to cancel.",
                id="remote-confirm-hint",
            )
        yield Footer()

    def action_confirm(self) -> None:
        self.app.pop_screen()
        self._on_confirm()

    def action_cancel(self) -> None:
        self.app.pop_screen()


# ---------------------------------------------------------------------------
# Workspace selection screen
# ---------------------------------------------------------------------------


class WorkspaceScreen(Screen):
    """Screen for listing and selecting a workspace."""

    BINDINGS = [
        Binding("ctrl+n", "add_workspace", "Add", priority=True),
        Binding("ctrl+e", "edit_workspace", "Edit", priority=True),
        Binding("ctrl+d", "delete_workspace", "Delete", priority=True),
        Binding("enter", "select_workspace", "Open", show=False),
    ]

    CSS = """
    WorkspaceScreen {
        layout: vertical;
        background: #020207;
    }
    #workspace-header {
        height: 3;
        margin: 1 2 0 2;
        padding: 0 2;
        background: #07070f;
        border: heavy #00ffff;
        border-title-color: #00ffff;
        border-title-style: bold;
        color: #d0e8f8;
        content-align: left middle;
    }
    #workspace-list {
        height: 1fr;
        border: round #00ffff;
        margin: 1 2;
        background: #07070f;
    }
    #workspace-hint {
        margin: 0 2 1 2;
        color: #6080a0;
        height: 1;
    }
    """

    def __init__(self, config: WorkspaceConfig, session: RollbackSession) -> None:
        super().__init__()
        self.config = config
        self.session = session

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "[bold bright_cyan]WORKSPACES[/]  "
            "[dim]Ctrl+N add  ·  Ctrl+E edit  ·  Ctrl+D delete  ·  Enter open[/]",
            id="workspace-header",
        )
        yield ListView(id="workspace-list")
        yield Static(
            "[dim]Select a workspace and press [bold]Enter[/] to connect[/]",
            id="workspace-hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv: ListView = self.query_one("#workspace-list")
        lv.clear()
        workspaces = self.config.list()
        if not workspaces:
            lv.append(
                ListItem(
                    Label(
                        "  [dim](no workspaces configured — press [bold bright_cyan]Ctrl+N[/] to add)[/]"
                    )
                )
            )
            return
        for ws in workspaces:
            auth = f"key: {ws.key_path}" if ws.key_path else "password"
            port_info = f":{ws.port}" if ws.port != 22 else ""
            lv.append(
                ListItem(
                    Label(
                        f"  [bold bright_cyan]{ws.name}[/]"
                        f"  [dim]║[/]  "
                        f"[bright_white]{ws.user}@{ws.host}{port_info}[/]"
                        f"  [dim]→[/]  [#6080a0]{ws.remote_root}[/]"
                        f"  [dim]·  local: {ws.local_root}  ·  {auth}[/]"
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

# Diff tag styles — used in _build_tree_selections
_DIFF_TAG_NEW      = "[bold bright_green][+][/]"  # new local file
_DIFF_TAG_MATCH    = "[dim][=][/]"                # same size as remote
_DIFF_TAG_MODIFIED = "[bold bright_yellow][M][/]"  # different size from remote


class FileSelectScreen(Screen):
    """Screen showing local and remote workspace files in a side-by-side split."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+d", "deploy_selected", "Deploy", priority=True),
        Binding("ctrl+x", "delete_remote_selected", "Delete Remote", priority=True),
        Binding("ctrl+r", "show_rollback", "Rollback", priority=True),
        Binding("space", "toggle_selection", "Toggle", show=False),
        Binding("f5", "refresh_files", "Refresh", priority=True),
        Binding("ctrl+a", "toggle_all_selection", "Sel All/None", priority=True),
    ]

    CSS = """
    FileSelectScreen {
        layout: vertical;
        background: #020207;
    }

    /* ── Top info bar ─────────────────────────────────────────── */
    #info-bar {
        height: 3;
        margin: 1 2 0 2;
        padding: 0 2;
        background: #07070f;
        border: heavy #00ffff;
        border-title-color: #00ffff;
        border-title-style: bold;
        color: #d0e8f8;
        content-align: left middle;
    }

    /* ── Status bar (connection + selection state) ────────────── */
    #status-bar {
        height: 1;
        margin: 0 2;
        padding: 0 2;
        background: #07070f;
        color: #6080a0;
    }

    /* ── Side-by-side file panels ─────────────────────────────── */
    #panels {
        height: 1fr;
        margin: 1 2 0 2;
    }
    #local-panel {
        width: 1fr;
        border: heavy #00ffff;
        border-title-color: #00ffff;
        border-title-style: bold;
        background: #07070f;
    }
    #remote-panel {
        width: 1fr;
        border: heavy #ff00ff;
        border-title-color: #ff00ff;
        border-title-style: bold;
        margin-left: 1;
        background: #07070f;
    }
    .panel-header {
        height: 2;
        background: #020207;
        color: #d0e8f8;
        padding: 0 2;
        content-align: left middle;
    }
    #local-list {
        height: 1fr;
    }
    #remote-list {
        height: 1fr;
    }

    /* ── Deploy log panel ─────────────────────────────────────── */
    #deploy-log {
        height: 9;
        border: double #39ff14;
        border-title-color: #39ff14;
        border-title-style: bold;
        margin: 1 2 0 2;
        overflow-y: scroll;
        background: #020a02;
        color: #39ff14;
        padding: 0 1;
        display: none;
    }

    /* ── Loading indicator (shown during SFTP ops) ────────────── */
    #loading-indicator {
        height: 1;
        margin: 0 2;
        display: none;
    }

    /* ── Rollback panel ───────────────────────────────────────── */
    #rollback-panel {
        height: 12;
        border: heavy #ff9500;
        border-title-color: #ff9500;
        border-title-style: bold;
        margin: 1 2 1 2;
        background: #0a0600;
        display: none;
    }
    #rollback-list {
        height: 1fr;
    }
    #rollback-result {
        height: 3;
        background: #050300;
        color: #ff9500;
        overflow-y: scroll;
        border-top: solid #2a1800;
        padding: 0 1;
    }
    """

    # Connection state labels — shown in status bar
    _CONN_IDLE        = "[dim]○  not connected[/]"
    _CONN_CONNECTING  = "[bold bright_cyan]◌  connecting...[/]"
    _CONN_CONNECTED   = "[bold bright_green]●  connected[/]"
    _CONN_ERROR       = "[bold bright_red]✗  connection error[/]"
    _CONN_LOADING     = "[bold bright_cyan]⟳  loading files...[/]"

    def __init__(self, workspace: Workspace, session: RollbackSession) -> None:
        super().__init__()
        self.workspace = workspace
        self.session = session
        self._sftp_client: Optional[SFTPClient] = None
        self._diff_checked = False
        self._deploy_log_lines: list[str] = []
        self._rollback_log_lines: list[str] = []
        self._rollback_panel_visible = False
        self._conn_state = self._CONN_IDLE
        self._selected_count = 0
        self._total_count = 0

    def compose(self) -> ComposeResult:
        ws = self.workspace
        port_info = f":{ws.port}" if ws.port != 22 else ""
        yield Header()
        # Connection info bar
        yield Static(
            f"[bold bright_cyan]{ws.name}[/]"
            f"  [dim]║[/]  "
            f"[bright_white]{ws.user}@{ws.host}{port_info}[/]"
            f"  [dim]→[/]  [#6080a0]{ws.remote_root}[/]"
            f"  [dim]·  local: {ws.local_root}[/]",
            id="info-bar",
        )
        # Status bar
        yield Static(self._CONN_IDLE, id="status-bar")
        # File panels
        with Horizontal(id="panels"):
            with Container(id="local-panel"):
                yield Label(
                    "[bold bright_cyan]  LOCAL[/]"
                    "  [dim]Space select  ·  Ctrl+A all/none  ·  Ctrl+D deploy[/]",
                    classes="panel-header",
                )
                yield SelectionList(id="local-list")
            with Container(id="remote-panel"):
                yield Label(
                    "[bold bright_magenta]  REMOTE[/]"
                    "  [dim]Space select  ·  Ctrl+X delete[/]",
                    classes="panel-header",
                )
                yield SelectionList(id="remote-list")
        # Loading indicator
        yield LoadingIndicator(id="loading-indicator")
        # Deploy log
        yield Static(id="deploy-log")
        # Rollback panel
        with Container(id="rollback-panel"):
            yield Label(
                "[bold bright_yellow]  ROLLBACK[/]  "
                "[dim]Space select  ·  Ctrl+R restore  ·  Esc close[/]",
                classes="panel-header",
            )
            yield SelectionList(id="rollback-list")
            yield Static(id="rollback-result")
        yield Footer()

    def on_mount(self) -> None:
        self._set_conn_state(self._CONN_CONNECTING)
        self._connect_and_load()

    def _set_conn_state(self, state: str) -> None:
        """Update the status bar with a new connection state message."""
        self._conn_state = state
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        """Redraw the status bar with current state + selection count."""
        sel_info = ""
        if self._total_count > 0:
            sel_info = (
                f"  [dim]║[/]  "
                f"[bold bright_cyan]{self._selected_count}[/]"
                f"[dim] / {self._total_count} selected[/]"
            )
        try:
            self.query_one("#status-bar", Static).update(
                f"  {self._conn_state}{sel_info}"
            )
        except Exception:
            pass

    def _show_loading(self, visible: bool) -> None:
        """Show or hide the loading indicator."""
        try:
            indicator = self.query_one("#loading-indicator", LoadingIndicator)
            indicator.display = visible
        except Exception:
            pass

    @work(thread=True)
    def _connect_and_load(self) -> None:
        """Connect to SFTP and load file lists (runs in background thread)."""
        self.app.call_from_thread(self._show_loading, True)
        client = SFTPClient()
        try:
            client.connect(self.workspace)
        except SFTPError as exc:
            self.app.call_from_thread(self._show_loading, False)
            self.app.call_from_thread(self._set_conn_state, self._CONN_ERROR)
            self.app.call_from_thread(
                self.notify,
                f"[bold bright_red]Connection failed:[/] {exc}",
                severity="error",
                timeout=10,
            )
            return

        self._sftp_client = client
        self.app.call_from_thread(self._set_conn_state, self._CONN_LOADING)

        if not self._diff_checked:
            self._diff_checked = True
            self._check_diff()

        self._load_file_lists()
        self.app.call_from_thread(self._show_loading, False)
        self.app.call_from_thread(self._set_conn_state, self._CONN_CONNECTED)

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
                f"[bold bright_yellow]  Directory diff warning:[/] {diff.summary()}\n"
                f"  Mismatch exceeds [bold]{threshold_pct}%[/] threshold. "
                "Review before deploying.",
                severity="warning",
                timeout=15,
            )

    def _load_file_lists(self) -> None:
        """Populate local and remote SelectionLists as tree views with file stats."""
        local_root = Path(self.workspace.local_root).expanduser().resolve()
        local_set: frozenset[str] = build_local_tree(local_root)

        # Collect empty local directories (dirs that exist but have no file descendants)
        empty_local_dirs: set[str] = set()
        try:
            for dirpath, dirnames, filenames in os.walk(local_root):
                # Skip hidden directories
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                # Compute the relative path of this directory
                abs_dir = Path(dirpath)
                try:
                    rel_dir = abs_dir.relative_to(local_root).as_posix()
                except ValueError:
                    continue
                if rel_dir == ".":
                    continue
                # A directory is empty if none of its descendants appear in local_set
                prefix = rel_dir + "/"
                has_descendants = any(
                    p == rel_dir or p.startswith(prefix) for p in local_set
                )
                if not has_descendants:
                    empty_local_dirs.add(rel_dir)
        except OSError:
            pass

        remote_stats: dict[str, tuple[int, float]] = {}
        empty_remote_dirs: frozenset[str] = frozenset()
        if self._sftp_client is not None:
            try:
                remote_stats = self._sftp_client.list_remote_tree_with_stats(
                    self.workspace.remote_root
                )
                empty_remote_dirs = self._sftp_client.list_remote_empty_dirs(
                    self.workspace.remote_root
                )
            except SFTPError:
                pass
        remote_set = frozenset(remote_stats.keys())

        # Collect local stats
        local_stats: dict[str, tuple[int, float]] = {}
        for rel_path in local_set:
            try:
                st = os.stat(local_root / rel_path)
                local_stats[rel_path] = (st.st_size, st.st_mtime)
            except OSError:
                local_stats[rel_path] = (0, 0.0)

        local_selections = self._build_tree_selections(
            paths=sorted(local_set),
            stats=local_stats,
            remote_stats=remote_stats,
            remote_set=remote_set,
            show_diff=True,
            empty_dirs=frozenset(empty_local_dirs),
        )
        remote_selections = self._build_tree_selections(
            paths=sorted(remote_set),
            stats=remote_stats,
            remote_stats={},
            remote_set=frozenset(),
            show_diff=False,
            empty_dirs=empty_remote_dirs,
        )

        self.app.call_from_thread(self._update_local_list, local_selections)
        self.app.call_from_thread(self._update_remote_list, remote_selections)
        # Update total count for status bar
        selectable = sum(
            1
            for s in local_selections
            if not getattr(s, "disabled", False)
            and not str(getattr(s, "value", "")).startswith("__dir__:")
        )
        self._total_count = selectable
        self.app.call_from_thread(self._update_status_bar)

    def _build_tree_selections(
        self,
        paths: list[str],
        stats: dict[str, tuple[int, float]],
        remote_stats: dict[str, tuple[int, float]],
        remote_set: frozenset[str],
        show_diff: bool,
        empty_dirs: frozenset[str] = frozenset(),
    ) -> list[Selection]:
        entries: list[Selection] = []
        seen_dirs: set[str] = set()

        for rel_path in sorted(paths):
            parts = rel_path.split("/")

            # Directory headers (disabled — navigate past, not selectable)
            for depth in range(len(parts) - 1):
                dir_path = "/".join(parts[: depth + 1])
                if dir_path not in seen_dirs:
                    seen_dirs.add(dir_path)
                    indent = "  " * depth
                    entries.append(
                        Selection(
                            f"{indent}[bold #6080a0]  {parts[depth]}/[/]",
                            f"__dir__:{dir_path}",
                            initial_state=False,
                            disabled=True,
                        )
                    )

            # File entry
            indent = "  " * (len(parts) - 1)
            filename = parts[-1]
            size, mtime = stats.get(rel_path, (0, 0.0))
            size_str = _fmt_size(size)
            date_str = _fmt_date(mtime)

            if show_diff:
                if rel_path not in remote_set:
                    tag = _DIFF_TAG_NEW
                else:
                    r_size = remote_stats.get(rel_path, (None,))[0]
                    tag = _DIFF_TAG_MATCH if r_size == size else _DIFF_TAG_MODIFIED
                label = f"{indent}{tag} [#d0e8f8]{filename}[/]  [dim]{size_str} {date_str}[/]"
            else:
                label = f"{indent}[#d0e8f8]{filename}[/]  [dim]{size_str} {date_str}[/]"

            entries.append(Selection(label, rel_path, initial_state=False))

        # Add empty directory entries that haven't already been added as headers
        for dir_path in sorted(empty_dirs):
            if dir_path in seen_dirs:
                continue
            seen_dirs.add(dir_path)
            parts = dir_path.split("/")
            dirname = parts[-1]
            depth = len(parts) - 1
            indent = "  " * depth
            entries.append(
                Selection(
                    f"{indent}[bold #6080a0]  {dirname}/[/]",
                    f"__dir__:{dir_path}",
                    initial_state=False,
                    disabled=True,
                )
            )

        return entries

    def _update_local_list(self, selections: list[Selection]) -> None:
        sl: SelectionList = self.query_one("#local-list")
        sl.clear_options()
        for sel in selections:
            sl.add_option(sel)

    def _update_remote_list(self, selections: list[Selection]) -> None:
        sl: SelectionList = self.query_one("#remote-list")
        sl.clear_options()
        for sel in selections:
            sl.add_option(sel)

    def action_delete_remote_selected(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        sl: SelectionList = self.query_one("#remote-list")
        selected = [v for v in sl.selected if not str(v).startswith("__dir__:")]
        if not selected:
            self.notify(
                "No remote files selected. Use [bold]Space[/] to select files.",
                severity="warning",
            )
            return
        # Show confirmation before deleting remote files
        file_list = ", ".join(str(v) for v in selected[:3])
        if len(selected) > 3:
            file_list += f", … (+{len(selected) - 3} more)"
        message = (
            f"Permanently delete [bold]{len(selected)}[/] remote file(s) from "
            f"[bold]{self.workspace.host}:{self.workspace.remote_root}[/]?\n\n"
            f"Files: {file_list}\n\n"
            f"[bold red]This cannot be undone.[/]"
        )
        self.app.push_screen(
            ConfirmScreen("Delete remote files", message, lambda: self._run_delete_remote(selected))
        )

    @work(thread=True)
    def _run_delete_remote(self, rel_paths: list[str]) -> None:
        assert self._sftp_client is not None
        self.app.call_from_thread(self._show_loading, True)
        results: list[str] = []
        for rel_path in rel_paths:
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"
            try:
                self._sftp_client.delete_remote_file(remote_abs)
                results.append(f"[bright_green]  Deleted:[/] {rel_path}")
            except SFTPError as exc:
                results.append(f"[bright_red]  Failed  {rel_path}:[/] {exc}")
        summary = "\n".join(results)
        self.app.call_from_thread(self._show_loading, False)
        self.app.call_from_thread(
            self.notify, f"Remote delete complete:\n{summary}", timeout=10
        )
        self._load_file_lists()

    @on(SelectionList.SelectionHighlighted, "#local-list")
    def on_local_highlighted(self, event: SelectionList.SelectionHighlighted) -> None:
        sel = event.selection
        if sel is None:
            return
        val = str(sel.value)
        if val.startswith("__dir__:"):
            return
        remote_sl: SelectionList = self.query_one("#remote-list")
        for i, opt in enumerate(remote_sl._options):  # type: ignore[attr-defined]
            if hasattr(opt, "value") and str(opt.value) == val:
                remote_sl.highlighted = i
                break

    @on(SelectionList.SelectionChanged, "#local-list")
    def on_local_selection_changed(
        self, event: SelectionList.SelectionChanged
    ) -> None:
        """Update selected count in status bar."""
        sl = self.query_one("#local-list", SelectionList)
        self._selected_count = sum(
            1
            for v in sl.selected
            if v is not None and not str(v).startswith("__dir__:")
        )
        self._update_status_bar()

    def action_toggle_selection(self) -> None:
        """Space: toggle the highlighted item, but never toggle directory headers."""
        sl = self.focused
        if not isinstance(sl, SelectionList):
            return
        highlighted = sl.highlighted
        if highlighted is None:
            return
        try:
            opt = sl.get_option_at_index(highlighted)
        except Exception:
            return
        val = getattr(opt, 'value', None)
        if val is not None and str(val).startswith('__dir__:'):
            return  # Do not toggle directory headers
        if getattr(opt, 'disabled', False):
            return  # Do not toggle disabled entries in general
        sl.toggle(opt)

    def action_toggle_all_selection(self) -> None:
        """Ctrl+A: select all files if any unselected, deselect all if all selected."""
        sl: SelectionList = self.query_one("#local-list")
        selectable_values = [
            o.value for o in sl._options  # type: ignore[attr-defined]
            if not getattr(o, "disabled", False)
            and hasattr(o, "value")
            and o.value is not None
            and not str(o.value).startswith("__dir__:")
        ]
        selected_values = {
            v for v in sl.selected
            if v is not None and not str(v).startswith("__dir__:")
        }
        if selectable_values and selected_values == set(selectable_values):
            sl.deselect_all()
        else:
            for val in selectable_values:
                sl.select(val)

    def action_deploy_selected(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        sl: SelectionList = self.query_one("#local-list")
        selected = list(sl.selected)
        if not selected:
            self.notify(
                "No files selected. Use [bold]Space[/] to select files.",
                severity="warning",
            )
            return
        # Show confirmation before deploying
        file_list = ", ".join(selected[:3])
        if len(selected) > 3:
            file_list += f", … (+{len(selected) - 3} more)"
        message = (
            f"Deploy [bold]{len(selected)}[/] file(s) to "
            f"[bold]{self.workspace.host}:{self.workspace.remote_root}[/]?\n\n"
            f"Files: {file_list}"
        )

        def _do_deploy() -> None:
            self._deploy_log_lines = []
            log_widget: Static = self.query_one("#deploy-log")
            log_widget.update("")
            log_widget.display = True
            self._run_deploy(selected)

        self.app.push_screen(ConfirmScreen("Deploy to remote", message, _do_deploy))

    def _append_deploy_log(self, line: str) -> None:
        self._deploy_log_lines.append(line)
        text = "\n".join(self._deploy_log_lines)
        log_widget: Static = self.query_one("#deploy-log")
        log_widget.update(text)

    @work(thread=True)
    def _run_deploy(self, selected_paths: list[str]) -> None:
        """Upload selected files inline, appending progress to the deploy-log panel."""
        assert self._sftp_client is not None
        local_root = Path(self.workspace.local_root).expanduser().resolve()
        self.app.call_from_thread(self._show_loading, True)
        self.app.call_from_thread(
            self._append_deploy_log,
            f"[bold bright_cyan]  DEPLOY[/]  {len(selected_paths)} file(s)  "
            f"[dim]→ {self.workspace.remote_root}[/]",
        )
        self.app.call_from_thread(self._append_deploy_log, "")

        for rel_path in selected_paths:
            local_abs = str(local_root / rel_path)
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"

            self.app.call_from_thread(
                self._append_deploy_log,
                f"  [dim]snapshot[/] {rel_path}",
            )
            try:
                original = self._sftp_client.download_file(remote_abs)
                self.session.snapshot(rel_path, original)
            except SFTPError as exc:
                self.app.call_from_thread(
                    self._append_deploy_log,
                    f"  [bright_yellow]  snapshot warn:[/] {exc}",
                )

            self.app.call_from_thread(
                self._append_deploy_log,
                f"  [bright_cyan]  upload  [/] {rel_path}",
            )
            try:
                bytes_written = self._sftp_client.upload_file(local_abs, remote_abs)
                self.app.call_from_thread(
                    self._append_deploy_log,
                    f"  [bold bright_green]  OK[/] [dim]{bytes_written:,} bytes[/]",
                )
            except SFTPError as exc:
                self.app.call_from_thread(
                    self._append_deploy_log,
                    f"  [bold bright_red]  FAILED:[/] {exc}",
                )

        self.app.call_from_thread(
            self._append_deploy_log,
            f"\n[bold bright_green]  DEPLOYMENT COMPLETE[/]",
        )
        self.app.call_from_thread(self._show_loading, False)
        self._load_file_lists()

    def action_back(self) -> None:
        if self._rollback_panel_visible:
            self.query_one("#rollback-panel").display = False
            self._rollback_panel_visible = False
        else:
            self.app.pop_screen()

    def action_show_rollback(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        if len(self.session) == 0:
            self.notify("No rollback entries in this session.", severity="information")
            return

        if not self._rollback_panel_visible:
            self.query_one("#rollback-panel").display = True
            self._rollback_panel_visible = True
            self._populate_rollback_list()
            self.query_one("#rollback-list", SelectionList).focus()
        else:
            sl: SelectionList = self.query_one("#rollback-list")
            selected = list(sl.selected)
            if not selected:
                self.query_one("#rollback-panel").display = False
                self._rollback_panel_visible = False
            else:
                # Show confirmation before rolling back
                file_list = ", ".join(selected[:3])
                if len(selected) > 3:
                    file_list += f", … (+{len(selected) - 3} more)"
                message = (
                    f"Restore [bold]{len(selected)}[/] file(s) on "
                    f"[bold]{self.workspace.host}:{self.workspace.remote_root}[/] "
                    f"to their pre-deploy snapshots?\n\n"
                    f"Files: {file_list}"
                )

                def _do_rollback() -> None:
                    self._rollback_log_lines = []
                    self.query_one("#rollback-result", Static).update("")
                    self._run_rollback(selected)

                self.app.push_screen(ConfirmScreen("Rollback remote files", message, _do_rollback))

    def _populate_rollback_list(self) -> None:
        sl: SelectionList = self.query_one("#rollback-list")
        sl.clear_options()
        for entry in self.session.list_entries():
            existed = "[dim]existed[/]" if entry.existed_remotely() else "[bold bright_green]NEW[/]"
            label = (
                f"  [bright_yellow]{entry.rel_path}[/]"
                f"  [{existed}]"
                f"  [dim]@ {entry.timestamp.strftime('%H:%M:%S')}[/]"
            )
            sl.add_option(Selection(label, entry.rel_path, initial_state=False))
        self.query_one("#rollback-result", Static).update("")

    def _append_rollback_log(self, line: str) -> None:
        self._rollback_log_lines.append(line)
        self.query_one("#rollback-result", Static).update(
            "\n".join(self._rollback_log_lines)
        )

    @work(thread=True)
    def _run_rollback(self, paths: list[str]) -> None:
        assert self._sftp_client is not None
        self.app.call_from_thread(self._show_loading, True)
        for rel_path in paths:
            entry = self.session.get_entry(rel_path)
            if entry is None:
                self.app.call_from_thread(
                    self._append_rollback_log,
                    f"[bright_red]  No snapshot:[/] {rel_path}",
                )
                continue
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"
            if entry.existed_remotely():
                try:
                    assert entry.original_bytes is not None
                    self._sftp_client.upload_bytes(entry.original_bytes, remote_abs)
                    self.app.call_from_thread(
                        self._append_rollback_log,
                        f"[bold bright_green]  Restored:[/] {rel_path}",
                    )
                except SFTPError as exc:
                    self.app.call_from_thread(
                        self._append_rollback_log,
                        f"[bold bright_red]  Failed {rel_path}:[/] {exc}",
                    )
            else:
                try:
                    self._sftp_client.delete_remote_file(remote_abs)
                    self.app.call_from_thread(
                        self._append_rollback_log,
                        f"[bold bright_yellow]  Deleted (new file rollback):[/] {rel_path}",
                    )
                except SFTPError as exc:
                    self.app.call_from_thread(
                        self._append_rollback_log,
                        f"[bold bright_red]  Failed to delete {rel_path}:[/] {exc}",
                    )
        self.app.call_from_thread(
            self._append_rollback_log,
            f"\n[bold bright_yellow]  ROLLBACK COMPLETE[/]",
        )
        self.app.call_from_thread(self._show_loading, False)
        self.app.call_from_thread(self._populate_rollback_list)
        self._load_file_lists()

    def action_refresh_files(self) -> None:
        self._set_conn_state(self._CONN_LOADING)
        self._refresh_file_lists_in_thread()

    @work(thread=True)
    def _refresh_file_lists_in_thread(self) -> None:
        """Background worker that re-fetches both file lists on F5."""
        self.app.call_from_thread(self._show_loading, True)
        self._load_file_lists()
        self.app.call_from_thread(self._show_loading, False)
        self.app.call_from_thread(self._set_conn_state, self._CONN_CONNECTED)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class DeployerApp(App):
    """Root application — initializes config and enters workspace selection."""

    TITLE = "Beam"
    SUB_TITLE = "Terminal SFTP deployment tool"

    CSS = """
    Screen {
        background: #020207;
    }
    Header {
        background: #07070f;
        color: #00ffff;
        text-style: bold;
    }
    Footer {
        background: #07070f;
        color: #6080a0;
    }
    Footer > .footer--key {
        background: #0d0d1c;
        color: #00ffff;
    }
    Footer > .footer--description {
        color: #6080a0;
    }
    SelectionList > .option-list--option-highlighted {
        background: #0d1a2a;
        color: #00ffff;
    }
    SelectionList > .option-list--option-selected {
        color: #39ff14;
    }
    SelectionList > .option-list--option-selected-highlighted {
        background: #0d1a2a;
        color: #39ff14;
    }
    ListView > ListItem.--highlight {
        background: #0d1a2a;
    }
    LoadingIndicator {
        color: #00ffff;
        background: #020207;
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
