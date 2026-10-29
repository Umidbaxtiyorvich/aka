# JARVIS'ni Windows 11'da sozlash. Faqat loyiha papkasi ichida .venv yaratadi va kutubxonalarni o'rnatadi.
# Windows sozlamalari, boshqa dasturlar yoki AI modellari O'ZGARTIRILMAYDI / yuklanmaydi.
# Ishga tushirish (loyiha papkasida): powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.11+ o'rnating: https://www.python.org/downloads/ (Add to PATH belgilang)" }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
Write-Host "Tayyor. Ishga tushirish: scripts\start_windows.ps1" -ForegroundColor Green
Write-Host "Ma'lumotlar papkasini boshqa diskda saqlash uchun (ixtiyoriy):  setx JARVIS_HOME D:\JARVIS_DATA"
