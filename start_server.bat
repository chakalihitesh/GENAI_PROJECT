@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting CodeLens AI Unified Application...
echo URL: http://localhost:8000  or  http://127.0.0.1:8000
echo ========================================================
python -m uvicorn main:app --app-dir "%~dp0backend" --host 0.0.0.0 --port 8000
pause
