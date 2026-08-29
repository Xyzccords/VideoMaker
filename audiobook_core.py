"""
audiobook_core.py
------------------
Motor de "VideoMaker Automatico".

Se encarga de:
  - Escanear la carpeta del canal (BOLILLO) y detectar solo los fanfics
    que tengan una subcarpeta "Español" con audios dentro.
  - Armar el nombre de salida: "<Titulo del fanfic>_<capitulos>.mp4".
  - Preparar los gameplays una sola vez (ver gameplay_pool.py).
  - Generar cada video pegando gameplay aleatorio debajo del audio.
  - Reportar progreso real (porcentaje + tiempo restante estimado) leyendo
    la salida "-progress" de ffmpeg.

COMO SE HACE CADA VIDEO
-----------------------
Hay dos caminos, y el programa elige solo:

  * Camino rapido (copia): si no hay logo, marca de agua, intro ni outro,
    el video se arma PEGANDO los gameplays ya preparados sin recodificar.
    Es del orden de 50 veces mas rapido que tiempo real.

  * Camino normal (recodifica): si hay logo, marca de agua, intro u outro,
    hay que volver a dibujar la imagen, asi que se recodifica. Aun asi es
    mucho mas rapido que antes porque lee los gameplays ya preparados en
    vez de los originales en 1080p120.
"""

import concurrent.futures
import os
import re
import json
import random
import subprocess
import tempfile
import threading
import time
import unicodedata

import gameplay_pool


AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma")
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm")

CARPETA_VIDEOS = "VIDEOS"
NOMBRES_ESPANOL = ("espanol", "espaniol", "spanish", "es")

# Un audio tocado hace menos de esto se considera "todavia se esta grabando".
SEGUNDOS_RECIEN_ESCRITO = 90
# Un audio que dure menos de esta fraccion de la mediana de su fanfic
# probablemente quedo cortado a medias.
UMBRAL_AUDIO_CORTO = 0.35

# Velocidades medidas en pruebas reales. Solo sirven para repartir la barra
# de progreso entre las etapas; el tiempo restante se recalcula solo.
VEL_PREPARAR = 14.0
VEL_COPIA = 45.0
VEL_RECODIFICAR = 28.0

# Windows: evita que se abra una ventana negra de consola por cada ffmpeg.
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_encoder_cache = None


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _sin_acentos(texto):
    desc = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in desc if not unicodedata.combining(c)).lower().strip()


def _limpiar_nombre(nombre):
    """Quita los caracteres que Windows no permite en nombres de archivo."""
    nombre = re.sub(r'[\\/:*?"<>|]', " ", nombre)
    nombre = re.sub(r"\s+", " ", nombre)
    return nombre.strip(" .")


def formato_tiempo(segundos):
    if segundos is None or segundos < 0:
        return "calculando..."
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


def get_duration(path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, creationflags=_SIN_VENTANA
    )
    info = json.loads(result.stdout)
    dur = info.get("format", {}).get("duration")
    if dur is not None:
        return float(dur)
    for s in info.get("streams", []):
        if s.get("duration"):
            return float(s["duration"])
    raise ValueError("no se pudo leer la duracion")


def list_files(folder, exts):
    files = []
    for entrada in os.scandir(folder):
        if entrada.is_file() and entrada.name.lower().endswith(exts):
            files.append(entrada.path)
    return sorted(files)


def _correr_ffmpeg(cmd, on_progress=None, should_stop=None, prioridad_baja=True):
    """
    Ejecuta ffmpeg leyendo "-progress" y devuelve (ok, cancelado, stderr).
    on_progress recibe los segundos de salida que lleva hechos.

    prioridad_baja hace que Windows le de preferencia a lo que estes usando:
    el video tarda practicamente lo mismo, pero la PC no se siente pesada.
    """
    should_stop = should_stop or (lambda: False)

    banderas = _SIN_VENTANA
    if prioridad_baja:
        banderas |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

    proceso = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", creationflags=banderas,
    )

    cancelado = False
    try:
        for linea in proceso.stdout:
            linea = linea.strip()
            if on_progress and (linea.startswith("out_time_us=")
                                or linea.startswith("out_time_ms=")):
                valor = linea.split("=", 1)[1]
                if valor.isdigit():
                    on_progress(int(valor) / 1_000_000.0)
            if should_stop():
                cancelado = True
                proceso.terminate()
                break
    finally:
        stderr = proceso.stderr.read() if proceso.stderr else ""
        proceso.wait()

    return (proceso.returncode == 0 and not cancelado), cancelado, stderr


# ---------------------------------------------------------------------------
# Escaneo de la carpeta del canal (BOLILLO)
# ---------------------------------------------------------------------------

def _carpeta_espanol(carpeta_fanfic):
    """Busca la subcarpeta de español sin importar acentos ni mayusculas."""
    try:
        for entrada in os.scandir(carpeta_fanfic):
            if entrada.is_dir() and _sin_acentos(entrada.name) in NOMBRES_ESPANOL:
                return entrada.path
    except OSError:
        pass
    return None


def rango_capitulos(nombre_archivo):
    """
    'Capitulo 1 al 11.mp3' -> '1-11'
    'Capitulo 7.mp3'       -> '7'
    'intro.mp3'            -> 'intro'
    """
    base = os.path.splitext(os.path.basename(nombre_archivo))[0]
    numeros = re.findall(r"\d+", base)
    if len(numeros) >= 2:
        return f"{int(numeros[0])}-{int(numeros[-1])}"
    if len(numeros) == 1:
        return str(int(numeros[0]))
    return _limpiar_nombre(base) or "sin_numero"


