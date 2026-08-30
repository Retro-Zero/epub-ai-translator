@echo off
title EPUB AI Translator
cd /d "C:\Users\hp\Desktop\Project\Translator\backend"
start "" http://127.0.0.1:8000
"C:\Users\hp\Desktop\Project\Translator\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000 --host 127.0.0.1
pause
