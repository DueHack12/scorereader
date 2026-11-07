@echo off
rem Shared helper: finds Python 3 and installs requirements. Called by the other .bat files.
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3 is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run this again.
  pause
  exit /b 1
)
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
exit /b 0