def _clave_orden(ruta):
    """Ordena 'Capitulo 9 al 16' antes que 'Capitulo 17 al 24'."""
    numeros = re.findall(r"\d+", os.path.basename(ruta))
    return (int(numeros[0]) if numeros else 10**9, os.path.basename(ruta).lower())


def escanear_canal(carpeta_canal):
    """
    Recorre la carpeta del canal (BOLILLO) y devuelve la lista de fanfics.

    Cada elemento es un dict:
        {"titulo": str, "carpeta": str, "carpeta_es": str, "audios": [rutas]}

    Se incluyen tambien los fanfics que todavia no tienen audios (con la
    lista vacia), para que se vean en la interfaz.
    """
    fanfics = []
    if not carpeta_canal or not os.path.isdir(carpeta_canal):
        return fanfics

    for entrada in sorted(os.scandir(carpeta_canal), key=lambda e: e.name.lower()):
        if not entrada.is_dir():
            continue
        if entrada.name.upper() == CARPETA_VIDEOS:
            continue

        carpeta_es = _carpeta_espanol(entrada.path)
        if not carpeta_es:
            continue

        audios = sorted(list_files(carpeta_es, AUDIO_EXTS), key=_clave_orden)

        fanfics.append({
            "titulo": entrada.name,
            "carpeta": entrada.path,
            "carpeta_es": carpeta_es,
            "audios": audios,
        })

    return fanfics


def ruta_salida(carpeta_canal, titulo_fanfic, audio_path):
    """<BOLILLO>/VIDEOS/<Titulo del fanfic>_<capitulos>.mp4"""
    carpeta = os.path.join(carpeta_canal, CARPETA_VIDEOS)
    nombre = _limpiar_nombre(f"{titulo_fanfic}_{rango_capitulos(audio_path)}")
    return os.path.join(carpeta, nombre + ".mp4")


# ---------------------------------------------------------------------------
# Codificador
# ---------------------------------------------------------------------------

def detectar_encoder(forzado="auto"):
    """
    Devuelve el nombre del codificador H.264 mas rapido que funcione en este PC.
    Prueba la GPU (NVIDIA / Intel / AMD) y cae a libx264 (CPU) si no hay.
    El resultado se recuerda para no repetir la prueba.
    """
    global _encoder_cache

    if forzado and forzado != "auto":
        return forzado
    if _encoder_cache:
        return _encoder_cache

    for enc in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            p = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi",
                 "-i", "testsrc=size=320x240:rate=10:duration=0.5",
                 "-c:v", enc, "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
                creationflags=_SIN_VENTANA,
            )
            if p.returncode == 0:
                _encoder_cache = enc
                return enc
        except Exception:
            continue

    _encoder_cache = "libx264"
    return "libx264"


def etiqueta_encoder(enc):
    return {
        "h264_nvenc": "GPU NVIDIA (NVENC) - rapido",
        "h264_qsv": "GPU Intel (QuickSync) - rapido",
        "h264_amf": "GPU AMD (AMF) - rapido",
        "libx264": "CPU (libx264) - lento pero compatible",
    }.get(enc, enc)


def _args_codificacion(cfg, encoder):
    """Parametros de calidad/velocidad segun el codificador elegido."""
    fps = int(cfg["fps"])
    calidad = int(cfg["crf"])          # menor = mejor calidad
    gop = str(max(2, fps * 2))         # keyframe cada 2 s (lo que pide YouTube)
    tope = gameplay_pool.maxrate_kbps(cfg)

    comunes = ["-g", gop, "-pix_fmt", "yuv420p"]

    if encoder == "h264_nvenc":
        # preset p4 en vez de p5, y sin rc-lookahead ni spatial-aq: medido con
        # SSIM y PSNR sale igual o mejor, pesa lo mismo y va un 70% mas rapido.
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4", "-tune", "hq",
            "-rc", "vbr", "-cq", str(calidad), "-b:v", "0",
            "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k",
            "-bf", "3",
        ] + comunes

    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "medium",
                "-global_quality", str(calidad),
                "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k"] + comunes

    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced",
                "-rc", "cqp", "-qp_i", str(calidad), "-qp_p", str(calidad)] + comunes

    return ["-c:v", "libx264",
            "-preset", cfg.get("preset", "veryfast"),
            "-crf", str(calidad),
            "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k"] + comunes


# ---------------------------------------------------------------------------
# Preparacion de los gameplays (se hace una vez y queda en cache)
# ---------------------------------------------------------------------------

