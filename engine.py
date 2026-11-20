"""Motor de mosaicos: solo PIL (sin OpenCV, sin Kivy). Todo en RGB."""
import math
import random
from PIL import Image, ImageDraw, ImageOps

SHAPES = ["Diamante", "Círculo", "Cuadrado", "Hexágono", "Triángulo", "Estrella", "Cruz"]
STYLES = SHAPES + ["Mixto", "Collage", "Grid 3x3", "Red de diamantes"]

ASPECTS = {
    "16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1500, 1500),
    "4:5": (1080, 1350), "Miniatura YT": (1280, 720), "Banner YT": (2560, 1440),
    "Portada FB": (851, 315), "21:9": (3440, 1440), "4K": (3840, 2160),
}

MAX_TILES = 2500  # tope de seguridad para no congelar el móvil


def load_image(path, max_side=1600):
    """Carga, corrige rotación EXIF y limita la resolución para ahorrar RAM."""
    try:
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        return im
    except Exception:
        return None


def powerclip(img, tw, th):
    """Recorte centrado + resize al tamaño exacto."""
    return ImageOps.fit(img, (max(1, int(tw)), max(1, int(th))), Image.BICUBIC)


def shape_points(shape, cx, cy, s, angle=0.0):
    r = s / 2
    if shape == "Cuadrado":
        p = [(-r, -r), (r, -r), (r, r), (-r, r)]
    elif shape == "Diamante":
        p = [(0, -r), (r, 0), (0, r), (-r, 0)]
    elif shape == "Hexágono":
        p = [(r * math.cos(math.radians(60 * i)), r * math.sin(math.radians(60 * i))) for i in range(6)]
    elif shape == "Triángulo":
        p = [(0, -r), (r * 0.866, r * 0.5), (-r * 0.866, r * 0.5)]
    elif shape == "Estrella":
        p = []
        for i in range(10):
            rad = r if i % 2 == 0 else r * 0.42
            a = math.radians(36 * i - 90)
            p.append((rad * math.cos(a), rad * math.sin(a)))
    elif shape == "Círculo":
        p = [(r * math.cos(math.tau * i / 64), r * math.sin(math.tau * i / 64)) for i in range(64)]
    else:  # Cruz
        b = r * 0.4
        p = [(-b, -r), (b, -r), (b, -b), (r, -b), (r, b), (b, b),
             (b, r), (-b, r), (-b, b), (-r, b), (-r, -b), (-b, -b)]
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in p]


