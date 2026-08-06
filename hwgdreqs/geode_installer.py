import platform
import os
from pathlib import Path

import requests
from PySide6.QtCore import Signal, Qt, QThread
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


GEODE_EXPLANATION_TEXT = (
    "Why this will NOT make it to the Geode in-game browser/index? "
    "because I am index banned, and since Someone else made the geode mod "
    "they (geode index staff) thought he's an alt of me so the mod got "
    "rejected so uh, yeah... you can not use this if you don't trust"
    "shit off the internet and thats valid LMAO, just to be sure, the"
    "source code of both the app + geode mod are public, you can audit/see"
    "/send the code to a clanker and confirm it's safe alr im tired writing ts"
)


class GeodeDownloadWorker(QThread):
    progress = Signal(int)
    status_text = Signal(str)
    finished_ok = Signal(bytes)
    error = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        download_url = (
            "https://github.com/HwGDReqs/HwGDReqs-geode/releases/latest/download/"
            "hwgdreqs.hwgdreqs-integration.geode"
        )
        try:
            self.status_text.emit("Connecting to GitHub...")
            headers = {"User-Agent": "HwGDReqs-Geode-Installer"}
            response = requests.get(
                download_url, headers=headers, stream=True, timeout=30
            )
            response.raise_for_status()

            total_length = response.headers.get("content-length")
            if total_length is None:
                self.status_text.emit("Downloading...")
                data_chunks = []
                for chunk in response.iter_content(chunk_size=8192):
                    if self._is_cancelled:
                        return
                    if chunk:
                        data_chunks.append(chunk)
                if not self._is_cancelled:
                    self.progress.emit(100)
                    self.finished_ok.emit(b"".join(data_chunks))
            else:
                total_length = int(total_length)
                dl = 0
                data_chunks = []
                for chunk in response.iter_content(chunk_size=8192):
                    if self._is_cancelled:
                        return
                    if chunk:
                        data_chunks.append(chunk)
                        dl += len(chunk)
                        percent = int((dl / total_length) * 100)
                        self.progress.emit(percent)
                        mb_dl = dl / (1024 * 1024)
                        mb_total = total_length / (1024 * 1024)
                        self.status_text.emit(
                            f"Downloading... {mb_dl:.1f} / {mb_total:.1f} MB"
                        )
                if not self._is_cancelled:
                    self.finished_ok.emit(b"".join(data_chunks))
        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(str(e))


class GeodeDownloadDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Installing Geode Mod")
        self.setModal(True)
        self.setMinimumSize(380, 140)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._worker: GeodeDownloadWorker | None = None
        self._result_data: bytes | None = None

        layout = QVBoxLayout(self)

        self._status_label = QLabel("Preparing download...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

    def start_download(self) -> int:
        self._worker = GeodeDownloadWorker(self)
        self._worker.progress.connect(self._progress_bar.setValue)
        self._worker.status_text.connect(self._status_label.setText)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        return self.exec()

    def get_data(self) -> bytes | None:
        return self._result_data

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker.wait()
        self.reject()

    def _on_finished(self, data: bytes) -> None:
        self._result_data = data
        self._status_label.setText("Download complete!")
        self._progress_bar.setValue(100)
        self.accept()

    def _on_error(self, error_msg: str) -> None:
        QMessageBox.warning(
            self, "Download Failed", f"Failed to download Geode integration: {error_msg}"
        )
        self.reject()


def _install_geode_data(parent, geode_data: bytes) -> None:
    system = platform.system()
    home = Path.home()

    possible_paths = []

    if system == "Windows":
        possible_paths.append(
            Path("C:/Program Files (x86)/Steam/steamapps/common/Geometry Dash/geode/mods")
        )
    elif system == "Darwin":
        possible_paths.append(
            home
            / "Library/Application Support/Steam/steamapps/common/Geometry Dash/Geometry Dash.app/Contents/geode/mods"
        )
    elif system == "Linux":
        possible_paths.append(
            home
            / ".local/share/Steam/steamapps/compatdata/322170/pfx/drive_c/users/steamuser/AppData/Local/Geode/mods"
        )
        possible_paths.append(
            home
            / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata/322170/pfx/drive_c/users/steamuser/AppData/Local/Geode/mods"
        )

    found_path = None
    for p in possible_paths:
        if p.exists() and p.is_dir():
            found_path = p
            break

    filename = "hwgdreqs.hwgdreqs-integration.geode"

    if found_path:
        target_file = found_path / filename
        try:
            target_file.write_bytes(geode_data)
            QMessageBox.information(
                parent,
                "Success",
                "Geode mods dir found and its successfully installed",
            )
        except Exception as e:
            QMessageBox.warning(
                parent, "Error", f"Found mods dir but failed to write: {e}"
            )
    else:
        downloads_dir = home / "Downloads"
        if not downloads_dir.exists():
            downloads_dir.mkdir(parents=True, exist_ok=True)

        target_file = downloads_dir / filename
        try:
            target_file.write_bytes(geode_data)
            QMessageBox.information(
                parent,
                "Installed to Downloads",
                "Alright i didn't knew where the f*ck did you install Geometry Dash BUT i left the .geode to your Downloads folder, copy it from there",
            )
        except Exception as e:
            QMessageBox.warning(
                parent, "Error", f"Failed to write to Downloads folder: {e}"
            )


def install_geode_integration(parent=None) -> None:
    dialog = GeodeDownloadDialog(parent)
    result = dialog.start_download()
    if result != QDialog.DialogCode.Accepted:
        return
    data = dialog.get_data()
    if data is None:
        return
    _install_geode_data(parent, data)