def preparar_gameplays(cfg, log=print, avance=None, should_stop=None,
                       forzar_todo=False):
    """
    Deja los gameplays listos para usar y devuelve [(ruta, duracion), ...].

    Los que ya vienen ligeros (por ejemplo grabados en 720p30) NO se
    convierten: se usan tal cual, porque prepararlos no ahorraria nada.
    Solo se convierten los pesados, como los de 1080p a 120 fps.

    forzar_todo=True obliga a convertir todo. Hace falta para el camino de
    copia directa, donde todos los archivos tienen que ser identicos.

    avance(segundos_convertidos, etiqueta) se llama para la barra.
    """
    should_stop = should_stop or (lambda: False)
    avance = avance or (lambda *a: None)

    gameplay_dir = cfg["gameplay_dir"]
    pool_dir = gameplay_pool.carpeta_pool(gameplay_dir)
    os.makedirs(pool_dir, exist_ok=True)

    manifiesto = gameplay_pool.cargar_manifiesto(gameplay_dir)
    origenes = list_files(gameplay_dir, VIDEO_EXTS)

    def _hay_que_convertir(ruta):
        if forzar_todo:
            return True
        return gameplay_pool.necesita_preparacion(ruta, cfg)

    def _ya_esta(ruta):
        c = gameplay_pool._clave(ruta, cfg)
        return (manifiesto.get(c)
                and os.path.isfile(os.path.join(pool_dir, f"gp_{c}.mp4")))

    total_pendientes = sum(1 for o in origenes
                           if _hay_que_convertir(o) and not _ya_esta(o))
    hecho_n = 0
    usados_tal_cual = 0

    listos = []
    hechos_seg = 0.0

    for origen in origenes:
        if should_stop():
            return listos

        clave = gameplay_pool._clave(origen, cfg)
        entrada = manifiesto.get(clave)
        destino = os.path.join(pool_dir, f"gp_{clave}.mp4")

        if entrada and os.path.isfile(destino):
            listos.append((destino, float(entrada["duracion"])))
            continue

        if not _hay_que_convertir(origen):
            # Ya viene ligero: se usa directo, sin convertir nada.
            try:
                listos.append((origen, get_duration(origen)))
                usados_tal_cual += 1
            except Exception as e:
                log(f"  [!] No se pudo leer {os.path.basename(origen)}: {e}")
            continue

        hecho_n += 1
        etiqueta = (f"Preparando gameplays: {hecho_n} de {total_pendientes} "
                    f"(esto solo pasa la primera vez)")

        try:
            _w, _h, dur_origen, _codec = gameplay_pool.info_video(origen)
        except Exception as e:
            log(f"  [!] No se pudo leer {os.path.basename(origen)}: {e}")
            continue

        log(f"  Preparando {os.path.basename(origen)} "
            f"({formato_tiempo(dur_origen)})...")

        tmp = destino + ".parcial.mp4"
        ok = False
        for usar_gpu in (True, False):
            cmd = gameplay_pool.comando_preparar(origen, tmp, cfg, usar_gpu=usar_gpu)
            ok, cancelado, stderr = _correr_ffmpeg(
                cmd,
                on_progress=lambda seg, base=hechos_seg, et=etiqueta: avance(
                    base + seg, et),
                should_stop=should_stop,
            )
            if cancelado:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return listos
            if ok:
                break
            if usar_gpu:
                log("  [i] La GPU no pudo con este archivo, se reintenta por CPU.")

        if not ok:
            log(f"  [!] No se pudo preparar {os.path.basename(origen)}: "
                f"{(stderr or '').strip()[-300:]}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            hechos_seg += dur_origen
            avance(hechos_seg, etiqueta)
            continue

        os.replace(tmp, destino)
        try:
            dur_final = get_duration(destino)
        except Exception:
            dur_final = dur_origen

        manifiesto[clave] = {"origen": os.path.basename(origen),
                             "duracion": dur_final}
        gameplay_pool.guardar_manifiesto(gameplay_dir, manifiesto)
        listos.append((destino, dur_final))

        hechos_seg += dur_origen
        avance(hechos_seg, etiqueta)

    # Limpieza: borra los preparados que ya no sirven (por ejemplo los de una
    # calidad anterior, o los de un gameplay que ya borraste). Si no, se van
    # acumulando y ocupan disco de mas.
    vigentes = {os.path.basename(p) for p, _d in listos}

    for clave in list(manifiesto):
        if f"gp_{clave}.mp4" not in vigentes:
            manifiesto.pop(clave, None)
    gameplay_pool.guardar_manifiesto(gameplay_dir, manifiesto)

    liberado = 0
    try:
        for entrada in os.scandir(pool_dir):
            if (entrada.is_file() and entrada.name.startswith("gp_")
                    and entrada.name.endswith(".mp4")
                    and entrada.name not in vigentes):
                try:
                    liberado += entrada.stat().st_size
                    os.remove(entrada.path)
                except OSError:
                    pass
    except OSError:
        pass

    if liberado:
        mb = liberado / (1024 ** 2)
        tamano = f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"
        log(f"  Se borraron gameplays preparados que ya no servian "
            f"({tamano} liberados).")

    if usados_tal_cual:
        log(f"  {usados_tal_cual} gameplay(s) ya venian ligeros: se usan "
            f"directo, sin convertir nada.")

    return listos


def segundos_por_preparar(cfg, forzar_todo=False):
    """Cuantos segundos de gameplay faltan por convertir (para la barra)."""
    gameplay_dir = cfg["gameplay_dir"]
    pool_dir = gameplay_pool.carpeta_pool(gameplay_dir)
    manifiesto = gameplay_pool.cargar_manifiesto(gameplay_dir)

    total = 0.0
    for origen in list_files(gameplay_dir, VIDEO_EXTS):
        clave = gameplay_pool._clave(origen, cfg)
        if manifiesto.get(clave) and os.path.isfile(
                os.path.join(pool_dir, f"gp_{clave}.mp4")):
            continue
        if not forzar_todo and not gameplay_pool.necesita_preparacion(origen, cfg):
            continue
        try:
            total += gameplay_pool.info_video(origen)[2]
        except Exception:
            pass
    return total


# ---------------------------------------------------------------------------
# Armado de cada video
# ---------------------------------------------------------------------------

def usa_camino_rapido(cfg):
    """
    Se puede copiar el gameplay sin recodificar solo si no hay logo ni marca
    de agua: esos se dibujan por video (filter_complex), no se hornean en el
    pool, porque hacerlo obligaria a reconvertir TODA la libreria de
    gameplays (horas de material) por unos pocos videos que se van a hacer
    ahora. Intro/outro si se pueden pegar por copia (se pre-arman aparte,
    son 1-2 archivos chicos, no toda la libreria).
    """
    return not (gameplay_pool.logo_activo(cfg) or gameplay_pool.watermark_activo(cfg))


def _elegir_clips_enteros(clips_pool, duracion_objetivo, margen=30):
    """
    Elige clips COMPLETOS del pool (sin recortarlos) hasta juntar al menos
    duracion_objetivo + margen. Se usa para el camino de copia: como no se
    recodifica, no se puede cortar un clip a la mitad; se pega de mas y
    "-shortest" recorta el sobrante al final.
    """
    orden = clips_pool[:]
    random.shuffle(orden)
    seleccion, acumulado, i = [], 0.0, 0
    while acumulado < duracion_objetivo + margen:
        ruta, dur = orden[i % len(orden)]
        if i and i % len(orden) == 0:
            random.shuffle(orden)
        seleccion.append(ruta)
        acumulado += dur
        i += 1
        if i > 10000:
            break
    return seleccion


def _concatenar_con_audio(clips, audio_path, destino, on_progress=None,
                          should_stop=None):
    """
    Pega una lista de clips de video (ya listos, mismos parametros) y les
    pone un audio encima, todo por copia (sin recodificar el video). El
    resultado se recorta a la duracion del audio.
    """
    lista = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                        encoding="utf-8")
    try:
        for ruta in clips:
            lista.write(f"file '{_escapar_concat(ruta)}'\n")
        lista.close()

        tmp = destino + ".parcial.mp4"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-nostats", "-progress", "pipe:1",
            "-f", "concat", "-safe", "0", "-i", lista.name,
            "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-shortest", "-movflags", "+faststart",
            tmp,
        ]
        ok, cancelado, stderr = _correr_ffmpeg(cmd, on_progress, should_stop)

        if not ok:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if cancelado:
                return False
            raise RuntimeError((stderr or "ffmpeg fallo").strip()[-1500:])

        os.replace(tmp, destino)
        return True
    finally:
        try:
            os.remove(lista.name)
        except OSError:
            pass