def paste_poly(canvas, img, pts, bt, bc):
    """Pega la foto recortada con la forma del polígono y un borde de grosor bt."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = int(math.floor(min(xs))) - 1, int(math.floor(min(ys))) - 1
    x1, y1 = int(math.ceil(max(xs))) + 1, int(math.ceil(max(ys))) + 1
    cw, ch = canvas.size
    if x1 <= 0 or y1 <= 0 or x0 >= cw or y0 >= ch or x1 - x0 < 2 or y1 - y0 < 2:
        return
    loc = [(x - x0, y - y0) for x, y in pts]
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    d = ImageDraw.Draw(mask)
    d.polygon(loc, fill=255)
    if bt > 0:
        canvas.paste(bc, (x0, y0, x1, y1), mask)               # relleno de borde
        d.line(loc + [loc[0]], fill=0, width=bt * 2, joint="curve")  # erosiona hacia dentro
    bb = mask.getbbox()
    if not bb:
        return
    fit = powerclip(img, bb[2] - bb[0], bb[3] - bb[1])
    canvas.paste(fit, (x0 + bb[0], y0 + bb[1]), mask.crop(bb))


def _pool(imgs, shuffle):
    while True:
        order = list(imgs)
        if shuffle:
            random.shuffle(order)
        yield from order


# ---------------------------------------------------------------- layouts
def render_tiles(w, h, imgs, shape, s, bt, bc, rng, rot, rot_random, shuffle):
    canvas = Image.new("RGB", (w, h), bc)
    pool = _pool(imgs, shuffle)
    step = max(10, int(s * (1 - rng)))
    ratio = 1.0 if shape == "Cuadrado" else (0.75 if shape == "Cruz" else 0.5)
    while (w / step + 3) * (h / (step * ratio) + 3) > MAX_TILES:
        step = int(step * 1.15) + 1
    step_y = max(5, int(step * ratio))
    stagger = shape != "Cuadrado"
    for r in range(-1, math.ceil(h / step_y) + 1):
        shift = step // 2 if (stagger and r % 2) else 0
        for c in range(-1, math.ceil(w / step) + 1):
            size = int(s * (1 + random.uniform(-rng, rng))) if rng > 0 else s
            sh = random.choice(SHAPES) if shape == "Mixto" else shape
            ang = rot + (random.uniform(-180, 180) if rot_random else 0)
            pts = shape_points(sh, c * step + shift, r * step_y, size, ang)
            paste_poly(canvas, next(pool), pts, bt, bc)
    return canvas


def _split(w, h):
    panels = [(0, 0, w, h)]
    for _ in range(random.randint(4, 8)):
        x, y, pw, ph = max(panels, key=lambda p: p[2] * p[3])
        panels.remove((x, y, pw, ph))
        vertical = pw > ph * 1.5 or (not ph > pw * 1.5 and random.random() < 0.5)
        k = random.uniform(0.35, 0.65)
        if vertical:
            sp = int(pw * k)
            panels += [(x, y, sp, ph), (x + sp, y, pw - sp, ph)]
        else:
            sp = int(ph * k)
            panels += [(x, y, pw, sp), (x, y + sp, pw, ph - sp)]
    return panels


def _rect_cells(w, h, imgs, bc, rects, bt, shuffle):
    canvas = Image.new("RGB", (w, h), bc)
    pool = _pool(imgs, shuffle)
    for x, y, rw, rh in rects:
        ew, eh = rw - bt * 2, rh - bt * 2
        if ew < 2 or eh < 2:
            continue
        canvas.paste(powerclip(next(pool), ew, eh), (x + bt, y + bt))
    return canvas


def render_collage(w, h, imgs, bt, bc, shuffle):
    return _rect_cells(w, h, imgs, bc, _split(w, h), bt, shuffle)


def render_grid(w, h, imgs, bt, bc, shuffle, cols=3, rows=3):
    cw, ch = (w - (cols + 1) * bt) // cols, (h - (rows + 1) * bt) // rows
    rects = [(bt + c * (cw + bt) - bt, bt + r * (ch + bt) - bt, cw + 2 * bt, ch + 2 * bt)
             for r in range(rows) for c in range(cols)]
    return _rect_cells(w, h, imgs, bc, rects, bt, shuffle)


def render_diamond_network(w, h, imgs, s, bt, bc, shuffle):
    canvas = Image.new("RGB", (w, h), bc)
    pool = _pool(imgs, shuffle)
    s = max(s, int((w + h) / 40))  # evita millones de celdas
    gc = gr = int((w + h) / s) + 4  # cubre las 4 esquinas del lienzo
    occ = [[False] * (gc + 2) for _ in range(gr + 2)]
    queue = []
    for r in range(gr - 1):
        for c in range(gc - 1):
            if not occ[r][c] and random.random() < 0.20 and not (occ[r+1][c] or occ[r][c+1] or occ[r+1][c+1]):
                occ[r][c] = occ[r+1][c] = occ[r][c+1] = occ[r+1][c+1] = True
                queue.append((r, c, "BIG"))
    for r in range(gr - 1):
        for c in range(gc - 1):
            if not occ[r][c] and random.random() < 0.30:
                if random.random() < 0.5 and not occ[r][c+1]:
                    occ[r][c] = occ[r][c+1] = True
                    queue.append((r, c, "H"))
                elif not occ[r+1][c]:
                    occ[r][c] = occ[r+1][c] = True
                    queue.append((r, c, "V"))
    for r in range(gr):
        for c in range(gc):
            if not occ[r][c]:
                occ[r][c] = True
                queue.append((r, c, "S"))
    dims = {"BIG": (2, 2), "H": (2, 1), "V": (1, 2), "S": (1, 1)}
    for r, c, kind in queue:
        dc, dr = dims[kind]
        corners = [(r, c), (r, c + dc), (r + dr, c + dc), (r + dr, c)]
        pts = [((cl - rl) * s / 2 + w // 2, (cl + rl) * s / 2 - w // 2 - s) for rl, cl in corners]
        paste_poly(canvas, next(pool), pts, bt, bc)
    return canvas


def render(style, w, h, imgs, s, bt, bc, rng=0.12, rot=0, rot_random=False, shuffle=True, seed=None):
    if seed is not None:
        random.seed(seed)  # mismo seed = mismo diseño
    if style == "Collage":
        return render_collage(w, h, imgs, bt, bc, shuffle)
    if style == "Grid 3x3":
        return render_grid(w, h, imgs, bt, bc, shuffle)
    if style == "Red de diamantes":
        return render_diamond_network(w, h, imgs, s, bt, bc, shuffle)
    return render_tiles(w, h, imgs, style, s, bt, bc, rng, rot, rot_random, shuffle)
