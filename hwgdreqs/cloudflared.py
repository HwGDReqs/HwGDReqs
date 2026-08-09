import os
import shutil
import re
from PySide6.QtCore import QObject, QProcess, Signal as pyqtSignal

class CloudflaredManager(QObject):
    link_ready = pyqtSignal(str)
    stopped = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._connecting = False
        self._url: str | None = None
        
    @staticmethod
    def is_installed():
        return shutil.which('cloudflared') is not None
        
    def start(self, port: int):
        if self._process is not None:
            self.stop()
            
        self._process = QProcess(self)
        self._process.setProgram('cloudflared')
        self._process.setArguments(['--url', f'http://localhost:{port}', '--no-autoupdate'])
        
        self._process.readyReadStandardOutput.connect(self._handle_output)
        self._process.readyReadStandardError.connect(self._handle_output)
        self._process.finished.connect(self._handle_finished)
        
        # merge stdout and stderr channels to make reading easier since cloudflared logs might go to stderr
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.start()
        
    def stop(self):
        if self._process is not None:
            self._process.terminate()
            if not self._process.waitForFinished(1000):
                self._process.kill()
            self._process = None
            self._url = None
            self.stopped.emit()
            
    def _handle_output(self):
        if not self._process:
            return
            
        data = self._process.readAll().data().decode('utf-8', errors='replace')
        # cloudflared outputs URLs in the format https://something.trycloudflare.com
        match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', data)
        if match:
            self._url = match.group(1)
            self.link_ready.emit(self._url)
            
    def _handle_finished(self):
        self._process = None
        self._url = None
        self.stopped.emit()
        
    def is_running(self):
        return self._process is not None and self._process.state() == QProcess.ProcessState.Running
