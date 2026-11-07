@echo off
cd /d "%~dp0.."
call windows\_setup.bat || goto :eof
echo Make sure ScoreConnect III is CLOSED and its service is stopped first.
%PY% scorereader.py --list-ports
echo.
%PY% scorereader.py --probe
pause
