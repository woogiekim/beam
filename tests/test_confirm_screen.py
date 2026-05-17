"""Tests for ConfirmScreen — generic remote-action confirmation dialog.

Covers:
- ConfirmScreen action_confirm calls on_confirm callback
- ConfirmScreen action_cancel does NOT call on_confirm
- action_deploy_selected pushes ConfirmScreen (not calling _run_deploy directly)
- action_delete_remote_selected pushes ConfirmScreen
- action_show_rollback pushes ConfirmScreen when files are selected
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from beam.app import ConfirmScreen


# ---------------------------------------------------------------------------
# ConfirmScreen unit tests — test action methods directly (no async)
# ---------------------------------------------------------------------------


class TestConfirmScreenActions:
    """Test ConfirmScreen action methods without running a full Textual app."""

    def _make_screen(self, on_confirm: "callable") -> ConfirmScreen:
        """Create a ConfirmScreen with a mocked app."""
        screen = ConfirmScreen.__new__(ConfirmScreen)
        screen._title = "Test Action"
        screen._message = "Are you sure?"
        screen._on_confirm = on_confirm
        # Mock the app so pop_screen works
        screen._app = MagicMock()
        return screen

    def test_action_confirm_calls_on_confirm(self) -> None:
        """action_confirm must invoke the on_confirm callback."""
        called = []

        def _cb() -> None:
            called.append(True)

        screen = self._make_screen(_cb)

        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: self._app)):
            screen.action_confirm()

        assert called == [True], "on_confirm must be called exactly once on confirm"

    def test_action_cancel_does_not_call_on_confirm(self) -> None:
        """action_cancel must NOT invoke the on_confirm callback."""
        called = []

        def _cb() -> None:
            called.append(True)

        screen = self._make_screen(_cb)

        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: self._app)):
            screen.action_cancel()

        assert called == [], "on_confirm must not be called on cancel"

    def test_action_confirm_pops_screen(self) -> None:
        """action_confirm pops the screen before calling on_confirm."""
        pop_called_before_cb = []
        mock_app = MagicMock()

        def _cb() -> None:
            # Record whether pop_screen was called before this callback
            pop_called_before_cb.append(mock_app.pop_screen.called)

        screen = ConfirmScreen.__new__(ConfirmScreen)
        screen._title = "Test"
        screen._message = "Msg"
        screen._on_confirm = _cb
        screen._app = mock_app

        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: self._app)):
            screen.action_confirm()

        # pop_screen should have been called
        mock_app.pop_screen.assert_called_once()
        # And it was called before the callback
        assert pop_called_before_cb == [True], "pop_screen must be called before on_confirm"

    def test_action_cancel_pops_screen(self) -> None:
        """action_cancel pops the screen."""
        mock_app = MagicMock()
        screen = ConfirmScreen.__new__(ConfirmScreen)
        screen._title = "Test"
        screen._message = "Msg"
        screen._on_confirm = lambda: None
        screen._app = mock_app

        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: self._app)):
            screen.action_cancel()

        mock_app.pop_screen.assert_called_once()


# ---------------------------------------------------------------------------
# ConfirmScreen constructor and attributes
# ---------------------------------------------------------------------------


class TestConfirmScreenInit:
    def test_init_stores_title_message_callback(self) -> None:
        """ConfirmScreen stores title, message, and callback correctly."""
        cb = lambda: None
        screen = ConfirmScreen("My Title", "My Message", cb)
        assert screen._title == "My Title"
        assert screen._message == "My Message"
        assert screen._on_confirm is cb


# ---------------------------------------------------------------------------
# action_deploy_selected — must push ConfirmScreen, not call _run_deploy
# ---------------------------------------------------------------------------


class TestDeployConfirm:
    def _make_file_screen(self, selected_files: list[str]) -> "FileSelectScreen":
        from beam.app import FileSelectScreen
        from beam.rollback import RollbackSession

        workspace = MagicMock()
        workspace.host = "test-host"
        workspace.remote_root = "/remote"
        session = RollbackSession()

        screen = FileSelectScreen.__new__(FileSelectScreen)
        screen.workspace = workspace
        screen.session = session
        screen._sftp_client = MagicMock()
        screen._deploy_log_lines = []
        screen._rollback_panel_visible = False

        mock_sl = MagicMock()
        mock_sl.selected = selected_files

        mock_log = MagicMock()
        mock_log.display = False

        def _query_one(selector, *args):
            if "#local-list" in str(selector) or selector == "#local-list":
                return mock_sl
            if "#deploy-log" in str(selector) or selector == "#deploy-log":
                return mock_log
            return MagicMock()

        screen.query_one = MagicMock(side_effect=_query_one)
        screen.notify = MagicMock()
        return screen

    def test_action_deploy_selected_pushes_confirm_screen(self) -> None:
        """action_deploy_selected should push ConfirmScreen, not run deploy directly."""
        screen = self._make_file_screen(["file1.txt", "file2.txt"])

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_deploy_selected()

        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, ConfirmScreen), (
            "action_deploy_selected must push a ConfirmScreen, not run deploy directly"
        )

    def test_action_deploy_selected_no_confirm_when_empty(self) -> None:
        """action_deploy_selected does NOT push ConfirmScreen when nothing is selected."""
        screen = self._make_file_screen([])

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_deploy_selected()

        mock_app.push_screen.assert_not_called()

    def test_action_deploy_not_connected(self) -> None:
        """action_deploy_selected shows error when not connected (no push_screen)."""
        screen = self._make_file_screen(["file1.txt"])
        screen._sftp_client = None

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_deploy_selected()

        mock_app.push_screen.assert_not_called()
        screen.notify.assert_called_once()


# ---------------------------------------------------------------------------
# action_delete_remote_selected — must push ConfirmScreen
# ---------------------------------------------------------------------------


class TestDeleteRemoteConfirm:
    def test_action_delete_remote_selected_pushes_confirm_screen(self) -> None:
        """action_delete_remote_selected should push ConfirmScreen."""
        from beam.app import FileSelectScreen
        from beam.rollback import RollbackSession

        workspace = MagicMock()
        workspace.host = "test-host"
        workspace.remote_root = "/remote"
        session = RollbackSession()

        screen = FileSelectScreen.__new__(FileSelectScreen)
        screen.workspace = workspace
        screen.session = session
        screen._sftp_client = MagicMock()
        screen.notify = MagicMock()

        mock_sl = MagicMock()
        mock_sl.selected = ["file1.txt"]
        screen.query_one = MagicMock(return_value=mock_sl)

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_delete_remote_selected()

        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, ConfirmScreen), (
            "action_delete_remote_selected must push a ConfirmScreen"
        )

    def test_action_delete_remote_no_push_when_empty(self) -> None:
        """action_delete_remote_selected does not push when nothing selected."""
        from beam.app import FileSelectScreen
        from beam.rollback import RollbackSession

        workspace = MagicMock()
        session = RollbackSession()

        screen = FileSelectScreen.__new__(FileSelectScreen)
        screen.workspace = workspace
        screen.session = session
        screen._sftp_client = MagicMock()
        screen.notify = MagicMock()

        mock_sl = MagicMock()
        mock_sl.selected = []
        screen.query_one = MagicMock(return_value=mock_sl)

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_delete_remote_selected()

        mock_app.push_screen.assert_not_called()


# ---------------------------------------------------------------------------
# action_show_rollback — must push ConfirmScreen when files are selected
# ---------------------------------------------------------------------------


class TestRollbackConfirm:
    def test_action_show_rollback_pushes_confirm_screen_when_files_selected(self) -> None:
        """action_show_rollback should push ConfirmScreen when files are selected."""
        from beam.app import FileSelectScreen
        from beam.rollback import RollbackSession

        workspace = MagicMock()
        workspace.host = "test-host"
        workspace.remote_root = "/remote"

        session = MagicMock()
        session.__len__ = MagicMock(return_value=2)

        screen = FileSelectScreen.__new__(FileSelectScreen)
        screen.workspace = workspace
        screen.session = session
        screen._sftp_client = MagicMock()
        screen._rollback_panel_visible = True  # panel already visible
        screen._rollback_log_lines = []
        screen.notify = MagicMock()

        mock_sl = MagicMock()
        mock_sl.selected = ["file1.txt"]
        mock_result = MagicMock()

        def _query_one(selector, *args):
            if "#rollback-list" in str(selector) or selector == "#rollback-list":
                return mock_sl
            return mock_result

        screen.query_one = MagicMock(side_effect=_query_one)

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_show_rollback()

        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, ConfirmScreen), (
            "action_show_rollback must push a ConfirmScreen when files are selected"
        )

    def test_action_show_rollback_closes_panel_when_no_files_selected(self) -> None:
        """action_show_rollback closes the panel when visible but nothing selected."""
        from beam.app import FileSelectScreen

        workspace = MagicMock()
        session = MagicMock()
        session.__len__ = MagicMock(return_value=1)

        screen = FileSelectScreen.__new__(FileSelectScreen)
        screen.workspace = workspace
        screen.session = session
        screen._sftp_client = MagicMock()
        screen._rollback_panel_visible = True
        screen.notify = MagicMock()

        mock_sl = MagicMock()
        mock_sl.selected = []  # nothing selected
        mock_panel = MagicMock()
        mock_panel.display = True

        def _query_one(selector, *args):
            if "#rollback-list" in str(selector) or selector == "#rollback-list":
                return mock_sl
            if "#rollback-panel" in str(selector) or selector == "#rollback-panel":
                return mock_panel
            return MagicMock()

        screen.query_one = MagicMock(side_effect=_query_one)

        mock_app = MagicMock()
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: mock_app)):
            screen.action_show_rollback()

        # Panel should be hidden, push_screen NOT called
        assert mock_panel.display is False
        mock_app.push_screen.assert_not_called()
