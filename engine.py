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
# Área media de cada pieza (en unidades de s*s). Sirve para limitar el número de piezas.
_AREA = {"Cuadrado": 1.0, "Diamante": 0.5, "Hexágono": 0.65, "Triángulo": 0.43,
         "Cruz": 0.56, "Estrella": 0.5, "Círculo": 0.5, "Mixto": 0.43}


def _tess(style, bx0, by0, bx1, by1, s):
    """Polígonos que encajan SIN huecos y cubren el rectángulo (bx0,by0)-(bx1,by1).
    Las piezas comparten vértices exactos, así que no queda fondo visible entre ellas."""
    m = s * 1.5
    x0, y0, x1, y1 = bx0 - m, by0 - m, bx1 + m, by1 + m
    P = []
    if style == "Cuadrado":
        for j in range(int(y0 // s) - 1, int(y1 // s) + 2):
            for i in range(int(x0 // s) - 1, int(x1 // s) + 2):
                P.append([(i * s, j * s), ((i + 1) * s, j * s), ((i + 1) * s, (j + 1) * s), (i * s, (j + 1) * s)])
    elif style == "Diamante":
        h = s / 2
        for j in range(int(y0 // h) - 1, int(y1 // h) + 2):
            for i in range(int(x0 // s) - 1, int(x1 // s) + 2):
                cx, cy = i * s + (j % 2) * h, j * h
                P.append([(cx, cy - h), (cx + h, cy), (cx, cy + h), (cx - h, cy)])
    elif style == "Hexágono":
        R = s / 2
        dx, dy = 1.5 * R, math.sqrt(3) * R
        for c in range(int(x0 // dx) - 1, int(x1 // dx) + 2):
            for r in range(int(y0 // dy) - 1, int(y1 // dy) + 2):
                cx, cy = c * dx, r * dy + (c % 2) * dy / 2
                P.append([(cx + R * math.cos(math.radians(60 * k)), cy + R * math.sin(math.radians(60 * k)))
                          for k in range(6)])
    elif style in ("Triángulo", "Mixto"):
        hh = s * math.sqrt(3) / 2
        for j in range(int(y0 // hh) - 1, int(y1 // hh) + 2):
            for i in range(int(x0 // s) - 1, int(x1 // s) + 2):
                x, y = i * s + (j % 2) * s / 2, j * hh
                P.append([(x + s / 2, y), (x + s, y + hh), (x, y + hh)])
                P.append([(x + s / 2, y), (x + 1.5 * s, y), (x + s, y + hh)])
        if style == "Mixto":
            P = _merge_triangles(P)
    elif style == "Cruz":
        u = s / 3
        b, r = u / 2, 1.5 * u
        cross = [(-b, -r), (b, -r), (b, -b), (r, -b), (r, b), (b, b),
                 (b, r), (-b, r), (-b, b), (-r, b), (-r, -b), (-b, -b)]
        n = int(max(abs(x0), abs(x1), abs(y0), abs(y1)) / u) + 3
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                cx, cy = (2 * i - j) * u, (i + 2 * j) * u
                if x0 - s < cx < x1 + s and y0 - s < cy < y1 + s:
                    P.append([(cx + px, cy + py) for px, py in cross])
    elif style == "Estrella":  # estrellas de 4 puntas que se tocan por la punta + piezas de relleno
        r = s / 2
        n = 0.56 * r / math.sqrt(2)
        star = [(r, 0), (n, n), (0, r), (-n, n), (-r, 0), (-n, -n), (0, -r), (n, -n)]
        gap = [(0, -r), (r - n, -r + n), (r, 0), (r - n, r - n), (0, r),
               (-r + n, r - n), (-r, 0), (-r + n, -r + n)]
        for j in range(int(y0 // s) - 1, int(y1 // s) + 2):
            for i in range(int(x0 // s) - 1, int(x1 // s) + 2):
                P.append([(i * s + px, j * s + py) for px, py in star])
                P.append([((i + .5) * s + px, (j + .5) * s + py) for px, py in gap])
    elif style == "Círculo":  # círculos tangentes + piezas curvas que rellenan los huecos
        r = s / 2
        circ = [(r * math.cos(math.tau * k / 40), r * math.sin(math.tau * k / 40)) for k in range(40)]  # pasos de 9°: coinciden con los arcos del relleno
        pts = {}
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            base = math.atan2(-sy, -sx)
            for k in range(11):
                a_ = base - math.pi / 4 + (math.pi / 2) * k / 10
                p = (sx * r + r * math.cos(a_), sy * r + r * math.sin(a_))
                pts[(round(p[0], 3), round(p[1], 3))] = p
        gap = sorted(pts.values(), key=lambda p: math.atan2(p[1], p[0]))
        for j in range(int(y0 // s) - 1, int(y1 // s) + 2):
            for i in range(int(x0 // s) - 1, int(x1 // s) + 2):
                P.append([(i * s + px, j * s + py) for px, py in circ])
                P.append([((i + .5) * s + px, (j + .5) * s + py) for px, py in gap])
    return [[(round(x, 3), round(y, 3)) for x, y in poly] for poly in P]


def _merge_triangles(tris):
    """Une triángulos vecinos al azar en rombos: mosaico irregular, igualmente sin huecos."""
    key = lambda p: (round(p[0] * 4), round(p[1] * 4))
    edges = {}
    for idx, tr in enumerate(tris):
        for k in range(3):
            edges.setdefault(frozenset((key(tr[k]), key(tr[(k + 1) % 3]))), []).append((idx, k))
    order = list(range(len(tris)))
    random.shuffle(order)
    used, out = set(), []
    for idx in order:
        if idx in used:
            continue
        used.add(idx)
        tr = tris[idx]
        if random.random() < 0.6:
            nb = []
            for k in range(3):
                for j, kk in edges[frozenset((key(tr[k]), key(tr[(k + 1) % 3])))]:
                    if j != idx and j not in used:
                        nb.append((j, k, kk))
            if nb:
                j, k, kk = random.choice(nb)
                used.add(j)
                other = tris[j]
                out.append([tr[(k + 2) % 3], tr[k], other[(kk + 2) % 3], tr[(k + 1) % 3]])
                continue
        out.append(tr)
    return out


def _transform(polys, jit, rot, cx, cy):
    """Irregularidad (vértices compartidos se mueven igual: sigue sin haber huecos) y giro global."""
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    moved, out = {}, []
    for poly in polys:
        pts = []
        for x, y in poly:
            if jit > 0:
                k = (round(x * 4), round(y * 4))
                if k not in moved:
                    moved[k] = (random.uniform(-jit, jit), random.uniform(-jit, jit))
                x, y = x + moved[k][0], y + moved[k][1]
            if rot:
                x, y = cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca
            pts.append((x, y))
        out.append(pts)
    return out


def render_tiles(w, h, imgs, shape, s, bt, bc, rng, rot, rot_random, shuffle):
    canvas = Image.new("RGB", (w, h), bc)
    pool = _pool(imgs, shuffle)
    s = max(24, int(s))
    angle = rot + (random.uniform(-180, 180) if rot_random else 0)
    cover = w * h * (2 if angle else 1)
    while cover / (s * s * _AREA.get(shape, 1.0)) > MAX_TILES:
        s = int(s * 1.15) + 1
    if angle:
        R = math.hypot(w, h) / 2
        bounds = (w / 2 - R, h / 2 - R, w / 2 + R, h / 2 + R)
    else:
        bounds = (0, 0, w, h)
    polys = _tess(shape, *bounds, s)
    polys = _transform(polys, rng * s * 0.3, angle, w / 2, h / 2)
    for pts in polys:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) < 0 or max(ys) < 0 or min(xs) > w or min(ys) > h:
            continue  # fuera del lienzo: no gasta fotos
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
