@echo off
cd /d "%~dp0"
if not exist .venv (py -m venv .venv || python -m venv .venv)
call .venv\Scripts\activate
pip install -q -r requirements.txt
start "" http://127.0.0.1:8000
python -m uvicorn main:app --reload
pause
