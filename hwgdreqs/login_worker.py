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

    def __init__(self, parent=None, *, include_chat_edit: bool = False, include_channel_moderate: bool = False) -> None:
        super().__init__(parent)
        self._include_chat_edit = include_chat_edit
        self._include_channel_moderate = include_channel_moderate

    def run(self) -> None:
        try:
            flow: DeviceFlowStart = start_device_flow(
                include_chat_edit=self._include_chat_edit,
                include_channel_moderate=self._include_channel_moderate,
            )
            self.started_flow.emit(flow)
            session = complete_device_login(
                flow.device_code,
                flow.interval,
                expires_in=flow.expires_in,
                chat_edit_scope=self._include_chat_edit,
                channel_moderate_scope=self._include_channel_moderate,
                on_pending=lambda attempt: self.auth_status.emit(
                    f"Waiting for Twitch authorization... ({attempt})"
                ),
            )
            self.login_complete.emit(session)
        except TwitchAuthError as exc:
            self.login_failed.emit(str(exc))
        except Exception as exc:
            self.login_failed.emit(f"Unexpected error: {exc}")


class KickLoginWorker(QThread):
    auth_url_ready = Signal(str)
    auth_status = Signal(str)
    login_complete = Signal(object)
    login_failed = Signal(str)

    CALLBACK_PORT = 6767
    CALLBACK_TIMEOUT = 300  # seconds

    def run(self) -> None:
        from hwgdreqs.kick_auth import (
            KickAuthError,
            start_pkce_flow,
            wait_for_callback,
            exchange_code,
            session_from_token,
        )
        try:
            self.auth_status.emit("Building Kick authorization URL…")
            auth_url, code_verifier, state = start_pkce_flow(port=self.CALLBACK_PORT)
            self.auth_url_ready.emit(auth_url)
            self.auth_status.emit(
                "Waiting for Kick authorization in your browser… "
                "(approve the login, then come back)"
            )
            code = wait_for_callback(
                port=self.CALLBACK_PORT,
                timeout=self.CALLBACK_TIMEOUT,
                expected_state=state,
            )
            self.auth_status.emit("Exchanging authorization code…")
            token_data = exchange_code(code, code_verifier, port=self.CALLBACK_PORT)
            self.auth_status.emit("Fetching Kick profile…")
            session = session_from_token(token_data)
            self.login_complete.emit(session)
        except KickAuthError as exc:
            self.login_failed.emit(str(exc))
        except Exception as exc:
            self.login_failed.emit(f"Unexpected error: {exc}")

