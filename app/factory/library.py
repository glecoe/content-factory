"""Библиотека съёмки «По изделиям»: папка library/ в проекте (или своя из LIBRARY_DIR),
в ней подпапка на каждое изделие с фото и видео.

Имена файлов вида «20.07.25 Model — 02000-60-020001-00_onmodel.jpg»: дата, тип съёмки, артикул."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from . import media
from .config import DATA, LIBRARY, ROOT, settings

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
THUMBS = DATA / "library_thumbs"
LABELS = (("model", "на модели"), ("catalog", "каталог"), ("banner", "баннер"))
INFO_FILE = "product.json"           # данные изделия в его папке: поля карточки
INFO_FIELDS = ("name", "brand", "price", "promo", "link", "description_ru", "visual_en")


def _configured() -> Path:
    """LIBRARY_DIR из настроек; пусто — папка library/ в проекте, относительный путь — от корня проекта."""
    v = (settings().get("LIBRARY_DIR") or "").strip()
    if not v:
        return LIBRARY
    p = Path(v).expanduser()
    return p if p.is_absolute() else ROOT / p


def root() -> Path | None:
    p = _configured()
    return p if p.is_dir() else None


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _kind(f: Path) -> str | None:
    ext = f.suffix.lower()
    return "photo" if ext in PHOTO_EXT else "video" if ext in VIDEO_EXT else None


def label(name: str) -> str:
    low = name.lower()
    return next((ru for key, ru in LABELS if key in low), "")


def _code(name: str) -> str:
    """Артикул из имени файла: часть после «—» без суффиксов _onmodel/_banner."""
    stem = Path(name).stem
    if "—" not in stem:
        return ""
    code = stem.rsplit("—", 1)[1].strip()
    return re.sub(r"_(onmodel|banner)$", "", code, flags=re.I)


def read_info(d: Path) -> tuple[dict | None, str]:
    """product.json папки изделия → (поля карточки + article, ошибка). Нет файла — (None, "")."""
    f = d / INFO_FILE
    if not f.is_file():
        return None, ""
    try:
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as e:
        return None, f"{INFO_FILE}: {e}"
    if not isinstance(raw, dict):
        return None, f"{INFO_FILE}: нужен объект {{…}}"
    info = {k: str(raw.get(k) or "").strip() for k in ("article", *INFO_FIELDS)}
    return info, ""


def list_items() -> dict:
    r = root()
    if not r:
        return {"root": str(_configured()), "ok": False, "items": []}
    items = []
    for d in sorted((x for x in r.iterdir() if x.is_dir() and not x.name.startswith(".")), key=lambda x: _natural(x.name)):
        files = []
        for f in sorted(d.iterdir(), key=lambda x: _natural(x.name)):
            k = _kind(f)
            if k and f.is_file() and not f.name.startswith("."):
                files.append({"path": f"{d.name}/{f.name}", "name": f.name, "kind": k,
                              "label": label(f.name), "size": f.stat().st_size})
        if not files:
            continue
        codes = [c for c in (_code(f["name"]) for f in files) if len(c) > 3]
        code = max(set(codes), key=codes.count) if codes else ""
        photos = [f for f in files if f["kind"] == "photo"]
        cover = next((f for f in photos if f["label"] == "каталог"), photos[0] if photos else files[0])
        info, info_error = read_info(d)
        items.append({"id": d.name, "code": (info or {}).get("article") or code, "cover": cover["path"],
                      "files": files, "photos": len(photos), "videos": len(files) - len(photos),
                      "info": info, "info_error": info_error})
    return {"root": str(r), "ok": True, "items": items}


def resolve(rel: str) -> Path:
    """Путь внутри библиотеки → файл; всё, что вне папки библиотеки, запрещено."""
    r = root()
    if not r:
        raise ValueError(f"Папка библиотеки не найдена: {_configured()}")
    f = (r / rel).resolve()
    if r.resolve() not in f.parents or not f.is_file() or not _kind(f):
        raise ValueError("Файл не найден в библиотеке")
    return f


def thumb(rel: str) -> Path:
    """Маленькое превью для окна выбора; кешируется в data/library_thumbs."""
    f = resolve(rel)
    st = f.stat()
    key = hashlib.sha1(f"{f}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
    out = THUMBS / f"{key}.jpg"
    if out.exists():
        return out
    THUMBS.mkdir(parents=True, exist_ok=True)
    tmp = THUMBS / f"{key}.{uuid.uuid4().hex[:6]}.tmp.jpg"
    try:
        if _kind(f) == "photo":
            media.prepare_photo(f, tmp, max_side=480)
        else:
            media.thumbnail(f, tmp)
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
    return out
