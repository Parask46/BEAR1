@echo off
cd /d C:\BEAR
start "Bear Web Server" cmd /c "python Web\webserver.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765