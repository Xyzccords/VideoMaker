"""
notificaciones.py
-----------------
Avisos de Windows para "VideoMaker Automatico".

Muestra una notificacion nativa (la que sale en la esquina inferior derecha
y queda guardada en el Centro de notificaciones) cuando termina el proceso.
No necesita instalar nada: usa PowerShell, que ya viene con Windows.

Si por lo que sea la notificacion nativa no funciona, al menos suena un
pitido, y la interfaz siempre muestra ademas un resumen en pantalla.
"""

import os
import subprocess
import tempfile
import threading

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICONO = os.path.join(BASE_DIR, "logo_vm.png")


def _escapar_xml(texto):
    return (
        str(texto)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pitido(exito=True):
    try:
        import winsound
        winsound.MessageBeep(
            winsound.MB_ICONASTERISK if exito else winsound.MB_ICONHAND
        )
    except Exception:
        pass


def notificar(titulo, mensaje, exito=True):
    """Lanza una notificacion de Windows. Nunca levanta excepciones."""
    _pitido(exito)

    imagen = ""
    if os.path.isfile(ICONO):
        imagen = (
            f'<image placement="appLogoOverride" hint-crop="circle" '
            f'src="{_escapar_xml(ICONO)}"/>'
        )

    xml = (
        '<toast activationType="protocol" launch="file:///'
        + _escapar_xml(BASE_DIR).replace("\\", "/")
        + '"><visual><binding template="ToastGeneric">'
        + imagen
        + f"<text>{_escapar_xml(titulo)}</text>"
        + f'<text>{_escapar_xml(mensaje)}</text>'
        + "</binding></visual></toast>"
    )

    script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml(@'
{xml}
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($toast)
"""

    def _enviar():
        # Arrancar PowerShell tarda un par de segundos, asi que va en su propio
        # hilo: la ventana del programa no se queda congelada mientras tanto.
        ruta_ps = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".ps1", delete=False, encoding="utf-8-sig"
            ) as f:
                f.write(script)
                ruta_ps = f.name

            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", ruta_ps],
                capture_output=True, timeout=25, creationflags=_SIN_VENTANA,
            )
        except Exception:
            pass
        finally:
            if ruta_ps:
                try:
                    os.remove(ruta_ps)
                except OSError:
                    pass

    threading.Thread(target=_enviar, daemon=True).start()


def notificar_resumen(resumen):
    """Construye el aviso final a partir del resumen que devuelve el core."""
    hechos = resumen.get("hechos", 0)
    errores = resumen.get("errores", [])
    omitidos = resumen.get("omitidos", 0)

    if resumen.get("cancelado"):
        titulo = "Proceso cancelado"
        cuerpo = f"Se alcanzaron a crear {hechos} video(s) antes de cancelar."
        notificar(titulo, cuerpo, exito=False)
        return titulo, cuerpo

    avisos = resumen.get("avisos", [])
    partes = [f"{hechos} video(s) creados"]
    if omitidos:
        partes.append(f"{omitidos} ya existian")

    if errores:
        titulo = "Termino con errores"
        partes.append(f"{len(errores)} con error")
        cuerpo = ", ".join(partes) + ".\n" + errores[0][:160]
        notificar(titulo, cuerpo, exito=False)
    elif avisos:
        titulo = "Terminado, pero revisa esto"
        partes.append(f"{len(avisos)} aviso(s)")
        cuerpo = ", ".join(partes) + ".\n" + avisos[0][:160]
        notificar(titulo, cuerpo, exito=False)
    else:
        titulo = "¡Videos terminados!"
        cuerpo = ", ".join(partes) + "."
        notificar(titulo, cuerpo, exito=True)

    return titulo, cuerpo


if __name__ == "__main__":
    notificar("VideoMaker Automatico", "Prueba de notificacion. Si ves esto, funciona.")
