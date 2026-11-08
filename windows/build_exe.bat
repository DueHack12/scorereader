@echo off
rem Builds dist\ScoreReader.exe (single file, no Python needed on other PCs)
cd /d "%~dp0.."
call windows\_setup.bat || goto :eof
%PY% -m pip install -q pyinstaller
%PY% -m PyInstaller --noconfirm --onefile --name ScoreReader --hidden-import sportzcast_mqtt --collect-submodules scoreboards --add-data "daktronics_fields.json;." --add-data "scoreboards/catalog.json;scoreboards" scorereader.py
echo. & echo Built dist\ScoreReader.exe
pause