def pick_clips_for_duration(gameplay_files, gameplay_durations, target_duration):
    pool = gameplay_files[:]
    selected = []
    accumulated = 0.0
    idx = 0

    while accumulated < target_duration:
        if idx % len(pool) == 0:
            random.shuffle(pool)
        clip = pool[idx % len(pool)]
        clip_duration = gameplay_durations[clip]

        remaining = target_duration - accumulated
        use_duration = min(clip_duration, remaining)

        if use_duration > 0.3:
            selected.append((clip, use_duration))
            accumulated += use_duration

        idx += 1
        if idx > 5000:
            break

    return selected


def _escapar_concat(ruta):
    return ruta.replace("\\", "/").replace("'", "'\\''")


def build_video_copia(audio_path, duracion_audio, clips_pool, output_path,
                      segmentos_extra=None, on_progress=None, should_stop=None):
    """
    Camino rapido: pega los gameplays ya preparados SIN recodificar el video
    y le pone el audio encima. El video se corta a la duracion del audio.

    segmentos_extra puede traer "intro" y/o "outro": rutas de video ya
    preparadas (mismo codec/formato que el pool) que se pegan tambien por
    copia, antes o despues del contenido principal, sin recodificar nada
    de eso tampoco.
    """
    segmentos_extra = segmentos_extra or {}
    seleccion = _elegir_clips_enteros(clips_pool, duracion_audio)

    tmp_contenido = output_path + ".contenido.mp4"
    ok = _concatenar_con_audio(seleccion, audio_path, tmp_contenido,
                               on_progress=on_progress, should_stop=should_stop)
    if not ok:
        return False

    partes = []
    if segmentos_extra.get("intro"):
        partes.append(segmentos_extra["intro"])
    partes.append(tmp_contenido)
    if segmentos_extra.get("outro"):
        partes.append(segmentos_extra["outro"])

    if len(partes) == 1:
        os.replace(tmp_contenido, output_path)
        return True

    lista_final = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                              encoding="utf-8")
    tmp = output_path + ".parcial.mp4"
    try:
        for ruta in partes:
            lista_final.write(f"file '{_escapar_concat(ruta)}'\n")
        lista_final.close()

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-nostats", "-f", "concat", "-safe", "0", "-i", lista_final.name,
            "-c", "copy", "-movflags", "+faststart", tmp,
        ]
        ok, cancelado, stderr = _correr_ffmpeg(cmd, None, should_stop)
        if not ok:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if cancelado:
                return False
            raise RuntimeError((stderr or "ffmpeg fallo").strip()[-1500:])

        os.replace(tmp, output_path)
        return True
    finally:
        try:
            os.remove(lista_final.name)
        except OSError:
            pass
        if os.path.exists(tmp_contenido):
            try:
                os.remove(tmp_contenido)
            except OSError:
                pass


_decoder_cache = {}


def decodificador_gpu(path):
    """
    Devuelve el decodificador por GPU que le sirve a este archivo, o None.

    Decodificar en la grafica en vez del procesador es lo que baja el uso de
    CPU a menos de la mitad (medido: 48% -> 19%) y encima va mas rapido.
    """
    if path in _decoder_cache:
        return _decoder_cache[path]

    dec = None
    try:
        if gameplay_pool.cuvid_disponible():
            codec = gameplay_pool.info_video(path)[3]
            pix = gameplay_pool.info_pix_fmt(path)
            # Si el formato de color no lo soporta la GPU, mejor ni intentarlo.
            if pix in gameplay_pool.PIX_FMT_GPU:
                dec = gameplay_pool.CUVID.get(codec)
    except Exception:
        dec = None

    _decoder_cache[path] = dec
    return dec


