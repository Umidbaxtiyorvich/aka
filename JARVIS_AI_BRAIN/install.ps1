# JARVIS AI BRAIN - Windows o'rnatuvchisi (bitta buyruq).
#
# PowerShell'ni oching va quyidagini qo'ying (yangi powershell.exe ochilmaydi):
#   irm https://raw.githubusercontent.com/Umidbaxtiyorvich/aka/ccr-f1c0e6d1-uu59k9/JARVIS_AI_BRAIN/install.ps1 | iex
#
# Nima qiladi (har bir katta yuklashdan oldin so'raydi):
#   1. Python 3.12 (yo'q bo'lsa, winget orqali, faqat sizning foydalanuvchingiz uchun)
#   2. Git (ixtiyoriy, o'zini yaxshilash uchun), JARVIS kodi (GitHub'dan), .venv va kutubxonalar
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
# Git: JARVIS'ning o'zini yaxshilash (taklif -> test -> tasdiq -> branch -> merge) uchun kerak
$UseGit = Have "git"
if (-not $UseGit -and (Ask "Git o'rnatilsinmi (~60 MB)? U JARVIS'ga sizning tasdig'ingiz bilan o'zini yaxshilash uchun kerak")) {
    WingetInstall "Git.Git" "Git" | Out-Null
    $UseGit = Have "git"
}
function G { & git -C $InstallDir -c user.name=JARVIS -c user.email=jarvis@localhost @args }
if ($UseGit -and -not (Test-Path (Join-Path $InstallDir ".git"))) {
    # Birinchi marta (yoki eski ZIP o'rnatishdan o'tish): kod nusxalanadi va mahalliy git tarixi boshlanadi
    robocopy $srcDir $InstallDir /E /XD data .venv /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Fayllarni nusxalashda xato (robocopy $LASTEXITCODE)" }
    G init -q
    G config core.autocrlf false
    G checkout -q -b main
    G add -A
    G commit -q -m "JARVIS o'rnatildi ($Branch)"
    G branch upstream
    Say "Git tarixi yaratildi (o'zini yaxshilash yoqilishi mumkin)." "Green"
} elseif ($UseGit) {
    # Yangilash: GitHub nusxasi 'upstream' branch'iga yoziladi, keyin sizning versiyangizga birlashtiriladi.
    # Siz tasdiqlagan mahalliy yaxshilanishlar shu tufayli o'chib ketmaydi.
    $wt = Join-Path $env:TEMP ("jarvis_up_" + [guid]::NewGuid().ToString("N"))
    G worktree prune
    G worktree add -q $wt upstream
    robocopy $srcDir $wt /MIR /XD data .venv .git /XF .git /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Fayllarni nusxalashda xato (robocopy $LASTEXITCODE)" }
    & git -C $wt add -A
    if (& git -C $wt status --porcelain) { & git -C $wt -c user.name=JARVIS -c user.email=jarvis@localhost commit -q -m "Yangilash ($Branch)" }
    G worktree remove --force $wt
    if (G status --porcelain --untracked-files=no) {
        Say "Kodda saqlanmagan o'zgarishlar bor - yangilanish o'tkazilmadi (eski versiya ishlayveradi)." "Yellow"
    } else {
        G merge -q --no-edit upstream
        if ($LASTEXITCODE -ne 0) {
            G merge --abort
            Say "Yangilanish mahalliy o'zgarishlaringiz bilan to'qnashdi - o'tkazilmadi. Eski versiya ishlayveradi." "Yellow"
        }
    }
} else {
    Say "Git yo'q: kod oddiy nusxalanadi, o'zini yaxshilash (git) o'chiq bo'ladi." "Yellow"
    # Kod yangilanadi; data\ (xotira, sozlamalar) va .venv saqlanadi
    robocopy $srcDir $InstallDir /E /XD data .venv /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Fayllarni nusxalashda xato (robocopy $LASTEXITCODE)" }
}
$global:LASTEXITCODE = 0
Remove-Item -Recurse -Force $tmp
Say "Kod: $InstallDir" "Green"

