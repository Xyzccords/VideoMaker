"""
videomaker.pyw  --  VideoMaker Automatico
=========================================

Interfaz para crear los videos del canal automaticamente.

Como funciona:
  1. Pones UNA sola ruta: la carpeta de tu canal ("BOLILLO").
  2. El programa recorre esa carpeta, encuentra cada fanfic y lee los audios
     que haya dentro de su subcarpeta "Español".
  3. Marcas o desmarcas los fanfics que quieras exportar (vienen todos
     marcados).
  4. Los videos salen en  BOLILLO\\VIDEOS  con el nombre
     "<Titulo del fanfic>_<capitulos>.mp4".

La extension es .pyw a proposito: asi Windows lo abre SIN la ventana negra
de CMD. Lo normal es abrirlo con el acceso directo del Escritorio.
"""

import ctypes
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import audiobook_core
import notificaciones


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "interfaz_config.json")
ICO_FILE = os.path.join(BASE_DIR, "logo_vm.ico")
PNG_FILE = os.path.join(BASE_DIR, "logo_vm.png")

APP_NOMBRE = "VideoMaker Automatico"
APP_ID = "Bolillo.VideoMakerAutomatico"

DEFAULTS = {
    "canal_dir": r"C:\Users\ADMIN\Desktop\Carpetas\Fernando\CANALES\BOLILLO",
    "gameplay_dir": "",
    "logo_path": "",
    "intro_path": "",
    "outro_path": "",
    "font_path": r"C:\Windows\Fonts\arialbd.ttf",
    "watermark_text": "",
    "width": "1280",
    "height": "720",
    "fps": "30",
    "logo_width": "300",
    "logo_opacity": "0.5",
    "font_size": "24",
    "crf": "30",
    "preset": "veryfast",
    "encoder": "auto",
    "cpu_uso": "medio",
    "paralelo": False,
}

# Estas claves guardan rutas: si apuntan a algo que ya no existe, se limpian
# solas al abrir (el programa venia con rutas de otra PC).
CLAVES_RUTA = ("canal_dir", "gameplay_dir", "logo_path", "intro_path",
               "outro_path", "font_path")

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"]
ENCODERS = ["auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264"]
# Cuanto procesador puede usar. La GPU hace el trabajo pesado igual.
CPU_USO = ["bajo", "medio", "maximo"]

# ---------------------------------------------------------------------
# Tema visual: negro con rojo
# ---------------------------------------------------------------------
C_BG = "#0d0d0d"
C_PANEL = "#161616"
C_PANEL_ALT = "#1c1c1c"
C_INPUT = "#232323"
C_BORDER = "#c23540"
C_RED = "#c23540"
C_RED_HOVER = "#d9505a"
C_RED_PRESS = "#8f2530"
C_TEXT = "#f2f2f2"
C_TEXT_DIM = "#9c9c9c"

FONT_BASE = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_HEADER = ("Segoe UI Semibold", 11)
FONT_TITLE = ("Segoe UI", 20, "bold")
FONT_LOG = ("Consolas", 9)


