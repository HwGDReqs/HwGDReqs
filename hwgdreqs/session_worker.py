from PySide6.QtCore import QThread, Signal

from hwgdreqs.twitch_auth import TwitchSession, load_session, validate_session


class SessionValidationWorker(QThread):
    auth_status = Signal(str)
    validation_complete = Signal(object)
    validation_failed = Signal()

    def run(self) -> None:
        session = load_session()
        if not session:
            self.validation_failed.emit()
            return

        validated = validate_session(
            session,
            on_pending=lambda: self.auth_status.emit("seeing auth i guess..."),
        )
        if validated:
            self.validation_complete.emit(validated)
        else:
            self.validation_failed.emit()
