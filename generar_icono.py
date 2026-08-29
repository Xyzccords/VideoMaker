"""
generar_icono.py
----------------
Genera el logo de "VideoMaker Automatico": un monograma VM minimalista y
moderno (trazos geometricos con puntas redondeadas y degradado rojo-naranja
sobre un cuadrado oscuro de esquinas redondeadas).

Crea dos archivos en esta misma carpeta:
  - logo_vm.ico  -> para el acceso directo y la barra de tareas
  - logo_vm.png  -> para mostrarlo dentro de la ventana

Solo hay que ejecutarlo una vez (necesita Pillow):

    pip install Pillow
    python generar_icono.py
"""

import os

from PIL import Image, ImageDraw

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICO_FILE = os.path.join(BASE_DIR, "logo_vm.ico")
PNG_FILE = os.path.join(BASE_DIR, "logo_vm.png")

# Lienzo grande y luego se reduce: asi los bordes quedan suaves (antialiasing).
S = 1024

FONDO_TOP = (26, 26, 35)
FONDO_BOT = (14, 14, 19)
ACENTO_A = (232, 65, 79)     # rojo
ACENTO_B = (255, 142, 75)    # naranja

# Monograma "VM" descrito como dos polilineas en un sistema donde la altura
# de las letras es 1.0. El hueco entre la V y la M ya tiene en cuenta el
# grosor del trazo, para que las letras no se toquen.
TRAZO_V = [(0.00, 0.00), (0.23, 1.00), (0.46, 0.00)]
TRAZO_M = [(0.78, 1.00), (0.78, 0.00), (1.09, 0.60), (1.40, 0.00), (1.40, 1.00)]
GROSOR = 0.18


def degradado_vertical(size, color_top, color_bot):
    img = Image.new("RGB", (1, size))
    px = img.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = tuple(
            round(color_top[i] + (color_bot[i] - color_top[i]) * t) for i in range(3)
        )
    return img.resize((size, size), Image.BICUBIC)


def degradado_diagonal(size, color_a, color_b):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / max(2 * (size - 1), 1)
            px[x, y] = tuple(
                round(color_a[i] + (color_b[i] - color_a[i]) * t) for i in range(3)
            )
    return img


def dibujar_trazo(draw, puntos, grosor):
    """Dibuja una polilinea gruesa con uniones y puntas redondeadas."""
    r = grosor / 2.0
    for (x1, y1), (x2, y2) in zip(puntos, puntos[1:]):
        draw.line([(x1, y1), (x2, y2)], fill=255, width=int(round(grosor)))
    for x, y in puntos:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=255)


def mascara_monograma(size):
    """Devuelve una mascara (L) con el monograma VM centrado."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    # Caja real de la marca, contando el grosor que sobresale en los extremos.
    todos = TRAZO_V + TRAZO_M
    r = GROSOR / 2.0
    x_min = min(p[0] for p in todos) - r
    x_max = max(p[0] for p in todos) + r
    y_min = min(p[1] for p in todos) - r
    y_max = max(p[1] for p in todos) + r

    escala = size * 0.42 / (y_max - y_min)
    off_x = (size - (x_max - x_min) * escala) / 2.0 - x_min * escala
    off_y = (size - (y_max - y_min) * escala) / 2.0 - y_min * escala

    def mapear(puntos):
        return [(off_x + px * escala, off_y + py * escala) for px, py in puntos]

    grosor = GROSOR * escala
    dibujar_trazo(draw, mapear(TRAZO_V), grosor)
    dibujar_trazo(draw, mapear(TRAZO_M), grosor)
    return mask


def mascara_esquinas(size, radio):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radio, fill=255)
    return mask


def construir_logo():
    fondo = degradado_vertical(S, FONDO_TOP, FONDO_BOT).convert("RGBA")

    # Borde interior sutil con el color de acento, da sensacion de "app".
    borde = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(borde).rounded_rectangle(
        [S * 0.02, S * 0.02, S * 0.98, S * 0.98],
        radius=int(S * 0.20),
        outline=ACENTO_A + (70,),
        width=int(S * 0.012),
    )
    fondo = Image.alpha_composite(fondo, borde)

    marca = degradado_diagonal(S, ACENTO_A, ACENTO_B).convert("RGBA")
    fondo.paste(marca, (0, 0), mascara_monograma(S))

    fondo.putalpha(mascara_esquinas(S, int(S * 0.22)))
    return fondo


def main():
    logo = construir_logo()

    logo.resize((512, 512), Image.LANCZOS).save(PNG_FILE, "PNG")

    tamanos = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    logo.save(ICO_FILE, format="ICO", sizes=tamanos)

    print(f"Creado: {ICO_FILE}")
    print(f"Creado: {PNG_FILE}")


if __name__ == "__main__":
    main()
