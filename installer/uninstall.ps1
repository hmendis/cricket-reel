# Cricket Reel - uninstaller. Removes the app, its shortcuts and the Settings > Apps entry.
# Your matches (Videos\Cricket Reels, or the folder you chose) and settings (%APPDATA%\CricketReel) are kept.
param([switch]$Quiet)
$dest = Join-Path $env:LOCALAPPDATA "Programs\Cricket Reel"
if (Get-Process -Name "Cricket Reel" -ErrorAction SilentlyContinue) {
    if (-not $Quiet) { Write-Host "Close Cricket Reel first, then uninstall again."; Read-Host "Press Enter to exit" }
    exit 1
}
if (-not $Quiet) {
    $a = Read-Host "Uninstall Cricket Reel? Your matches and settings are kept. (y/N)"
    if ($a -notmatch '^[yY]') { exit 0 }
}
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Cricket Reel.lnk") -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Cricket Reel.lnk") -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CricketReel" -Recurse -ErrorAction SilentlyContinue
# The script lives inside the folder it deletes: hand the final delete to a short-lived background shell.
Start-Process -WindowStyle Hidden powershell.exe -ArgumentList "-NoProfile -Command `"Start-Sleep 2; Remove-Item -LiteralPath '$dest' -Recurse -Force`""
if (-not $Quiet) { Write-Host "Cricket Reel has been uninstalled. Your matches and settings were kept." }
