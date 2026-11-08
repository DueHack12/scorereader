@echo off
rem Builds dist\ScoreReader\ (ScoreReader.exe plus its files; no Python needed on other PCs)
cd /d "%~dp0.."
call windows\_setup.bat || goto :eof
%PY% -m pip install -q pyinstaller
%PY% windows\make_version_info.py
%PY% -m PyInstaller --noconfirm --onedir --name ScoreReader --icon assets\icon.ico --version-file windows\version_info.txt --hidden-import sportzcast_mqtt --collect-submodules scoreboards --add-data "daktronics_fields.json;." --add-data "scoreboards/catalog.json;scoreboards" --add-data "assets;assets" scorereader.py
echo. & echo Built dist\ScoreReader\ScoreReader.exe (keep the whole ScoreReader folder together)
pause
