"""Motor de mosaicos: solo PIL (sin OpenCV, sin Kivy). Todo en RGB."""
import colorsys
import heapq
import math
import random
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

SHAPES = ["Diamante", "Círculo", "Cuadrado", "Hexágono", "Triángulo", "Estrella", "Cruz"]
STYLES = SHAPES + ["Mixto", "Collage", "Grid 3x3", "Red de diamantes",
                   "Polaroid", "Muro", "Héroe", "Diagonal", "Corazón", "Rueda", "Anillos",
                   "Película", "Vitral", "Foto-mosaico",
                   "Áureo", "Bento", "Pirámide", "Cuadro", "Ladrillo", "Persianas", "Abanico",
                   "Burbujas", "Círculos", "Flor", "Carrusel", "Arcos", "Cabina", "Tablero",
                   "Horizonte", "Chevron", "Olas", "Gema", "Mondrian", "Marcos"]
STYLE_GROUPS = {
    "Teselados sin huecos": SHAPES + ["Mixto"],
    "Collages": ["Collage", "Grid 3x3", "Red de diamantes", "Polaroid", "Muro", "Héroe", "Diagonal",
                 "Corazón", "Rueda", "Anillos", "Película", "Vitral", "Foto-mosaico"],
    "Más collages": ["Áureo", "Bento", "Pirámide", "Cuadro", "Ladrillo", "Persianas", "Abanico",
                     "Burbujas", "Círculos", "Flor", "Carrusel", "Arcos", "Cabina", "Tablero",
                     "Horizonte", "Chevron", "Olas", "Gema", "Mondrian", "Marcos"],
}
assert sum(STYLE_GROUPS.values(), []) == STYLES

ASPECTS = {
    "16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1500, 1500),
    "4:5": (1080, 1350), "Miniatura YT": (1280, 720), "Banner YT": (2560, 1440),
    "Portada FB": (851, 315), "21:9": (3440, 1440), "4K": (3840, 2160),
}

MAX_TILES = 2500  # tope de seguridad para no congelar el móvil

FX = ["Ninguno", "Blanco y negro", "Sepia", "Vivo"]
BORDERS = ["Sólido", "Arcoíris", "Por pieza", "Degradado"]
_BORD = {"mode": "Sólido", "w": 1, "h": 1}   # modo de borde de la render en curso
_OVR = {}                                     # {n.º de pieza: foto} elegidas a mano
LAST = {"centers": [], "ids": [], "P": 0, "size": (1, 1)}   # reparto de la última render


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


def _bcol(cx, cy, bc):
    """Color del borde de una pieza según el modo: sólido, arcoíris, por pieza o degradado."""
    m = _BORD["mode"]
    if m == "Sólido":
        return bc
    if m == "Degradado":
        k = max(0.0, min(1.0, (cx / _BORD["w"] + cy / _BORD["h"]) / 2))
        return tuple(int(a + (255 - a - a) * k) for a in bc)
    hue = (cx / _BORD["w"] * 0.6 + cy / _BORD["h"] * 0.4) % 1.0 if m == "Arcoíris" \
        else random.Random(int(cx) * 73856093 ^ int(cy) * 19349663).random()
    return tuple(int(255 * v) for v in colorsys.hsv_to_rgb(hue, 0.85, 1.0))


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
        canvas.paste(_bcol(sum(xs) / len(xs), sum(ys) / len(ys), bc), (x0, y0, x1, y1), mask)  # relleno de borde
        d.line(loc + [loc[0]], fill=0, width=bt * 2 + 1, joint="curve")  # erosiona hacia dentro (+1: sin píxeles sueltos)
    bb = mask.getbbox()
    if not bb:
        return
    fit = powerclip(img, bb[2] - bb[0], bb[3] - bb[1])
    canvas.paste(fit, (x0 + bb[0], y0 + bb[1]), mask.crop(bb))


def _adjacency(polys):
    """Para cada pieza, las piezas que comparten un borde con ella."""
    key = lambda p: (round(p[0] * 4), round(p[1] * 4))
    edges, adj = {}, [[] for _ in polys]
    for i, pl in enumerate(polys):
        for k in range(len(pl)):
            edges.setdefault(frozenset((key(pl[k]), key(pl[(k + 1) % len(pl)]))), []).append(i)
    for v in edges.values():
        if len(v) == 2 and v[0] != v[1]:
            adj[v[0]].append(v[1])
            adj[v[1]].append(v[0])
    return adj


