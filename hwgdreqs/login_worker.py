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

    def run(self) -> None:
        try:
            flow: DeviceFlowStart = start_device_flow()
            self.started_flow.emit(flow)
            session = complete_device_login(
                flow.device_code,
                flow.interval,
                expires_in=flow.expires_in,
                on_pending=lambda attempt: self.auth_status.emit(
                    f"Waiting for Twitch authorization... ({attempt})"
                ),
            )
            self.login_complete.emit(session)
        except TwitchAuthError as exc:
            self.login_failed.emit(str(exc))
        except Exception as exc:
            self.login_failed.emit(f"Unexpected error: {exc}")
