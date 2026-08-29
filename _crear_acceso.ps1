# Crea el acceso directo de VideoMaker Automatico en el Escritorio.
# Lo llama "INSTALAR - doble clic la primera vez.bat".

$ErrorActionPreference = "Stop"

$carpeta   = $PSScriptRoot
$lanzador  = Join-Path $carpeta "Iniciar VideoMaker.vbs"
$icono     = Join-Path $carpeta "logo_vm.ico"
$escritorio = [Environment]::GetFolderPath("DesktopDirectory")
$destino   = Join-Path $escritorio "VideoMaker Automatico.lnk"

Write-Host ""
Write-Host "  VideoMaker Automatico - instalacion" -ForegroundColor Cyan
Write-Host "  -----------------------------------"
Write-Host ""

if (-not (Test-Path $lanzador)) {
    Write-Host "  ERROR: falta 'Iniciar VideoMaker.vbs'." -ForegroundColor Red
    Write-Host "  Descomprime el RAR COMPLETO y ejecuta esto desde ahi."
    exit 1
}

# --- Revisar que haya Python ------------------------------------------------
$python = $null
foreach ($c in @("$env:WINDIR\pyw.exe",
                 "$env:LOCALAPPDATA\Programs\Python\Launcher\pyw.exe")) {
    if (Test-Path $c) { $python = $c; break }
}
if (-not $python) {
    $encontrado = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Directory -ErrorAction SilentlyContinue |
                  ForEach-Object { Join-Path $_.FullName "pythonw.exe" } |
                  Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($encontrado) { $python = $encontrado }
}
if (-not $python) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source }
}

if ($python) {
    Write-Host "  [OK] Python encontrado:" -ForegroundColor Green
    Write-Host "       $python"
} else {
    Write-Host "  [!] NO se encontro Python en esta PC." -ForegroundColor Yellow
    Write-Host "      Instalalo desde https://www.python.org/downloads/"
    Write-Host "      y marca la casilla 'Add Python to PATH'."
    Write-Host "      Luego vuelve a ejecutar este instalador."
}

# --- ffmpeg incluido --------------------------------------------------------
if ((Test-Path (Join-Path $carpeta "bin\ffmpeg.exe")) -and
    (Test-Path (Join-Path $carpeta "bin\ffprobe.exe"))) {
    Write-Host "  [OK] ffmpeg incluido en la carpeta 'bin'." -ForegroundColor Green
} else {
    Write-Host "  [!] Falta la carpeta 'bin' con ffmpeg." -ForegroundColor Yellow
    Write-Host "      Descomprime el RAR completo otra vez."
}

# --- Crear el acceso directo ------------------------------------------------
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($destino)
$s.TargetPath       = $lanzador
$s.WorkingDirectory = $carpeta
$s.IconLocation     = "$icono,0"
$s.Description      = "Crea los videos del canal automaticamente"
$s.Save()

Write-Host "  [OK] Acceso directo creado en el Escritorio." -ForegroundColor Green
Write-Host ""
Write-Host "  LISTO. Ya puedes cerrar esta ventana y abrir" -ForegroundColor Cyan
Write-Host "  'VideoMaker Automatico' desde el Escritorio." -ForegroundColor Cyan
Write-Host ""
Write-Host "  (Si mueves esta carpeta de sitio, vuelve a ejecutar el instalador.)"
Write-Host ""
