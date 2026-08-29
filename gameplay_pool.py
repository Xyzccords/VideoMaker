"""
gameplay_pool.py
----------------
Prepara los gameplays UNA sola vez y guarda el resultado en cache.

Por que:
  Los gameplays originales son 1080p a 120 fps y 20-40 Mbps. Decodificar eso
  entero para cada video es lo que hacia que tardara tanto (se decodifican
  120 fotogramas por segundo para quedarse solo con 30).

  Aqui se convierten una vez a la resolucion y fps finales. A partir de ese
  momento todos los videos se arman leyendo estos archivos ya listos, que
  son baratisimos de leer, y en el mejor de los casos ni siquiera hay que
  recodificar: se copia el video tal cual.

Los archivos preparados quedan en una subcarpeta "_VideoMaker_listos" dentro
de tu carpeta de gameplays. Se pueden borrar sin miedo: se vuelven a crear.
"""

import hashlib
import json
import os
import subprocess

_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

NOMBRE_POOL = "_VideoMaker_listos"
MANIFIESTO = "_manifiesto.json"

# Decodificadores por GPU de NVIDIA. Son los que hacen el trabajo pesado.
CUVID = {
    "h264": "h264_cuvid",
    "hevc": "hevc_cuvid",
    "vp9": "vp9_cuvid",
    "av1": "av1_cuvid",
    "mpeg4": "mpeg4_cuvid",
    "mpeg2video": "mpeg2_cuvid",
    "vc1": "vc1_cuvid",
}

_cuvid_ok = None


def carpeta_pool(gameplay_dir):
    return os.path.join(gameplay_dir, NOMBRE_POOL)


def _ruta_manifiesto(gameplay_dir):
    return os.path.join(carpeta_pool(gameplay_dir), MANIFIESTO)


