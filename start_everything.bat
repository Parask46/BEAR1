@echo off
title Bear System Launcher

echo =======================================
echo Launching Bear Agent and Web Server...
echo =======================================

:: 1. Optional: Start Ollama in the background if it isn't running
echo Starting Ollama...
start "Ollama Server" cmd /c "ollama serve"
timeout /t 2 >nul

:: 2. Start the Agent in a new window
echo Starting Bear Agent...
start "Bear Agent" cmd /k "cd Agent\Bear && python agent.py"

:: 3. Start the Web Server in a new window
:: (If your webserver.py is in a specific folder like Web/, change this to: cd Web && python webserver.py)
echo Starting Web Server...
start "Bear Web Server" cmd /k "python webserver.py"

echo.
echo All services have been launched in separate windows!
echo You can now close this launcher window.
timeout /t 5 >nul
exit