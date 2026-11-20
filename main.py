"""Mosaic Studio - UI moderna (Kivy). Motor de render en engine.py (solo PIL)."""
import io
import os
import sys
import uuid
import datetime
import json
import random
import threading
from functools import partial

from kivy.config import Config
Config.set("graphics", "multisamples", "0")

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scatter import Scatter
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from PIL import Image as PILImage, ImageOps

import engine

IS_ANDROID = "ANDROID_ARGUMENT" in os.environ or "android" in sys.platform

# ------------------------------------------------------------------ tema
BG = (0.055, 0.063, 0.082, 1)
SURFACE = (0.095, 0.105, 0.135, 1)
SURFACE2 = (0.15, 0.165, 0.21, 1)
ACCENT = (0.40, 0.42, 0.98, 1)
TEXT = (0.93, 0.94, 0.97, 1)
MUTED = (0.56, 0.59, 0.66, 1)
WHITE = (1, 1, 1, 1)
Window.clearcolor = BG
if not IS_ANDROID:
    Window.size = (400, 800)

# ------------------------------------------------------------------ rutas
if IS_ANDROID:
    try:
        from android.storage import primary_external_storage_path
        BASE = primary_external_storage_path()
    except Exception:
        BASE = "/storage/emulated/0"
else:
    BASE = os.path.expanduser("~")


def start_dir():
    for sub in ("Pictures", "DCIM"):
        p = os.path.join(BASE, sub)
        if os.path.isdir(p):
            return p
    return BASE


EXPORT_DIR = os.path.join(BASE, "Pictures", "MosaicStudio")
HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "icon.png")


def unique_name():
    return f"MOSAIC_{uuid.uuid4().hex[:4].upper()}_{datetime.datetime.now():%Y%m%d_%H%M%S}"


def media_scan(path):
    if not IS_ANDROID:
        return
    try:
        from jnius import autoclass
        scanner = autoclass("android.media.MediaScannerConnection")
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        scanner.scanFile(activity, [path], None, None)
    except Exception:
        pass


# ------------------------------------------------------------------ widgets base
def lbl(text="", size=14, color=TEXT, halign="left", bold=False, **kw):
    w = Label(text=text, font_size=sp(size), color=color, halign=halign,
              valign="middle", bold=bold, **kw)
    w.bind(size=lambda i, v: setattr(i, "text_size", v))
    return w


