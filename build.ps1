<#
.SYNOPSIS
    Script di compilazione dell'eseguibile unico per English Assessment Engine.
.PARAMETER SkipBuild
    Se specificato, non ricompila (utile per creare solo il collegamento).
.PARAMETER Shortcut
    Se specificato, crea un collegamento "English Assessment Engine.lnk" sul Desktop.
#>
param(
    [switch]$Shortcut,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# Individuazione interprete Python (py launcher o python)
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "py" }

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Compilazione English Assessment Engine (PyInstaller)" -ForegroundColor Cyan
Write-Host "  Interprete: $pythonCmd" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$exePath = Join-Path $scriptDir "dist\AssessmentEngine.exe"

if (-not $SkipBuild) {
    if (Test-Path $exePath) { Remove-Item $exePath -Force }
    # PyInstaller scrive i log su stderr: con "Stop" PowerShell 5.1 li tratterebbe come errori
    $ErrorActionPreference = "Continue"
    & $pythonCmd -m PyInstaller AssessmentEngine.spec --clean --noconfirm
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller terminato con codice $LASTEXITCODE" }
}
if (-not (Test-Path $exePath)) {
    Write-Error "Build fallita: l'eseguibile non e stato generato in $exePath"
}

$exeSizeMB = [math]::Round(((Get-Item $exePath).Length / 1MB), 2)
Write-Host ""
Write-Host "Eseguibile creato con successo:" -ForegroundColor Green
Write-Host "  Percorso:   $exePath" -ForegroundColor Green
Write-Host "  Dimensione: $exeSizeMB MB" -ForegroundColor Green

if ($Shortcut) {
    try {
        $desktopPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
        $shortcutFile = Join-Path $desktopPath "English Assessment Engine.lnk"
        $wshShell = New-Object -ComObject WScript.Shell
        $lnk = $wshShell.CreateShortcut($shortcutFile)
        $lnk.TargetPath = $exePath
        $lnk.WorkingDirectory = (Split-Path $exePath -Parent)
        $lnk.Description = "English Assessment Engine - Diagnostic Report Generator"
        $lnk.Save()
        Write-Host "Collegamento creato sul Desktop:" -ForegroundColor Green
        Write-Host "  $shortcutFile" -ForegroundColor Green
    }
    catch {
        Write-Warning "Impossibile creare il collegamento sul Desktop: $_"
    }
}

Write-Host ""
Write-Host "Operazione completata." -ForegroundColor Cyan