def hilos_cpu(cfg):
    """Cuantos hilos puede usar ffmpeg segun lo que hayas elegido."""
    nucleos = os.cpu_count() or 4
    modo = (cfg.get("cpu_uso") or "medio").lower()
    if modo == "maximo":
        return 0                       # 0 = sin limite
    if modo == "bajo":
        return max(2, nucleos // 6)    # ~2 en un i5-12400F
    return max(3, nucleos // 3)        # "medio": ~4 en un i5-12400F


def _build_filter_and_inputs(clips, audio_path, cfg, usar_gpu=True, clips_outro=None):
    """Arma inputs + filter_complex soportando intro/outro/logo/marca de agua.

    Si el outro es un archivo de audio (mp3, etc.) en vez de video, clips_outro
    trae los gameplays elegidos para ponerle de fondo, igual que al audio
    principal.
    """
    width, height, fps = cfg["width"], cfg["height"], cfg["fps"]

    def _dec(ruta):
        """Argumentos del decodificador por GPU para esta entrada."""
        if not usar_gpu:
            return []
        d = decodificador_gpu(ruta)
        return ["-c:v", d] if d else []

    inputs = []
    filter_chunks = []
    idx = 0

    def _agregar_clips(lista_clips, etiqueta):
        """Agrega los -i de una lista de gameplays y concatena su video en [etiqueta]."""
        nonlocal idx
        inicio = idx
        for clip_path, use_duration in lista_clips:
            # -t antes de -i corta el clip al leerlo: ffmpeg no decodifica de mas.
            inputs.extend(_dec(clip_path) + ["-t", f"{use_duration + 0.3:.3f}",
                                             "-i", clip_path])
            filter_chunks.append(
                f"[{idx}:v]trim=0:{use_duration:.3f},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={fps},setsar=1[{etiqueta}{idx - inicio}]"
            )
            idx += 1
        n = idx - inicio
        refs = "".join(f"[{etiqueta}{i}]" for i in range(n))
        filter_chunks.append(f"{refs}concat=n={n}:v=1:a=0[{etiqueta}]")

    _agregar_clips(clips, "vcontent")
    content_label = "vcontent"

    use_logo = bool(cfg.get("logo_path")) and os.path.isfile(cfg["logo_path"])
    if use_logo:
        logo_idx = idx
        idx += 1
        inputs += ["-i", cfg["logo_path"]]
        filter_chunks.append(
            f"[{logo_idx}:v]scale={cfg['logo_width']}:-1,format=rgba,"
            f"colorchannelmixer=aa={cfg['logo_opacity']}[logo]"
        )
        filter_chunks.append(f"[{content_label}][logo]overlay=(W-w)/2:(H-h)/2[vlogo]")
        content_label = "vlogo"

    watermark_text = (cfg.get("watermark_text") or "").strip()
    fuente_ok = bool(cfg.get("font_path")) and os.path.isfile(cfg.get("font_path", ""))
    if watermark_text and fuente_ok:
        font_escaped = cfg["font_path"].replace("\\", "/").replace(":", "\\:")
        safe_text = watermark_text.replace("\\", "").replace("'", "").replace(":", "")
        filter_chunks.append(
            f"[{content_label}]drawtext=fontfile='{font_escaped}':text='{safe_text}':"
            f"x=20:y=20:fontsize={cfg['font_size']}:fontcolor=white:box=1:"
            f"boxcolor=black@0.5:boxborderw=8[vwm]"
        )
        content_label = "vwm"

    use_intro = bool(cfg.get("intro_path")) and os.path.isfile(cfg["intro_path"])
    use_outro = bool(cfg.get("outro_path")) and os.path.isfile(cfg["outro_path"])
    outro_es_audio = use_outro and (
        os.path.splitext(cfg["outro_path"])[1].lower() in AUDIO_EXTS)
    if outro_es_audio and not clips_outro:
        # No se pudieron elegir gameplays para el outro de audio: se omite.
        use_outro = False
        outro_es_audio = False

    intro_idx = outro_idx = None
    if use_intro:
        intro_idx = idx
        idx += 1
        inputs += _dec(cfg["intro_path"]) + ["-i", cfg["intro_path"]]
    if use_outro and not outro_es_audio:
        outro_idx = idx
        idx += 1
        inputs += _dec(cfg["outro_path"]) + ["-i", cfg["outro_path"]]

    audio_idx = idx
    idx += 1
    inputs += ["-i", audio_path]

    segments = []  # lista de (video_label, audio_label)

    if use_intro:
        filter_chunks.append(
            f"[{intro_idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1[introv]"
        )
        filter_chunks.append(
            f"[{intro_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[introa]"
        )
        segments.append(("introv", "introa"))

    filter_chunks.append(
        f"[{audio_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[maina]"
    )
    segments.append((content_label, "maina"))

    if use_outro:
        if outro_es_audio:
            _agregar_clips(clips_outro, "outrov")
            outro_audio_idx = idx
            idx += 1
            inputs += ["-i", cfg["outro_path"]]
            filter_chunks.append(
                f"[{outro_audio_idx}:a]aformat=sample_rates=44100:"
                f"channel_layouts=stereo[outroa]"
            )
        else:
            filter_chunks.append(
                f"[{outro_idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},fps={fps},setsar=1[outrov]"
            )
            filter_chunks.append(
                f"[{outro_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[outroa]"
            )
        segments.append(("outrov", "outroa"))

    if len(segments) == 1:
        outv_label, outa_label = segments[0]
    else:
        concat_in = "".join(f"[{v}][{a}]" for v, a in segments)
        filter_chunks.append(f"{concat_in}concat=n={len(segments)}:v=1:a=1[outv][outa]")
        outv_label, outa_label = "outv", "outa"

    filter_complex = ";".join(filter_chunks)
    return inputs, filter_complex, outv_label, outa_label


def build_video(audio_path, clips, output_path, cfg, encoder, on_progress=None,
                should_stop=None, clips_outro=None):
    """Camino normal: recodifica porque hay logo, marca de agua, intro u outro."""
    tmp = output_path + ".parcial.mp4"
    hilos = hilos_cpu(cfg)
    modo = (cfg.get("cpu_uso") or "medio").lower()

    def armar(usar_gpu):
        inputs, filtro, v, a = _build_filter_and_inputs(
            clips, audio_path, cfg, usar_gpu=usar_gpu, clips_outro=clips_outro)
        limites = []
        if hilos:
            limites = ["-threads", str(hilos),
                       "-filter_complex_threads", str(hilos)]
        return (
            ["ffmpeg", "-y", "-hide_banner", "-nostdin",
             "-loglevel", "error", "-nostats", "-progress", "pipe:1"]
            + limites + inputs
            + ["-filter_complex", filtro, "-map", f"[{v}]", "-map", f"[{a}]"]
            + _args_codificacion(cfg, encoder)
            + ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
               "-movflags", "+faststart", tmp]
        )

    baja = modo != "maximo"
    ok, cancelado, stderr = _correr_ffmpeg(
        armar(True), on_progress, should_stop, prioridad_baja=baja)

    # Si la GPU no pudo con algun archivo, se reintenta todo por CPU.
    if not ok and not cancelado:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        ok, cancelado, stderr = _correr_ffmpeg(
            armar(False), on_progress, should_stop, prioridad_baja=baja)

    if not ok:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        if cancelado:
            return False
        raise RuntimeError((stderr or "ffmpeg fallo").strip()[-1500:])

    os.replace(tmp, output_path)
    return True


# ---------------------------------------------------------------------------
# Avisos sobre los audios
# ---------------------------------------------------------------------------

def _avisar_audios_cortos(tareas, log, resumen):
    """
    Avisa si algun audio dura muchisimo menos que los demas del mismo fanfic:
    casi siempre significa que el programa de voces se corto a medias y ese
    capitulo quedo incompleto. No se salta (por si de verdad es corto), pero
    queda anotado en el aviso final.
    """
    por_fanfic = {}
    for t in tareas:
        if t.get("duracion", 0) > 0:
            por_fanfic.setdefault(t["fanfic"], []).append(t)

    for fanfic, lista in por_fanfic.items():
        if len(lista) < 3:
            continue
        duraciones = sorted(t["duracion"] for t in lista)
        mediana = duraciones[len(duraciones) // 2]
        for t in lista:
            if t["duracion"] < mediana * UMBRAL_AUDIO_CORTO:
                aviso = (f"{os.path.basename(t['audio'])} ({fanfic}) dura solo "
                         f"{formato_tiempo(t['duracion'])}, cuando los demas de ese "
                         f"fanfic duran ~{formato_tiempo(mediana)}. Puede estar "
                         f"incompleto: revisalo antes de subirlo.")
                log(f"  [!] {aviso}")
                resumen["avisos"].append(aviso)


# ---------------------------------------------------------------------------
# Proceso principal
# ---------------------------------------------------------------------------

def generar_videos(cfg, log=print, progreso=None, should_stop=None):
    """
    cfg necesita:
      canal_dir      -> carpeta BOLILLO
      fanfics        -> lista de titulos seleccionados (si falta, se usan todos)
      gameplay_dir, width, height, fps, crf, preset, encoder
      logo_path, logo_width, logo_opacity, intro_path, outro_path,
      watermark_text, font_path, font_size

    progreso(fraccion, etapa, segundos_restantes) se llama para la barra.
    Devuelve un resumen con hechos / omitidos / errores / avisos.
    """
    should_stop = should_stop or (lambda: False)
    progreso = progreso or (lambda *a, **k: None)

    resumen = {"hechos": 0, "omitidos": 0, "errores": [], "avisos": [],
               "cancelado": False, "encoder": "", "carpeta_salida": ""}

    canal_dir = cfg.get("canal_dir", "")
    carpeta_salida = os.path.join(canal_dir, CARPETA_VIDEOS)
    os.makedirs(carpeta_salida, exist_ok=True)
    resumen["carpeta_salida"] = carpeta_salida

    progreso(0.0, "Buscando fanfics y audios...", None)

    seleccion = cfg.get("fanfics")
    fanfics = escanear_canal(canal_dir)
    if seleccion is not None:
        fanfics = [f for f in fanfics if f["titulo"] in seleccion]

    if not fanfics:
        log("No hay ningun fanfic seleccionado.")
        return resumen

    if not list_files(cfg["gameplay_dir"], VIDEO_EXTS):
        log(f"No se encontraron gameplays en {cfg['gameplay_dir']}")
        resumen["errores"].append("No hay videos de gameplay en la carpeta indicada.")
        return resumen

    # --- Tareas pendientes -------------------------------------------------
    progreso(0.0, "Revisando que videos faltan...", None)
    tareas = []
    for f in fanfics:
        if not f["audios"]:
            log(f"[i] '{f['titulo']}' todavia no tiene audios en su carpeta Español.")
            continue
        for audio in f["audios"]:
            salida = ruta_salida(canal_dir, f["titulo"], audio)
            if os.path.exists(salida):
                resumen["omitidos"] += 1
                continue

            # Si el archivo se acaba de tocar, lo mas probable es que el
            # programa de voces lo siga escribiendo.
            try:
                edad = time.time() - os.path.getmtime(audio)
            except OSError:
                edad = 999
            if edad < SEGUNDOS_RECIEN_ESCRITO:
                aviso = (f"{os.path.basename(audio)} se esta creando ahora mismo; "
                         f"se deja para la proxima vez.")
                log(f"  [i] {aviso}")
                resumen["avisos"].append(aviso)
                continue

            tareas.append({"fanfic": f["titulo"], "audio": audio, "salida": salida})

    if not tareas:
        log("Todos los videos de los fanfics seleccionados ya estaban creados.")
        progreso(1.0, "Nada nuevo que hacer", 0)
        return resumen

    # --- Duracion de los audios -------------------------------------------
    progreso(0.0, f"Midiendo duracion de {len(tareas)} audios...", None)
    total_audio = 0.0
    for t in tareas:
        if should_stop():
            resumen["cancelado"] = True
            return resumen
        try:
            t["duracion"] = get_duration(t["audio"])
        except Exception as e:
            t["duracion"] = 0.0
            log(f"  [!] No se pudo leer {os.path.basename(t['audio'])}: {e}")
        total_audio += t["duracion"]

    total_audio = max(total_audio, 1.0)
    _avisar_audios_cortos(tareas, log, resumen)

    encoder = detectar_encoder(cfg.get("encoder", "auto"))
    resumen["encoder"] = encoder

    # Si hay logo o marca de agua no se puede usar copia directa (se dibujan
    # por video, no se hornean en el pool: hacerlo obligaria a reconvertir
    # TODA la libreria de gameplays por unos pocos videos). Si no hay logo ni
    # marca de agua, se intenta copia directa e intro/outro se pre-arman una
    # sola vez mas abajo; si algo de eso falla, se cae a recodificar.
    rapido = usa_camino_rapido(cfg)

    # --- Reparto de la barra de progreso ----------------------------------
    # La unidad es "segundos de trabajo estimados", asi las dos etapas
    # (preparar gameplays y armar videos) caben en la misma barra.
    # En el camino de copia directa todos los archivos deben ser identicos,
    # asi que ahi si hay que convertirlos todos.
    seg_preparar = segundos_por_preparar(cfg, forzar_todo=rapido)
    trabajo_preparar = seg_preparar / VEL_PREPARAR
    trabajo_videos = total_audio / (VEL_COPIA if rapido else VEL_RECODIFICAR)
    trabajo_total = max(trabajo_preparar + trabajo_videos, 0.001)

    inicio = time.time()
    hecho = [0.0]

    def reportar(trabajo_hecho, etapa):
        frac = min(trabajo_hecho / trabajo_total, 0.999)
        transcurrido = time.time() - inicio
        restante = None
        if frac > 0.005 and transcurrido > 3:
            restante = transcurrido / frac * (1 - frac)
        progreso(frac, etapa, restante)

    log(f"Codificador: {etiqueta_encoder(encoder)}")
    log("Modo previsto: copia directa (intro/outro se arman una vez y se "
        "pegan por copia)" if rapido
        else "Modo: recodificando (hay logo o marca de agua)")
    log(f"Videos por crear: {len(tareas)}  ({formato_tiempo(total_audio)} de audio)"
        f"  |  ya existian: {resumen['omitidos']}")
    log("")
    log("Reparto del tiempo estimado:")
    if trabajo_preparar > 0:
        log(f"   {'preparar gameplays (solo esta vez)':<36}: "
            f"~{formato_tiempo(trabajo_preparar)}")
    plural = "video" if len(tareas) == 1 else "videos"
    log(f"   {f'generar los {len(tareas)} {plural}':<36}: ~{formato_tiempo(trabajo_videos)}")
    log(f"   {'TOTAL':<36}: ~{formato_tiempo(trabajo_total)}")
    if trabajo_preparar > 0:
        log("   (la proxima vez te ahorras la parte de preparar)")
    log("")

    # --- Etapa 1: preparar los gameplays -----------------------------------
    if seg_preparar > 0:
        log(f"Preparando gameplays por primera vez "
            f"({formato_tiempo(seg_preparar)} de material). "
            f"Esto solo pasa una vez.")

    etapa_prep = "Preparando gameplays (esto solo pasa la primera vez)"
    reportar(0.0, etapa_prep)

    clips_pool = preparar_gameplays(
        cfg, log=log,
        avance=lambda seg, et=etapa_prep: reportar(
            min(seg, seg_preparar) / VEL_PREPARAR, et),
        should_stop=should_stop,
        forzar_todo=rapido,
    )

    if should_stop():
        resumen["cancelado"] = True
        progreso(0.0, "Cancelado", 0)
        return resumen

    if not clips_pool:
        log("No se pudo preparar ningun gameplay.")
        resumen["errores"].append("No se pudo preparar ningun gameplay.")
        return resumen

    hecho[0] = trabajo_preparar
    log(f"Gameplays listos: {len(clips_pool)}")
    log(f"Salida: {carpeta_salida}")

    duraciones_pool = {ruta: dur for ruta, dur in clips_pool}
    rutas_pool = [ruta for ruta, _d in clips_pool]

    outro_path = cfg.get("outro_path") or ""
    outro_es_audio = (bool(outro_path) and os.path.isfile(outro_path)
                      and os.path.splitext(outro_path)[1].lower() in AUDIO_EXTS)

    # --- Etapa 1.5: pre-armar intro/outro, UNA sola vez (solo si vamos por
    # copia directa; si ya hay logo/marca de agua no vale la pena intentarlo)
    segmentos_extra = {}
    clips_outro = None      # solo se usa si se termina cayendo a recodificar

    if rapido:
        try:
            if cfg.get("intro_path") and os.path.isfile(cfg["intro_path"]):
                segmentos_extra["intro"] = gameplay_pool.preparar_segmento_video(
                    cfg["intro_path"], cfg)

            if outro_path and os.path.isfile(outro_path):
                if outro_es_audio:
                    dur_outro = get_duration(outro_path)
                    pool_dir = gameplay_pool.carpeta_pool(cfg["gameplay_dir"])
                    clave_outro = gameplay_pool._clave_segmento(outro_path, cfg)
                    destino_outro = os.path.join(pool_dir, f"seg_outro_{clave_outro}.mp4")
                    if not os.path.isfile(destino_outro):
                        clips_para_outro = _elegir_clips_enteros(clips_pool, dur_outro)
                        if not _concatenar_con_audio(clips_para_outro, outro_path,
                                                     destino_outro, should_stop=should_stop):
                            raise RuntimeError("no se pudo armar el outro")
                    segmentos_extra["outro"] = destino_outro
                else:
                    segmentos_extra["outro"] = gameplay_pool.preparar_segmento_video(
                        outro_path, cfg)
        except Exception as e:
            log(f"  [i] No se pudo preparar intro/outro por copia ({e}); "
                f"se recodificara en su lugar.")
            rapido = False
            segmentos_extra = {}

    if not rapido and outro_es_audio:
        # Camino normal: hay que elegir gameplay de fondo para el outro de
        # audio (se recorta por filtro, no por copia).
        try:
            dur_outro = get_duration(outro_path)
            clips_outro = pick_clips_for_duration(
                rutas_pool, duraciones_pool, dur_outro)
        except Exception as e:
            aviso = (f"No se pudo usar el outro de audio "
                     f"({os.path.basename(outro_path)}): {e}")
            log(f"  [!] {aviso}")
            resumen["avisos"].append(aviso)

    # El fallback de arriba puede haber cambiado "rapido": se recalcula el
    # estimado para que el porcentaje de la barra no quede desfasado.
    vel = VEL_COPIA if rapido else VEL_RECODIFICAR
    trabajo_videos = total_audio / vel
    trabajo_total = max(trabajo_preparar + trabajo_videos, 0.001)

    # --- Etapa 2: armar los videos ----------------------------------------
    paralelo = bool(cfg.get("paralelo")) and len(tareas) > 1
    resumen_lock = threading.Lock()
    hecho_lock = threading.Lock()
    maximo_reportado = [hecho[0]]

    # Reparto fijo del progreso por tarea (no depende del orden en que
    # terminen): necesario para que la barra avance bien cuando se generan
    # varios videos a la vez.
    bases = []
    acumulado = hecho[0]
    for t in tareas:
        bases.append(acumulado)
        acumulado += t["duracion"] / vel

    def reportar_monotono(candidato, etapa):
        with hecho_lock:
            if candidato > maximo_reportado[0]:
                maximo_reportado[0] = candidato
                reportar(candidato, etapa)

    def procesar(n, t):
        nombre = os.path.basename(t["salida"])
        etapa = f"({n} de {len(tareas)})  {nombre}"
        base = bases[n - 1]

        def al_avanzar(seg_video, _base=base, _etapa=etapa, _dur=t["duracion"]):
            reportar_monotono(_base + min(seg_video, _dur) / vel, _etapa)

        al_avanzar(0.0)
        log(f"Generando: {nombre}")

        try:
            if t["duracion"] <= 0:
                raise RuntimeError("el audio esta vacio o dañado")

            if rapido:
                ok = build_video_copia(
                    t["audio"], t["duracion"], clips_pool, t["salida"],
                    segmentos_extra=segmentos_extra,
                    on_progress=al_avanzar, should_stop=should_stop)
            else:
                clips = pick_clips_for_duration(
                    rutas_pool, duraciones_pool, t["duracion"])
                if not clips:
                    raise RuntimeError("no se pudieron elegir clips de gameplay")
                ok = build_video(t["audio"], clips, t["salida"], cfg, encoder,
                                 on_progress=al_avanzar, should_stop=should_stop,
                                 clips_outro=clips_outro)

            with resumen_lock:
                if ok:
                    resumen["hechos"] += 1
                else:
                    resumen["cancelado"] = True
        except Exception as e:
            msg = f"{t['fanfic']} -> {nombre}: {e}"
            log(f"  [ERROR] {msg}")
            with resumen_lock:
                resumen["errores"].append(msg)

    if paralelo:
        log("Generando videos de a 2 en paralelo (activado en Otras Configuraciones).")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futuros = []
            for n, t in enumerate(tareas, start=1):
                if should_stop():
                    resumen["cancelado"] = True
                    break
                futuros.append(pool.submit(procesar, n, t))
            for f in futuros:
                f.result()
    else:
        for n, t in enumerate(tareas, start=1):
            if should_stop():
                resumen["cancelado"] = True
                break
            procesar(n, t)

    hecho[0] = maximo_reportado[0]

    if resumen["cancelado"]:
        progreso(min(hecho[0] / trabajo_total, 1.0), "Cancelado", 0)
        log("Proceso cancelado por el usuario.")
    else:
        progreso(1.0, "Terminado", 0)
        log(f"Listo. {resumen['hechos']} video(s) creados en {carpeta_salida}")

    return resumen