class RBtn(ButtonBehavior, Label):
    """Botón redondeado con feedback al pulsar."""

    def __init__(self, bg=SURFACE2, fg=TEXT, radius=14, **kw):
        kw.setdefault("font_size", sp(13))
        super().__init__(**kw)
        self.bg, self.color = bg, fg
        self.halign = self.valign = "center"
        with self.canvas.before:
            self._c = Color(*bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._upd, size=self._upd, state=self._state)

    def _upd(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self.text_size = (self.width - dp(8), self.height)

    def _state(self, *_):
        k = 0.78 if self.state == "down" else 1
        self._c.rgba = (self.bg[0] * k, self.bg[1] * k, self.bg[2] * k, self.bg[3])

    def set_colors(self, bg, fg):
        self.bg, self.color = bg, fg
        self._c.rgba = bg


class ChipGroup:
    """Selección única con chips."""

    def __init__(self, options, default, on_change=None, cols=3, height=44):
        self.value, self.on_change, self.chips = default, on_change, {}
        self.widget = GridLayout(cols=cols, spacing=dp(8), size_hint_y=None,
                                 row_default_height=dp(height), row_force_default=True)
        self.widget.bind(minimum_height=self.widget.setter("height"))
        for o in options:
            c = RBtn(text=o, font_size=sp(12), radius=12)
            c.bind(on_release=lambda _b, o=o: self.select(o))
            self.chips[o] = c
            self.widget.add_widget(c)
        self._paint()

    def select(self, o, notify=True):
        self.value = o
        self._paint()
        if notify and self.on_change:
            self.on_change(o)

    def _paint(self):
        for o, c in self.chips.items():
            c.set_colors(*((ACCENT, WHITE) if o == self.value else (SURFACE2, TEXT)))


class Toggle(RBtn):
    def __init__(self, text, active=False, **kw):
        super().__init__(text=text, radius=12, **kw)
        self.title, self.active = text, active
        self.bind(on_release=self.flip)
        self._paint()

    def flip(self, *_):
        self.active = not self.active
        self._paint()

    def _paint(self):
        self.text = f"{self.title}: {'SÍ' if self.active else 'NO'}"
        self.set_colors(*((ACCENT, WHITE) if self.active else (SURFACE2, MUTED)))


class SliderRow(BoxLayout):
    def __init__(self, title, mn, mx, val, step=1, fmt="{:.0f}", **kw):
        super().__init__(orientation="vertical", size_hint_y=None, height=dp(62), **kw)
        head = BoxLayout(size_hint_y=None, height=dp(24))
        head.add_widget(lbl(title, 13, MUTED))
        self.value_lbl = lbl(fmt.format(val), 13, TEXT, halign="right", bold=True)
        head.add_widget(self.value_lbl)
        self.slider = Slider(min=mn, max=mx, value=val, step=step, value_track=True,
                             value_track_color=ACCENT, cursor_size=(dp(24), dp(24)))
        self.slider.bind(value=lambda _s, v: setattr(self.value_lbl, "text", fmt.format(v)))
        self.add_widget(head)
        self.add_widget(self.slider)

    @property
    def value(self):
        return self.slider.value


class AppBar(BoxLayout):
    def __init__(self, title, left=None, right=None, **kw):
        super().__init__(size_hint_y=None, height=dp(60), padding=(dp(12), dp(8)),
                         spacing=dp(8), **kw)
        if left:
            self.add_widget(left)
        elif os.path.exists(LOGO):
            self.add_widget(Image(source=LOGO, size_hint=(None, None), size=(dp(40), dp(40)),
                                  pos_hint={"center_y": 0.5}))
        self.add_widget(lbl(title, 20, TEXT, bold=True))
        if right:
            self.add_widget(right)


class Toast(Label):
    def __init__(self, text, **kw):
        super().__init__(text=text, font_size=sp(13), color=TEXT, size_hint=(None, None),
                         padding=(dp(18), dp(10)), **kw)
        self.texture_update()
        self.size = (min(self.texture_size[0] + dp(36), Window.width - dp(32)),
                     self.texture_size[1] + dp(20))
        self.text_size = (self.width - dp(36), None)
        self.pos = ((Window.width - self.width) / 2, dp(110))
        with self.canvas.before:
            Color(0.2, 0.22, 0.3, 0.97)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])


def toast(text, dur=2.2):
    t = Toast(text)
    Window.add_widget(t)
    anim = Animation(opacity=0, duration=0.4, t="in_quad")
    anim.bind(on_complete=lambda *_: Window.remove_widget(t))
    Clock.schedule_once(lambda _dt: anim.start(t), dur)


class Busy(ModalView):
    def __init__(self, **kw):
        super().__init__(size_hint=(None, None), size=(dp(250), dp(110)), auto_dismiss=False,
                         background="", background_color=SURFACE, **kw)
        self.msg = lbl("", 15, TEXT, halign="center")
        self.add_widget(self.msg)

    def show(self, text):
        self.msg.text = text
        self.open()


