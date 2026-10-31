# JARVIS'ni yangilash (mahalliy skript). "JARVIS yangilash" yorlig'i, JARVIS.exe --update va dashboard tugmasi shuni ishga tushiradi.
# O'rnatuvchi avval FAYLGA yuklanadi, keyin shu fayldan bajariladi ("irm | iex" emas — antivirus/Windows bloklamasligi uchun).
# Xotira va sozlamalar (data\) saqlanadi.
param(
    [string]$Branch = "ccr-f1c0e6d1-uu59k9",
    [switch]$Yes,
    [switch]$Minimal,
    [switch]$NoLaunch
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path $PSScriptRoot -Parent
$File = Join-Path $env:TEMP ("jarvis_install_" + [guid]::NewGuid().ToString("N") + ".ps1")
Write-Host "JARVIS yangilanmoqda: $Root" -ForegroundColor Green
Write-Host "Yangi o'rnatuvchi yuklanmoqda..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/Umidbaxtiyorvich/aka/$Branch/JARVIS_AI_BRAIN/install.ps1" -OutFile $File
} catch {
    Write-Host "Yuklab bo'lmadi: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Internetni tekshiring va qayta urining." -ForegroundColor Yellow
    exit 1
}
$params = @{ InstallDir = $Root; Branch = $Branch }
if ($Yes) { $params.Yes = $true }
if ($Minimal) { $params.Minimal = $true }
if ($NoLaunch) { $params.NoLaunch = $true }
try { & $File @params } finally { Remove-Item $File -Force -ErrorAction SilentlyContinue }
