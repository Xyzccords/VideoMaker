"""
interfaz.py
-----------
Interfaz de escritorio (Tkinter) para:
  1) Generar videos de audiolibros con gameplay random (audiobook_core.py)
  2) Traducir capitulos .docx de novelas (traducir_core.py)

REQUISITOS:
  - Python 3.9+ con Tkinter (ya viene incluido en Windows)
  - ffmpeg en el PATH (para la pestaña de audiolibros)
  - pip install python-docx deep-translator

USO:
  python interfaz.py

Este archivo debe estar en la MISMA carpeta que audiobook_core.py,
traducir_core.py y logo_foxverso.png.

La configuracion que escribas se guarda automaticamente en
"interfaz_config.json" (misma carpeta) para que la proxima vez que abras
el programa ya esten tus rutas puestas.
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import audiobook_core
import traducir_core


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "interfaz_config.json")
LOGO_FILE = os.path.join(BASE_DIR, "logo_foxverso.png")

DEFAULTS = {
    "audio_dir": "",
    "gameplay_dir": "",
    "output_dir": "",
    "logo_path": "",
    "intro_path": "",
    "outro_path": "",
    "watermark_text": "Patreon Foxverso en la descripcion =)",
    "font_path": r"C:\Windows\Fonts\arialbd.ttf",
    "width": "854",
    "height": "480",
    "fps": "15",
    "logo_width": "300",
    "logo_opacity": "0.5",
    "font_size": "20",
    "crf": "20",
    "preset": "veryfast",
    "carpeta_novelas": "",
    "idioma_origen": "en",
    "idioma_destino": "es",
}

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"]
IDIOMAS = ["en", "es", "fr", "pt", "de", "it", "ja", "ko", "zh-CN"]

# ---------------------------------------------------------------------
# Tema visual: negro con rojo (suavizado), estilo "gamer"
# ---------------------------------------------------------------------
C_BG = "#0d0d0d"          # fondo general
C_PANEL = "#161616"       # fondo de paneles/secciones
C_INPUT = "#232323"       # fondo de campos de texto
C_BORDER = "#c23540"      # rojo principal, mas suave que antes (bordes, acentos)
C_RED = "#c23540"         # rojo botones (suavizado)
C_RED_HOVER = "#d9505a"   # rojo mas claro (hover)
C_RED_PRESS = "#8f2530"   # rojo oscuro (presionado)
C_TEXT = "#f2f2f2"        # texto principal
C_TEXT_DIM = "#9c9c9c"    # texto secundario

FONT_BASE = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_HEADER = ("Segoe UI Black", 11)
FONT_TITLE = ("Segoe UI Black", 18)
FONT_LOG = ("Consolas", 9)


def aplicar_tema(root: tk.Tk):
    root.configure(bg=C_BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=C_BG, foreground=C_TEXT, font=FONT_BASE)

    style.configure("TFrame", background=C_BG)
    style.configure("TLabel", background=C_BG, foreground=C_TEXT, font=FONT_BASE)
    style.configure("Titulo.TLabel", background=C_BG, foreground=C_RED, font=FONT_TITLE)

    style.configure("TLabelframe", background=C_BG, bordercolor=C_BORDER,
                     darkcolor=C_BG, lightcolor=C_BG, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=C_BG, foreground=C_RED, font=FONT_HEADER)

    style.configure("TButton", background=C_RED, foreground="#ffffff",
                     font=FONT_BOLD, padding=(14, 8), borderwidth=0, focusthickness=0)
    style.map(
        "TButton",
        background=[("active", C_RED_HOVER), ("pressed", C_RED_PRESS), ("disabled", "#3a3a3a")],
        foreground=[("disabled", "#7a7a7a")],
    )

    style.configure("Secundario.TButton", background=C_PANEL, foreground=C_TEXT,
                     font=FONT_BOLD, padding=(14, 8), borderwidth=1)
    style.map(
        "Secundario.TButton",
        background=[("active", "#262626"), ("pressed", "#0f0f0f")],
        bordercolor=[("!disabled", C_RED)],
    )

    style.configure("TEntry", fieldbackground=C_INPUT, foreground=C_TEXT,
                     insertcolor=C_TEXT, bordercolor=C_BORDER, lightcolor=C_INPUT,
                     darkcolor=C_INPUT, borderwidth=1)
    style.map("TEntry", bordercolor=[("focus", C_RED)])

    style.configure("TCombobox", fieldbackground=C_INPUT, background=C_INPUT,
                     foreground=C_TEXT, arrowcolor=C_RED, bordercolor=C_BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", C_INPUT)],
              foreground=[("readonly", C_TEXT)])
    root.option_add("*TCombobox*Listbox.background", C_INPUT)
    root.option_add("*TCombobox*Listbox.foreground", C_TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", C_RED)

    style.configure("TNotebook", background=C_BG, bordercolor=C_BG)
    style.configure("TNotebook.Tab", background=C_PANEL, foreground=C_TEXT_DIM,
                     font=FONT_BOLD, padding=(18, 10), borderwidth=0)
    style.map(
        "TNotebook.Tab",
        background=[("selected", C_RED)],
        foreground=[("selected", "#ffffff")],
        expand=[("selected", (0, 0, 0, 0))],
    )

    style.configure("TProgressbar", background=C_RED, troughcolor=C_INPUT,
                     bordercolor=C_BG, lightcolor=C_RED, darkcolor=C_RED)


def estilizar_texto(widget: tk.Text):
    widget.configure(
        bg=C_INPUT, fg=C_TEXT, insertbackground=C_TEXT,
        selectbackground=C_RED, selectforeground="#ffffff",
        relief="flat", borderwidth=6, font=FONT_LOG,
        highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_RED,
    )


def cargar_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def guardar_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Herramientas Foxverso")
        self.geometry("900x720")
        self.minsize(760, 600)

        aplicar_tema(self)

        self.cfg = cargar_config()

        header = ttk.Frame(self)
        header.pack(anchor="w", fill="x", padx=16, pady=(14, 4))

        self._logo_img = None
        if os.path.exists(LOGO_FILE):
            try:
                img = tk.PhotoImage(file=LOGO_FILE)
                # Reduce el tamaño si la imagen es grande (subsample = division entera)
                factor = max(1, min(img.width(), img.height()) // 48)
                if factor > 1:
                    img = img.subsample(factor, factor)
                self._logo_img = img
                ttk.Label(header, image=self._logo_img, background=C_BG).pack(
                    side="left", padx=(0, 10)
                )
            except tk.TclError:
                self._logo_img = None

        ttk.Label(header, text="FOXVERSO", style="Titulo.TLabel").pack(side="left")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_video = TabAudiolibros(notebook, self)
        self.tab_trad = TabTraducir(notebook, self)

        notebook.add(self.tab_video, text="Audiolibros -> Video")
        notebook.add(self.tab_trad, text="Traducir novelas")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        guardar_config(self.cfg)
        self.destroy()


class TabAudiolibros(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app
        self.cfg = app.cfg
        self.log_queue = queue.Queue()
        self.worker = None
        self.stop_flag = False

        self.vars = {}
        row = 0

        def campo_ruta(label, key, es_archivo=False, filetypes=None):
            nonlocal row
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
            var = tk.StringVar(value=self.cfg.get(key, ""))
            self.vars[key] = var
            entry = ttk.Entry(self, textvariable=var, width=70)
            entry.grid(row=row, column=1, sticky="we", padx=6, pady=4)

            def elegir():
                if es_archivo:
                    ruta = filedialog.askopenfilename(filetypes=filetypes or [("Todos", "*.*")])
                else:
                    ruta = filedialog.askdirectory()
                if ruta:
                    var.set(ruta)

            ttk.Button(self, text="Elegir...", style="Secundario.TButton",
                       command=elegir).grid(row=row, column=2, padx=6)
            row += 1

        ttk.Label(self, text="Carpetas", font=FONT_HEADER, foreground=C_RED).grid(
            row=row, column=0, sticky="w", padx=6, pady=(8, 2)
        )
        row += 1
        campo_ruta("Carpeta de audios:", "audio_dir")
        campo_ruta("Carpeta de gameplays:", "gameplay_dir")
        campo_ruta("Carpeta de salida:", "output_dir")

        ttk.Label(self, text="Marca de agua (opcional)", font=FONT_HEADER,
                  foreground=C_RED).grid(row=row, column=0, sticky="w", padx=6, pady=(12, 2))
        row += 1
        campo_ruta("Logo (imagen):", "logo_path", es_archivo=True,
                    filetypes=[("Imagenes", "*.png *.jpg *.jpeg")])
        campo_ruta("Intro (video):", "intro_path", es_archivo=True,
                    filetypes=[("Video", "*.mp4 *.mkv *.mov")])
        campo_ruta("Outro (video):", "outro_path", es_archivo=True,
                    filetypes=[("Video", "*.mp4 *.mkv *.mov")])
        campo_ruta("Fuente (.ttf):", "font_path", es_archivo=True,
                    filetypes=[("Fuente", "*.ttf")])

        ttk.Label(self, text="Texto de marca de agua:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        var_wm = tk.StringVar(value=self.cfg.get("watermark_text", ""))
        self.vars["watermark_text"] = var_wm
        ttk.Entry(self, textvariable=var_wm, width=70).grid(
            row=row, column=1, sticky="we", padx=6, pady=4
        )
        row += 1

        ttk.Label(self, text="Video", font=FONT_HEADER, foreground=C_RED).grid(
            row=row, column=0, sticky="w", padx=6, pady=(12, 2)
        )
        row += 1

        frame_num = ttk.Frame(self)
        frame_num.grid(row=row, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        row += 1

        def campo_num(frame, label, key, width=6):
            ttk.Label(frame, text=label).pack(side="left", padx=(0, 4))
            var = tk.StringVar(value=self.cfg.get(key, ""))
            self.vars[key] = var
            ttk.Entry(frame, textvariable=var, width=width).pack(side="left", padx=(0, 12))

        campo_num(frame_num, "Ancho:", "width")
        campo_num(frame_num, "Alto:", "height")
        campo_num(frame_num, "FPS:", "fps")
        campo_num(frame_num, "Ancho logo:", "logo_width")
        campo_num(frame_num, "Opacidad logo (0-1):", "logo_opacity")
        campo_num(frame_num, "Tam. fuente:", "font_size")

        frame_num2 = ttk.Frame(self)
        frame_num2.grid(row=row, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        row += 1
        campo_num(frame_num2, "CRF (calidad, menor=mejor):", "crf")
        ttk.Label(frame_num2, text="Preset:").pack(side="left", padx=(0, 4))
        var_preset = tk.StringVar(value=self.cfg.get("preset", "veryfast"))
        self.vars["preset"] = var_preset
        ttk.Combobox(frame_num2, textvariable=var_preset, values=PRESETS, width=10,
                     state="readonly").pack(side="left")

        # Botones
        frame_botones = ttk.Frame(self)
        frame_botones.grid(row=row, column=0, columnspan=3, sticky="w", padx=6, pady=(14, 4))
        row += 1
        self.btn_generar = ttk.Button(frame_botones, text="Generar videos", command=self.iniciar)
        self.btn_generar.pack(side="left", padx=(0, 8))
        self.btn_cancelar = ttk.Button(frame_botones, text="Cancelar", style="Secundario.TButton",
                                        command=self.cancelar, state="disabled")
        self.btn_cancelar.pack(side="left")

        # Log
        ttk.Label(self, text="Log", font=FONT_HEADER, foreground=C_RED).grid(
            row=row, column=0, sticky="w", padx=6, pady=(4, 2)
        )
        row += 1
        self.txt_log = tk.Text(self, height=14, wrap="word")
        estilizar_texto(self.txt_log)
        self.txt_log.grid(row=row, column=0, columnspan=3, sticky="nsew", padx=6, pady=6)
        self.grid_rowconfigure(row, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.after(150, self.revisar_cola)

    def log(self, texto):
        self.log_queue.put(texto)

    def revisar_cola(self):
        try:
            while True:
                texto = self.log_queue.get_nowait()
                self.txt_log.insert("end", texto + "\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.after(150, self.revisar_cola)

    def leer_config_actual(self):
        for k, v in self.vars.items():
            self.cfg[k] = v.get()
        return self.cfg

    def iniciar(self):
        cfg = self.leer_config_actual()

        if not cfg["audio_dir"] or not os.path.isdir(cfg["audio_dir"]):
            messagebox.showerror("Falta configuracion", "Elige una carpeta de audios valida.")
            return
        if not cfg["gameplay_dir"] or not os.path.isdir(cfg["gameplay_dir"]):
            messagebox.showerror("Falta configuracion", "Elige una carpeta de gameplays valida.")
            return
        if not cfg["output_dir"]:
            messagebox.showerror("Falta configuracion", "Elige una carpeta de salida.")
            return

        try:
            cfg_num = dict(cfg)
            cfg_num["width"] = int(cfg["width"])
            cfg_num["height"] = int(cfg["height"])
            cfg_num["fps"] = int(cfg["fps"])
            cfg_num["logo_width"] = int(cfg["logo_width"])
            cfg_num["logo_opacity"] = float(cfg["logo_opacity"])
            cfg_num["font_size"] = int(cfg["font_size"])
            cfg_num["crf"] = int(cfg["crf"])
        except ValueError:
            messagebox.showerror("Valor invalido",
                                  "Revisa que ancho/alto/fps/crf/etc sean numeros.")
            return

        guardar_config(self.app.cfg)

        self.txt_log.delete("1.0", "end")
        self.stop_flag = False
        self.btn_generar.config(state="disabled")
        self.btn_cancelar.config(state="normal")

        def tarea():
            try:
                audiobook_core.generar_videos(
                    cfg_num, log=self.log, should_stop=lambda: self.stop_flag
                )
            except Exception as e:
                self.log(f"[ERROR] {e}")
            finally:
                self.log("--- Proceso terminado ---")
                self.btn_generar.config(state="normal")
                self.btn_cancelar.config(state="disabled")

        self.worker = threading.Thread(target=tarea, daemon=True)
        self.worker.start()

    def cancelar(self):
        self.stop_flag = True
        self.log("Cancelando... (se detiene despues del video actual)")


class TabTraducir(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app
        self.cfg = app.cfg
        self.log_queue = queue.Queue()
        self.worker = None
        self.stop_flag = False

        row = 0
        ttk.Label(self, text="Carpeta con los capitulos (.docx) sin traducir:").grid(
            row=row, column=0, sticky="w", padx=6, pady=(10, 4)
        )
        row += 1

        frame_carpeta = ttk.Frame(self)
        frame_carpeta.grid(row=row, column=0, sticky="we", padx=6, pady=4)
        row += 1
        self.var_carpeta = tk.StringVar(value=self.cfg.get("carpeta_novelas", ""))
        ttk.Entry(frame_carpeta, textvariable=self.var_carpeta, width=75).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(frame_carpeta, text="Elegir...", style="Secundario.TButton",
                   command=self.elegir_carpeta).pack(side="left")

        frame_idiomas = ttk.Frame(self)
        frame_idiomas.grid(row=row, column=0, sticky="w", padx=6, pady=8)
        row += 1
        ttk.Label(frame_idiomas, text="Idioma origen:").pack(side="left", padx=(0, 4))
        self.var_origen = tk.StringVar(value=self.cfg.get("idioma_origen", "en"))
        ttk.Combobox(frame_idiomas, textvariable=self.var_origen, values=IDIOMAS, width=8,
                     state="readonly").pack(side="left", padx=(0, 16))
        ttk.Label(frame_idiomas, text="Idioma destino:").pack(side="left", padx=(0, 4))
        self.var_destino = tk.StringVar(value=self.cfg.get("idioma_destino", "es"))
        ttk.Combobox(frame_idiomas, textvariable=self.var_destino, values=IDIOMAS, width=8,
                     state="readonly").pack(side="left")

        ttk.Label(self, text="La traduccion se guarda en una carpeta hermana "
                              "\"(traducido)\" con la misma estructura. Los capitulos "
                              "ya traducidos se saltan automaticamente.",
                  wraplength=780, foreground=C_TEXT_DIM, background=C_BG).grid(
            row=row, column=0, sticky="w", padx=6, pady=(0, 8)
        )
        row += 1

        self.progreso = ttk.Progressbar(self, mode="determinate")
        self.progreso.grid(row=row, column=0, sticky="we", padx=6, pady=6)
        row += 1

        frame_botones = ttk.Frame(self)
        frame_botones.grid(row=row, column=0, sticky="w", padx=6, pady=(4, 4))
        row += 1
        self.btn_traducir = ttk.Button(frame_botones, text="Traducir", command=self.iniciar)
        self.btn_traducir.pack(side="left", padx=(0, 8))
        self.btn_cancelar = ttk.Button(frame_botones, text="Cancelar", style="Secundario.TButton",
                                        command=self.cancelar, state="disabled")
        self.btn_cancelar.pack(side="left")

        self.txt_log = tk.Text(self, height=16, wrap="word")
        estilizar_texto(self.txt_log)
        self.txt_log.grid(row=row, column=0, sticky="nsew", padx=6, pady=6)
        self.grid_rowconfigure(row, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.after(150, self.revisar_cola)

    def elegir_carpeta(self):
        ruta = filedialog.askdirectory()
        if ruta:
            self.var_carpeta.set(ruta)

    def log(self, texto):
        self.log_queue.put(texto)

    def revisar_cola(self):
        try:
            while True:
                texto = self.log_queue.get_nowait()
                self.txt_log.insert("end", texto + "\n")
                self.txt_log.see("end")
        except queue.Empty:
            pass
        self.after(150, self.revisar_cola)

    def actualizar_progreso(self, hecho, total):
        def _actualizar():
            self.progreso["maximum"] = max(total, 1)
            self.progreso["value"] = hecho
        self.after(0, _actualizar)

    def iniciar(self):
        carpeta = self.var_carpeta.get().strip()
        if not carpeta or not os.path.isdir(carpeta):
            messagebox.showerror("Falta configuracion", "Elige una carpeta valida.")
            return

        self.cfg["carpeta_novelas"] = carpeta
        self.cfg["idioma_origen"] = self.var_origen.get()
        self.cfg["idioma_destino"] = self.var_destino.get()
        guardar_config(self.app.cfg)

        self.txt_log.delete("1.0", "end")
        self.progreso["value"] = 0
        self.stop_flag = False
        self.btn_traducir.config(state="disabled")
        self.btn_cancelar.config(state="normal")

        cfg = {
            "carpeta_base": carpeta,
            "idioma_origen": self.var_origen.get(),
            "idioma_destino": self.var_destino.get(),
        }

        def tarea():
            try:
                traducir_core.traducir_carpeta(
                    cfg,
                    log=self.log,
                    progreso=self.actualizar_progreso,
                    should_stop=lambda: self.stop_flag,
                )
            except Exception as e:
                self.log(f"[ERROR] {e}")
            finally:
                self.log("--- Proceso terminado ---")
                self.btn_traducir.config(state="normal")
                self.btn_cancelar.config(state="disabled")

        self.worker = threading.Thread(target=tarea, daemon=True)
        self.worker.start()

    def cancelar(self):
        self.stop_flag = True
        self.log("Cancelando... (se detiene despues del capitulo actual)")


if __name__ == "__main__":
    app = App()
    app.mainloop()
