@echo off
net stop ScoreConnectIII
taskkill /IM ScoreConnectIII.exe /F 2>nul
echo If this said "Access is denied", right-click this file and choose Run as administrator.
echo To keep it from starting again: Services ^> ScoreConnectIII ^> Startup type: Disabled.
pause
