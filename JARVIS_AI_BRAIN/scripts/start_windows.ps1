# JARVIS serverini ishga tushiradi (faqat shu kompyuterdan: http://127.0.0.1:8765)
Set-Location (Split-Path $PSScriptRoot -Parent)
Start-Process "http://127.0.0.1:8765"
.\.venv\Scripts\python.exe -m jarvis.api --port 8765
