# JARVIS AI BRAIN - Windows o'rnatuvchisi (bitta buyruq).
#
# PowerShell'ni oching va quyidagini qo'ying:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Umidbaxtiyorvich/aka/ccr-f1c0e6d1-uu59k9/JARVIS_AI_BRAIN/install.ps1 | iex"
#
# Nima qiladi (har bir katta yuklashdan oldin so'raydi):
#   1. Python 3.12 (yo'q bo'lsa, winget orqali, faqat sizning foydalanuvchingiz uchun)
#   2. JARVIS kodi (GitHub'dan), .venv va kutubxonalar
#   3. Ixtiyoriy: brauzer agenti (Chromium ~150 MB), FFmpeg, espeak-ng (o'zbekcha ovoz), Ollama + mahalliy AI modellari
#   4. Ish stolida "JARVIS" yorlig'i, ixtiyoriy avtomatik ishga tushirish
# Windows sozlamalari o'zgartirilmaydi, administrator huquqi so'ralmaydi. Mavjud data\ papkasi (xotira) saqlanadi.
param(
    [string]$InstallDir = "",
    [string]$Branch = "ccr-f1c0e6d1-uu59k9",
    [switch]$Yes,          # barcha savollarga "ha"
    [switch]$Minimal,      # ixtiyoriy komponentlarsiz (CI va tez sinov uchun)
    [switch]$NoLaunch      # oxirida ishga tushirmaslik
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = "Umidbaxtiyorvich/aka"

function Say($t, $c = "Cyan") { Write-Host $t -ForegroundColor $c }
function Ask($q) {
    if ($Yes) { return $true }
    if ($Minimal) { return $false }
    $a = Read-Host "$q [H/y] (H = ha)"
    return ($a -eq "" -or $a -match "^(h|ha|y|yes)$")
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function RefreshPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function WingetInstall($id, $name) {
    if (-not (Have "winget")) { Say "  winget topilmadi - $name ni qo'lda o'rnating." "Yellow"; return $false }
    Say "  winget install $id ..."
    winget install -e --id $id --scope user --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        winget install -e --id $id --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Host
    }
    RefreshPath
    return ($LASTEXITCODE -eq 0)
}

Say "=== JARVIS AI BRAIN o'rnatuvchisi ===" "Green"

# --- 0. Joy tanlash ---
if (-not $InstallDir) {
    $d = Get-PSDrive -Name D -PSProvider FileSystem -ErrorAction SilentlyContinue
    if ($d -and $d.Free -gt 10GB) { $InstallDir = "D:\JARVIS_AI_BRAIN" } else { $InstallDir = Join-Path $env:USERPROFILE "JARVIS_AI_BRAIN" }
}
Say "O'rnatish joyi: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# --- 1. Python ---
function FindPython {
    foreach ($c in @("py -3.12", "py -3.13", "py -3.11", "python")) {
        $parts = $c.Split(" ")
        try {
            $v = & $parts[0] $parts[1..9] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -and ([version]$v -ge [version]"3.11")) { return $c }
        } catch {}
    }
    return $null
}
$Py = FindPython
if (-not $Py) {
    Say "Python 3.11+ topilmadi."
    if (Ask "Python 3.12 o'rnatilsinmi (~30 MB, winget)?") {
        WingetInstall "Python.Python.3.12" "Python" | Out-Null
        $Py = FindPython
    }
    if (-not $Py) { throw "Python o'rnatilmadi. https://www.python.org/downloads/ dan o'rnating ('Add to PATH' ni belgilang) va qayta ishga tushiring." }
}
Say "Python: $Py" "Green"

# --- 2. JARVIS kodi ---
Say "JARVIS kodi yuklanmoqda ($Branch)..."
$tmp = Join-Path $env:TEMP ("jarvis_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$zip = Join-Path $tmp "src.zip"
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem -Path $tmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "JARVIS_AI_BRAIN") } | Select-Object -First 1
if (-not $src) { throw "Arxivda JARVIS_AI_BRAIN papkasi topilmadi" }
$srcDir = Join-Path $src.FullName "JARVIS_AI_BRAIN"
# Kod yangilanadi; data\ (xotira, sozlamalar) va .venv saqlanadi
robocopy $srcDir $InstallDir /E /XD data .venv /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Fayllarni nusxalashda xato (robocopy $LASTEXITCODE)" }
$global:LASTEXITCODE = 0
Remove-Item -Recurse -Force $tmp
Say "Kod: $InstallDir" "Green"