def cargar_manifiesto(gameplay_dir):
    try:
        with open(_ruta_manifiesto(gameplay_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_manifiesto(gameplay_dir, datos):
    os.makedirs(carpeta_pool(gameplay_dir), exist_ok=True)
    try:
        with open(_ruta_manifiesto(gameplay_dir), "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# La GPU solo sabe decodificar estos formatos de color. Con cualquier otro
# (por ejemplo yuv444p, o 10 bits) hay que tirar de procesador.
PIX_FMT_GPU = ("yuv420p", "yuvj420p", "nv12", "p010le", "yuv420p10le")


def info_video(path):
    """Devuelve (ancho, alto, duracion, codec) del archivo."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", path]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=_SIN_VENTANA)
    info = json.loads(r.stdout)
    vs = next(s for s in info["streams"] if s.get("codec_type") == "video")
    dur = info.get("format", {}).get("duration") or vs.get("duration")
    return int(vs["width"]), int(vs["height"]), float(dur), vs.get("codec_name", "")


def info_pix_fmt(path):
    """Formato de color del video (yuv420p, yuv444p, etc.)."""
    cmd = ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
           "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", path]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=_SIN_VENTANA)
    return r.stdout.strip()


def cuvid_disponible():
    """Prueba una vez si el decodificador por GPU funciona en esta PC."""
    global _cuvid_ok
    if _cuvid_ok is not None:
        return _cuvid_ok
    try:
        # Se crea un h264 diminuto y se intenta decodificar con la GPU.
        # El -pix_fmt yuv420p es imprescindible: sin el, x264 genera yuv444p,
        # que la GPU no sabe decodificar, y la prueba fallaria sin motivo.
        p1 = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=size=640x480:rate=30:duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "h264", "-"],
            capture_output=True, timeout=40, creationflags=_SIN_VENTANA)
        p2 = subprocess.run(
            ["ffmpeg", "-v", "error", "-c:v", "h264_cuvid", "-f", "h264",
             "-i", "pipe:0", "-f", "null", "-"],
            input=p1.stdout, capture_output=True, timeout=40,
            creationflags=_SIN_VENTANA)
        _cuvid_ok = (p2.returncode == 0)
    except Exception:
        _cuvid_ok = False
    return _cuvid_ok


def _medidas_escalado(ancho_src, alto_src, ancho, alto):
    """
    Calcula a que tamano hay que escalar para CUBRIR el destino sin deformar
    (lo mismo que force_original_aspect_ratio=increase), para despues recortar.
    """
    if not ancho_src or not alto_src:
        return ancho, alto, False
    escala = max(ancho / ancho_src, alto / alto_src)
    w = int(round(ancho_src * escala / 2)) * 2
    h = int(round(alto_src * escala / 2)) * 2
    w, h = max(w, ancho), max(h, alto)
    return w, h, (w != ancho or h != alto)


def info_fps(path):
    """Fotogramas por segundo reales del archivo."""
    cmd = ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", path]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=_SIN_VENTANA)
    txt = r.stdout.strip()
    if "/" in txt:
        a, b = txt.split("/")
        return float(a) / float(b) if float(b) else 0.0
    return float(txt or 0)


# Si el gameplay ya es casi tan ligero como el video final, prepararlo no
# ahorra nada (medido: 29.5x directo contra 29.9x preparado). Solo se prepara
# cuando el original es bastante mas pesado que el destino.
FACTOR_VALE_LA_PENA = 1.5


def necesita_preparacion(origen, cfg):
    """
    Decide si conviene convertir este gameplay o si se puede usar tal cual.

    Se compara el trabajo de decodificar: ancho x alto x fps. Un archivo de
    1080p120 tiene 9 veces mas pixeles por segundo que uno de 720p30, y ahi
    preparar si vale mucho la pena. Uno que ya viene en 720p30 no.
    """
    ancho, alto, fps = int(cfg["width"]), int(cfg["height"]), int(cfg["fps"])
    destino_pps = ancho * alto * fps

    try:
        w, h, _dur, _codec = info_video(origen)
        f = info_fps(origen) or fps
    except Exception:
        return True   # si no se puede leer, mejor prepararlo

    origen_pps = w * h * f
    return origen_pps > destino_pps * FACTOR_VALE_LA_PENA


def maxrate_kbps(cfg):
    """
    Tope de bitrate acorde a la resolucion, los fps y la calidad pedida.
    Referencia: ~2200 kbps para 1280x720 a 30 fps con calidad 30.
    """
    ancho, alto, fps = int(cfg["width"]), int(cfg["height"]), int(cfg["fps"])
    calidad = int(cfg["crf"])
    proporcion = (ancho * alto * fps) / (1280 * 720 * 30)
    factor = 2 ** ((30 - calidad) / 6.0)
    return max(300, int(2200 * proporcion * factor))


def logo_activo(cfg):
    """True si hay un logo configurado y el archivo existe."""
    ruta = cfg.get("logo_path") or ""
    return bool(ruta) and os.path.isfile(ruta)


def watermark_activo(cfg):
    """True si hay texto de marca de agua Y una fuente valida para dibujarlo."""
    texto = (cfg.get("watermark_text") or "").strip()
    fuente = cfg.get("font_path") or ""
    return bool(texto) and bool(fuente) and os.path.isfile(fuente)


def _firma_branding(cfg):
    """
    Identifica el logo/marca de agua actuales. Se mete en la clave de cache
    de cada clip preparado: si cambias el logo o el texto, se vuelven a
    hornear todos los clips del pool.
    """
    partes = []
    if logo_activo(cfg):
        try:
            st = os.stat(cfg["logo_path"])
            partes.append(f"logo:{st.st_size}:{int(st.st_mtime)}:"
                          f"{cfg.get('logo_width')}:{cfg.get('logo_opacity')}")
        except OSError:
            partes.append("logo:?")
    if watermark_activo(cfg):
        try:
            st = os.stat(cfg["font_path"])
            partes.append(f"wm:{cfg.get('watermark_text')}:{st.st_size}:"
                          f"{int(st.st_mtime)}:{cfg.get('font_size')}")
        except OSError:
            partes.append("wm:?")
    return "|".join(partes)


def _clave(origen, cfg):
    """Identifica un gameplay preparado. Si algo cambia, se vuelve a hacer."""
    try:
        st = os.stat(origen)
        firma = f"{os.path.basename(origen)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        firma = os.path.basename(origen)
    ajustes = f"{cfg['width']}x{cfg['height']}@{cfg['fps']}q{cfg['crf']}"
    return hashlib.md5(
        f"{firma}|{ajustes}|{_firma_branding(cfg)}".encode("utf-8")
    ).hexdigest()[:16]


def _clave_segmento(origen, cfg, extra=""):
    """Igual que _clave, pero para intro/outro/portada (no llevan branding)."""
    try:
        st = os.stat(origen)
        firma = f"{os.path.basename(origen)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        firma = os.path.basename(origen)
    ajustes = f"{cfg['width']}x{cfg['height']}@{cfg['fps']}q{cfg['crf']}"
    return hashlib.md5(
        f"{firma}|{ajustes}|{extra}".encode("utf-8")
    ).hexdigest()[:16]


def comando_preparar(origen, destino, cfg, usar_gpu=True):
    """
    Arma el ffmpeg que convierte un gameplay al formato comun del pool.

    Si hay logo o marca de agua configurados, se hornean aqui mismo, UNA
    sola vez por clip del pool, en vez de aplicarlos en cada video que se
    genera despues. Asi los videos finales pueden pegarse por copia
    (-c:v copy) aunque tengan logo o marca de agua encima.
    """
    ancho, alto, fps = int(cfg["width"]), int(cfg["height"]), int(cfg["fps"])
    calidad = int(cfg["crf"])
    tope = maxrate_kbps(cfg)

    try:
        w_src, h_src, _dur, codec = info_video(origen)
    except Exception:
        w_src = h_src = 0
        codec = ""

    entrada = []
    filtros = []

    dec = CUVID.get(codec) if usar_gpu else None
    if dec and cuvid_disponible():
        # La GPU decodifica Y escala de una vez: es lo que da la velocidad.
        w_esc, h_esc, hay_recorte = _medidas_escalado(w_src, h_src, ancho, alto)
        entrada = ["-c:v", dec, "-resize", f"{w_esc}x{h_esc}"]
        if hay_recorte:
            filtros.append(f"crop={ancho}:{alto}")
    else:
        filtros.append(
            f"scale={ancho}:{alto}:force_original_aspect_ratio=increase")
        filtros.append(f"crop={ancho}:{alto}")

    filtros += [f"fps={fps}", "setsar=1"]

    inputs_extra = []
    filter_chunks = ["[0:v]" + ",".join(filtros) + "[vbase]"]
    label = "vbase"

    if logo_activo(cfg):
        logo_idx = 1  # [0] es el gameplay; el logo es la siguiente entrada
        inputs_extra += ["-i", cfg["logo_path"]]
        filter_chunks.append(
            f"[{logo_idx}:v]scale={cfg['logo_width']}:-1,format=rgba,"
            f"colorchannelmixer=aa={cfg['logo_opacity']}[logo]"
        )
        filter_chunks.append(f"[{label}][logo]overlay=(W-w)/2:(H-h)/2[vlogo]")
        label = "vlogo"

    if watermark_activo(cfg):
        font_escaped = cfg["font_path"].replace("\\", "/").replace(":", "\\:")
        texto = (cfg.get("watermark_text") or "").strip()
        safe_text = texto.replace("\\", "").replace("'", "").replace(":", "")
        filter_chunks.append(
            f"[{label}]drawtext=fontfile='{font_escaped}':text='{safe_text}':"
            f"x=20:y=20:fontsize={cfg['font_size']}:fontcolor=white:box=1:"
            f"boxcolor=black@0.5:boxborderw=8[vwm]"
        )
        label = "vwm"

    cadena = ";".join(filter_chunks)

    # Sin fotogramas B y con keyframes fijos: asi todos los archivos del pool
    # encajan entre si y despues se pueden pegar sin recodificar.
    return (
        ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
         "-nostats", "-progress", "pipe:1"]
        + entrada
        + ["-i", origen]
        + inputs_extra
        + ["-filter_complex", cadena, "-map", f"[{label}]", "-an",
           "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
           "-rc", "vbr", "-cq", str(calidad), "-b:v", "0",
           "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k",
           "-bf", "0", "-g", str(fps), "-forced-idr", "1", "-no-scenecut", "1",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
           destino]
    )


def preparar_segmento_video(origen, cfg):
    """
    Convierte un video (intro/outro) UNA sola vez al mismo formato que el
    pool de gameplays, para poder pegarlo despues con -c:v copy. Devuelve
    la ruta del archivo cacheado (no hace nada si ya existia).
    """
    pool_dir = carpeta_pool(cfg["gameplay_dir"])
    os.makedirs(pool_dir, exist_ok=True)
    clave = _clave_segmento(origen, cfg)
    destino = os.path.join(pool_dir, f"seg_{clave}.mp4")
    if os.path.isfile(destino):
        return destino

    ancho, alto, fps = int(cfg["width"]), int(cfg["height"]), int(cfg["fps"])
    calidad = int(cfg["crf"])
    tope = maxrate_kbps(cfg)
    filtro = (f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
              f"crop={ancho}:{alto},fps={fps},setsar=1")

    tmp = destino + ".parcial.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-nostats", "-i", origen, "-vf", filtro,
        "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
        "-rc", "vbr", "-cq", str(calidad), "-b:v", "0",
        "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k",
        "-bf", "0", "-g", str(fps), "-forced-idr", "1", "-no-scenecut", "1",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        tmp,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_SIN_VENTANA)
    if r.returncode != 0 or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise RuntimeError((r.stderr or "ffmpeg fallo al preparar el segmento").strip()[-500:])

    os.replace(tmp, destino)
    return destino


def preparar_portada(imagen, audio, duracion, cfg):
    """
    Arma UNA sola vez la imagen fija + el audio de "Intro 2" de un fanfic,
    en el mismo formato que el pool, para poder pegarla por copia despues.
    Devuelve la ruta del archivo cacheado (no hace nada si ya existia).
    """
    pool_dir = carpeta_pool(cfg["gameplay_dir"])
    os.makedirs(pool_dir, exist_ok=True)
    clave = _clave_segmento(imagen, cfg, extra=os.path.basename(audio))
    destino = os.path.join(pool_dir, f"portada_{clave}.mp4")
    if os.path.isfile(destino):
        return destino

    ancho, alto, fps = int(cfg["width"]), int(cfg["height"]), int(cfg["fps"])
    calidad = int(cfg["crf"])
    tope = maxrate_kbps(cfg)
    filtro = (f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
              f"crop={ancho}:{alto},fps={fps},setsar=1")

    tmp = destino + ".parcial.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-nostats", "-loop", "1", "-t", f"{duracion:.3f}", "-i", imagen,
        "-i", audio, "-vf", filtro,
        "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq",
        "-rc", "vbr", "-cq", str(calidad), "-b:v", "0",
        "-maxrate", f"{tope}k", "-bufsize", f"{tope * 2}k",
        "-bf", "0", "-g", str(fps), "-forced-idr", "1", "-no-scenecut", "1",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-shortest", tmp,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_SIN_VENTANA)
    if r.returncode != 0 or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise RuntimeError((r.stderr or "ffmpeg fallo al preparar la portada").strip()[-500:])

    os.replace(tmp, destino)
    return destino
