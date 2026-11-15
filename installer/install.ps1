# Cricket Reel - per-user installer (no admin needed).
# Copies the app to %LOCALAPPDATA%\Programs\Cricket Reel, adds a Start menu entry, an optional desktop
# shortcut, and an entry in Settings > Apps so it can be uninstalled. Your matches and settings live in
# your user folders and are never touched by installing, updating or uninstalling.
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA "Programs\Cricket Reel"
$exeName = "Cricket Reel.exe"

Write-Host ""
Write-Host "  Installing Cricket Reel to $dest" -ForegroundColor Green
if (Get-Process -Name "Cricket Reel" -ErrorAction SilentlyContinue) {
    Write-Host "  Cricket Reel is running - close it first, then run the installer again." -ForegroundColor Yellow
    Read-Host "  Press Enter to exit"; exit 1
}
if ((Resolve-Path $src).Path -ne $dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item (Join-Path $src "*") $dest -Recurse -Force
}
$exe = Join-Path $dest $exeName
$icon = Join-Path $dest "_internal\assets\icon.ico"
if (-not (Test-Path $icon)) { $icon = $exe }

$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = $exe
    $s.WorkingDirectory = $dest
    $s.IconLocation = $icon
    $s.Description = "Cricket Reel - batting highlight reels"
    $s.Save()
}
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Cricket Reel.lnk"
New-Shortcut $startMenu
Write-Host "  Added to the Start menu."

$answer = Read-Host "  Add a desktop shortcut too? (Y/n)"
if ($answer -notmatch '^[nN]') {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "Cricket Reel.lnk")
    Write-Host "  Desktop shortcut added."
}

# Settings > Apps entry (current user)
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CricketReel"
New-Item -Path $key -Force | Out-Null
$size = [int]((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$un = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
@{ DisplayName = "Cricket Reel"; DisplayIcon = $icon; DisplayVersion = "1.0.0"; Publisher = "Cricket Reel";
   InstallLocation = $dest; UninstallString = $un; QuietUninstallString = "$un -Quiet"; NoModify = 1; NoRepair = 1;
   EstimatedSize = $size }.GetEnumerator() | ForEach-Object {
    $type = if ($_.Value -is [int]) { "DWord" } else { "String" }
    New-ItemProperty -Path $key -Name $_.Key -Value $_.Value -PropertyType $type -Force | Out-Null
}

Write-Host ""
Write-Host "  Done. Start Cricket Reel from the Start menu." -ForegroundColor Green
$run = Read-Host "  Open it now? (Y/n)"
if ($run -notmatch '^[nN]') { Start-Process $exe }
