@echo off
set PYTHONPATH=K:\DIY\videobot\app
cd /d K:\DIY\videobot\app
python -m uvicorn main:app --host 127.0.0.1 --port 8000