# --- 3. Virtual muhit va kutubxonalar ---
Set-Location $InstallDir
$parts = $Py.Split(" ")
# Uzilib qolgan o'rnatishdan qolgan buzuq .venv'ni aniqlash va qayta yaratish
if (Test-Path ".venv") {
    $ok = $false
    if (Test-Path ".venv\Scripts\python.exe") {
        try { & ".venv\Scripts\python.exe" -c "import pip" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
    }
    if (-not $ok) {
        Say "Eski .venv buzilgan (o'rnatish uzilgan bo'lishi mumkin) - qayta yaratiladi..." "Yellow"
        Remove-Item -Recurse -Force ".venv"
    }
    $global:LASTEXITCODE = 0
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Say "Virtual muhit yaratilmoqda (.venv)..."
    & $parts[0] $parts[1..9] -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv yaratilmadi" }
}
$VPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
Say "pip yangilanmoqda..."
& $VPy -m pip install --upgrade pip --disable-pip-version-check --progress-bar on
Say "Kutubxonalar o'rnatilmoqda (~60 MB, internetga qarab 2-10 daqiqa). Oynani yopmang..."
& $VPy -m pip install -r requirements.txt --disable-pip-version-check --progress-bar on
if ($LASTEXITCODE -ne 0) { throw "Kutubxonalar o'rnatilmadi (internetni tekshiring)" }
& $VPy -c "import jarvis.core; print('JARVIS', __import__('jarvis').__version__, 'tayyor')"
if ($LASTEXITCODE -ne 0) { throw "JARVIS yuklanmadi" }

# --- 4. Ixtiyoriy komponentlar ---
if (Ask "Brauzer agenti (YesPOS hisobotlarini o'qish uchun, Chromium ~150 MB) o'rnatilsinmi?") {
    Say "Playwright o'rnatilmoqda..."
    & $VPy -m pip install playwright --disable-pip-version-check
    Say "Chromium yuklanmoqda (~150 MB)..."
    & $VPy -m playwright install chromium
}
if (-not (Have "ffmpeg") -and (Ask "FFmpeg (video studiya, ~100 MB) o'rnatilsinmi?")) { WingetInstall "Gyan.FFmpeg" "FFmpeg" | Out-Null }
if (-not (Have "espeak-ng") -and (Ask "espeak-ng (o'zbekcha ovoz, ~5 MB) o'rnatilsinmi?")) {
    if (-not (WingetInstall "eSpeak-NG.eSpeak-NG" "espeak-ng")) {
        Say "  espeak-ng'ni qo'lda o'rnating: https://github.com/espeak-ng/espeak-ng/releases (espeak-ng.msi)" "Yellow"
    }
}
if (Ask "Ovozni mahalliy tanish (faster-whisper, ~100 MB; model keyin dashboard'dan yuklanadi) o'rnatilsinmi?") {
    Say "faster-whisper o'rnatilmoqda..."
    & $VPy -m pip install faster-whisper --disable-pip-version-check
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
rem Server allaqachon ishlayotgan bo'lsa, qayta ishga tushirilmaydi
curl.exe -s -o nul http://127.0.0.1:8765/api/auth/status && goto open
start "" /min "$InstallDir\.venv\Scripts\pythonw.exe" -m jarvis.api --port 8765
echo JARVIS ishga tushmoqda...
for /l %%i in (1,1,60) do (
  curl.exe -s -o nul http://127.0.0.1:8765/api/auth/status && goto open
  timeout /t 1 /nobreak >nul
)
echo JARVIS ishga tushmadi. Sababi: data\logs\server.log
echo Qo'lda tekshirish: .venv\Scripts\python.exe -m jarvis.api
pause
exit /b 1
:open
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
    # Shu jarayonning o'zida (yangi powershell.exe ochmasdan) ishga tushiriladi
    & (Join-Path $InstallDir "scripts\install_autostart.ps1")
}

Say ""
Say "=== Tayyor ===" "Green"
Say "Ochish: ish stolidagi 'JARVIS' yorlig'i yoki http://127.0.0.1:8765"
Say "Birinchi kirishda PIN o'rnatasiz. YesPOS: POS ulanishi -> 'YesPOS sozlamasi' -> 'POS'ga kirish'."
Say "Yangilash: shu buyruqni qayta ishga tushiring (xotira saqlanadi)."
if (-not $NoLaunch) { Start-Process $launcher }
