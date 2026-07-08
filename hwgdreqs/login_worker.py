from PySide6.QtCore import QThread, Signal

from hwgdreqs.twitch_auth import (
    DeviceFlowStart,
    TwitchAuthError,
    complete_device_login,
    start_device_flow,
)


class DeviceLoginWorker(QThread):
    started_flow = Signal(object)
    auth_status = Signal(str)
    login_complete = Signal(object)
    login_failed = Signal(str)

    def __init__(self, parent=None, *, include_chat_edit: bool = False) -> None:
        super().__init__(parent)
        self._include_chat_edit = include_chat_edit

    def run(self) -> None:
        try:
            flow: DeviceFlowStart = start_device_flow(
                include_chat_edit=self._include_chat_edit,
            )
            self.started_flow.emit(flow)
            session = complete_device_login(
                flow.device_code,
                flow.interval,
                expires_in=flow.expires_in,
                chat_edit_scope=self._include_chat_edit,
                on_pending=lambda attempt: self.auth_status.emit(
                    f"Waiting for Twitch authorization... ({attempt})"
                ),
            )
            self.login_complete.emit(session)
        except TwitchAuthError as exc:
            self.login_failed.emit(str(exc))
        except Exception as exc:
            self.login_failed.emit(f"Unexpected error: {exc}")
