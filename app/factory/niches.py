"""Ниши контент-завода. У каждой ниши свой контекст (что продаём, кому, как показывать товар),
свой профиль вкуса, свои тренды (ресёрч) и свои изделия.

Данные: data/niches/<id>/niche.json, taste.md, ratings.jsonl, research/…
Старые данные (одна ювелирная ниша) при первом запуске переносятся в нишу «Ювелирка» — копированием, без удаления.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import DATA

NICHES = DATA / "niches"
CURRENT = NICHES / "_current.txt"
_lock = threading.RLock()

# Поля контекста: что редактирует владелец и что подставляется в промпты агентов
FIELDS = {
    "name": "Название ниши",
    "description": "Что продаём (по-русски, подробно)",
    "audience": "Аудитория",
    "tone": "Тон и настроение бренда",
    "markets": "Рынки",
    "product_ru": "Товар одним словом (RU)",
    "product_en": "Товар одним словом (EN)",
    "use_ru": "Как товар показывают в использовании (RU)",
    "use_en": "In-use shot (EN)",
    "model_en": "Модель/сцена для ИИ-кадров (EN)",
    "fidelity_en": "Что нельзя менять в товаре (EN)",
    "passport_en": "Что описать в паспорте товара (EN)",
    "look_en": "Стиль рекламы (EN)",
    "negative_en": "Негативный промпт (EN)",
}

JEWELRY = {
    "id": "jewelry", "name": "Ювелирка",
    "description": "Ювелирные украшения: кольца с драгоценными камнями (изумруд, бриллианты), золото 585. Продажа через свой интернет-магазин.",
    "audience": "Женщины 25–45 лет, покупают себе и в подарок; мужчины, выбирающие подарок или помолвочное кольцо.",
    "tone": "Тихая роскошь: спокойно, дорого, без суеты.",
    "markets": "Россия и СНГ",
    "product_ru": "кольцо", "product_en": "ring",
    "use_ru": "на руке", "use_en": "worn on the ring finger of an elegant hand",
    "model_en": "a young woman's elegant hand with a nude manicure, natural skin texture",
    "fidelity_en": "geometry, proportions, stones (shape, color, count), prongs, metal color and realistic size on the finger",
    "passport_en": "metal color, ring shape, center stone (shape, color, approx size), side stones layout (halo, pavé, count if few), band details",
    "look_en": "luxury jewelry commercial, macro, shallow depth of field, sparkling highlights",
    "negative_en": ("changing ring design, changing stone shape, changing stone color, extra stones, missing stones, "
                    "oversized ring, deformed ring, melting metal, ring floating, ring merging with finger, extra fingers, "
                    "six fingers, fused fingers, distorted hand, plastic skin, blurry, flicker, jitter, text, watermark, logo"),
}

GENERIC = {
    "product_ru": "товар", "product_en": "product",
    "use_ru": "в использовании", "use_en": "being used naturally by a person",
    "model_en": "a stylish person in a clean, premium setting",
    "fidelity_en": "shape, proportions, colors, materials, labels and size",
    "passport_en": "shape, colors, materials, textures, distinctive details, labels",
    "look_en": "premium commercial, photorealistic, clean composition, soft light",
    "negative_en": ("changing product design, wrong colors, wrong proportions, warped label, extra parts, deformed product, "
                    "melting, extra fingers, distorted hands, plastic skin, blurry, flicker, jitter, text, watermark, logo"),
}

TASTE_GENERIC = """# Профиль вкуса (стартовый)
- Дорого и спокойно: мягкий свет, чистый фон, один главный объект в кадре.
- Хук в первую секунду: самый эффектный ракурс товара или момент использования.
- Медленные движения камеры, мягкие переходы, ролик 12–15 секунд.
- Товар нельзя искажать: форма, цвет, детали и надписи одинаковы во всех кадрах.
- Музыка спокойная, без вокала; тексты короткие, без восклицаний.
- Около 30% роликов — эксперименты на трендах недели."""


def _dir(nid: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", nid or ""):
        raise ValueError("bad niche id")
    return NICHES / nid


def research_dir(nid: str) -> Path:
    d = _dir(nid) / "research"
    for sub in ("", "refs", "briefs"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _slug(text: str) -> str:
    tr = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeejziiklmnoprstufhccss_y_eua")
    t = re.sub(r"[^a-z0-9]+", "-", (text or "").lower().translate(tr)).strip("-")
    return (t[:20] or "niche") + "-" + uuid.uuid4().hex[:4]


def migrate():
    """Один раз: старые общие данные → ниша «Ювелирка» (копии; старые файлы остаются на месте)."""
    with _lock:
        NICHES.mkdir(parents=True, exist_ok=True)
        if any(NICHES.glob("*/niche.json")):
            return
        d = _dir("jewelry")
        d.mkdir(parents=True, exist_ok=True)
        n = dict(JEWELRY, created=datetime.now().isoformat(timespec="seconds"))
        old_cfg = DATA / "research" / "config.json"
        if old_cfg.exists():
            try:
                c = json.loads(old_cfg.read_text(encoding="utf-8"))
                n["description"] = c.get("niche") or n["description"]
                n["audience"] = c.get("audience") or n["audience"]
                n["markets"] = c.get("markets") or n["markets"]
            except Exception:
                pass
        (d / "niche.json").write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")
        if (DATA / "taste.md").exists():
            shutil.copyfile(DATA / "taste.md", d / "taste.md")
        else:
            src = Path(__file__).with_name("taste_default.md")
            if src.exists():
                shutil.copyfile(src, d / "taste.md")
        if (DATA / "ratings.jsonl").exists():
            shutil.copyfile(DATA / "ratings.jsonl", d / "ratings.jsonl")
        if (DATA / "research").exists():
            shutil.copytree(DATA / "research", d / "research", dirs_exist_ok=True)
        CURRENT.write_text("jewelry")


def list_niches():
    migrate()
    out = []
    from . import store
    counts = {}
    for p in store.list_products(None):
        counts[p.get("niche") or "jewelry"] = counts.get(p.get("niche") or "jewelry", 0) + 1
    for f in sorted(NICHES.glob("*/niche.json")):
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if n.get("archived"):
            continue
        out.append({"id": n["id"], "name": n.get("name"), "description": n.get("description", "")[:160],
                    "products": counts.get(n["id"], 0), "created": n.get("created", "")})
    out.sort(key=lambda x: x.get("created", ""))
    return out


def load(nid: str) -> dict:
    migrate()
    f = _dir(nid) / "niche.json"
    if not f.exists():
        raise ValueError("Ниша не найдена")
    return json.loads(f.read_text(encoding="utf-8"))


def save(n: dict):
    with _lock:
        d = _dir(n["id"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "niche.json").write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")


def create(data: dict) -> dict:
    migrate()
    nid = _slug(data.get("name") or "niche")
    n = {"id": nid, "created": datetime.now().isoformat(timespec="seconds"), "name": data.get("name") or "Новая ниша",
         "description": data.get("description", ""), "audience": data.get("audience", ""), "tone": data.get("tone", ""),
         "markets": data.get("markets", "Россия и СНГ"), **GENERIC}
    for k in FIELDS:
        if data.get(k):
            n[k] = data[k]
    save(n)
    (_dir(nid) / "taste.md").write_text(TASTE_GENERIC, encoding="utf-8")
    research_dir(nid)
    return n


def update(nid: str, data: dict) -> dict:
    n = load(nid)
    for k in FIELDS:
        if k in data and data[k] is not None:
            n[k] = str(data[k]).strip()
    save(n)
    return n


def archive(nid: str):
    n = load(nid)
    n["archived"] = True
    save(n)


def delete(nid: str) -> dict:
    """Удалить нишу навсегда: её папку (вкус, оценки, ресёрч) и все её изделия с роликами. Последнюю нишу не удаляем."""
    from . import store
    with _lock:
        n = load(nid)
        if not any(x["id"] != nid for x in list_niches()):
            raise ValueError("Это единственная ниша — сначала создай другую.")
        products = [p["id"] for p in store.list_products(nid)]
        for pid in products:
            shutil.rmtree(store.pdir(pid), ignore_errors=True)
        shutil.rmtree(_dir(nid), ignore_errors=True)
        if CURRENT.exists() and CURRENT.read_text().strip() == nid:
            CURRENT.unlink()
        return {"ok": True, "name": n.get("name"), "products": len(products)}


def default_id() -> str:
    migrate()
    if CURRENT.exists():
        v = CURRENT.read_text().strip()
        if (NICHES / v / "niche.json").exists():
            return v
    lst = list_niches()
    return lst[0]["id"] if lst else "jewelry"


def resolve(nid: str | None) -> str:
    """id ниши или ниша по умолчанию."""
    if nid and (NICHES / nid / "niche.json").exists():
        return nid
    return default_id()


def ctx(nid: str | None) -> dict:
    """Контекст ниши для промптов: всегда все поля (пустые добираются из общих значений)."""
    nid = resolve(nid)
    n = load(nid)
    base = JEWELRY if nid == "jewelry" else GENERIC
    return {**base, **{k: v for k, v in n.items() if v not in (None, "")}, "id": nid}


def ctx_text(c: dict) -> str:
    return (f"НИША: {c.get('name')}\nЧто продаём: {c.get('description')}\nАудитория: {c.get('audience')}\n"
            f"Тон: {c.get('tone')}\nРынки: {c.get('markets')}")


# ---------------------------------------------------------------- вкус ниши
def taste_path(nid) -> Path:
    return _dir(resolve(nid)) / "taste.md"


def ratings_path(nid) -> Path:
    return _dir(resolve(nid)) / "ratings.jsonl"


CTX_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in FIELDS if k != "name"},
              "required": ["product_ru", "product_en", "use_ru", "use_en", "model_en", "fidelity_en", "passport_en",
                           "look_en", "negative_en"]}


def run_fill(job, nid):
    """ИИ дописывает технические поля ниши по её описанию."""
    from . import brains
    n = load(nid)
    prompt = f"""Ниша контент-завода рекламных роликов 9:16 (10–15 сек) для соцсетей.
Название: {n.get('name')}
Что продаём: {n.get('description')}
Аудитория: {n.get('audience') or '(уточни сам)'}

Заполни контекст ниши для видео- и фото-моделей:
- product_ru / product_en — товар одним-двумя словами;
- use_ru / use_en — как товар показывают в использовании (на руке, на лице, в интерьере, на ноге…);
- model_en — кто/что в ИИ-кадрах с товаром (модель, руки, интерьер), фотореалистично;
- fidelity_en — что в товаре нельзя менять ни в одном кадре (форма, цвет, этикетка, детали…);
- passport_en — что перечислить в «паспорте» товара по фото для точного воспроизведения;
- look_en — стиль рекламы этой ниши; negative_en — негативный промпт против типичных искажений;
- audience, tone, markets — уточни, если пусто. description — оставь как есть или аккуратно дополни.
Английские поля — по-английски, остальное — по-русски. Ответ — JSON."""
    data, _ = brains.ask("research", prompt, schema=CTX_SCHEMA, temperature=0.4, job=job, timeout=400)
    keep = {k: v for k, v in data.items() if k in FIELDS and v and (k not in ("description",) or not n.get(k))}
    update(nid, keep)
    job.say("Контекст ниши заполнен: " + ", ".join(keep))
    return keep
