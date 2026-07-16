echo off
echo Installing Deps
py -m pip install -r requirements.txt
echo packaging using pyinstallah
py -m PyInstaller HwGDReqs.spec
