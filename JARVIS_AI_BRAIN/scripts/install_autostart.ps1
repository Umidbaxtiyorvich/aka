# JARVIS'ni Windows'ga kirganda avtomatik ishga tushirish (ixtiyoriy). Administrator huquqi KERAK EMAS.
# O'rnatish:   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
# O'chirish:   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Uninstall
# Faqat joriy foydalanuvchi uchun "Logon" vazifasi yaratiladi; server faqat 127.0.0.1 da ishlaydi.
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$TaskName = "JARVIS_AI_BRAIN"
if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Avtomatik ishga tushirish o'chirildi." -ForegroundColor Green
    exit 0
}
$Root = Split-Path $PSScriptRoot -Parent
$Py = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Py)) { throw "Avval scripts\setup_windows.ps1 ni ishga tushiring (.venv topilmadi)" }
$Action = New-ScheduledTaskAction -Execute $Py -Argument "-m jarvis.api --port 8765" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Xato bilan to'xtasa — 1 daqiqadan keyin qayta ishga tushadi (3 martagacha)
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 365) -AllowStartIfOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host "Tayyor: Windows'ga kirganingizda JARVIS fon rejimida ishga tushadi (http://127.0.0.1:8765)." -ForegroundColor Green
Write-Host "Hozir ishga tushirish: Start-ScheduledTask -TaskName $TaskName"
