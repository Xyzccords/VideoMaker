"""
crear_acceso_directo.py
-----------------------
Crea el acceso directo de "VideoMaker Automatico" en el Escritorio, con el
logo VM y apuntando a pythonw.exe (por eso NO se abre la ventana negra de CMD).

Ejecutalo una sola vez:

    python crear_acceso_directo.py

Si mueves la carpeta del programa a otro sitio, vuelve a ejecutarlo.
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE_DIR, "videomaker.pyw")
ICO = os.path.join(BASE_DIR, "logo_vm.ico")
NOMBRE = "VideoMaker Automatico"

_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def buscar_pythonw():
    """pythonw.exe es el Python 'sin consola'. Suele estar junto a python.exe."""
    candidato = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.isfile(candidato):
        return candidato
    return sys.executable


def escritorio():
    """Ruta real del Escritorio (funciona aunque este redirigido a OneDrive)."""
    ps = ("[Environment]::GetFolderPath("
          "[Environment+SpecialFolder]::DesktopDirectory)")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=20, creationflags=_SIN_VENTANA,
        )
        ruta = r.stdout.strip()
        if ruta and os.path.isdir(ruta):
            return ruta
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def crear_acceso(destino):
    pythonw = buscar_pythonw()
    icono = ICO if os.path.isfile(ICO) else pythonw

    ps = f"""
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{destino}')
$s.TargetPath       = '{pythonw}'
$s.Arguments        = '"{APP}"'
$s.WorkingDirectory = '{BASE_DIR}'
$s.IconLocation     = '{icono}'
$s.Description      = 'Crea los videos del canal automaticamente'
$s.WindowStyle      = 7
$s.Save()
"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, timeout=40, creationflags=_SIN_VENTANA,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "PowerShell no pudo crear el acceso directo")


def main():
    if not os.path.isfile(APP):
        print(f"ERROR: no encuentro {APP}")
        return 1
    if not os.path.isfile(ICO):
        print("AVISO: no existe logo_vm.ico. Ejecuta antes:  python generar_icono.py")

    destinos = [
        os.path.join(escritorio(), f"{NOMBRE}.lnk"),
        os.path.join(BASE_DIR, f"{NOMBRE}.lnk"),
    ]

    for destino in destinos:
        try:
            crear_acceso(destino)
            print(f"Acceso directo creado: {destino}")
        except Exception as e:
            print(f"No se pudo crear {destino}: {e}")

    print("\nListo. Abre el programa con el acceso directo del Escritorio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
