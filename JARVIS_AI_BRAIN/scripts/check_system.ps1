# JARVIS diagnostikasi (Windows 11). Hech narsani o'zgartirmaydi — faqat o'qiydi.
# Ishga tushirish: powershell -ExecutionPolicy Bypass -File scripts\check_system.ps1
Write-Host "=== JARVIS tizim diagnostikasi ===" -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
Write-Host ("OS: {0} (build {1})" -f $os.Caption, $os.BuildNumber)
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Write-Host ("CPU: {0}, yadrolar: {1}, oqimlar: {2}" -f $cpu.Name, $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
Write-Host ("RAM: {0:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB))
Write-Host "`n--- GPU ---"
Get-CimInstance Win32_VideoController | ForEach-Object {
    Write-Host ("GPU: {0}  | AdapterRAM: {1:N1} GB (4 GB dan katta bo'lsa noto'g'ri ko'rsatishi mumkin)" -f $_.Name, ($_.AdapterRAM / 1GB))
}
# Aniq VRAM (registr orqali, faqat o'qish)
Get-ItemProperty "HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*" -ErrorAction SilentlyContinue |
    Where-Object { $_."HardwareInformation.qwMemorySize" } | ForEach-Object {
        Write-Host ("Aniq VRAM: {0} = {1:N1} GB" -f $_.DriverDesc, ($_."HardwareInformation.qwMemorySize" / 1GB))
    }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { nvidia-smi --query-gpu=name,memory.total --format=csv }
Write-Host "Qo'lda tekshirish: Win+R -> dxdiag -> Display (Display Memory)"
Write-Host "`n--- Disklar ---"
Get-PSDrive -PSProvider FileSystem | ForEach-Object { Write-Host ("{0}: bo'sh {1:N1} GB" -f $_.Name, ($_.Free / 1GB)) }
Write-Host "`n--- Dasturlar ---"
foreach ($t in "python", "git", "ollama", "ffmpeg") {
    $c = Get-Command $t -ErrorAction SilentlyContinue
    if ($c) { Write-Host "[+] $t : $($c.Source)" -ForegroundColor Green } else { Write-Host "[-] $t topilmadi" -ForegroundColor Yellow }
}