def aplicar_tema(root):
    root.configure(bg=C_BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=C_BG, foreground=C_TEXT, font=FONT_BASE)
    style.configure("TFrame", background=C_BG)
    style.configure("Panel.TFrame", background=C_PANEL)
    style.configure("Fila.TFrame", background=C_PANEL)
    style.configure("FilaAlt.TFrame", background=C_PANEL_ALT)

    style.configure("TLabel", background=C_BG, foreground=C_TEXT, font=FONT_BASE)
    style.configure("Titulo.TLabel", background=C_BG, foreground=C_TEXT, font=FONT_TITLE)
    style.configure("Sub.TLabel", background=C_BG, foreground=C_TEXT_DIM, font=FONT_SMALL)
    style.configure("Header.TLabel", background=C_BG, foreground=C_RED, font=FONT_HEADER)
    style.configure("Estado.TLabel", background=C_BG, foreground=C_TEXT, font=FONT_BOLD)
    style.configure("Fila.TLabel", background=C_PANEL, foreground=C_TEXT, font=FONT_BASE)
    style.configure("FilaAlt.TLabel", background=C_PANEL_ALT, foreground=C_TEXT, font=FONT_BASE)
    style.configure("FilaDim.TLabel", background=C_PANEL, foreground=C_TEXT_DIM, font=FONT_SMALL)
    style.configure("FilaAltDim.TLabel", background=C_PANEL_ALT, foreground=C_TEXT_DIM,
                    font=FONT_SMALL)

    style.configure("TLabelframe", background=C_BG, bordercolor=C_BORDER,
                    darkcolor=C_BG, lightcolor=C_BG, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=C_BG, foreground=C_RED, font=FONT_HEADER)

    style.configure("TButton", background=C_RED, foreground="#ffffff",
                    font=FONT_BOLD, padding=(14, 8), borderwidth=0, focusthickness=0)
    style.map("TButton",
              background=[("active", C_RED_HOVER), ("pressed", C_RED_PRESS),
                          ("disabled", "#3a3a3a")],
              foreground=[("disabled", "#7a7a7a")])

    style.configure("Secundario.TButton", background=C_PANEL, foreground=C_TEXT,
                    font=FONT_BOLD, padding=(12, 6), borderwidth=1)
    style.map("Secundario.TButton",
              background=[("active", "#262626"), ("pressed", "#0f0f0f"),
                          ("disabled", "#151515")],
              bordercolor=[("!disabled", C_RED)],
              foreground=[("disabled", "#5a5a5a")])

    style.configure("Mini.TButton", background=C_PANEL, foreground=C_TEXT,
                    font=FONT_SMALL, padding=(8, 3), borderwidth=1)
    style.map("Mini.TButton",
              background=[("active", "#262626"), ("pressed", "#0f0f0f")],
              bordercolor=[("!disabled", "#3a3a3a")])

    # Cabecera de las secciones desplegables
    style.configure("Desple.TButton", background=C_PANEL, foreground=C_RED,
                    font=FONT_HEADER, padding=(12, 8), borderwidth=1, anchor="w")
    style.map("Desple.TButton",
              background=[("active", "#212121"), ("pressed", "#0f0f0f")],
              bordercolor=[("!disabled", "#3a3a3a")])

    style.configure("TEntry", fieldbackground=C_INPUT, foreground=C_TEXT,
                    insertcolor=C_TEXT, bordercolor=C_BORDER, lightcolor=C_INPUT,
                    darkcolor=C_INPUT, borderwidth=1, padding=4)
    style.map("TEntry", bordercolor=[("focus", C_RED)])

    style.configure("TCombobox", fieldbackground=C_INPUT, background=C_INPUT,
                    foreground=C_TEXT, arrowcolor=C_RED, bordercolor=C_BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", C_INPUT)],
              foreground=[("readonly", C_TEXT)])
    root.option_add("*TCombobox*Listbox.background", C_INPUT)
    root.option_add("*TCombobox*Listbox.foreground", C_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", C_RED)

    style.configure("TCheckbutton", background=C_PANEL, foreground=C_TEXT)

    style.configure("TProgressbar", background=C_RED, troughcolor=C_INPUT,
                    bordercolor=C_BG, lightcolor=C_RED, darkcolor=C_RED, thickness=22)

    style.configure("Vertical.TScrollbar", background=C_PANEL, troughcolor=C_BG,
                    bordercolor=C_BG, arrowcolor=C_TEXT_DIM, darkcolor=C_PANEL,
                    lightcolor=C_PANEL)
    style.map("Vertical.TScrollbar", background=[("active", C_RED)])


# ---------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------

def cargar_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                guardado = json.load(f)
            for k in DEFAULTS:
                if k in guardado:
                    cfg[k] = guardado[k]
        except Exception:
            pass

    # Limpia rutas que ya no existen (venian de la PC de otra persona).
    for k in CLAVES_RUTA:
        if cfg.get(k) and not os.path.exists(cfg[k]):
            cfg[k] = DEFAULTS[k] if os.path.exists(DEFAULTS.get(k, "")) else ""
    return cfg


def guardar_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({k: cfg.get(k, "") for k in DEFAULTS}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------
# Widgets auxiliares
# ---------------------------------------------------------------------

class Desplegable(ttk.Frame):
    """
    Seccion que se abre y se cierra al hacer clic en su titulo.

    Con alto_max, el contenido va dentro de un area con scroll y nunca crece
    mas de esa altura: asi los botones y la barra de progreso no se salen
    de la ventana cuando se abre la seccion.
    """

    def __init__(self, parent, titulo, abierto=False, alto_max=None):
        super().__init__(parent)
        self._titulo = titulo
        self._abierto = tk.BooleanVar(value=abierto)

        self.boton = ttk.Button(self, style="Desple.TButton", command=self.alternar)
        self.boton.pack(fill="x")

        if alto_max:
            self._scroll = AreaScroll(self, alto=alto_max, fondo=C_PANEL)
            self.cuerpo = ttk.Frame(self._scroll.interior, style="Panel.TFrame",
                                    padding=(14, 10))
            self.cuerpo.pack(fill="both", expand=True)
            self._caja = self._scroll
        else:
            self.cuerpo = ttk.Frame(self, style="Panel.TFrame", padding=(14, 10))
            self._caja = self.cuerpo

        self._pintar()
        if abierto:
            self._caja.pack(fill="both", expand=True)

    def _pintar(self):
        flecha = "\u25bc" if self._abierto.get() else "\u25b6"
        self.boton.config(text=f"  {flecha}   {self._titulo}")

    def alternar(self):
        self._abierto.set(not self._abierto.get())
        if self._abierto.get():
            self._caja.pack(fill="both", expand=True)
        else:
            self._caja.forget()
        self._pintar()

    def abrir(self):
        if not self._abierto.get():
            self.alternar()


class Casilla(tk.Label):
    """
    Casilla de marcado propia (roja con palomita cuando esta marcada).
    Se usa en vez de ttk.Checkbutton porque el tema oscuro de Tk dibuja
    una X en lugar de un visto, y una X se lee como "descartado".
    """

    def __init__(self, parent, variable, fondo):
        super().__init__(parent, width=2, bd=0, cursor="hand2",
                         font=("Segoe UI", 11, "bold"), highlightthickness=1)
        self.var = variable
        self._fondo = fondo
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *a: self._pintar())
        self._pintar()

    def _click(self, _e=None):
        self.var.set(not self.var.get())

    def _pintar(self):
        if self.var.get():
            self.config(text="✓", bg=C_RED, fg="#ffffff",
                        highlightbackground=C_RED_HOVER, highlightcolor=C_RED_HOVER)
        else:
            self.config(text=" ", bg=C_INPUT, fg=C_INPUT,
                        highlightbackground="#4a4a4a", highlightcolor="#4a4a4a")


class AreaScroll(ttk.Frame):
    """Area con scroll vertical. Se usa para la lista y para la configuracion."""

    def __init__(self, parent, alto=180, fondo=C_PANEL):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=fondo, highlightthickness=1,
                                highlightbackground="#2c2c2c", bd=0, height=alto)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                    style="Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.interior = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._win = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")

        self.interior.bind("<Configure>", self._al_cambiar_interior)
        self.canvas.bind("<Configure>", self._al_cambiar_canvas)
        self.canvas.bind("<Enter>", lambda e: self._bind_rueda(True))
        self.canvas.bind("<Leave>", lambda e: self._bind_rueda(False))

    def _al_cambiar_interior(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _al_cambiar_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _bind_rueda(self, activar):
        if activar:
            self.canvas.bind_all("<MouseWheel>", self._rueda)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _rueda(self, e):
        if self.canvas.bbox("all") and self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def limpiar(self):
        for w in self.interior.winfo_children():
            w.destroy()


# ---------------------------------------------------------------------
# Aplicacion
# ---------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_NOMBRE)
        self.geometry("960x900")
        self.minsize(880, 700)
        aplicar_tema(self)
        self._poner_icono()

        self.cfg = cargar_config()
        self.vars = {}
        self.fanfics = []
        self.filas = []
        self.worker = None
        self.stop_flag = False
        self.cola_log = queue.Queue()
        self.estado_progreso = (0.0, "", None)
        self.resumen_final = None
        self.texto_final = None

        self._construir()
        self.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self.after(100, self._latido)
        self.after(250, self.refrescar_fanfics)

    # ---------------------------------------------------------------- icono
    def _poner_icono(self):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
        if os.path.exists(ICO_FILE):
            try:
                self.iconbitmap(default=ICO_FILE)
            except tk.TclError:
                pass

    # ------------------------------------------------------------- interfaz
    def _construir(self):
        cont = ttk.Frame(self, padding=(16, 12))
        cont.pack(fill="both", expand=True)

        self._cabecera(cont)
        self._seccion_canal(cont)

        # Lo de abajo se ancla al fondo (side="bottom", de abajo hacia arriba)
        # para que los botones y la barra de progreso SIEMPRE se vean, aunque
        # se abran las secciones desplegables.
        self.detalles = Desplegable(cont, "Ver detalles del proceso", abierto=False)
        self.detalles.pack(side="bottom", fill="x", pady=(8, 0))
        self.txt_log = tk.Text(self.detalles.cuerpo, height=7, wrap="word",
                               bg=C_INPUT, fg=C_TEXT, insertbackground=C_TEXT,
                               selectbackground=C_RED, relief="flat", borderwidth=6,
                               font=FONT_LOG, highlightthickness=1,
                               highlightbackground="#2c2c2c")
        self.txt_log.pack(fill="both", expand=True)

        self._seccion_progreso(cont)
        self._seccion_acciones(cont)

        self.otras = Desplegable(cont, "Otras Configuraciones", abierto=False,
                                 alto_max=200)
        self.otras.pack(side="bottom", fill="x", pady=(10, 0))
        self._llenar_otras(self.otras.cuerpo)

        # Este va al final y con expand: se queda con el espacio que sobre.
        self._seccion_fanfics(cont)

    def _cabecera(self, parent):
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 12))

        self._logo_img = None
        if os.path.exists(PNG_FILE):
            try:
                img = tk.PhotoImage(file=PNG_FILE)
                factor = max(1, img.width() // 46)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self._logo_img = img
                tk.Label(header, image=img, bg=C_BG, bd=0).pack(side="left", padx=(0, 12))
            except tk.TclError:
                self._logo_img = None

        caja = ttk.Frame(header)
        caja.pack(side="left", anchor="w")
        ttk.Label(caja, text=APP_NOMBRE, style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(caja, text="Audiolibros + gameplay, en automatico",
                  style="Sub.TLabel").pack(anchor="w")

    def _seccion_canal(self, parent):
        marco = ttk.Labelframe(parent, text=" Carpeta del canal ", padding=(12, 10))
        marco.pack(fill="x")

        ttk.Label(marco, text="Aqui va la carpeta que contiene un subfolder por cada "
                              "fanfic (cada uno con su carpeta \"Español\").",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 6))

        fila = ttk.Frame(marco)
        fila.pack(fill="x")

        self.var_canal = tk.StringVar(value=self.cfg.get("canal_dir", ""))
        self.vars["canal_dir"] = self.var_canal
        ttk.Entry(fila, textvariable=self.var_canal).pack(side="left", fill="x",
                                                          expand=True, padx=(0, 8))
        ttk.Button(fila, text="Elegir...", style="Secundario.TButton",
                   command=self.elegir_canal).pack(side="left")
        self.var_canal.trace_add("write", lambda *a: self._programar_refresco())
        self._refresco_pendiente = None

    def _seccion_fanfics(self, parent):
        marco = ttk.Labelframe(parent, text=" Fanfics a exportar ", padding=(12, 10))
        marco.pack(fill="both", expand=True, pady=(10, 0))

        barra = ttk.Frame(marco)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="Marcar todos", style="Mini.TButton",
                   command=lambda: self.marcar_todos(True)).pack(side="left", padx=(0, 6))
        ttk.Button(barra, text="Desmarcar todos", style="Mini.TButton",
                   command=lambda: self.marcar_todos(False)).pack(side="left", padx=(0, 6))
        ttk.Button(barra, text="Actualizar lista", style="Mini.TButton",
                   command=self.refrescar_fanfics).pack(side="left")

        self.lbl_resumen = ttk.Label(barra, text="", style="Sub.TLabel")
        self.lbl_resumen.pack(side="right")

        self.lista = AreaScroll(marco, alto=150)
        self.lista.pack(fill="both", expand=True)

    def _llenar_otras(self, cuerpo):
        cuerpo.columnconfigure(1, weight=1)
        fila = [0]

        def titulo(texto):
            ttk.Label(cuerpo, text=texto, style="Header.TLabel",
                      background=C_PANEL).grid(row=fila[0], column=0, columnspan=3,
                                               sticky="w", pady=(10, 4))
            fila[0] += 1

        def campo_ruta(label, key, es_archivo=False, filetypes=None, ayuda=None):
            ttk.Label(cuerpo, text=label, background=C_PANEL).grid(
                row=fila[0], column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value=self.cfg.get(key, ""))
            self.vars[key] = var
            ttk.Entry(cuerpo, textvariable=var).grid(row=fila[0], column=1,
                                                     sticky="we", pady=3)

            def elegir():
                if es_archivo:
                    ruta = filedialog.askopenfilename(
                        filetypes=filetypes or [("Todos", "*.*")])
                else:
                    ruta = filedialog.askdirectory()
                if ruta:
                    var.set(os.path.normpath(ruta))

            ttk.Button(cuerpo, text="Elegir...", style="Mini.TButton",
                       command=elegir).grid(row=fila[0], column=2, padx=(8, 0))
            fila[0] += 1
            if ayuda:
                ttk.Label(cuerpo, text=ayuda, style="Sub.TLabel",
                          background=C_PANEL).grid(row=fila[0], column=1, sticky="w",
                                                   pady=(0, 4))
                fila[0] += 1

        def campo_texto(label, key):
            ttk.Label(cuerpo, text=label, background=C_PANEL).grid(
                row=fila[0], column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value=self.cfg.get(key, ""))
            self.vars[key] = var
            ttk.Entry(cuerpo, textvariable=var).grid(row=fila[0], column=1,
                                                     sticky="we", pady=3)
            fila[0] += 1

        titulo("Carpetas")
        campo_ruta("Carpeta de gameplays:", "gameplay_dir",
                   ayuda="Videos de fondo (Minecraft, Parkour, etc.). Obligatoria.")

        titulo("Marca de agua e intro / outro  (todo opcional)")
        campo_ruta("Logo (imagen):", "logo_path", es_archivo=True,
                   filetypes=[("Imagenes", "*.png *.jpg *.jpeg")])
        campo_ruta("Intro (video):", "intro_path", es_archivo=True,
                   filetypes=[("Video", "*.mp4 *.mkv *.mov")])
        campo_ruta("Outro (video o audio):", "outro_path", es_archivo=True,
                   filetypes=[("Video o audio", "*.mp4 *.mkv *.mov *.mp3 *.wav "
                                                "*.m4a *.flac *.ogg *.opus *.aac *.wma")],
                   ayuda="Si eliges un audio (mp3, etc.), se le pone gameplay "
                         "de fondo igual que al resto del video.")
        campo_ruta("Fuente (.ttf):", "font_path", es_archivo=True,
                   filetypes=[("Fuente", "*.ttf")])
        campo_texto("Texto de marca de agua:", "watermark_text")

        titulo("Video")
        caja1 = ttk.Frame(cuerpo, style="Panel.TFrame")
        caja1.grid(row=fila[0], column=0, columnspan=3, sticky="w", pady=4)
        fila[0] += 1

        def campo_num(frame, label, key, width=6):
            ttk.Label(frame, text=label, background=C_PANEL).pack(side="left", padx=(0, 4))
            var = tk.StringVar(value=self.cfg.get(key, ""))
            self.vars[key] = var
            ttk.Entry(frame, textvariable=var, width=width).pack(side="left", padx=(0, 14))

        campo_num(caja1, "Ancho:", "width")
        campo_num(caja1, "Alto:", "height")
        campo_num(caja1, "FPS:", "fps")
        campo_num(caja1, "Ancho logo:", "logo_width")
        campo_num(caja1, "Opacidad logo:", "logo_opacity")
        campo_num(caja1, "Tam. fuente:", "font_size")

        caja2 = ttk.Frame(cuerpo, style="Panel.TFrame")
        caja2.grid(row=fila[0], column=0, columnspan=3, sticky="w", pady=4)
        fila[0] += 1
        campo_num(caja2, "Calidad (menor = mejor, mas peso):", "crf", width=5)

        ttk.Label(caja2, text="Preset CPU:", background=C_PANEL).pack(side="left", padx=(0, 4))
        var_preset = tk.StringVar(value=self.cfg.get("preset", "veryfast"))
        self.vars["preset"] = var_preset
        ttk.Combobox(caja2, textvariable=var_preset, values=PRESETS, width=10,
                     state="readonly").pack(side="left", padx=(0, 14))

        ttk.Label(caja2, text="Codificador:", background=C_PANEL).pack(side="left", padx=(0, 4))
        var_enc = tk.StringVar(value=self.cfg.get("encoder", "auto"))
        self.vars["encoder"] = var_enc
        ttk.Combobox(caja2, textvariable=var_enc, values=ENCODERS, width=12,
                     state="readonly").pack(side="left", padx=(0, 14))

        ttk.Label(caja2, text="Uso del CPU:", background=C_PANEL).pack(side="left", padx=(0, 4))
        var_cpu = tk.StringVar(value=self.cfg.get("cpu_uso", "medio"))
        self.vars["cpu_uso"] = var_cpu
        ttk.Combobox(caja2, textvariable=var_cpu, values=CPU_USO, width=8,
                     state="readonly").pack(side="left")

        ttk.Label(cuerpo, style="Sub.TLabel", background=C_PANEL, wraplength=640,
                  text="Uso del CPU: \"medio\" es lo recomendado; el trabajo pesado "
                       "lo hace la grafica igual. \"bajo\" si quieres seguir usando "
                       "la PC sin que se ponga lenta. \"maximo\" solo si vas a "
                       "dejarla sola.").grid(
            row=fila[0], column=0, columnspan=3, sticky="w", pady=(6, 0))
        fila[0] += 1

        ttk.Label(cuerpo, style="Sub.TLabel", background=C_PANEL, wraplength=640,
                  text="Guia de calidad: 23 = maxima (archivos enormes), "
                       "30 = recomendada, 33 = ligera. Para gameplay de fondo, "
                       "30 se ve bien y pesa la mitad que 23.").grid(
            row=fila[0], column=0, columnspan=3, sticky="w", pady=(2, 0))
        fila[0] += 1

        self.lbl_encoder = ttk.Label(cuerpo, text="", style="Sub.TLabel", background=C_PANEL)
        self.lbl_encoder.grid(row=fila[0], column=0, columnspan=3, sticky="w", pady=(2, 0))
        fila[0] += 1
        threading.Thread(target=self._detectar_encoder_fondo, daemon=True).start()

        titulo("Rendimiento")
        caja3 = ttk.Frame(cuerpo, style="Panel.TFrame")
        caja3.grid(row=fila[0], column=0, columnspan=3, sticky="w", pady=4)
        fila[0] += 1

        ttk.Label(caja3, text="Generar videos de a 2 en paralelo:",
                 background=C_PANEL).pack(side="left", padx=(0, 8))
        var_paralelo = tk.BooleanVar(value=bool(self.cfg.get("paralelo", False)))
        self.vars["paralelo"] = var_paralelo
        Casilla(caja3, var_paralelo, C_PANEL).pack(side="left")

        ttk.Label(cuerpo, style="Sub.TLabel", background=C_PANEL, wraplength=640,
                  text="Experimental: procesa 2 videos a la vez en vez de uno por "
                       "uno. Util cuando generas varios capitulos de una sola vez. "
                       "Si notas errores o que se pone mas lento (poca VRAM o "
                       "disco lento), desmarcalo.").grid(
            row=fila[0], column=0, columnspan=3, sticky="w", pady=(2, 0))
        fila[0] += 1

        titulo("Gameplays preparados")
        ttk.Label(cuerpo, style="Sub.TLabel", background=C_PANEL, wraplength=640,
                  text="La primera vez el programa convierte tus gameplays a una "
                       "version ligera y la guarda. Gracias a eso los videos "
                       "salen mucho mas rapido. Si cambias resolucion, fps o "
                       "calidad se rehacen solos.").grid(
            row=fila[0], column=0, columnspan=3, sticky="w", pady=(2, 6))
        fila[0] += 1
        ttk.Button(cuerpo, text="Borrar y rehacer gameplays preparados",
                   style="Mini.TButton", command=self.borrar_pool).grid(
            row=fila[0], column=0, columnspan=2, sticky="w")
        fila[0] += 1

    def _detectar_encoder_fondo(self):
        try:
            enc = audiobook_core.detectar_encoder("auto")
            texto = f"\"auto\" usara: {audiobook_core.etiqueta_encoder(enc)}"
        except Exception:
            texto = ""
        self.after(0, lambda: self.lbl_encoder.config(text=texto))

    def _seccion_acciones(self, parent):
        fila = ttk.Frame(parent)
        fila.pack(side="bottom", fill="x", pady=(14, 6))

        self.btn_generar = ttk.Button(fila, text="Generar videos", command=self.iniciar)
        self.btn_generar.pack(side="left", padx=(0, 8))
        self.btn_cancelar = ttk.Button(fila, text="Cancelar", style="Secundario.TButton",
                                       command=self.cancelar, state="disabled")
        self.btn_cancelar.pack(side="left", padx=(0, 8))
        ttk.Button(fila, text="Abrir carpeta VIDEOS", style="Secundario.TButton",
                   command=self.abrir_salida).pack(side="left")

    def _seccion_progreso(self, parent):
        marco = ttk.Frame(parent)
        marco.pack(side="bottom", fill="x", pady=(4, 0))

        barra = ttk.Frame(marco)
        barra.pack(fill="x")
        self.progreso = ttk.Progressbar(barra, mode="determinate", maximum=1000)
        self.progreso.pack(side="left", fill="x", expand=True)
        self.lbl_pct = ttk.Label(barra, text="0 %", style="Estado.TLabel", width=6,
                                 anchor="e")
        self.lbl_pct.pack(side="left", padx=(10, 0))

        self.lbl_etapa = ttk.Label(marco, text="Listo para empezar.", style="Estado.TLabel")
        self.lbl_etapa.pack(anchor="w", pady=(8, 0))
        self.lbl_eta = ttk.Label(marco, text="", style="Sub.TLabel")
        self.lbl_eta.pack(anchor="w")

    # ------------------------------------------------------- lista fanfics
    def elegir_canal(self):
        ruta = filedialog.askdirectory(title="Elige la carpeta de tu canal (BOLILLO)")
        if ruta:
            self.var_canal.set(os.path.normpath(ruta))

    def _programar_refresco(self):
        if self._refresco_pendiente:
            self.after_cancel(self._refresco_pendiente)
        self._refresco_pendiente = self.after(600, self.refrescar_fanfics)

    def refrescar_fanfics(self):
        self._refresco_pendiente = None
        marcados_antes = {f["titulo"] for f, v in self.filas if not v.get()}

        canal = self.var_canal.get().strip()
        self.fanfics = audiobook_core.escanear_canal(canal)

        self.lista.limpiar()
        self.filas = []

        if not canal or not os.path.isdir(canal):
            self._mensaje_lista("Elige arriba la carpeta de tu canal para ver los fanfics.")
            self.lbl_resumen.config(text="")
            return

        if not self.fanfics:
            self._mensaje_lista("No se encontro ningun fanfic con carpeta \"Español\" "
                                "dentro de esta ruta.")
            self.lbl_resumen.config(text="")
            return

        total_audios = 0
        for i, f in enumerate(self.fanfics):
            estilo = "Fila" if i % 2 == 0 else "FilaAlt"
            n = len(f["audios"])
            total_audios += n

            fondo = C_PANEL if i % 2 == 0 else C_PANEL_ALT
            fila = ttk.Frame(self.lista.interior, style=f"{estilo}.TFrame", padding=(10, 7))
            fila.pack(fill="x")

            var = tk.BooleanVar(value=f["titulo"] not in marcados_antes)
            casilla = Casilla(fila, var, fondo)
            casilla.pack(side="right")

            detalle = (f"{n} audio(s)" if n else "sin audios todavia")
            lbl_det = ttk.Label(fila, text=detalle, style=f"{estilo}Dim.TLabel",
                                width=18, anchor="e")
            lbl_det.pack(side="right", padx=(8, 12))

            lbl_tit = ttk.Label(fila, text=f["titulo"], style=f"{estilo}.TLabel",
                                anchor="w")
            lbl_tit.pack(side="left", fill="x", expand=True)

            # Hacer clic en cualquier parte de la fila tambien marca/desmarca.
            for w in (fila, lbl_det, lbl_tit):
                w.bind("<Button-1>", lambda _e, v=var: v.set(not v.get()))
                w.configure(cursor="hand2")

            self.filas.append((f, var))

        self.lbl_resumen.config(
            text=f"{len(self.fanfics)} fanfic(s)  ·  {total_audios} audio(s)")

    def _mensaje_lista(self, texto):
        ttk.Label(self.lista.interior, text=texto, style="FilaDim.TLabel",
                  wraplength=640, padding=(12, 14)).pack(anchor="w")

    def marcar_todos(self, valor):
        for _f, var in self.filas:
            var.set(valor)

    def seleccionados(self):
        return [f["titulo"] for f, var in self.filas if var.get()]

    def borrar_pool(self):
        """Borra la cache de gameplays preparados para que se rehaga."""
        import shutil
        import gameplay_pool

        carpeta_gp = self.vars["gameplay_dir"].get().strip()
        if not carpeta_gp or not os.path.isdir(carpeta_gp):
            messagebox.showinfo(APP_NOMBRE, "Primero elige la carpeta de gameplays.")
            return

        pool = gameplay_pool.carpeta_pool(carpeta_gp)
        if not os.path.isdir(pool):
            messagebox.showinfo(APP_NOMBRE, "Todavia no hay gameplays preparados.")
            return

        if not messagebox.askyesno(
                APP_NOMBRE,
                "Se borraran los gameplays preparados.\n\n"
                "No se toca ningun gameplay original ni ningun video ya hecho.\n"
                "La proxima vez que generes videos se vuelven a preparar "
                "(tarda un rato solo esa vez).\n\n¿Continuar?"):
            return

        try:
            shutil.rmtree(pool)
            messagebox.showinfo(APP_NOMBRE, "Listo, se borraron.")
        except OSError as e:
            messagebox.showerror(APP_NOMBRE, f"No se pudieron borrar:\n{e}")

    def abrir_salida(self):
        canal = self.var_canal.get().strip()
        if not canal or not os.path.isdir(canal):
            messagebox.showinfo(APP_NOMBRE, "Primero elige la carpeta de tu canal.")
            return
        carpeta = os.path.join(canal, audiobook_core.CARPETA_VIDEOS)
        os.makedirs(carpeta, exist_ok=True)
        os.startfile(carpeta)

    # --------------------------------------------------------------- log
    def log(self, texto):
        self.cola_log.put(str(texto))

    def _latido(self):
        try:
            while True:
                self.txt_log.insert("end", self.cola_log.get_nowait() + "\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass

        frac, etapa, restante = self.estado_progreso
        self.progreso["value"] = int(frac * 1000)
        self.lbl_pct.config(text=f"{frac * 100:.0f} %")

        if self.texto_final:
            # Al acabar mandan estos textos, no los del progreso: si no, el
            # siguiente latido borraria el resultado final de la pantalla.
            self.lbl_etapa.config(text=self.texto_final[0])
            self.lbl_eta.config(text=self.texto_final[1])
        else:
            if etapa:
                self.lbl_etapa.config(text=etapa)
            if restante is None:
                self.lbl_eta.config(text="")
            else:
                self.lbl_eta.config(
                    text="Falta aproximadamente "
                         + audiobook_core.formato_tiempo(restante)
                         + " para terminar TODO (no solo esta parte)")

        if self.resumen_final is not None:
            resumen = self.resumen_final
            self.resumen_final = None
            self._terminar(resumen)

        self.after(200, self._latido)

    def _reportar(self, frac, etapa, restante):
        self.estado_progreso = (frac, etapa, restante)

    # ------------------------------------------------------------ proceso
    def leer_config(self):
        for k, v in self.vars.items():
            self.cfg[k] = v.get().strip() if isinstance(v.get(), str) else v.get()
        return self.cfg

    def iniciar(self):
        cfg = self.leer_config()

        if not cfg["canal_dir"] or not os.path.isdir(cfg["canal_dir"]):
            messagebox.showerror(APP_NOMBRE, "Elige una carpeta de canal valida.")
            return
        if not cfg["gameplay_dir"] or not os.path.isdir(cfg["gameplay_dir"]):
            messagebox.showerror(
                APP_NOMBRE,
                "Falta la carpeta de gameplays.\n\n"
                "Abrela en \"Otras Configuraciones\" y elige la carpeta con tus "
                "videos de fondo.")
            self.otras.abrir()
            return

        elegidos = self.seleccionados()
        if not elegidos:
            messagebox.showerror(APP_NOMBRE, "No marcaste ningun fanfic.")
            return

        audios = sum(len(f["audios"]) for f, var in self.filas if var.get())
        if not audios:
            messagebox.showwarning(
                APP_NOMBRE,
                "Los fanfics marcados todavia no tienen audios dentro de su "
                "carpeta \"Español\".\n\nColoca ahi los .mp3 y vuelve a intentarlo.")
            return

        try:
            cfg_num = dict(cfg)
            for k in ("width", "height", "fps", "logo_width", "font_size", "crf"):
                cfg_num[k] = int(cfg[k])
            cfg_num["logo_opacity"] = float(cfg["logo_opacity"])
        except ValueError:
            messagebox.showerror(
                APP_NOMBRE,
                "Revisa que ancho, alto, fps, calidad, etc. sean numeros.")
            return

        cfg_num["fanfics"] = elegidos
        guardar_config(self.cfg)

        self.txt_log.delete("1.0", "end")
        self.stop_flag = False
        self.texto_final = None
        self.estado_progreso = (0.0, "Preparando...", None)
        self.btn_generar.config(state="disabled")
        self.btn_cancelar.config(state="normal")

        def tarea():
            try:
                resumen = audiobook_core.generar_videos(
                    cfg_num, log=self.log, progreso=self._reportar,
                    should_stop=lambda: self.stop_flag,
                )
            except Exception as e:
                self.log(f"[ERROR] {e}")
                resumen = {"hechos": 0, "omitidos": 0, "errores": [str(e)],
                           "cancelado": False, "carpeta_salida": ""}
            self.resumen_final = resumen

        self.worker = threading.Thread(target=tarea, daemon=True)
        self.worker.start()

    def _terminar(self, resumen):
        self.btn_generar.config(state="normal")
        self.btn_cancelar.config(state="disabled")

        titulo, cuerpo = notificaciones.notificar_resumen(resumen)
        self.texto_final = (titulo, cuerpo.replace("\n", "   "))

        errores = resumen.get("errores", [])
        avisos = resumen.get("avisos", [])

        def lista(items, limite=5):
            texto = "\n\n".join(f"- {x}" for x in items[:limite])
            if len(items) > limite:
                texto += f"\n\n...y {len(items) - limite} mas (mira 'Ver detalles')."
            return texto

        if errores or avisos:
            partes = [cuerpo]
            if errores:
                partes.append("Problemas:\n\n" + lista(errores))
            if avisos:
                partes.append("Revisa esto:\n\n" + lista(avisos))
            partes.append("Carpeta:\n" + resumen.get("carpeta_salida", ""))
            messagebox.showwarning(APP_NOMBRE, "\n\n".join(partes))
        elif not resumen.get("cancelado"):
            messagebox.showinfo(
                APP_NOMBRE,
                f"{cuerpo}\n\nEstan en:\n{resumen.get('carpeta_salida', '')}")

        self.refrescar_fanfics()

    def cancelar(self):
        self.stop_flag = True
        self.log("Cancelando... (se detiene al terminar el video actual)")
        self.btn_cancelar.config(state="disabled")

    def al_cerrar(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                    APP_NOMBRE,
                    "Todavia se estan generando videos.\n\n¿Cerrar de todas formas?"):
                return
            self.stop_flag = True
        self.leer_config()
        guardar_config(self.cfg)
        self.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App()
    try:
        app.tk.call("tk", "scaling", app.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
