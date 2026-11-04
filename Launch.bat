@echo off
REM Project: 3D Printing Model Prompt
REM File: Launch.bat
REM Description: Double-click launcher. Finds free host ports for
REM   the app and the bundled Ollama (or reuses the ones already resolved),
REM   starts the stack, and opens the app in your browser. Same as
REM   `python launch.py up` then `python launch.py open`. See launch.py.
REM Inputs: none (APP_HOST_PORT / OLLAMA_HOST_PORT in .env pin the ports;
REM   OLLAMA_HOST or LLM_PROVIDER=claude in .env skips the bundled Ollama).
REM Outputs: the running stack and a browser tab.
REM Troubleshooting: "python is not recognized" -- install Python 3.11+ and tick
REM   "Add to PATH"; Docker Desktop must be running.
cd /d "%~dp0"
python launch.py up
if errorlevel 1 goto :error
python launch.py open
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Something went wrong -- see the messages above.
pause
