@echo off
cd /d "%~dp0.."
call windows\_setup.bat || goto :eof
%PY% scorereader.py --demo
pause