# ------------------------------------------------------------------ galería
class Thumb(ButtonBehavior, FloatLayout):
    def __init__(self, path, **kw):
        super().__init__(size_hint_y=None, **kw)
        self.path = path
        with self.canvas.before:
            Color(*SURFACE2)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.img = Image()
        self.add_widget(self.img)
        with self.canvas.after:
            self._dim = Color(0, 0, 0, 0)
            self._dr = Rectangle(pos=self.pos, size=self.size)
            self._bc = Color(ACCENT[0], ACCENT[1], ACCENT[2], 0)
            self._bl = Line(width=dp(2.5), rectangle=(0, 0, 0, 0))
        self.badge = Label(text="", size_hint=(None, None), size=(dp(26), dp(26)),
                           font_size=sp(13), bold=True, color=WHITE, opacity=0)
        with self.badge.canvas.before:
            Color(*ACCENT)
            self._be = Ellipse(pos=self.badge.pos, size=self.badge.size)
        self.badge.bind(pos=lambda i, v: setattr(self._be, "pos", v))
        self.add_widget(self.badge)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._bg.pos = self._dr.pos = self.pos
        self._bg.size = self._dr.size = self.size
        self._bl.rectangle = (self.x + 1, self.y + 1, self.width - 2, self.height - 2)
        self.img.pos, self.img.size = self.pos, self.size
        self.badge.pos = (self.right - dp(32), self.top - dp(32))

    def set_number(self, n):
        on = n > 0
        self.badge.text = str(n) if on else ""
        self.badge.opacity = 1 if on else 0
        self._bc.a = 1 if on else 0
        self._dim.a = 0.25 if on else 0


def make_thumb_bytes(path):
    im = PILImage.open(path)
    im.draft("RGB", (512, 512))
    im = ImageOps.fit(ImageOps.exif_transpose(im).convert("RGB"), (256, 256))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


