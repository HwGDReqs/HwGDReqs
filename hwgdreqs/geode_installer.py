import platform
import urllib.request
from pathlib import Path

from PySide6.QtWidgets import QMessageBox


def install_geode_integration(parent=None):
    download_url = "https://github.com/HwGDReqs/HwGDReqs-geode/releases/latest/download/hwgdreqs.hwgdreqs-integration.geode"
    
    try:
        response = urllib.request.urlopen(download_url)
        geode_data = response.read()
    except Exception as e:
        QMessageBox.warning(parent, "Download Failed", f"Failed to download Geode integration: {e}")
        return

    system = platform.system()
    home = Path.home()
    
    possible_paths = []
    
    if system == "Windows":
        possible_paths.append(Path("C:/Program Files (x86)/Steam/steamapps/common/Geometry Dash/geode/mods"))
    elif system == "Darwin":
        possible_paths.append(home / "Library/Application Support/Steam/steamapps/common/Geometry Dash/Geometry Dash.app/Contents/geode/mods")
    elif system == "Linux":
        possible_paths.append(home / ".local/share/Steam/steamapps/compatdata/322170/pfx/drive_c/users/steamuser/AppData/Local/Geode/mods")
        possible_paths.append(home / ".var/app/com.valvesoftware.Steam/data/Steam/steamapps/compatdata/322170/pfx/drive_c/users/steamuser/AppData/Local/Geode/mods")

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
                "Geode mods dir found and its successfully installed"
            )
        except Exception as e:
            QMessageBox.warning(parent, "Error", f"Found mods dir but failed to write: {e}")
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
                "Alright i didn't knew where the f*ck did you install Geometry Dash BUT i left the .geode to your Downloads folder, copy it from there"
            )
        except Exception as e:
            QMessageBox.warning(parent, "Error", f"Failed to write to Downloads folder: {e}")
