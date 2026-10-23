"""3D-модель изделия (.stl) → студийные фото-ракурсы для конвейера роликов.

Без внешних зависимостей, кроме Pillow: разбор STL (бинарный и текстовый), ортографическая проекция,
сортировка граней по глубине и мягкий свет «как в лайтбоксе». Дальше ракурсы идут как обычные фото."""
from __future__ import annotations

import math
import struct
from pathlib import Path

SIZE = 1536                 # сторона готового кадра
SS = 2                      # сглаживание: рисуем крупнее и уменьшаем
MAX_TRIS = 400_000          # потолок граней на кадр — больше нет смысла, детали меньше пикселя
BASE = (196, 192, 186)      # нейтральный «глиняный» цвет модели
VIEWS = (                   # (подпись, поворот вокруг вертикали, наклон камеры сверху), градусы
    ("3D · анфас", 0, 12),
    ("3D · 3/4", 38, 24),
    ("3D · профиль", 90, 10),
    ("3D · сверху 3/4", 215, 55),
)


class STLError(ValueError):
    pass


def parse(data: bytes) -> list[tuple]:
    """Грани как кортежи из 9 чисел (x1,y1,z1, x2,y2,z2, x3,y3,z3)."""
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if n and len(data) >= 84 + 50 * n and not (data[:5].lower() == b"solid" and b"facet" in data[84:1024]):
            return [t[3:12] for t in struct.iter_unpack("<12f2x", data[84:84 + 50 * n])]
    text = data.decode("ascii", "ignore")
    pts = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("vertex"):
            parts = s.split()
            if len(parts) >= 4:
                pts.extend(float(v) for v in parts[1:4])
    tris = [tuple(pts[i:i + 9]) for i in range(0, len(pts) - 8, 9)]
    if not tris:
        raise STLError("В STL-файле не нашлось ни одной грани — файл повреждён или это не STL.")
    return tris


def _normalize(tris: list[tuple]) -> list[tuple]:
    """Центр в нуле, размер ≈ 1, ось Z (вверх у 3D-печати) → Y (вверх у камеры)."""
    tris = [t for t in tris if all(math.isfinite(v) for v in t)]
    if not tris:
        raise STLError("В STL-файле нет корректных граней.")
    if len(tris) > MAX_TRIS:
        step = len(tris) / MAX_TRIS
        tris = [tris[int(i * step)] for i in range(MAX_TRIS)]
    xs = [v for t in tris for v in t[0::3]]
    ys = [v for t in tris for v in t[1::3]]
    zs = [v for t in tris for v in t[2::3]]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    k = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0
    out = []
    for t in tris:
        out.append(tuple(c for i in range(3) for c in
                         ((t[3 * i] - cx) / k, (t[3 * i + 2] - cz) / k, -(t[3 * i + 1] - cy) / k)))
    return out


def _unit(x, y, z):
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


LIGHTS = (  # направление (к свету, в системе камеры), сила
    (_unit(-0.5, 0.7, 0.8), 0.75),   # ключевой сверху слева
    (_unit(0.7, 0.2, 0.6), 0.30),    # заполняющий справа
    (_unit(0.0, 0.4, -1.0), 0.25),   # контровой сзади
)
HALF = _unit(-0.25, 0.35, 1.4)        # для блика от ключевого света


def _render_view(tris: list[tuple], yaw: float, pitch: float, out: Path):
    from PIL import Image, ImageDraw, ImageFilter

    S = SIZE * SS
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))

    def cam(x, y, z):
        x, z = x * cy - z * sy, x * sy + z * cy           # поворот вокруг вертикали
        y, z = y * cp - z * sp, y * sp + z * cp           # наклон камеры вниз
        return x, y, z

    faces, minx, maxx, miny, maxy = [], 1e9, -1e9, 1e9, -1e9
    for t in tris:
        a, b, c = cam(*t[0:3]), cam(*t[3:6]), cam(*t[6:9])
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln == 0:
            continue
        nx, ny, nz = nx / ln, ny / ln, nz / ln
        if nz < 0:                                         # освещаем обе стороны: в STL часто перевёрнуты нормали
            nx, ny, nz = -nx, -ny, -nz
        faces.append(((a[2] + b[2] + c[2]) / 3, a, b, c, (nx, ny, nz)))
        for p in (a, b, c):
            minx, maxx, miny, maxy = min(minx, p[0]), max(maxx, p[0]), min(miny, p[1]), max(maxy, p[1])
    if not faces:
        raise STLError("В STL-файле все грани вырожденные — нечего рисовать.")
    faces.sort(key=lambda f: f[0])                         # дальние первыми

    scale = 0.72 * S / max(maxx - minx, maxy - miny, 1e-9)
    ox, oy = S / 2 - (minx + maxx) / 2 * scale, S * 0.47 + (miny + maxy) / 2 * scale

    # фон: мягкий вертикальный градиент и тень на «столе»
    bg = Image.linear_gradient("L").resize((S, S)).point(lambda v: 246 - v * 34 // 255)
    img = Image.merge("RGB", (bg, bg.point(lambda v: v - 2), bg.point(lambda v: v - 5)))
    shadow = Image.new("L", (S, S), 0)
    w = max(maxx - minx, (maxy - miny) * 0.5) * scale
    floor = oy - miny * scale
    ImageDraw.Draw(shadow).ellipse((S / 2 - w * 0.48, floor - w * 0.05, S / 2 + w * 0.48, floor + w * 0.07), fill=110)
    shadow = shadow.filter(ImageFilter.GaussianBlur(S / 60))
    img.paste((120, 116, 110), mask=shadow)

    draw = ImageDraw.Draw(img)
    for _, a, b, c, n in faces:
        light = 0.28
        for d, k in LIGHTS:
            light += k * max(0.0, n[0] * d[0] + n[1] * d[1] + n[2] * d[2])
        spec = max(0.0, n[0] * HALF[0] + n[1] * HALF[1] + n[2] * HALF[2]) ** 40 * 70
        col = tuple(min(255, int(ch * light + spec)) for ch in BASE)
        poly = [(ox + p[0] * scale, oy - p[1] * scale) for p in (a, b, c)]
        draw.polygon(poly, fill=col, outline=col)          # обводка того же цвета закрывает щели между гранями
    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((SIZE, SIZE), Image.LANCZOS).save(out, "JPEG", quality=92)


def render_views(data: bytes, out_dir: Path, stem: str) -> list[tuple[str, Path]]:
    """STL → [(подпись ракурса, путь к JPEG)]."""
    tris = _normalize(parse(data))
    res = []
    for i, (label, yaw, pitch) in enumerate(VIEWS, 1):
        dst = out_dir / f"{stem}_view{i}.jpg"
        _render_view(tris, yaw, pitch, dst)
        res.append((label, dst))
    return res
