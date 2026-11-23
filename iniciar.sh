#!/bin/sh
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate && pip install -q -r requirements.txt
(sleep 2; xdg-open http://127.0.0.1:8000 2>/dev/null || open http://127.0.0.1:8000) &
python -m uvicorn main:app --reload