class Gallery(Screen):
    MAX_FILES = 400

    def __init__(self, **kw):
        super().__init__(**kw)
        self.selected, self.thumbs, self._token, self.folder = [], {}, 0, ""
        root = BoxLayout(orientation="vertical")
        pick = RBtn(text="Carpeta", bg=ACCENT, fg=WHITE, size_hint_x=None, width=dp(100))
        pick.bind(on_release=self.open_picker)
        root.add_widget(AppBar("Mosaic Studio", right=pick))
        self.sub = lbl("Elige una carpeta para empezar", 12, MUTED, size_hint_y=None,
                       height=dp(22), padding=(dp(16), 0))
        root.add_widget(self.sub)

        body = FloatLayout()
        sv = ScrollView(size_hint=(1, 1))
        self.grid = GridLayout(cols=3, spacing=dp(6), padding=dp(10), size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter("height"), width=self._cell)
        sv.add_widget(self.grid)
        body.add_widget(sv)
        self.empty = lbl("Aquí aparecerán tus fotos.\nToca «Carpeta» para elegirlas.",
                         15, MUTED, halign="center", size_hint=(1, 1))
        body.add_widget(self.empty)
        root.add_widget(body)

        bar = BoxLayout(size_hint_y=None, height=dp(78), padding=dp(12), spacing=dp(8))
        with bar.canvas.before:
            Color(*SURFACE)
            self._barbg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=lambda i, v: setattr(self._barbg, "pos", v),
                 size=lambda i, v: setattr(self._barbg, "size", v))
        all_b, clr = RBtn(text="Todas"), RBtn(text="Limpiar")
        all_b.bind(on_release=self.select_all)
        clr.bind(on_release=self.clear)
        self.go = RBtn(text="Continuar", bg=SURFACE2, fg=MUTED, size_hint_x=1.5, bold=True)
        self.go.bind(on_release=self.next)
        for w in (all_b, clr, self.go):
            bar.add_widget(w)
        root.add_widget(bar)
        self.add_widget(root)

    # --- carpeta
    def open_picker(self, *_):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        fc = FileChooserListView(path=start_dir(), dirselect=True)
        shortcuts = GridLayout(cols=4, size_hint_y=None, height=dp(40), spacing=dp(6))
        for name, sub in (("Pictures", "Pictures"), ("DCIM", "DCIM"),
                          ("Download", "Download"), ("Inicio", "")):
            b = RBtn(text=name, radius=10)
            target = os.path.join(BASE, sub) if sub else BASE
            b.bind(on_release=lambda _b, t=target: setattr(fc, "path", t) if os.path.isdir(t) else None)
            shortcuts.add_widget(b)
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        cancel, ok = RBtn(text="Cancelar"), RBtn(text="Usar esta carpeta", bg=ACCENT, fg=WHITE)
        actions.add_widget(cancel)
        actions.add_widget(ok)
        for w in (shortcuts, fc, actions):
            box.add_widget(w)
        pop = Popup(title="Elegir carpeta", content=box, size_hint=(0.96, 0.94),
                    background="", background_color=SURFACE, separator_color=ACCENT)

        def accept(*_):
            sel = fc.selection[0] if fc.selection and os.path.isdir(fc.selection[0]) else fc.path
            pop.dismiss()
            self.load_folder(sel)

        ok.bind(on_release=accept)
        cancel.bind(on_release=pop.dismiss)
        pop.open()

    def load_folder(self, folder):
        self.folder = folder
        self._token += 1
        self.selected, self.thumbs = [], {}
        self.grid.clear_widgets()
        try:
            files = sorted(f for f in os.listdir(folder)
                           if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")))
        except Exception:
            files = []
        if len(files) > self.MAX_FILES:
            toast(f"Mostrando las primeras {self.MAX_FILES} fotos")
            files = files[:self.MAX_FILES]
        paths = [os.path.join(folder, f) for f in files]
        for p in paths:
            t = Thumb(p)
            t.bind(on_release=self.toggle)
            self.thumbs[p] = t
            self.grid.add_widget(t)
        self._cell()
        self.empty.opacity = 0 if paths else 1
        self.empty.text = "No hay fotos en esta carpeta." if not paths else ""
        self.sub.text = f"{os.path.basename(folder) or folder}  ·  {len(paths)} fotos"
        self.refresh()
        threading.Thread(target=self._thumb_worker, args=(paths, self._token), daemon=True).start()

    def _thumb_worker(self, paths, token):
        for p in paths:
            if token != self._token:
                return
            try:
                data = make_thumb_bytes(p)
            except Exception:
                continue
            Clock.schedule_once(partial(self._set_thumb, p, data, token))

    def _set_thumb(self, path, data, token, _dt):
        if token == self._token and path in self.thumbs:
            self.thumbs[path].img.texture = CoreImage(io.BytesIO(data), ext="jpg").texture

    def _cell(self, *_):
        side = (self.grid.width - dp(20) - dp(12)) / 3
        for t in self.grid.children:
            t.height = side

    # --- selección
    def toggle(self, thumb):
        if thumb.path in self.selected:
            self.selected.remove(thumb.path)
        else:
            self.selected.append(thumb.path)
        self.refresh()

    def select_all(self, *_):
        self.selected = [t.path for t in reversed(self.grid.children)]
        self.refresh()

    def clear(self, *_):
        self.selected = []
        self.refresh()

    def refresh(self):
        for p, t in self.thumbs.items():
            t.set_number(self.selected.index(p) + 1 if p in self.selected else 0)
        n = len(self.selected)
        self.go.text = f"Continuar ({n})" if n else "Continuar"
        self.go.set_colors(*((ACCENT, WHITE) if n else (SURFACE2, MUTED)))

    def next(self, *_):
        if not self.selected:
            toast("Selecciona al menos una foto")
            return
        self.manager.get_screen("editor").load_images(list(self.selected))
        self.manager.current = "editor"


# ------------------------------------------------------------------ editor
SWATCHES = [(255, 255, 255), (0, 0, 0), (245, 232, 205), (30, 41, 59), (239, 68, 68), (250, 204, 21)]


class Editor(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.imgs, self.result, self.working, self.seed = [], None, False, None
        self.bc = (255, 255, 255)
        self.busy = Busy()
        root = BoxLayout(orientation="vertical")

        back = RBtn(text="‹", font_size=sp(24), size_hint_x=None, width=dp(44), radius=22)
        back.bind(on_release=lambda *_: setattr(self.manager, "current", "gallery"))
        save = RBtn(text="Guardar", bg=SURFACE2, size_hint_x=None, width=dp(96))
        save.bind(on_release=self.save)
        root.add_widget(AppBar("Editor", left=back, right=save))

        # vista previa
        self.stage = FloatLayout()
        self.scatter = Scatter(do_rotation=False, size_hint=(None, None), scale_min=0.5, scale_max=6)
        self.preview = Image(allow_stretch=True)
        self.scatter.add_widget(self.preview)
        self.stage.add_widget(self.scatter)
        self.hint = lbl("Pulsa «Generar» para crear\ntu mosaico", 15, MUTED,
                        halign="center", size_hint=(1, 1))
        self.stage.add_widget(self.hint)
        self.stage.bind(size=self._fit_preview, pos=self._fit_preview)
        root.add_widget(self.stage)

        root.add_widget(self._build_sheet())
        self.add_widget(root)

    def _fit_preview(self, *_):
        if self.scatter.scale == 1:
            self.scatter.size = self.stage.size
            self.scatter.pos = self.stage.pos

    # --- hoja inferior
    def _build_sheet(self):
        sheet = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(330),
                          padding=(dp(14), dp(14), dp(14), dp(10)), spacing=dp(10))
        with sheet.canvas.before:
            Color(*SURFACE)
            self._sbg = RoundedRectangle(pos=sheet.pos, size=sheet.size, radius=[dp(24)])
        sheet.bind(pos=self._sheet_bg, size=self._sheet_bg)

        self.tabs = ChipGroup(["Estilo", "Ajustes", "Formato"], "Estilo", self._tab, cols=3, height=38)
        sheet.add_widget(self.tabs.widget)

        self.sv = ScrollView(do_scroll_x=False)
        sheet.add_widget(self.sv)

        self.style = ChipGroup(engine.STYLES, "Diamante", cols=3)
        self.aspect = ChipGroup(list(engine.ASPECTS) + ["Original"], "16:9", cols=3)
        self.page_style = self._wrap(self.style.widget)
        self.page_aspect = self._wrap(self.aspect.widget)

        self.s_size = SliderRow("Tamaño de tesela", 50, 800, 400, 10, "{:.0f} px")
        self.s_border = SliderRow("Grosor de borde", 0, 50, 8, 1, "{:.0f} px")
        self.s_var = SliderRow("Variación de tamaño", 0, 0.5, 0.12, 0.01, "{:.2f}")
        self.s_rot = SliderRow("Rotación fija", -180, 180, 0, 1, "{:.0f}°")
        self.t_rand = Toggle("Rotación aleatoria", False, size_hint_y=None, height=dp(42))
        self.t_mix = Toggle("Mezclar fotos", True, size_hint_y=None, height=dp(42))
        self.t_fix = Toggle("Fijar diseño", False, size_hint_y=None, height=dp(42))
        sw_title = lbl("Color de borde", 13, MUTED, size_hint_y=None, height=dp(24))
        self.sw_grid = GridLayout(cols=7, spacing=dp(8), size_hint_y=None, height=dp(40))
        self.swatch_btns = []
        for c in SWATCHES:
            b = RBtn(bg=(c[0] / 255, c[1] / 255, c[2] / 255, 1), radius=20, font_size=sp(18))
            b.bind(on_release=lambda _b, c=c: self.set_color(c))
            self.swatch_btns.append((c, b))
            self.sw_grid.add_widget(b)
        more = RBtn(text="+", bg=SURFACE2, radius=20, font_size=sp(20))
        more.bind(on_release=self.pick_color)
        self.sw_grid.add_widget(more)
        self.page_adjust = self._wrap(self.s_size, self.s_border, self.s_var, self.s_rot,
                                      self.t_rand, self.t_mix, self.t_fix, sw_title, self.sw_grid)
        self.set_color(self.bc)

        actions = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        self.fmt = ChipGroup(["JPG", "PNG"], "JPG", cols=2, height=52)
        self.fmt.widget.size_hint_x = None
        self.fmt.widget.width = dp(130)
        gen = RBtn(text="Generar", bg=ACCENT, fg=WHITE, font_size=sp(16), bold=True, radius=16)
        gen.bind(on_release=self.generate)
        actions.add_widget(self.fmt.widget)
        actions.add_widget(gen)
        sheet.add_widget(actions)
        self._tab("Estilo")
        return sheet

    def _sheet_bg(self, inst, *_):
        self._sbg.pos = (inst.x, inst.y - dp(30))     # el borde inferior queda fuera de pantalla
        self._sbg.size = (inst.width, inst.height + dp(30))

    @staticmethod
    def _wrap(*widgets):
        box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6), padding=(0, dp(2)))
        box.bind(minimum_height=box.setter("height"))
        for w in widgets:
            box.add_widget(w)
        return box

    def _tab(self, name):
        page = {"Estilo": self.page_style, "Ajustes": self.page_adjust, "Formato": self.page_aspect}[name]
        self.sv.clear_widgets()
        self.sv.add_widget(page)
        self.sv.scroll_y = 1

    # --- color
    def set_color(self, c):
        self.bc = c
        for col, b in self.swatch_btns:
            lum = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
            b.text = "•" if col == c else ""
            b.color = (0, 0, 0, 1) if lum > 140 else WHITE
            b.set_colors(b.bg, b.color)

    def pick_color(self, *_):
        from kivy.uix.colorpicker import ColorPicker
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        cp = ColorPicker()
        ok = RBtn(text="Aceptar", bg=ACCENT, fg=WHITE, size_hint_y=None, height=dp(48))
        box.add_widget(cp)
        box.add_widget(ok)
        pop = Popup(title="Color de borde", content=box, size_hint=(0.94, 0.9),
                    background="", background_color=SURFACE, separator_color=ACCENT)

        def done(*_):
            c = cp.color
            self.set_color((int(c[0] * 255), int(c[1] * 255), int(c[2] * 255)))
            pop.dismiss()

        ok.bind(on_release=done)
        pop.open()

    # --- cargar fotos
    def load_images(self, paths):
        self.imgs, self.working = [], True
        self.busy.show(f"Cargando {len(paths)} fotos…")
        threading.Thread(target=self._load_worker, args=(paths,), daemon=True).start()

    def _load_worker(self, paths):
        imgs = [im for im in (engine.load_image(p) for p in paths) if im is not None]
        Clock.schedule_once(lambda _dt: self._loaded(imgs))

    def _loaded(self, imgs):
        self.imgs, self.working = imgs, False
        self.busy.dismiss()
        toast(f"{len(imgs)} fotos listas" if imgs else "No se pudo leer ninguna foto")

    # --- generar
    def _size(self):
        name = self.aspect.value
        if name == "Original" and self.imgs:
            w, h = self.imgs[0].size
            k = max(1, 1500 / max(w, h))
            return int(w * k), int(h * k)
        return engine.ASPECTS.get(name, (1920, 1080))

    def generate(self, *_):
        if self.working:
            return
        if not self.imgs:
            toast("Primero elige fotos en la galería")
            return
        self.working = True
        if not (self.t_fix.active and self.seed is not None):
            self.seed = random.randrange(1 << 30)
        w, h = self._size()
        args = dict(style=self.style.value, w=w, h=h, imgs=list(self.imgs),
                    s=int(self.s_size.value), bt=int(self.s_border.value), bc=self.bc,
                    rng=self.s_var.value, rot=self.s_rot.value,
                    rot_random=self.t_rand.active, shuffle=self.t_mix.active, seed=self.seed)
        self.busy.show("Generando mosaico…")
        threading.Thread(target=self._work, args=(args,), daemon=True).start()

    def _work(self, args):
        try:
            out = engine.render(**args)
            prev = out.copy()
            prev.thumbnail((1600, 1600))
            buf = io.BytesIO()
            prev.save(buf, "JPEG", quality=90)
            data = buf.getvalue()
            Clock.schedule_once(lambda _dt: self._done(out, data))
        except Exception as e:
            msg = str(e)[:90]
            Clock.schedule_once(lambda _dt, m=msg: self._fail(m))

    def _done(self, out, data):
        self.result = out
        self.preview.texture = CoreImage(io.BytesIO(data), ext="jpg").texture
        self.hint.opacity = 0
        self.scatter.scale = 1
        self.scatter.size, self.scatter.pos = self.stage.size, self.stage.pos
        self.working = False
        self.busy.dismiss()
        toast("Mosaico listo")

    def _fail(self, msg):
        self.working = False
        self.busy.dismiss()
        toast(f"Error: {msg}", 3.5)

    # --- recordar ajustes
    def get_settings(self):
        return dict(style=self.style.value, aspect=self.aspect.value, fmt=self.fmt.value,
                    size=self.s_size.value, bt=self.s_border.value, vari=self.s_var.value,
                    rot=self.s_rot.value, rr=self.t_rand.active, mix=self.t_mix.active,
                    fix=self.t_fix.active, bc=list(self.bc))

    def apply_settings(self, d):
        try:
            self.style.select(d["style"], False)
            self.aspect.select(d["aspect"], False)
            self.fmt.select(d["fmt"], False)
            self.s_size.slider.value, self.s_border.slider.value = d["size"], d["bt"]
            self.s_var.slider.value, self.s_rot.slider.value = d["vari"], d["rot"]
            for t, k in ((self.t_rand, "rr"), (self.t_mix, "mix"), (self.t_fix, "fix")):
                t.active = d[k]
                t._paint()
            self.set_color(tuple(d["bc"]))
        except Exception:
            pass  # ajustes viejos o corruptos: se usan los valores por defecto

    # --- guardar
    def save(self, *_):
        if self.result is None:
            toast("Genera un mosaico primero")
            return
        fmt = self.fmt.value.lower()
        threading.Thread(target=self._save_worker, args=(self.result, fmt), daemon=True).start()
        toast("Guardando…", 1.2)

    def _save_worker(self, img, fmt):
        try:
            os.makedirs(EXPORT_DIR, exist_ok=True)
            path = os.path.join(EXPORT_DIR, f"{unique_name()}.{fmt}")
            if fmt == "jpg":
                img.save(path, "JPEG", quality=95, subsampling=0)
            else:
                img.save(path, "PNG")
            media_scan(path)
            Clock.schedule_once(lambda _dt: toast("Guardado en Pictures/MosaicStudio", 3))
        except Exception as e:
            msg = str(e)[:80]
            Clock.schedule_once(lambda _dt, m=msg: toast(f"No se pudo guardar: {m}", 3.5))