# --- 3. Virtual muhit va kutubxonalar ---
Set-Location $InstallDir
$parts = $Py.Split(" ")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $parts[0] $parts[1..9] -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv yaratilmadi" }
}
$VPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
& $VPy -m pip install --upgrade pip --quiet
& $VPy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Kutubxonalar o'rnatilmadi (internetni tekshiring)" }
& $VPy -c "import jarvis.core; print('JARVIS', __import__('jarvis').__version__, 'tayyor')"
if ($LASTEXITCODE -ne 0) { throw "JARVIS yuklanmadi" }

# --- 4. Ixtiyoriy komponentlar ---
if (Ask "Brauzer agenti (YesPOS hisobotlarini o'qish uchun, Chromium ~150 MB) o'rnatilsinmi?") {
    & $VPy -m pip install playwright --quiet
    & $VPy -m playwright install chromium
}
if (-not (Have "ffmpeg") -and (Ask "FFmpeg (video studiya, ~100 MB) o'rnatilsinmi?")) { WingetInstall "Gyan.FFmpeg" "FFmpeg" | Out-Null }
if (-not (Have "espeak-ng") -and (Ask "espeak-ng (o'zbekcha ovoz, ~5 MB) o'rnatilsinmi?")) {
    if (-not (WingetInstall "eSpeak-NG.eSpeak-NG" "espeak-ng")) {
        Say "  espeak-ng'ni qo'lda o'rnating: https://github.com/espeak-ng/espeak-ng/releases (espeak-ng.msi)" "Yellow"
    }
}
if (Ask "Ovozni mahalliy tanish (faster-whisper, ~100 MB; model keyin dashboard'dan yuklanadi) o'rnatilsinmi?") {
    & $VPy -m pip install faster-whisper --quiet
}
if (-not (Have "ollama") -and (Ask "Ollama (mahalliy AI dvigateli, ~1 GB) o'rnatilsinmi?")) { WingetInstall "Ollama.Ollama" "Ollama" | Out-Null }
if (Have "ollama") {
    & $VPy scripts\setup_ai.py
    if (Ask "Yuqoridagi AI modellari sozlanib, yuklansinmi (~4.6 GB)?") {
        Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        $yesArg = @()
        if ($Yes) { $yesArg = @("--yes") }
        & $VPy scripts\setup_ai.py --apply --pull @yesArg
    }
}

# --- 5. Yorliq va ishga tushirish ---
$launcher = Join-Path $InstallDir "JARVIS.cmd"
@"
@echo off
cd /d "$InstallDir"
start "" /min "$InstallDir\.venv\Scripts\pythonw.exe" -m jarvis.api --port 8765
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8765
"@ | Set-Content -Path $launcher -Encoding ASCII
try {
    $desk = [Environment]::GetFolderPath("Desktop")
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk "JARVIS.lnk"))
    $sh.TargetPath = $launcher
    $sh.WorkingDirectory = $InstallDir
    $sh.WindowStyle = 7
    $sh.Description = "JARVIS AI BRAIN"
    $sh.Save()
    Say "Ish stolida 'JARVIS' yorlig'i yaratildi." "Green"
} catch { Say "Yorliq yaratilmadi: $launcher ni ishga tushiring." "Yellow" }
if (Ask "Windows'ga kirganda JARVIS avtomatik ishga tushsinmi?") {
    powershell -ExecutionPolicy Bypass -File (Join-Path $InstallDir "scripts\install_autostart.ps1")
}

Say ""
Say "=== Tayyor ===" "Green"
Say "Ochish: ish stolidagi 'JARVIS' yorlig'i yoki http://127.0.0.1:8765"
Say "Birinchi kirishda PIN o'rnatasiz. YesPOS: POS ulanishi -> 'YesPOS sozlamasi' -> 'POS'ga kirish'."
Say "Yangilash: shu buyruqni qayta ishga tushiring (xotira saqlanadi)."
if (-not $NoLaunch) { Start-Process $launcher }
