"""Beam TUI Application.

Interactive terminal UI built with textual.
Provides screens for workspace selection, file multi-select, deployment, and rollback.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional


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
        Binding("ctrl+s", "submit", "Save", priority=True),
    ]

    CSS = """
    WorkspaceFormScreen {
        layout: vertical;
        background: #0a0a0f;
    }
    #form-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    #form-inner {
        margin: 1 4;
        height: auto;
        background: #0f0f1a;
        border: round #00e5ff;
        padding: 1 2;
    }
    .field-label {
        margin-top: 1;
        color: #4a5a6a;
    }
    .required-label {
        margin-top: 1;
        color: #00e5ff;
    }
    #form-error {
        margin: 0 4;
        color: #ff3355;
        height: auto;
    }
    Input {
        background: #0f0f1a;
        border: round #4a5a6a;
        color: #c8d8e8;
    }
    Input:focus {
        border: round #00e5ff;
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
        Binding("enter", "confirm_delete", "Yes — delete", priority=True),
    ]

    CSS = """
    DeleteConfirmScreen {
        layout: vertical;
        align: center middle;
        background: #0a0a0f;
    }
    #confirm-box {
        width: 60;
        height: auto;
        border: round #ff3355;
        padding: 2 4;
        background: #0f0f1a;
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
        Binding("ctrl+n", "add_workspace", "Add", priority=True),
        Binding("ctrl+e", "edit_workspace", "Edit", priority=True),
        Binding("ctrl+d", "delete_workspace", "Delete", priority=True),
        Binding("enter", "select_workspace", "Open", show=False),
    ]

    CSS = """
    WorkspaceScreen {
        layout: vertical;
        background: #0a0a0f;
    }
    #workspace-list {
        height: 1fr;
        border: round #00e5ff;
        margin: 1 2;
        background: #0f0f1a;
    }
    #workspace-hint {
        margin: 1 2 0 2;
        color: #4a5a6a;
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
        background: #0a0a0f;
    }
    #info-bar {
        height: 3;
        margin: 1 2 0 2;
        padding: 0 1;
        background: #0f0f1a;
        border: round #4a5a6a;
        color: #c8d8e8;
    }
    #panels {
        height: 1fr;
        margin: 1 2;
    }
    #local-panel {
        width: 1fr;
        border: round #00e5ff;
        background: #0f0f1a;
    }
    #remote-panel {
        width: 1fr;
        border: round #00ff88;
        margin-left: 1;
        background: #0f0f1a;
    }
    .panel-header {
        height: 1;
        background: #0a0a0f;
        color: #c8d8e8;
        padding: 0 1;
        text-align: center;
    }
    #local-list {
        height: 1fr;
    }
    #remote-list {
        height: 1fr;
    }
    #deploy-log {
        height: 8;
        border: round #00ff88;
        margin: 0 2 0 2;
        overflow-y: scroll;
        background: #050508;
        color: #00ff88;
        display: none;
    }
    #rollback-panel {
        height: 12;
        border: round #ffaa00;
        margin: 0 2 1 2;
        background: #0f0a00;
        display: none;
    }
    #rollback-panel-header {
        height: 1;
        background: #1a1000;
        color: #ffaa00;
        padding: 0 1;
    }
    #rollback-list {
        height: 1fr;
    }
    #rollback-result {
        height: 3;
        background: #050300;
        color: #ffaa00;
        overflow-y: scroll;
        border-top: solid #3a2800;
        padding: 0 1;
    }
    """

    def __init__(self, workspace: Workspace, session: RollbackSession) -> None:
        super().__init__()
        self.workspace = workspace
        self.session = session
        self._sftp_client: Optional[SFTPClient] = None
        self._diff_checked = False
        self._deploy_log_lines: list[str] = []
        self._rollback_log_lines: list[str] = []
        self._rollback_panel_visible = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="info-bar"):
            yield Label(
                f"[bold]{self.workspace.name}[/]  "
                f"{self.workspace.user}@{self.workspace.host}:{self.workspace.remote_root}  "
                f"→ local: {self.workspace.local_root}"
            )
        with Horizontal(id="panels"):
            with Container(id="local-panel"):
                yield Label(
                    "[bold #00e5ff]Local[/]  [dim](Space to select, Ctrl+A all, Ctrl+D deploy)[/]",
                    classes="panel-header",
                )
                yield SelectionList(id="local-list")
            with Container(id="remote-panel"):
                yield Label(
                    "[bold #00ff88]Remote[/]  [dim](Space to select, Ctrl+X to delete)[/]",
                    classes="panel-header",
                )
                yield SelectionList(id="remote-list")
        yield Static(id="deploy-log")
        with Container(id="rollback-panel"):
            yield Label(
                "[bold #ffaa00]Rollback[/]  [dim]Space to select, Ctrl+R to restore, Esc to close[/]",
                id="rollback-panel-header",
            )
            yield SelectionList(id="rollback-list")
            yield Static(id="rollback-result")
        yield Footer()

    def on_mount(self) -> None:
        self._connect_and_load()

    @work(thread=True)
    def _connect_and_load(self) -> None:
        """Connect to SFTP and load file lists (runs in background thread)."""
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

        if not self._diff_checked:
            self._diff_checked = True
            self._check_diff()

        self._load_file_lists()

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

    def _load_file_lists(self) -> None:
        """Populate local and remote SelectionLists as tree views with file stats."""
        local_root = Path(self.workspace.local_root).expanduser().resolve()
        local_set: frozenset[str] = build_local_tree(local_root)

        remote_stats: dict[str, tuple[int, float]] = {}
        if self._sftp_client is not None:
            try:
                remote_stats = self._sftp_client.list_remote_tree_with_stats(
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
        )
        remote_selections = self._build_tree_selections(
            paths=sorted(remote_set),
            stats=remote_stats,
            remote_stats={},
            remote_set=frozenset(),
            show_diff=False,
        )

        self.app.call_from_thread(self._update_local_list, local_selections)
        self.app.call_from_thread(self._update_remote_list, remote_selections)

    def _build_tree_selections(
        self,
        paths: list[str],
        stats: dict[str, tuple[int, float]],
        remote_stats: dict[str, tuple[int, float]],
        remote_set: frozenset[str],
        show_diff: bool,
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
                            f"{indent}📁 {parts[depth]}/",
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
                    tag = "[+]"
                else:
                    r_size = remote_stats.get(rel_path, (None,))[0]
                    tag = "[=]" if r_size == size else "[M]"
                label = f"{indent}{tag} {filename}  {size_str} {date_str}"
            else:
                label = f"{indent}{filename}  {size_str} {date_str}"

            entries.append(Selection(label, rel_path, initial_state=False))

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
            self.notify("No remote files selected. Use Space to select files.", severity="warning")
            return
        self._run_delete_remote(selected)

    @work(thread=True)
    def _run_delete_remote(self, rel_paths: list[str]) -> None:
        assert self._sftp_client is not None
        results: list[str] = []
        for rel_path in rel_paths:
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"
            try:
                self._sftp_client.delete_remote_file(remote_abs)
                results.append(f"Deleted: {rel_path}")
            except SFTPError as exc:
                results.append(f"Failed {rel_path}: {exc}")
        summary = "\n".join(results)
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
        selectable = [
            o for o in sl._options  # type: ignore[attr-defined]
            if not (hasattr(o, "value") and str(o.value).startswith("__dir__:"))
            and not getattr(o, "disabled", False)
        ]
        selected_count = len(list(sl.selected))
        if len(selectable) > 0 and selected_count == len(selectable):
            sl.deselect_all()
        else:
            sl.select_all()

    def action_deploy_selected(self) -> None:
        if self._sftp_client is None:
            self.notify("Not connected.", severity="error")
            return
        sl: SelectionList = self.query_one("#local-list")
        selected = list(sl.selected)
        if not selected:
            self.notify("No files selected. Use Space to select files.", severity="warning")
            return
        # Inline deploy — clear log and show panel
        self._deploy_log_lines = []
        log_widget: Static = self.query_one("#deploy-log")
        log_widget.update("")
        log_widget.display = True
        self._run_deploy(selected)

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

        for rel_path in selected_paths:
            local_abs = str(local_root / rel_path)
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"

            self.app.call_from_thread(self._append_deploy_log, f"Snapshotting: {rel_path}")
            try:
                original = self._sftp_client.download_file(remote_abs)
                self.session.snapshot(rel_path, original)
            except SFTPError as exc:
                self.app.call_from_thread(
                    self._append_deploy_log, f"  [yellow]Snapshot warning:[/] {exc}"
                )

            self.app.call_from_thread(self._append_deploy_log, f"Uploading:   {rel_path}")
            try:
                bytes_written = self._sftp_client.upload_file(local_abs, remote_abs)
                self.app.call_from_thread(
                    self._append_deploy_log, f"  [green]OK[/] ({bytes_written} bytes)"
                )
            except SFTPError as exc:
                self.app.call_from_thread(
                    self._append_deploy_log, f"  [red]FAILED:[/] {exc}"
                )

        self.app.call_from_thread(
            self._append_deploy_log, "\n[bold green]Deployment complete.[/]"
        )

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
        else:
            sl: SelectionList = self.query_one("#rollback-list")
            selected = list(sl.selected)
            if not selected:
                self.query_one("#rollback-panel").display = False
                self._rollback_panel_visible = False
            else:
                self._rollback_log_lines = []
                self.query_one("#rollback-result", Static).update("")
                self._run_rollback(selected)

    def _populate_rollback_list(self) -> None:
        sl: SelectionList = self.query_one("#rollback-list")
        sl.clear_options()
        for entry in self.session.list_entries():
            existed = "existed" if entry.existed_remotely() else "NEW"
            label = (
                f"{entry.rel_path}  [{existed}]"
                f"  @ {entry.timestamp.strftime('%H:%M:%S')}"
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
        for rel_path in paths:
            entry = self.session.get_entry(rel_path)
            if entry is None:
                self.app.call_from_thread(
                    self._append_rollback_log, f"No snapshot: {rel_path}"
                )
                continue
            remote_abs = f"{self.workspace.remote_root.rstrip('/')}/{rel_path}"
            if entry.existed_remotely():
                try:
                    assert entry.original_bytes is not None
                    self._sftp_client.upload_bytes(entry.original_bytes, remote_abs)
                    self.app.call_from_thread(
                        self._append_rollback_log, f"Restored: {rel_path}"
                    )
                except SFTPError as exc:
                    self.app.call_from_thread(
                        self._append_rollback_log, f"Failed {rel_path}: {exc}"
                    )
            else:
                try:
                    self._sftp_client.delete_remote_file(remote_abs)
                    self.app.call_from_thread(
                        self._append_rollback_log,
                        f"Deleted (new file rollback): {rel_path}",
                    )
                except SFTPError as exc:
                    self.app.call_from_thread(
                        self._append_rollback_log, f"Failed to delete {rel_path}: {exc}"
                    )
        self.app.call_from_thread(
            self._append_rollback_log, "\n[bold yellow]Rollback complete.[/]"
        )
        self.app.call_from_thread(self._populate_rollback_list)

    def action_refresh_files(self) -> None:
        self._refresh_file_lists_in_thread()

    @work(thread=True)
    def _refresh_file_lists_in_thread(self) -> None:
        """Background worker that re-fetches both file lists on F5."""
        self._load_file_lists()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class DeployerApp(App):
    """Root application — initializes config and enters workspace selection."""

    TITLE = "Beam"
    SUB_TITLE = "Terminal SFTP deployment tool"

    CSS = """
    Screen {
        background: #0a0a0f;
    }
    Header {
        background: #0f0f1a;
        color: #00e5ff;
    }
    Footer {
        background: #0f0f1a;
        color: #4a5a6a;
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