# ------------------------------------------------------------------ app
class MosaicStudioApp(App):
    title = "Mosaic Studio"
    icon = LOGO

    def _cfg(self):
        return os.path.join(self.user_data_dir, "settings.json")

    def on_start(self):
        try:
            with open(self._cfg()) as f:
                cfg = json.load(f)
        except Exception:
            return
        self.sm.get_screen("editor").apply_settings(cfg.get("editor", {}))
        folder = cfg.get("folder")
        if folder and os.path.isdir(folder):
            self.sm.get_screen("gallery").load_folder(folder)

    def on_stop(self):
        try:
            os.makedirs(self.user_data_dir, exist_ok=True)
            with open(self._cfg(), "w") as f:
                json.dump({"editor": self.sm.get_screen("editor").get_settings(),
                           "folder": self.sm.get_screen("gallery").folder}, f)
        except Exception:
            pass

    def _key(self, _win, key, *_):
        """Botón atrás de Android: vuelve a la galería en vez de cerrar la app."""
        if key == 27 and self.sm.current == "editor":
            self.sm.current = "gallery"
            return True
        return False

    def build(self):
        if IS_ANDROID:
            try:
                from android.permissions import request_permissions
                request_permissions(["android.permission.READ_MEDIA_IMAGES",
                                     "android.permission.READ_EXTERNAL_STORAGE",
                                     "android.permission.WRITE_EXTERNAL_STORAGE"])
            except Exception:
                pass
        self.sm = ScreenManager(transition=SlideTransition(duration=0.2))
        self.sm.add_widget(Gallery(name="gallery"))
        self.sm.add_widget(Editor(name="editor"))
        Window.bind(on_keyboard=self._key)
        return self.sm


if __name__ == "__main__":
    MosaicStudioApp().run()