def _assign(imgs, centers, cell, shuffle, adj=None):
    """Reparte las fotos para que las repetidas queden lo más lejos posible entre sí.
    1) Con adj (piezas que se tocan) colorea el mosaico con DSATUR: nunca dos vecinas con la misma
       foto mientras haya fotos suficientes. 2) Entre las opciones válidas, la foto cuya copia más
       cercana esté más lejos; en empate, la menos usada. 3) Una pasada final corrige conflictos."""
    P, N = len(imgs), len(centers)
    if P == 1 or N == 0:
        return [imgs[0]] * N
    order = list(range(P))
    if shuffle:
        random.shuffle(order)          # sin mezclar: respeta el orden de selección en los empates
    rank = {p: i for i, p in enumerate(order)}
    cell = max(1.0, cell)
    cnt, ids, grid = [0] * P, [-1] * N, {}

    def place(k):
        x, y = centers[k]
        gx, gy = int(x // cell), int(y // cell)
        near = {}
        for ix in range(gx - 3, gx + 4):
            for iy in range(gy - 3, gy + 4):
                for px, py, p in grid.get((ix, iy), ()):
                    d = (px - x) ** 2 + (py - y) ** 2
                    if d < near.get(p, 1e18):
                        near[p] = d
        lo = min(cnt)
        pool = [p for p in range(P) if cnt[p] <= lo + 1]
        banned = {ids[j] for j in adj[k] if ids[j] >= 0} if adj else set()
        cand = [p for p in pool if p not in banned] or [p for p in range(P) if p not in banned]
        if not cand:                    # hay menos fotos de las necesarias: el mínimo de choques
            conf = {p: sum(1 for j in adj[k] if ids[j] == p) for p in pool}
            m = min(conf.values())
            cand = [p for p in pool if conf[p] == m]
        best = min(cand, key=lambda p: (-near.get(p, 1e18), cnt[p], rank[p]))
        cnt[best] += 1
        ids[k] = best
        grid.setdefault((gx, gy), []).append((x, y, best))
        return best

    if adj is None:
        for k in range(N):
            place(k)
    else:                               # DSATUR: siempre la pieza con más colores distintos a su alrededor
        sat, done = [set() for _ in range(N)], [False] * N
        heap = [(0, -len(adj[k]), random.random(), k) for k in range(N)]
        heapq.heapify(heap)
        while heap:
            s_, _d, _r, k = heapq.heappop(heap)
            if done[k] or -s_ != len(sat[k]):
                continue
            c = place(k)
            done[k] = True
            for j in adj[k]:
                if not done[j] and c not in sat[j]:
                    sat[j].add(c)
                    heapq.heappush(heap, (-len(sat[j]), -len(adj[j]), random.random(), j))

    # pasada final: cada pieza pasa a la foto con menos conflictos con sus vecinas
    cells = {}
    for k, (x, y) in enumerate(centers):
        cells.setdefault((int(x // cell), int(y // cell)), []).append(k)
    cap, lim2 = -(-N // P) + 1, (2 * cell) ** 2
    for it in range(8):
        moved, todo = 0, list(range(N))
        random.shuffle(todo)
        for k in todo:
            x, y = centers[k]
            gx, gy = int(x // cell), int(y // cell)
            score = [0.0] * P
            for ix in range(gx - 2, gx + 3):
                for iy in range(gy - 2, gy + 3):
                    for j in cells.get((ix, iy), ()):
                        if j != k:
                            d = (centers[j][0] - x) ** 2 + (centers[j][1] - y) ** 2
                            if d < lim2:
                                score[ids[j]] += 1.0 / ((d / (cell * cell)) ** 2 + 0.1)
            if adj:
                for j in adj[k]:
                    score[ids[j]] += 30.0
            cur = ids[k]
            best = min((p for p in range(P) if p == cur or cnt[p] < cap),
                       key=lambda p: (score[p], cnt[p], rank[p]))
            if best != cur and (score[best] < score[cur] - 1e-9
                                or (it < 4 and abs(score[best] - score[cur]) <= 1e-9 and random.random() < 0.3)):
                cnt[cur] -= 1
                cnt[best] += 1
                ids[k] = best
                moved += 1
        if not moved:
            break
    for k, p in _OVR.items():                # fotos elegidas a mano para una pieza
        if 0 <= k < N and 0 <= p < P:
            ids[k] = p
    LAST.update(centers=list(centers), ids=list(ids), P=P)
    return [imgs[i] for i in ids]


def _visible(pts, w, h):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return not (max(xs) < 0 or max(ys) < 0 or min(xs) > w or min(ys) > h)


def _center(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


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
    polys = [p for p in polys if _visible(p, w, h)]
    picks = _assign(imgs, [_center(p) for p in polys], s * 0.6, shuffle, _adjacency(polys))
    for pts, im in zip(polys, picks):
        paste_poly(canvas, im, pts, bt, bc)
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
    cells = [(x, y, rw, rh) for x, y, rw, rh in rects if rw - bt * 2 >= 2 and rh - bt * 2 >= 2]
    picks = _assign(imgs, [(x + rw / 2, y + rh / 2) for x, y, rw, rh in cells], max(w, h) / 8, shuffle)
    d = ImageDraw.Draw(canvas)
    for (x, y, rw, rh), im in zip(cells, picks):
        if bt > 0 and _BORD["mode"] != "Sólido":
            d.rectangle((x, y, x + rw - 1, y + rh - 1), fill=_bcol(x + rw / 2, y + rh / 2, bc))
        canvas.paste(powerclip(im, rw - bt * 2, rh - bt * 2), (x + bt, y + bt))
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
    items = []
    for r, c, kind in queue:
        dc, dr = dims[kind]
        corners = [(r, c), (r, c + dc), (r + dr, c + dc), (r + dr, c)]
        pts = [((cl - rl) * s / 2 + w // 2, (cl + rl) * s / 2 - w // 2 - s) for rl, cl in corners]
        if _visible(pts, w, h):
            items.append(pts)
    picks = _assign(imgs, [_center(p) for p in items], s * 0.6, shuffle, _adjacency(items))
    for pts, im in zip(items, picks):
        paste_poly(canvas, im, pts, bt, bc)
    return canvas


# ---------------------------------------------------------------- 10 collages nuevos
# Regla de todos: ninguna foto se superpone ni se toca. Entre dos fotos queda siempre, como mínimo,
# la separación _gap() (el grosor de borde, y nunca menos de ~1.2 % del lado corto del lienzo).
POLAROID_FRAME = (253, 253, 251)
POLAROID_EDGE = (205, 205, 205)
FILM_BAND = (22, 22, 25)


def _gap(w, h, bt):
    return max(int(bt), 6, int(0.012 * min(w, h)))


def _margin(g):
    return (g + 1) // 2      # cada foto se recorta g/2 por lado: entre dos vecinas queda g


def _clip(poly, a, b, c):
    """Recorta un polígono al semiplano a*x + b*y + c >= 0 (Sutherland-Hodgman)."""
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        dp, dq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if dp >= 0:
            out.append(p)
        if (dp >= 0) != (dq >= 0):
            k = dp / (dp - dq)
            out.append((p[0] + k * (q[0] - p[0]), p[1] + k * (q[1] - p[1])))
    return out


def _poly_collage(w, h, imgs, polys, bt, bc, shuffle, cell):
    m = _margin(_gap(w, h, bt)) + 1
    canvas = Image.new("RGB", (w, h), bc)
    polys = [p for p in polys if len(p) >= 3 and _visible(p, w, h)]
    picks = _assign(imgs, [_center(p) for p in polys], cell, shuffle, _adjacency(polys))
    for pts, im in zip(polys, picks):
        paste_poly(canvas, im, pts, m, bc)
    return canvas


def _rect_collage(w, h, imgs, rects, bt, bc, shuffle):
    return _rect_cells(w, h, imgs, bc, rects, _margin(_gap(w, h, bt)), shuffle)


def _polaroid_plan(w, h, s, g, rng, rot, rot_random):
    """Una polaroid por casilla, girada y siempre dentro de su casilla: no pueden tocarse."""
    cell = max(80.0, s * 1.15)
    while True:
        cols, rows = max(1, round(w / cell)), max(1, round(h / cell))
        if cols * rows <= 80:
            break
        cell *= 1.15
    cw, ch = w / cols, h / rows
    amp = min(25.0, 6 + 30 * rng)
    if rot_random:
        amp = max(amp, 18)
    plan = []
    for r in range(rows):
        for c in range(cols):
            ang = rot + random.uniform(-amp, amp)
            a = math.radians(ang)
            bw = 0.84 * abs(math.cos(a)) + abs(math.sin(a))
            bh = 0.84 * abs(math.sin(a)) + abs(math.cos(a))
            k = min((cw - g) / bw, (ch - g) / bh)
            if k < 24:
                continue
            pw, ph = 0.84 * k, k
            sx, sy = (cw - g - bw * k) / 2, (ch - g - bh * k) / 2
            cx = (c + 0.5) * cw + random.uniform(-0.8, 0.8) * sx
            cy = (r + 0.5) * ch + random.uniform(-0.8, 0.8) * sy
            co, si = math.cos(a), math.sin(a)
            poly = [(cx + x * co + y * si, cy - x * si + y * co)
                    for x, y in ((-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2))]
            plan.append((cx, cy, pw, ph, ang, poly))
    return plan


def render_polaroid(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    plan = _polaroid_plan(w, h, s, _gap(w, h, bt), rng, rot, rot_random)
    canvas = Image.new("RGB", (w, h), bc)
    picks = _assign(imgs, [(p[0], p[1]) for p in plan], max(w, h) / 6, shuffle)
    for (cx, cy, pw, ph, ang, _), im in zip(plan, picks):
        pw, ph = int(pw), int(ph)
        tile = Image.new("RGBA", (pw, ph), POLAROID_FRAME + (255,))
        ImageDraw.Draw(tile).rectangle((0, 0, pw - 1, ph - 1), outline=POLAROID_EDGE)
        side, bottom = max(2, int(pw * 0.07)), int(pw * 0.22)
        tile.paste(powerclip(im, pw - 2 * side, ph - side - bottom), (side, side))
        tile = tile.rotate(ang, expand=True, resample=Image.BICUBIC)
        canvas.paste(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)), tile)
    return canvas


def render_muro(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cols = max(2, min(12, round(w / (s * 0.75))))
    rects = []
    for c in range(cols):
        x0, x1 = round(c * w / cols), round((c + 1) * w / cols)
        k = max(2, min(6, round(h / (s * 0.9)) + random.choice((-1, 0, 1))))
        wts = [random.uniform(0.6, 1.5) for _ in range(k)]
        y = 0.0
        for i, wt in enumerate(wts):
            y1 = h if i == k - 1 else y + h * wt / sum(wts)
            rects.append((x0, int(y), x1 - x0, int(y1) - int(y)))
            y = y1
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_hero(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    land = w >= h
    L, S = (w, h) if land else (h, w)            # L = lado largo, S = lado corto
    big = int(L * 0.58)
    first = random.random() < 0.5
    cell = max(60, s * 0.55)
    ro, rl = (big, L - big) if first else (0, L - big)
    cols, rows = max(1, round(rl / cell)), max(2, round(S / cell))
    spans = [(round(i * rl / cols), round((i + 1) * rl / cols)) for i in range(cols)]
    rspans = [(round(i * S / rows), round((i + 1) * S / rows)) for i in range(rows)]
    boxes = [((0 if first else L - big), 0, big, S)]
    boxes += [(ro + a, c0, b - a, c1 - c0) for a, b in spans for c0, c1 in rspans]
    rects = boxes if land else [(y, x, hh, ww) for x, y, ww, hh in boxes]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_diagonal(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    ang = rot if rot else 22.0
    if rot_random:
        ang = random.uniform(15, 60) * random.choice((-1, 1))
    a = math.radians(ang)
    nx, ny = -math.sin(a), math.cos(a)
    cx, cy = w / 2, h / 2
    T = abs(w * math.sin(a)) + abs(h * math.cos(a))
    k = max(3, min(24, round(T / (s * 0.6))))
    wts = [random.uniform(0.7, 1.3) for _ in range(k)]
    rect = [(0, 0), (w, 0), (w, h), (0, h)]
    polys, t0 = [], -T / 2
    for wt in wts:
        t1 = t0 + T * wt / sum(wts)
        p = _clip(rect, nx, ny, -(nx * cx + ny * cy) - t0)
        if len(p) >= 3:
            p = _clip(p, -nx, -ny, (nx * cx + ny * cy) + t1)
        polys.append(p)
        t0 = t1
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, s * 0.6)


def _heart(w, h):
    pts = [(16 * math.sin(t) ** 3,
            -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
           for t in (math.tau * i / 200 for i in range(200))]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    k = 0.92 * min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [(w / 2 + (x - mx) * k, h / 2 + (y - my) * k) for x, y in pts]


def render_heart(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(_heart(w, h), fill=255)
    px, m = mask.load(), _margin(_gap(w, h, bt))
    x0, y0, x1, y1 = mask.getbbox()
    c = max(32, int(s * 0.2))                       # unas 12 piezas a lo ancho: la forma se reconoce
    while ((x1 - x0) * (y1 - y0) * 0.6) / (c * c) > 500:
        c = int(c * 1.15) + 1
    gx, gy = x0 + ((x1 - x0) % c) // 2, y0 + ((y1 - y0) % c) // 2
    rects = []
    for j in range((y1 - y0) // c + 1):
        for i in range((x1 - x0) // c + 1):
            x, y = gx + i * c, gy + j * c
            pts = ((x + m, y + m), (x + c - m, y + m), (x + c - m, y + c - m), (x + m, y + c - m))
            if all(0 <= u < w and 0 <= v < h and px[u, v] for u, v in pts):
                rects.append((x, y, c, c))
    return _rect_collage(w, h, imgs, rects or [(0, 0, w, h)], bt, bc, shuffle)


def _sector(cx, cy, r0, r1, a0, a1, steps=16):
    arc = lambda r, u0, u1: [(cx + r * math.cos(u0 + (u1 - u0) * i / steps),
                              cy + r * math.sin(u0 + (u1 - u0) * i / steps)) for i in range(steps + 1)]
    return arc(r1, a0, a1) + (arc(r0, a1, a0) if r0 > 0 else [(cx, cy)])


def _disc(cx, cy, r, n=48):
    return [(cx + r * math.cos(math.tau * i / n), cy + r * math.sin(math.tau * i / n)) for i in range(n)]


def render_wheel(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cx, cy, mn = w / 2, h / 2, min(w, h)
    R = math.hypot(w, h) / 2 + 4
    r0 = 0.22 * mn
    n = max(6, min(16, round(math.pi * mn / s)))
    a0 = math.radians(rot + (random.uniform(0, 360) if rot_random else 0))
    polys = [_disc(cx, cy, r0)]
    polys += [_sector(cx, cy, r0, R, a0 + math.tau * i / n, a0 + math.tau * (i + 1) / n) for i in range(n)]
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, mn / 4)


def render_rings(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cx, cy, mn = w / 2, h / 2, min(w, h)
    R = math.hypot(w, h) / 2 + 4
    edges, counts = [0.18 * mn, 0.36 * mn, 0.56 * mn, R], [6, 12, 18]
    a0 = math.radians(rot + (random.uniform(0, 360) if rot_random else 0))
    polys = [_disc(cx, cy, edges[0])]
    for ring, n in enumerate(counts):
        off = a0 + (math.pi / n if ring % 2 else 0)
        polys += [_sector(cx, cy, edges[ring], edges[ring + 1], off + math.tau * i / n,
                          off + math.tau * (i + 1) / n) for i in range(n)]
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, mn / 4)


def render_film(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g = _gap(w, h, bt)
    canvas = Image.new("RGB", (w, h), bc)
    d = ImageDraw.Draw(canvas)
    rows = max(2, min(8, round(h / (s * 0.75))))
    frames = []
    for r in range(rows):
        y0, y1 = int(r * h / rows + g / 2), int((r + 1) * h / rows - g / 2)
        sh = y1 - y0
        d.rectangle((0, y0, w, y1), fill=FILM_BAND)
        hw, hh = max(5, int(sh * 0.075)), max(3, int(sh * 0.05))
        pitch = hw * 2.2
        for i in range(int(w / pitch) + 1):
            hx = int(i * pitch + pitch * 0.25)
            for hy in (y0 + int(sh * 0.06), y1 - int(sh * 0.06) - hh):
                d.rounded_rectangle((hx, hy, hx + hw, hy + hh), radius=max(1, hh // 3), fill=bc)
        fh = int(sh * 0.64)
        fy = y0 + (sh - fh) // 2
        gf = max(g, int(sh * 0.07))
        cols = max(1, int((w - gf) // (fh * 1.35 + gf)))
        fw = int((w - gf * (cols + 1)) / cols)
        frames += [(gf + c * (fw + gf), fy, fw, fh) for c in range(cols)]
    picks = _assign(imgs, [(x + fw / 2, y + fh / 2) for x, y, fw, fh in frames], max(w, h) / 6, shuffle)
    for (x, y, fw, fh), im in zip(frames, picks):
        canvas.paste(powerclip(im, fw, fh), (x, y))
    return canvas


def _voronoi(w, h, n):
    cols = max(1, round(math.sqrt(n * w / h)))
    rows = max(1, round(n / cols))
    pts = [((c + 0.5 + random.uniform(-0.4, 0.4)) * w / cols, (r + 0.5 + random.uniform(-0.4, 0.4)) * h / rows)
           for r in range(rows) for c in range(cols)]
    rect = [(0, 0), (w, 0), (w, h), (0, h)]
    for it in range(3):
        cells = []
        for xi, yi in pts:
            poly = rect
            for xj, yj in sorted(pts, key=lambda p: (p[0] - xi) ** 2 + (p[1] - yi) ** 2)[1:]:
                if math.hypot(xj - xi, yj - yi) / 2 > max(math.hypot(px - xi, py - yi) for px, py in poly):
                    break          # las demás ya no pueden recortar esta celda
                poly = _clip(poly, xi - xj, yi - yj, ((xj * xj + yj * yj) - (xi * xi + yi * yi)) / 2)
                if len(poly) < 3:
                    break
            cells.append(poly)
        if it < 2:                 # relajación: acerca cada semilla al centro de su celda (celdas más regulares)
            pts = [_center(p) if len(p) >= 3 else q for p, q in zip(cells, pts)]
    return cells


def render_stained(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    n = max(6, min(60, round(w * h / (s * s * 0.7))))
    return _poly_collage(w, h, imgs, _voronoi(w, h, n), bt, bc, shuffle, math.sqrt(w * h / n) * 0.6)


def render_photomosaic(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    """La PRIMERA foto se reconstruye con miniaturas de las demás, según el color de cada zona."""
    g = _gap(w, h, bt)
    cell = max(24, int(s / 8), int(math.sqrt(w * h / 2500)))
    cols, rows = max(1, w // cell), max(1, h // cell)
    cw, ch = w / cols, h / rows
    m = min(_margin(g), max(1, int(0.2 * min(cw, ch))))
    tw, th = max(2, int(cw) - 2 * m), max(2, int(ch) - 2 * m)
    target = powerclip(imgs[0], w, h).resize((cols, rows), Image.BOX)
    srcs = imgs[1:] or imgs
    base = [powerclip(im, tw, th) for im in srcs]
    avg = [im.resize((1, 1), Image.BOX).getpixel((0, 0)) for im in base]
    P, cnt = len(srcs), [0] * len(srcs)
    grid = [[-1] * cols for _ in range(rows)]
    canvas = Image.new("RGB", (w, h), bc)
    for r in range(rows):
        for c in range(cols):
            tc = target.getpixel((c, r))
            near = {grid[r][c - 1] if c else -1, grid[r - 1][c] if r else -1,
                    grid[r - 1][c - 1] if r and c else -1, grid[r - 1][c + 1] if r and c + 1 < cols else -1}
            mean = (r * cols + c) / P
            p = min(range(P), key=lambda q: sum((a - b) ** 2 for a, b in zip(avg[q], tc))
                    + (1e7 if (q in near and P > 1) else 0) + 60 * (cnt[q] - mean))
            cnt[p] += 1
            grid[r][c] = p
            tile = Image.blend(base[p], Image.new("RGB", (tw, th), tc), 0.58)   # acerca el color al de la foto
            canvas.paste(tile, (int(c * cw) + m, int(r * ch) + m))
    return canvas


COLLAGES = {"Polaroid": render_polaroid, "Muro": render_muro, "Héroe": render_hero,
            "Diagonal": render_diagonal, "Corazón": render_heart, "Rueda": render_wheel,
            "Anillos": render_rings, "Película": render_film, "Vitral": render_stained,
            "Foto-mosaico": render_photomosaic}


# ---------------------------------------------------------------- 20 collages creativos más
# Misma regla: ninguna foto se superpone ni se toca (separación mínima _gap()).
def _spans(total, n, weights=None):
    weights = weights or [1.0] * n
    tot, pos, out = sum(weights), 0.0, [0]
    for wt in weights:
        pos += total * wt / tot
        out.append(int(round(pos)))
    return out


def _pack(xs, ys):
    """Une celdas contiguas de una rejilla (1x1, 2x1, 1x2, 2x2) al azar, sin dejar huecos."""
    nx, ny = len(xs) - 1, len(ys) - 1
    used = [[False] * nx for _ in range(ny)]
    rects = []
    for r in range(ny):
        for c in range(nx):
            if used[r][c]:
                continue
            opts = [(1, 1)]
            for (dc, dr), p in (((2, 2), 0.16), ((2, 1), 0.28), ((1, 2), 0.28)):
                if c + dc <= nx and r + dr <= ny and random.random() < p and \
                        all(not used[r + i][c + j] for i in range(dr) for j in range(dc)):
                    opts.append((dc, dr))
            dc, dr = random.choice(opts[1:] or opts)
            for i in range(dr):
                for j in range(dc):
                    used[r + i][c + j] = True
            rects.append((xs[c], ys[r], xs[c + dc] - xs[c], ys[r + dr] - ys[r]))
    return rects


def _shapes_collage(w, h, imgs, polys, bt, bc, shuffle, cell):
    """Formas sueltas (ya separadas por construcción), sin recorte extra."""
    canvas = Image.new("RGB", (w, h), bc)
    polys = [p for p in polys if len(p) >= 3 and _visible(p, w, h)]
    picks = _assign(imgs, [_center(p) for p in polys], cell, shuffle)
    for pts, im in zip(polys, picks):
        paste_poly(canvas, im, pts, int(bt), bc)
    return canvas


def render_golden(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    rects, x, y, rw, rh, flip = [], 0, 0, w, h, random.random() < 0.5
    stop = max(70, s * 0.3)
    while min(rw, rh) > stop and len(rects) < 14:
        if rw >= rh:
            sq = rh
            rects.append((x, y, sq, rh) if flip else (x + rw - sq, y, sq, rh))
            x, rw = (x + sq if flip else x), rw - sq
        else:
            sq = rw
            rects.append((x, y, rw, sq) if flip else (x, y + rh - sq, rw, sq))
            y, rh = (y + sq if flip else y), rh - sq
        flip = not flip
    rects.append((x, y, rw, rh))
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_bento(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cols, rows = max(3, min(6, round(w / (s * 0.8)))), max(3, min(6, round(h / (s * 0.8))))
    return _rect_collage(w, h, imgs, _pack(_spans(w, cols), _spans(h, rows)), bt, bc, shuffle)


def render_pyramid(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    rows = max(2, min(7, round(h / (s * 0.6))))
    ys, pw, flip = _spans(h, rows), w // rows, random.random() < 0.5
    rects = []
    for i in range(rows):
        n = rows - i if flip else i + 1
        x0 = (w - n * pw) // 2
        rects += [(x0 + j * pw, ys[i], pw, ys[i + 1] - ys[i]) for j in range(n)]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_centerpiece(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    t = int(min(w, h) * 0.2)
    rects = [(t, t, w - 2 * t, h - 2 * t)]
    xs, ys = _spans(w, max(2, round(w / (t * 1.4)))), _spans(h - 2 * t, max(1, round((h - 2 * t) / (t * 1.4))))
    for i in range(len(xs) - 1):
        rects += [(xs[i], 0, xs[i + 1] - xs[i], t), (xs[i], h - t, xs[i + 1] - xs[i], t)]
    for i in range(len(ys) - 1):
        rects += [(0, t + ys[i], t, ys[i + 1] - ys[i]), (w - t, t + ys[i], t, ys[i + 1] - ys[i])]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_brick(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    hb = max(80, s * 0.45)
    rows = max(2, round(h / hb))
    n = max(2, round(w / (hb * 1.9)))
    ys, cw, rects = _spans(h, rows), w / n, []
    for r in range(rows):
        if r % 2 == 0:
            edges = [int(round(k * cw)) for k in range(n + 1)]
        else:
            edges = [0] + [int(round((k + 0.5) * cw)) for k in range(n)] + [w]
        rects += [(edges[i], ys[r], edges[i + 1] - edges[i], ys[r + 1] - ys[r]) for i in range(len(edges) - 1)]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_blinds(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    vertical = w >= h
    L = w if vertical else h
    n = max(4, min(30, round(L / (s * 0.35))))
    b = _spans(L, n, [random.uniform(0.5, 1.6) for _ in range(n)])
    rects = [(b[i], 0, b[i + 1] - b[i], h) for i in range(n)] if vertical \
        else [(0, b[i], w, b[i + 1] - b[i]) for i in range(n)]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_fan(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cx, cy, R = w / 2, h, math.hypot(w / 2, h) + 4
    n = max(5, min(12, round(w / (s * 0.5))))
    polys = [_sector(cx, cy, 0, R, math.pi + math.pi * i / n, math.pi + math.pi * (i + 1) / n) for i in range(n)]
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, min(w, h) / 4)


def render_bubbles(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g = _gap(w, h, bt)
    rmax = max(40, min(min(w, h) * 0.24, s * 0.55))
    rmin, circles, r = max(18, rmax * 0.2), [], rmax
    while r >= rmin and len(circles) < 90:
        fails = 0
        while fails < 80 and len(circles) < 90:
            x, y = random.uniform(r + g, w - r - g), random.uniform(r + g, h - r - g)
            if all(math.hypot(x - cx, y - cy) >= r + cr + g + 1 for cx, cy, cr in circles):
                circles.append((x, y, r))
                fails = 0
            else:
                fails += 1
        r *= 0.9
    return _shapes_collage(w, h, imgs, [_disc(x, y, r) for x, y, r in circles], bt, bc, shuffle, rmax * 1.5)


def render_circles(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g, cell = _gap(w, h, bt), max(120, s * 0.7)
    xs, ys = _spans(w, max(2, round(w / cell))), _spans(h, max(1, round(h / cell)))
    polys = []
    for r in range(len(ys) - 1):
        for c in range(len(xs) - 1):
            cw, ch = xs[c + 1] - xs[c], ys[r + 1] - ys[r]
            polys.append(_disc(xs[c] + cw / 2, ys[r] + ch / 2, (min(cw, ch) - g - 1) / 2))
    return _shapes_collage(w, h, imgs, polys, bt, bc, shuffle, cell)


def render_flower(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g, cx, cy, mn = _gap(w, h, bt), w / 2, h / 2, min(w, h)
    n = max(6, min(12, round(mn / (s * 0.45))))
    d, a = 0.31 * mn, 0.16 * mn
    b = max(8, 0.36 * 2 * d * math.sin(math.pi / n) - g)
    a0 = math.radians(rot + (random.uniform(0, 360) if rot_random else 0))
    polys = [_disc(cx, cy, max(10, d - a - 1.5 * g))]
    for i in range(n):
        th = a0 + math.tau * i / n
        ct, st = math.cos(th), math.sin(th)
        polys.append([(cx + (d + a * math.cos(ph)) * ct - b * math.sin(ph) * st,
                       cy + (d + a * math.cos(ph)) * st + b * math.sin(ph) * ct)
                      for ph in (math.tau * k / 40 for k in range(40))])
    return _shapes_collage(w, h, imgs, polys, bt, bc, shuffle, mn / 4)


def render_carousel(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g, cx, cy, mn = _gap(w, h, bt), w / 2, h / 2, min(w, h)
    n = max(6, min(14, round(mn / (s * 0.32))))
    sn = math.sin(math.pi / n)
    Rc = (0.49 * mn + g / 2) / (1 + sn)
    q = (2 * Rc * sn - g) / 1.4143
    a0 = math.radians(rot + (random.uniform(0, 360) if rot_random else 0))
    polys = [_disc(cx, cy, max(10, Rc * (1 - sn) - 0.7 * g))]
    for i in range(n):
        th = a0 + math.tau * i / n
        px, py, ct, st = cx + Rc * math.cos(th), cy + Rc * math.sin(th), math.cos(th), math.sin(th)
        polys.append([(px + u * ct - v * st, py + u * st + v * ct)
                      for u, v in ((-q / 2, -q / 2), (q / 2, -q / 2), (q / 2, q / 2), (-q / 2, q / 2))])
    return _shapes_collage(w, h, imgs, polys, bt, bc, shuffle, mn / 4)


def render_arches(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g = _gap(w, h, bt)
    xs = _spans(w, max(2, min(8, round(w / (s * 0.8)))))
    ys = _spans(h, max(1, min(4, round(h / (s * 1.1)))))
    polys = []
    for r in range(len(ys) - 1):
        for c in range(len(xs) - 1):
            ah = ys[r + 1] - ys[r] - g
            aw = min(xs[c + 1] - xs[c] - g, ah * 1.6)
            if aw < 24 or ah < 24:
                continue
            x, y = xs[c] + (xs[c + 1] - xs[c] - aw) / 2, ys[r] + g / 2
            rad = aw / 2
            polys.append([(x, y + ah), (x, y + rad)]
                         + [(x + rad - rad * math.cos(math.pi * i / 24), y + rad - rad * math.sin(math.pi * i / 24))
                            for i in range(1, 24)] + [(x + aw, y + rad), (x + aw, y + ah)])
    return _shapes_collage(w, h, imgs, polys, bt, bc, shuffle, s * 0.8)


def render_booth(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    g = _gap(w, h, bt)
    n = max(2, min(5, round(w / (s * 0.9))))
    gs = max(g, int(0.03 * w))
    sw, sh = (w - (n + 1) * gs) // n, h - 2 * gs
    pad = max(g, int(sw * 0.07))
    k = max(3, min(6, round(sh / (sw * 0.85))))
    pw, ph = sw - 2 * pad, (sh - (k + 1) * pad) // k
    canvas = Image.new("RGB", (w, h), bc)
    d, frames = ImageDraw.Draw(canvas), []
    for i in range(n):
        x = gs + i * (sw + gs)
        d.rectangle((x, gs, x + sw - 1, gs + sh - 1), fill=POLAROID_FRAME)
        frames += [(x + pad, gs + pad + j * (ph + pad), pw, ph) for j in range(k)]
    picks = _assign(imgs, [(x + pw / 2, y + ph / 2) for x, y, _, _ in frames], max(w, h) / 6, shuffle)
    for (x, y, fw, fh), im in zip(frames, picks):
        canvas.paste(powerclip(im, fw, fh), (x, y))
    return canvas


def render_checker(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cell = max(90, s * 0.6)
    xs, ys = _spans(w, max(2, round(w / cell))), _spans(h, max(2, round(h / cell)))
    par = random.randint(0, 1)
    rects = [(xs[c], ys[r], xs[c + 1] - xs[c], ys[r + 1] - ys[r])
             for r in range(len(ys) - 1) for c in range(len(xs) - 1) if (r + c) % 2 == par]
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def render_skyline(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    n = max(5, min(18, round(w / (s * 0.4))))
    xs, rects = _spans(w, n), []
    for i in range(n):
        bh = int(h * random.uniform(0.38, 0.97))
        x, bw = xs[i], xs[i + 1] - xs[i]
        if bh > 0.62 * h:
            top = int(bh * 0.55)
            rects += [(x, h - bh, bw, top), (x, h - bh + top, bw, bh - top)]
        else:
            rects.append((x, h - bh, bw, bh))
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


def _bands(w, h, n, f, amp, samples):
    """Franjas entre curvas paralelas y = j*alto + f(x): comparten el borde exacto."""
    bh = (h + 2 * amp + 4) / n
    xs = [w * i / samples for i in range(samples + 1)]
    line = lambda j: [(x, -amp - 2 + j * bh + f(x)) for x in xs]
    return [line(j) + line(j + 1)[::-1] for j in range(n)]


def render_chevron(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    amp = 0.25 * h
    polys = _bands(w, h, max(4, min(14, round(h / (s * 0.5)))), lambda x: amp * abs(x - w / 2) / (w / 2), amp, 2)
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, s * 0.6)


def render_waves(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    amp = 0.06 * h
    polys = _bands(w, h, max(4, min(14, round(h / (s * 0.5)))), lambda x: amp * math.sin(math.tau * 2 * x / w), amp, 48)
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, s * 0.6)


def render_gem(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    cx, cy, mn = w / 2, h / 2, min(w, h)
    r2 = 0.47 * mn
    r1 = 0.5 * r2
    a0 = math.radians(rot + (random.uniform(0, 60) if rot_random else 0))
    P = [(cx + r1 * math.cos(a0 + math.pi / 3 * i), cy + r1 * math.sin(a0 + math.pi / 3 * i)) for i in range(6)]
    Q = [(cx + r2 * math.cos(a0 + math.pi / 3 * i + math.pi / 6), cy + r2 * math.sin(a0 + math.pi / 3 * i + math.pi / 6))
         for i in range(6)]
    polys = [[(cx, cy), P[i], P[(i + 1) % 6]] for i in range(6)]
    polys += [[P[i], P[(i + 1) % 6], Q[i]] for i in range(6)]
    polys += [[Q[i - 1], Q[i], P[i]] for i in range(6)]
    return _poly_collage(w, h, imgs, polys, bt, bc, shuffle, mn / 5)


def render_mondrian(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    def cuts(total, k):
        for _ in range(60):
            pts = sorted(random.uniform(0.12, 0.88) for _ in range(k))
            if all(b - a >= 0.14 for a, b in zip([0] + pts, pts + [1])):
                break
        return [0] + [int(p * total) for p in pts] + [total]
    xs, ys = cuts(w, random.randint(3, 5)), cuts(h, random.randint(2, 3))
    return _rect_collage(w, h, imgs, _pack(xs, ys), bt, bc, shuffle)


def render_nested(w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle):
    t = max(80, int(min(w, h) * 0.17))
    rects, x, y, rw, rh = [], 0, 0, w, h
    for _ in range(2):
        if rw <= 2 * t + 80 or rh <= 2 * t + 80:
            break
        xs, ys = _spans(rw, max(2, round(rw / (t * 1.5)))), _spans(rh - 2 * t, max(1, round((rh - 2 * t) / (t * 1.5))))
        for i in range(len(xs) - 1):
            rects += [(x + xs[i], y, xs[i + 1] - xs[i], t), (x + xs[i], y + rh - t, xs[i + 1] - xs[i], t)]
        for i in range(len(ys) - 1):
            rects += [(x, y + t + ys[i], t, ys[i + 1] - ys[i]), (x + rw - t, y + t + ys[i], t, ys[i + 1] - ys[i])]
        x, y, rw, rh = x + t, y + t, rw - 2 * t, rh - 2 * t
    rects.append((x, y, rw, rh))
    return _rect_collage(w, h, imgs, rects, bt, bc, shuffle)


COLLAGES.update({"Áureo": render_golden, "Bento": render_bento, "Pirámide": render_pyramid,
                 "Cuadro": render_centerpiece, "Ladrillo": render_brick, "Persianas": render_blinds,
                 "Abanico": render_fan, "Burbujas": render_bubbles, "Círculos": render_circles,
                 "Flor": render_flower, "Carrusel": render_carousel, "Arcos": render_arches,
                 "Cabina": render_booth, "Tablero": render_checker, "Horizonte": render_skyline,
                 "Chevron": render_chevron, "Olas": render_waves, "Gema": render_gem,
                 "Mondrian": render_mondrian, "Marcos": render_nested})


# ---------------------------------------------------------------- filtros, marca y render final
def apply_fx(im, fx, bright=1.0, contrast=1.0):
    if fx == "Blanco y negro":
        im = ImageOps.grayscale(im).convert("RGB")
    elif fx == "Sepia":
        im = ImageOps.colorize(ImageOps.grayscale(im), (28, 16, 6), (255, 238, 205))
    elif fx == "Vivo":
        im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.6)).enhance(1.1)
    if bright != 1.0:
        im = ImageEnhance.Brightness(im).enhance(bright)
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    return im


def add_brand(img, logo_path, opacity=0.6, rel_width=0.17):
    """Marca PHAIZERX en la esquina inferior derecha, con sombra suave para que se lea sobre cualquier fondo."""
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception:
        return img
    w, h = img.size
    lw = max(40, int(w * rel_width))
    logo = logo.resize((lw, max(1, round(logo.height * lw / logo.width))), Image.LANCZOS)
    alpha = logo.getchannel("A").point(lambda v: int(v * opacity))
    x, y = w - lw - int(w * 0.02), h - logo.height - int(h * 0.02)
    shadow = alpha.point(lambda v: int(v * 0.6))
    img.paste(Image.new("RGB", logo.size, (0, 0, 0)), (x + 2, y + 2), shadow)
    img.paste(logo.convert("RGB"), (x, y), alpha)
    return img


def _render_core(style, w, h, imgs, s, bt, bc, rng=0.12, rot=0, rot_random=False, shuffle=True, seed=None):
    if seed is not None:
        random.seed(seed)  # mismo seed = mismo diseño
    if style in COLLAGES:
        return COLLAGES[style](w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle)
    if style == "Collage":
        return render_collage(w, h, imgs, bt, bc, shuffle)
    if style == "Grid 3x3":
        return render_grid(w, h, imgs, bt, bc, shuffle)
    if style == "Red de diamantes":
        return render_diamond_network(w, h, imgs, s, bt, bc, shuffle)
    return render_tiles(w, h, imgs, style, s, bt, bc, rng, rot, rot_random, shuffle)


def render(style, w, h, imgs, s, bt, bc, rng=0.12, rot=0, rot_random=False, shuffle=True, seed=None,
           border="Sólido", fx="Ninguno", bright=1.0, contrast=1.0, overrides=None):
    """border: modo del borde (BORDERS). fx/bright/contrast: filtro de fotos (no toca el color del borde).
    overrides: {n.º de pieza: n.º de foto} para cambiar a mano la foto de una pieza."""
    _BORD.update(mode=border, w=max(1, w), h=max(1, h))
    _OVR.clear()
    _OVR.update(overrides or {})
    LAST.update(centers=[], ids=[], P=0, size=(w, h))
    if fx != "Ninguno" or bright != 1.0 or contrast != 1.0:
        imgs = [apply_fx(im, fx, bright, contrast) for im in imgs]
    return _render_core(style, w, h, imgs, s, bt, bc, rng, rot, rot_random, shuffle, seed)
