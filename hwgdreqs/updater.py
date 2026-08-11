import hashlib
import platform
import sys
import os
import subprocess
import tempfile
from pathlib import Path
import requests

from PySide6.QtCore import Signal, Qt, QThread, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QMessageBox,
    QProgressDialog,
    QApplication,
)

from hwgdreqs.config import APP_VERSION, exec_dir


def _detect_run_mode() -> str:
    """Detect how the app is currently running.
    
    Returns one of: 'frozen_windows', 'frozen_macos', 'pip', 'source'
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            return "frozen_windows"
        elif sys.platform == "darwin":
            return "frozen_macos"
        else:
            return "frozen_other"
    
    # Check if running from a pip installation (hwgdreqs is in site-packages)
    try:
        import importlib.util
        spec = importlib.util.find_spec("hwgdreqs")
        if spec is not None and spec.origin is not None:
            import site
            site_packages_dirs = site.getsitepackages() if hasattr(site, 'getsitepackages') else []
            # Also check user site
            user_site = site.getusersitepackages() if hasattr(site, 'getusersitepackages') else None
            if user_site:
                site_packages_dirs = list(site_packages_dirs) + [user_site]
            origin = os.path.normcase(os.path.abspath(spec.origin))
            for sp in site_packages_dirs:
                if origin.startswith(os.path.normcase(os.path.abspath(sp))):
                    return "pip"
    except Exception:
        pass
    
    return "source"


def _parse_version(v: str) -> tuple[int, ...] | None:
    """Parse a dotted numeric version string ('1.1.0', 'v1.2') into a tuple
    of ints for comparison. Returns None if it doesn't look like one.
    """
    v = v.strip().lower().lstrip("v")
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _is_update_available(latest: str, current: str) -> bool:
    latest_t = _parse_version(latest)
    current_t = _parse_version(current)
    if latest_t is not None and current_t is not None:
        return latest_t > current_t
    return latest.strip().lower().lstrip("v") != current.strip().lower().lstrip("v")


def _asset_digests(release_data: dict) -> dict[str, str]:
    """Map asset filename -> 'sha256:<hex>' digest string, from a GitHub
    releases API response. GitHub computes and exposes this automatically
    for assets uploaded since mid-2025; older assets may have a null
    digest, in which case the name is simply absent from the returned dict.
    """
    out: dict[str, str] = {}
    for asset in release_data.get("assets", []) or []:
        name = asset.get("name")
        digest = asset.get("digest")
        if name and digest:
            out[name] = digest
    return out


class UpdateCheckerWorker(QThread):
    finished = Signal(str, str, dict)  # tag_name, body, asset_digests (filename -> "sha256:<hex>")
    error = Signal(str)

    def run(self) -> None:
        try:
            headers = {"User-Agent": "HwGDReqs-Updater"}
            response = requests.get(
                "https://api.github.com/repos/HwGDReqs/HwGDReqs/releases/latest",
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            tag_name = data.get("tag_name", "").strip()
            body = data.get("body", "").strip()
            self.finished.emit(tag_name, body, _asset_digests(data))
        except Exception as e:
            self.error.emit(str(e))


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, url: str, dest_path: str, parent=None, *, expected_digest: str | None = None) -> None:
        super().__init__(parent)
        self.url = url
        self.dest_path = dest_path
        self._is_cancelled = False
        self._expected_digest = expected_digest

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            dest_dir = os.path.dirname(self.dest_path)
            os.makedirs(dest_dir, exist_ok=True)

            headers = {"User-Agent": "HwGDReqs-Updater"}
            response = requests.get(self.url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            hasher = hashlib.sha256()
            total_length = response.headers.get('content-length')
            if total_length is None:
                with open(self.dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            self._cleanup()
                            return
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                if self._is_cancelled:
                    return
                if not self._verify(hasher):
                    return
                self.progress.emit(100)
                self.finished.emit()
            else:
                total_length = int(total_length)
                dl = 0
                with open(self.dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            self._cleanup()
                            return
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)
                            dl += len(chunk)
                            percent = int((dl / total_length) * 100)
                            self.progress.emit(percent)
                if self._is_cancelled:
                    return
                if not self._verify(hasher):
                    return
                self.finished.emit()
        except Exception as e:
            self._cleanup()
            if not self._is_cancelled:
                self.error.emit(str(e))

    def _verify(self, hasher) -> bool:
        if not self._expected_digest:
            return True
        actual = f"sha256:{hasher.hexdigest()}"
        if actual == self._expected_digest:
            return True
        self._cleanup()
        self.error.emit(
            "Downloaded file failed checksum verification against GitHub's "
            "published digest for this release. The download may have been "
            "corrupted or tampered with, so it was not installed."
        )
        return False

    def _cleanup(self) -> None:
        try:
            if os.path.exists(self.dest_path):
                os.remove(self.dest_path)
        except Exception:
            pass


class UpdaterTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._check_worker = None
        self._download_worker = None
        self._progress_dialog = None
        self._run_mode = _detect_run_mode()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(15)

        title_label = QLabel("Application Updater")
        title_font = title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        self._version_label = QLabel(f"Current Version: {APP_VERSION}")
        version_font = self._version_label.font()
        version_font.setPointSize(12)
        self._version_label.setFont(version_font)
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._version_label)

        self._status_label = QLabel("Check for new updates of HwGDReqs.")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("color: gray;")
        layout.addWidget(self._status_label)

        self._check_btn = QPushButton("Check For Updates")
        self._check_btn.setFixedWidth(200)
        self._check_btn.clicked.connect(self._check_for_updates)
        layout.addWidget(self._check_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

    def check_for_updates_on_startup(self):
        self._check_for_updates(silent=True)

    def _check_for_updates(self, silent=False) -> None:
        self._check_btn.setEnabled(False)
        self._status_label.setText("Checking for updates...")
        self._status_label.setStyleSheet("color: #007acc;")

        self._check_worker = UpdateCheckerWorker(self)
        self._check_worker.finished.connect(
            lambda tag, body, digests: self._on_check_finished(tag, body, digests, silent)
        )
        self._check_worker.error.connect(
            lambda err: self._on_check_error(err, silent)
        )
        self._check_worker.start()

    def _on_check_finished(self, latest_version: str, body: str, digests: dict, silent=False) -> None:
        self._check_btn.setEnabled(True)

        if _is_update_available(latest_version, APP_VERSION):
            self._status_label.setText(f"Update available: {latest_version}")
            self._status_label.setStyleSheet("color: #4caf50; font-weight: bold;")

            def ask_update(prompt: str) -> bool:
                msg = QMessageBox(self)
                msg.setWindowTitle("Update Available")
                msg.setText(f"{prompt}\n\n**Release Notes:**\n{body}")
                msg.setTextFormat(Qt.TextFormat.MarkdownText)
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setIcon(QMessageBox.Icon.Question)
                return msg.exec() == QMessageBox.StandardButton.Yes

            if self._run_mode == "frozen_windows":
                # PyInstaller on Windows: download installer and run it
                if ask_update(f"There is an update ({latest_version}). Download and install it now?"):
                    filename = "HwGDReqs-setup-online.exe"
                    url = f"https://github.com/HwGDReqs/HwGDReqs/releases/latest/download/{filename}"
                    dest = str(Path(tempfile.gettempdir()) / filename)
                    self._download_update(url, dest, mode="windows_installer", expected_digest=digests.get(filename))

            elif self._run_mode == "frozen_macos":
                # PyInstaller on macOS: download DMG to ~/Downloads
                machine = platform.machine().lower()
                if machine == "arm64" or machine.startswith("arm"): # yes im dumb
                    dmg_name = "hwgdreqs-macos-silicon.dmg"
                else:
                    dmg_name = "hwgdreqs-macos-intel.dmg"
                url = f"https://github.com/HwGDReqs/HwGDReqs/releases/latest/download/{dmg_name}"
                downloads_dir = Path.home() / "Downloads"
                downloads_dir.mkdir(parents=True, exist_ok=True)
                dest_path = downloads_dir / dmg_name
                # Auto-rename if file already exists
                counter = 1
                while dest_path.exists():
                    stem, suffix = dmg_name.rsplit(".", 1)
                    dest_path = downloads_dir / f"{stem} ({counter}).{suffix}"
                    counter += 1
                if ask_update(f"There is an update ({latest_version}).\nDownload {dmg_name} to your Downloads folder?"):
                    self._download_update(url, str(dest_path), mode="macos_dmg", expected_digest=digests.get(dmg_name))

            elif self._run_mode == "pip":
                # pip installation: tell the user to run pip upgrade
                if ask_update(f"There is an update ({latest_version}). To update, run:\n\n`pip install --upgrade hwgdreqs`\n\nWould you like to copy this command to clipboard?"):
                    QGuiApplication.clipboard().setText("pip install --upgrade hwgdreqs")
                    QMessageBox.information(self, "Copied!", "Command copied to clipboard!")

            else:
                # Running from source: tell the user to git pull
                if ask_update(f"There is an update ({latest_version}). Since you are running from source, pull the latest changes:\n\n`git pull`\n\nWould you like to copy this command to clipboard?"):
                    QGuiApplication.clipboard().setText("git pull")
                    QMessageBox.information(self, "Copied!", "Command copied to clipboard!")
        else:
            self._status_label.setText("You are running the latest version.")
            self._status_label.setStyleSheet("color: green;")
            if not silent:
                QMessageBox.information(
                    self,
                    "Up to Date",
                    "You are already using the latest version of HwGDReqs."
                )

    def _on_check_error(self, error_msg: str, silent=False) -> None:
        self._check_btn.setEnabled(True)
        self._status_label.setText("Failed to check for updates.")
        self._status_label.setStyleSheet("color: red;")
        if not silent:
            QMessageBox.warning(
                self,
                "Check Failed",
                f"Could not check for updates:\n{error_msg}"
            )

    def _download_update(self, download_url: str, dest_file: str, mode: str = "windows_installer", *, expected_digest: str | None = None) -> None:
        self._download_mode = mode
        self._check_btn.setEnabled(False)
        self._status_label.setText("Downloading update...")
        self._status_label.setStyleSheet("color: #007acc;")

        label = "Downloading update..."
        self._progress_dialog = QProgressDialog(label, "Cancel", 0, 100, self)
        self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setValue(0)

        self._download_worker = UpdateDownloadWorker(download_url, dest_file, self, expected_digest=expected_digest)
        self._download_worker.progress.connect(self._progress_dialog.setValue)
        self._download_worker.finished.connect(lambda: self._on_download_finished(dest_file))
        self._download_worker.error.connect(self._on_download_error)

        self._progress_dialog.canceled.connect(self._cancel_download)
        self._download_worker.start()

    def _cancel_download(self) -> None:
        if self._download_worker:
            self._download_worker.cancel()
            self._download_worker.wait()
        self._check_btn.setEnabled(True)
        self._status_label.setText("Download cancelled.")
        self._status_label.setStyleSheet("color: orange;")
        QMessageBox.information(self, "Cancelled", "Update download was cancelled.")

    def _on_download_finished(self, dest_file: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()

        mode = getattr(self, "_download_mode", "windows_installer")

        if mode == "windows_installer":
            self._status_label.setText("Download complete. Launching installer...")
            self._status_label.setStyleSheet("color: green; font-weight: bold;")
            self._check_btn.setEnabled(False)
            self._run_installer_and_exit(dest_file)
        elif mode == "macos_dmg":
            self._status_label.setText("Download complete! Check your Downloads folder.")
            self._status_label.setStyleSheet("color: green; font-weight: bold;")
            self._check_btn.setEnabled(True)
            QMessageBox.information(
                self,
                "Download Complete",
                f"The update has been downloaded to your Downloads folder:\n"
                f"{dest_file}\n\n"
                "Open the DMG file, drag HwGDReqs to Applications, and relaunch the app."
            )

    def _on_download_error(self, error_msg: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
        
        self._check_btn.setEnabled(True)
        self._status_label.setText("Download failed.")
        self._status_label.setStyleSheet("color: red;")
        QMessageBox.warning(
            self,
            "Download Failed",
            f"An error occurred while downloading the update:\n{error_msg}"
        )

    def _run_installer_and_exit(self, installer_path: str) -> None:
        try:
            subprocess.Popen(
                [installer_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception:
            pass

        QApplication.quit()
        sys.exit(0)


def _download_update_for_startup(parent, download_url, dest_file, mode="windows_installer", *, expected_digest=None):
    parent._startup_progress_dialog = QProgressDialog("Downloading update...", "Cancel", 0, 100, parent)
    parent._startup_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    parent._startup_progress_dialog.setMinimumDuration(0)
    parent._startup_progress_dialog.setValue(0)
    
    parent._startup_download_worker = UpdateDownloadWorker(download_url, dest_file, parent, expected_digest=expected_digest)
    
    def cancel_download():
        parent._startup_download_worker.cancel()
        parent._startup_download_worker.wait()
        QMessageBox.information(parent, "Cancelled", "Update download was cancelled.")
    
    parent._startup_progress_dialog.canceled.connect(cancel_download)
    parent._startup_download_worker.progress.connect(parent._startup_progress_dialog.setValue)
    
    def on_download_finished():
        if parent._startup_download_worker._is_cancelled:
            return
        parent._startup_progress_dialog.close()
        
        if mode == "windows_installer":
            try:
                subprocess.Popen(
                    [dest_file],
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            except Exception:
                pass
            
            QApplication.quit()
            sys.exit(0)
        elif mode == "macos_dmg":
            QMessageBox.information(
                parent,
                "Download Complete",
                f"The update has been downloaded to your Downloads folder:\n"
                f"{dest_file}\n\n"
                "Open the DMG file, drag HwGDReqs to Applications, and relaunch the app."
            )
        
    def on_download_error(error_msg):
        parent._startup_progress_dialog.close()
        QMessageBox.warning(
            parent,
            "Download Failed",
            f"An error occurred while downloading the update:\n{error_msg}"
        )
    
    parent._startup_download_worker.finished.connect(on_download_finished)
    parent._startup_download_worker.error.connect(on_download_error)
    parent._startup_download_worker.start()


def check_for_updates_on_startup(parent):
    parent._check_update_worker = UpdateCheckerWorker(parent)
    run_mode = _detect_run_mode()
    
    def on_finished(latest_version, body, digests):
        if _is_update_available(latest_version, APP_VERSION):
            def ask_update(prompt: str) -> bool:
                msg = QMessageBox(parent)
                msg.setWindowTitle("Update Available")
                msg.setText(f"{prompt}\n\n**Release Notes:**\n{body}")
                msg.setTextFormat(Qt.TextFormat.MarkdownText)
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setIcon(QMessageBox.Icon.Question)
                return msg.exec() == QMessageBox.StandardButton.Yes

            if run_mode == "frozen_windows":
                if ask_update(f"There is an update ({latest_version}). Download and install it now?"):
                    filename = "HwGDReqs-setup-online.exe"
                    url = f"https://github.com/HwGDReqs/HwGDReqs/releases/latest/download/{filename}"
                    dest = str(Path(tempfile.gettempdir()) / filename)
                    _download_update_for_startup(parent, url, dest, mode="windows_installer", expected_digest=digests.get(filename))

            elif run_mode == "frozen_macos":
                machine = platform.machine().lower()
                if machine == "arm64" or machine.startswith("arm"):
                    dmg_name = "hwgdreqs-macos-silicon.dmg"
                else:
                    dmg_name = "hwgdreqs-macos-intel.dmg"
                url = f"https://github.com/HwGDReqs/HwGDReqs/releases/latest/download/{dmg_name}"
                downloads_dir = Path.home() / "Downloads"
                downloads_dir.mkdir(parents=True, exist_ok=True)
                dest_path = downloads_dir / dmg_name
                counter = 1
                while dest_path.exists():
                    stem, suffix = dmg_name.rsplit(".", 1)
                    dest_path = downloads_dir / f"{stem} ({counter}).{suffix}"
                    counter += 1
                if ask_update(f"There is an update ({latest_version}).\nDownload {dmg_name} to your Downloads folder?"):
                    _download_update_for_startup(parent, url, str(dest_path), mode="macos_dmg", expected_digest=digests.get(dmg_name))

            elif run_mode == "pip":
                if ask_update(f"There is an update ({latest_version}). To update, run:\n\n`pip install --upgrade hwgdreqs`\n\nWould you like to copy this command to clipboard?"):
                    QGuiApplication.clipboard().setText("pip install --upgrade hwgdreqs")
                    QMessageBox.information(parent, "Copied!", "Command copied to clipboard!")

            else:
                if ask_update(f"There is an update ({latest_version}). Since you are running from source, pull the latest changes:\n\n`git pull`\n\nWould you like to copy this command to clipboard?"):
                    QGuiApplication.clipboard().setText("git pull")
                    QMessageBox.information(parent, "Copied!", "Command copied to clipboard!")
    
    parent._check_update_worker.finished.connect(on_finished)
    parent._check_update_worker.start()
