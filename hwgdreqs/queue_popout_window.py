"""
Queue Popout Window
A standalone, read-only window that mirrors the main queue list.
Designed for OBS window capture – fully resizable, no interaction.
"""

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
)

from hwgdreqs.config import asset_path
from hwgdreqs.queue_manager import QueueManager


_DIFFICULTY_ICON_MAP = {
    "Unrated": "unrated.png",
    "Auto": "auto.png",
    "Easy": "easy.png",
    "Normal": "normal.png",
    "Hard": "hard.png",
    "Harder": "harder.png",
    "Insane": "insane.png",
}


def _difficulty_icon_file(difficulty: str) -> str:
    if difficulty.endswith("Demon"):
        return "demon.png"
    return _DIFFICULTY_ICON_MAP.get(difficulty, "unrated.png")


class PopoutQueueItemWidget(QWidget):

    def __init__(
        self,
        text: str,
        platform_icon_path: str | None,
        difficulty: str,
        scale: float = 1.0,
    ):
        super().__init__()
        self.setMouseTracking(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        icon_size = max(8, int(24 * scale))
        layout.setContentsMargins(
            max(2, int(5 * scale)),
            max(2, int(5 * scale)),
            max(2, int(5 * scale)),
            max(2, int(5 * scale)),
        )
        layout.setSpacing(max(2, int(4 * scale)))

        diff_icon_file = _difficulty_icon_file(difficulty)
        diff_path = asset_path(diff_icon_file)
        if diff_path.exists():
            diff_label = QLabel()
            diff_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            diff_pixmap = QPixmap(str(diff_path)).scaled(
                icon_size, icon_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            diff_label.setPixmap(diff_pixmap)
            layout.addWidget(diff_label)

        text_label = QLabel(text)
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_label.setWordWrap(True)
        text_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        font = text_label.font()
        font.setPointSizeF(max(6.0, 10.0 * scale))
        text_label.setFont(font)
        layout.addWidget(text_label)

        if platform_icon_path:
            plat_path = asset_path(platform_icon_path)
            if plat_path.exists():
                plat_label = QLabel()
                plat_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                plat_pixmap = QPixmap(str(plat_path)).scaled(
                    icon_size, icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                plat_label.setPixmap(plat_pixmap)
                layout.addWidget(plat_label)


class QueuePopoutWindow(QMainWindow):

    def __init__(self, queue: QueueManager, parent=None):
        super().__init__(parent)
        self._queue = queue
        self.setWindowTitle("Queue Popout")
        self.setMinimumSize(200, 150)
        self.resize(400, 600)

        self._settings = QSettings()
        geometry = self._settings.value("popout_geometry")
        if geometry:
            self.restoreGeometry(geometry)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # no scrolling
        self._list.setFlow(QListWidget.Flow.TopToBottom)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setUniformItemSizes(False)
        self._list.setWordWrap(True)
        self._list.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._list)

        self._twitch_icon_path = "twitch.svg"
        self._youtube_icon_path = "youtube.svg"

        self._queue.add_listener(self.refresh)
        self.refresh()

    def _get_scale(self) -> float:
        return max(0.3, min(3.0, float(self._queue.queue_popout_scale)))

    def refresh(self) -> None:
        scale = self._get_scale()
        self._list.clear()
        for index, entry in enumerate(self._queue.levels):
            text = f'[{index + 1}] "{entry.name}" by {entry.author}'

            platform_icon_path = None
            if entry.platform == "youtube":
                platform_icon_path = self._youtube_icon_path
            elif entry.platform == "twitch":
                platform_icon_path = self._twitch_icon_path

            widget = PopoutQueueItemWidget(text, platform_icon_path, entry.difficulty, scale)

            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable
            item.setSizeHint(widget.sizeHint())

            self._list.addItem(item)
            self._list.setItemWidget(item, widget)

    def closeEvent(self, event):
        self._settings.setValue("popout_geometry", self.saveGeometry())
        super().closeEvent(event)

    def shutdown(self) -> None:
        self._queue.remove_listener(self.refresh)
        self.close()
