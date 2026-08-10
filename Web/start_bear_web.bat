@echo off
cd /d C:\BEAR\Agent\Bear
start "Bear Web Server" cmd /c "python web_server.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765