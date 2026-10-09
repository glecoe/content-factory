"""Лаборатория сайтов — второй цех.

Цепочка: бриф (лого/название, сфера, лендинг или сайт, страницы)
 → бренд-кит (цвета из логотипа + характер бренда)
 → ресёрч (поиск лидеров сферы и эталонов дизайна, скриншоты, разбор глазами)
 → стратег (3 концепции + живое превью первого экрана)
 → автор промтов (пакет для Claude Code / Codex: MASTER + страница за страницей + тексты)
 → сборка (Claude Code по подписке собирает статический сайт) → проверка по скриншотам → правки.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .config import SITES, settings, int_setting
from . import store

_lock = threading.RLock()
TASTE = SITES / "taste.md"
PHOTO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}


# ============================================================================= хранилище
def pdir(sid: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", sid or ""):
        raise ValueError("bad site id")
    return SITES / sid


def _slug(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (t[:24] or "site") + "-" + uuid.uuid4().hex[:6]


# ============================================================================= направления (проекты студии)
LABS = SITES / "_labs"
LAB_FIELDS = {"name": "Название направления", "description": "Какие сайты делаем, для кого",
              "audience": "Клиенты направления", "style": "Предпочтения по стилю", "notes": "Правила и ограничения"}


def _lab_dir(lid: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", lid or ""):
        raise ValueError("bad lab id")
    return LABS / lid


def migrate_labs():
    with _lock:
        LABS.mkdir(parents=True, exist_ok=True)
        if any(LABS.glob("*/lab.json")):
            return
        d = _lab_dir("general")
        d.mkdir(parents=True, exist_ok=True)
        (d / "lab.json").write_text(json.dumps({
            "id": "general", "name": "Все сайты", "description": "Сайты и лендинги для любых компаний.", "audience": "",
            "style": "", "notes": "", "created": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        if (SITES / "taste.md").exists():
            shutil.copyfile(SITES / "taste.md", d / "taste.md")
        if (SITES / "ratings.jsonl").exists():
            shutil.copyfile(SITES / "ratings.jsonl", d / "ratings.jsonl")


def list_labs():
    migrate_labs()
    counts = {}
    for p in list_projects(None):
        counts[p["lab"]] = counts.get(p["lab"], 0) + 1
    out = []
    for f in LABS.glob("*/lab.json"):
        try:
            l = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if l.get("archived"):
            continue
        out.append({"id": l["id"], "name": l.get("name"), "description": (l.get("description") or "")[:160],
                    "sites": counts.get(l["id"], 0), "created": l.get("created", "")})
    out.sort(key=lambda x: x["created"])
    return out


def load_lab(lid) -> dict:
    migrate_labs()
    f = _lab_dir(resolve_lab(lid)) / "lab.json"
    return json.loads(f.read_text(encoding="utf-8"))


def resolve_lab(lid) -> str:
    migrate_labs()
    if lid and (LABS / lid / "lab.json").exists():
        return lid
    return "general" if (LABS / "general" / "lab.json").exists() else (list_labs() or [{"id": "general"}])[0]["id"]


def create_lab(data: dict) -> dict:
    migrate_labs()
    lid = _slug(data.get("name") or "lab").replace("site", "lab")
    l = {"id": lid, "created": datetime.now().isoformat(timespec="seconds"),
         **{k: (data.get(k) or "") for k in LAB_FIELDS}}
    l["name"] = l["name"] or "Новое направление"
    _lab_dir(lid).mkdir(parents=True, exist_ok=True)
    (_lab_dir(lid) / "lab.json").write_text(json.dumps(l, ensure_ascii=False, indent=2), encoding="utf-8")
    return l


def update_lab(lid, data: dict) -> dict:
    l = load_lab(lid)
    for k in LAB_FIELDS:
        if k in data and data[k] is not None:
            l[k] = str(data[k]).strip()
    (_lab_dir(l["id"]) / "lab.json").write_text(json.dumps(l, ensure_ascii=False, indent=2), encoding="utf-8")
    return l


def archive_lab(lid):
    l = load_lab(lid)
    l["archived"] = True
    (_lab_dir(l["id"]) / "lab.json").write_text(json.dumps(l, ensure_ascii=False, indent=2), encoding="utf-8")


def lab_text(p) -> str:
    l = load_lab(p.get("lab"))
    if l["id"] == "general" and not (l.get("style") or l.get("notes")):
        return ""
    parts = [f"Направление студии: {l.get('name')} — {l.get('description','')}"]
    for k, t in (("audience", "Клиенты направления"), ("style", "Стиль направления"), ("notes", "Правила направления")):
        if l.get(k):
            parts.append(f"{t}: {l[k]}")
    return "\n".join(parts)


def list_projects(lab: str | None = "__all__"):
    out = []
    for d in sorted([x for x in SITES.iterdir() if x.is_dir() and not x.name.startswith("_")],
                    key=lambda p: p.stat().st_mtime, reverse=True):
        f = d / "project.json"
        if f.exists():
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                lid = p.get("lab") or "general"
                if lab not in (None, "__all__") and lid != lab:
                    continue
                out.append({"id": p["id"], "name": p.get("name"), "kind": p.get("kind"), "stage": stage(p),
                            "builds": len(p.get("builds", [])), "lab": lid,
                            "logo": p.get("logo"), "sphere": (p.get("sphere") or "")[:120]})
            except Exception:
                pass
    return out


def create(data: dict) -> dict:
    with _lock:
        sid = _slug(data.get("name") or "site")
        d = pdir(sid)
        for sub in ("logo", "shots", "previews", "prompts", "builds", "refs"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        p = {"id": sid, "created": datetime.now().isoformat(timespec="seconds"),
             "name": data.get("name") or "Новый сайт", "sphere": data.get("sphere", ""),
             "kind": data.get("kind") or "landing", "pages_n": int(data.get("pages_n") or 1),
             "pages_wish": data.get("pages_wish", ""), "audience": data.get("audience", ""),
             "goal": data.get("goal", ""), "references": data.get("references", ""),
             "notes": data.get("notes", ""), "stack": data.get("stack") or "static",
             "logo": None, "brand": None, "research": None, "concepts": [], "chosen": None,
             "feedback": "", "prompts": None, "builds": [], "photos": None, "lab": resolve_lab(data.get("lab"))}
        save(p)
        return p


def load(sid: str) -> dict:
    p = json.loads((pdir(sid) / "project.json").read_text(encoding="utf-8"))
    bd = pdir(sid) / "builds"
    known = {b["dir"] for b in p.get("builds", [])}
    lost = [d for d in sorted(bd.iterdir(), key=lambda x: x.name) if d.is_dir() and d.name not in known] if bd.exists() else []
    if lost:   # сборка оборвалась до записи в проект — показываем её как незаконченную
        for d in lost:
            p.setdefault("builds", []).append({
                "dir": d.name, "created": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"),
                "pages": _site_pages(d), "files": _count_files(d), "status": "partial", "stack": p.get("stack") or "static",
                "summary": "Сборка была прервана до конца. Нажми «Продолжить сборку» — Claude Code доделает недостающее.",
                "review": None, "sessions": []})
        save(p)
    return p


def save(p: dict):
    with _lock:
        f = pdir(p["id"]) / "project.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)


def update(sid: str, fn):
    with _lock:
        p = load(sid)
        fn(p)
        save(p)
        return p


BRIEF_KEYS = ("name", "sphere", "kind", "pages_n", "pages_wish", "audience", "goal", "references", "notes", "stack")


def update_brief(sid, data: dict):
    def fn(p):
        for k in BRIEF_KEYS:
            if k in data:
                p[k] = data[k]
        p["pages_n"] = 1 if p.get("kind") == "landing" else max(2, min(30, int(p.get("pages_n") or 5)))
    return update(sid, fn)


def stage(p) -> str:
    if p.get("builds"):
        return "сборка"
    if p.get("prompts"):
        return "промт"
    if (p.get("photos") or {}).get("slots"):
        return "фото"
    if p.get("concepts"):
        return "концепции"
    if p.get("research"):
        return "ресёрч"
    return "бриф"


def add_logo(sid, filename: str, data: bytes) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in PHOTO_EXT:
        raise ValueError("Логотип: png, jpg, svg или webp.")
    d = pdir(sid) / "logo"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"logo{ext}"
    for old in d.glob("logo.*"):
        old.unlink()
    f.write_bytes(data)
    return update(sid, lambda p: p.__setitem__("logo", f.name))


def remove_logo(sid):
    return update(sid, lambda p: p.__setitem__("logo", None))


def logo_path(p) -> Path | None:
    if not p.get("logo"):
        return None
    f = pdir(p["id"]) / "logo" / p["logo"]
    return f if f.exists() else None


def logo_raster(p) -> Path | None:
    """Растровая копия логотипа (SVG модели не всегда открывают)."""
    f = logo_path(p)
    if not f:
        return None
    if f.suffix.lower() != ".svg":
        return f
    out = f.with_name("logo_raster.png")
    if out.exists():
        return out
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 800, "height": 800})
            pg.goto(f.resolve().as_uri())
            pg.screenshot(path=str(out), omit_background=True)
            br.close()
        return out
    except Exception:
        return None


# ============================================================================= вкус сайтов
TASTE_DEFAULT = """# Вкус сайтов (стартовый)
- Ясность важнее эффектов: за 5 секунд понятно, кто компания, что предлагает и что нажать.
- Крупная выразительная типографика, много воздуха, строгая сетка, 1–2 акцентных цвета из бренда.
- Настоящие фото и конкретика (цифры, кейсы, цены) вместо стоковых картинок и общих слов.
- Спокойная анимация: появление при прокрутке, мягкие ховеры. Никаких каруселей ради каруселей.
- Мобильная версия продумана отдельно, кнопка действия всегда под рукой.
- Тексты короткие, живые, без канцелярита и «лидеров рынка»."""


def taste_text(lab=None) -> str:
    f = _lab_dir(resolve_lab(lab)) / "taste.md"
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8")
    return TASTE_DEFAULT


def save_taste(text: str, lab=None):
    (_lab_dir(resolve_lab(lab)) / "taste.md").write_text(text, encoding="utf-8")


def rate(sid, what: str, ref, like: bool, comment: str = ""):
    """Оценка концепции или сборки — копится для профиля вкуса сайтов."""
    p = load(sid)
    row = {"ts": time.time(), "project": sid, "lab": resolve_lab(p.get("lab")), "sphere": p.get("sphere"), "kind": p.get("kind"),
           "what": what, "like": like, "comment": comment}
    if what == "concept":
        c = p["concepts"][int(ref)]
        row["concept"] = {k: c.get(k) for k in ("name", "idea", "mood", "layout", "typography", "palette")}
        update(sid, lambda x: x["concepts"][int(ref)].update({"like": like, "comment": comment}))
    else:
        b = next((b for b in p["builds"] if b["dir"] == ref), None)
        row["build"] = {"dir": ref, "concept": (p["concepts"][p["chosen"]] or {}).get("name") if p.get("chosen") is not None else ""}
        update(sid, lambda x: [bb.update({"like": like, "comment": comment}) for bb in x["builds"] if bb["dir"] == ref])
    with (_lab_dir(row["lab"]) / "ratings.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ratings(lab=None):
    f = _lab_dir(resolve_lab(lab)) / "ratings.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def run_taste(job, lab=None):
    from . import brains
    rows = ratings(lab)
    if not rows:
        raise ValueError("Пока нет оценок концепций или сборок.")
    prompt = f"""Ты ведёшь профиль вкуса владельца лаборатории сайтов. Направление: {load_lab(lab).get('name')}.
Текущий профиль:
{taste_text(lab)}

Оценки (like=true — понравилось):
{json.dumps(rows[-60:], ensure_ascii=False)[:14000]}

Обнови профиль: 6–12 конкретных пунктов на русском (типографика, цвет, сетка, плотность, анимация, тексты, структура),
что не нравится, и 1–2 гипотезы для экспериментов. Верни только текст профиля в Markdown."""
    text, _ = brains.ask("site_strategy", prompt, temperature=0.4, job=job)
    save_taste(text, lab)
    return {"taste": text}


# ============================================================================= 1. бренд-кит
def logo_colors(path: Path, n=6) -> list[str]:
    """Основные цвета логотипа (без фона), HEX. Нужен Pillow; без него — пусто."""
    try:
        from PIL import Image
    except ImportError:
        return []
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return []
    im.thumbnail((200, 200))
    px = [(r, g, b) for r, g, b, a in im.getdata() if a > 200]
    if not px:
        return []
    corner = im.getpixel((0, 0))
    bg = corner[:3] if corner[3] > 200 else None
    from collections import Counter
    q = Counter((r // 16 * 16 + 8, g // 16 * 16 + 8, b // 16 * 16 + 8) for r, g, b in px)
    out = []
    for (r, g, b), cnt in q.most_common(40):
        if bg and abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) < 40:
            continue
        if any(abs(r - int(h[1:3], 16)) + abs(g - int(h[3:5], 16)) + abs(b - int(h[5:7], 16)) < 60 for h in out):
            continue
        out.append(f"#{r:02X}{g:02X}{b:02X}")
        if len(out) >= n:
            break
    return out


BRAND_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "personality": {"type": "array", "items": {"type": "string"}},
    "tone_of_voice": {"type": "string"},
    "colors": {"type": "array", "items": {"type": "object", "properties": {
        "hex": {"type": "string"}, "role": {"type": "string"}, "name": {"type": "string"}}, "required": ["hex", "role"]}},
    "fonts": {"type": "object", "properties": {
        "heading": {"type": "string"}, "body": {"type": "string"}, "why": {"type": "string"}}, "required": ["heading", "body"]},
    "logo_notes": {"type": "string"},
    "do": {"type": "array", "items": {"type": "string"}},
    "dont": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "colors", "fonts", "tone_of_voice"]}


def brief_text(p) -> str:
    kind = "лендинг (одна длинная страница)" if p.get("kind") == "landing" else f"полноценный сайт, страниц: {p.get('pages_n')}"
    lines = [f"Компания: {p.get('name')}", f"Сфера деятельности: {p.get('sphere')}", f"Формат: {kind}"]
    lt = lab_text(p)
    if lt:
        lines.insert(0, lt)
    if p.get("kind") != "landing" and p.get("pages_wish"):
        lines.append(f"Обязательные страницы: {p['pages_wish']}")
    for k, t in (("audience", "Аудитория"), ("goal", "Главное целевое действие"), ("references", "Сайты, которые нравятся владельцу"),
                 ("notes", "Пожелания")):
        if p.get(k):
            lines.append(f"{t}: {p[k]}")
    return "\n".join(lines)


def run_brand(job, sid):
    from . import brains
    p = load(sid)
    logo = logo_raster(p)
    measured = logo_colors(logo) if logo else []
    if measured:
        job.say("Цвета логотипа: " + " ".join(measured))
    prompt = f"""Ты — бренд-дизайнер. Составь бренд-кит для сайта компании.
{brief_text(p)}
{"Логотип приложен — посмотри его внимательно." if logo else "Логотипа нет — предложи фирменный стиль по названию и сфере."}
{"Измеренные цвета логотипа (используй их как основу, HEX точные): " + ", ".join(measured) if measured else ""}

Требования:
- colors: 5–7 цветов с ролями (primary, accent, background, surface, text, muted…) — контраст текста к фону ≥ 4.5:1.
- fonts: шрифты из Google Fonts С ПОДДЕРЖКОЙ КИРИЛЛИЦЫ (например: Manrope, Inter, Onest, Unbounded, Montserrat, Raleway,
  Playfair Display, Cormorant Garamond, Lora, PT Serif, Golos Text, Rubik, Nunito, Prata, Literata, Commissioner).
- personality — 3–5 слов о характере бренда; tone_of_voice — как бренд говорит с клиентом.
- do/dont — что в дизайне подчёркивает бренд и чего избегать.
Пиши по-русски. Ответ — JSON."""
    data, meta = brains.ask("site_brand", prompt, images=[logo] if logo else None, schema=BRAND_SCHEMA,
                            temperature=0.6, job=job, timeout=600)
    data["measured"] = measured
    update(sid, lambda x: x.__setitem__("brand", data))
    job.say("Бренд-кит: " + data.get("summary", "")[:200])
    return data


def save_brand(sid, brand: dict):
    return update(sid, lambda p: p.__setitem__("brand", {**(p.get("brand") or {}), **brand}))


# ============================================================================= 2. ресёрч
RESEARCH_SCHEMA = {"type": "object", "properties": {
    "sites": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "url": {"type": "string"}, "kind": {"type": "string", "enum": ["competitor", "reference"]},
        "why": {"type": "string"}}, "required": ["name", "url", "kind", "why"]}},
    "trends": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "how_to_use": {"type": "string"}}, "required": ["name", "how_to_use"]}},
    "sphere_patterns": {"type": "array", "items": {"type": "string"}},
    "must_have_sections": {"type": "array", "items": {"type": "string"}},
    "conversion": {"type": "array", "items": {"type": "string"}},
    "mistakes": {"type": "array", "items": {"type": "string"}},
    "photo_trends": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "what": {"type": "string"}, "how_to_shoot": {"type": "string"},
        "where": {"type": "string"}}, "required": ["name", "what", "how_to_shoot"]}},
    "photo_avoid": {"type": "array", "items": {"type": "string"}},
    "sources": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "url": {"type": "string"}}, "required": ["url"]}}},
    "required": ["sites", "trends", "sphere_patterns", "must_have_sections"]}

VISUAL_SCHEMA = {"type": "object", "properties": {
    "reviews": {"type": "array", "items": {"type": "object", "properties": {
        "url": {"type": "string"}, "layout": {"type": "string"}, "hero": {"type": "string"},
        "typography": {"type": "string"}, "colors": {"type": "string"}, "imagery": {"type": "string"},
        "photo_style": {"type": "string"},
        "strong": {"type": "string"}, "weak": {"type": "string"}, "steal": {"type": "string"}},
        "required": ["url", "hero", "strong", "steal"]}},
    "common_visual_language": {"type": "string"},
    "gaps": {"type": "array", "items": {"type": "string"}}},
    "required": ["reviews", "common_visual_language"]}


def _screenshot(urls: list[str], out_dir: Path, job) -> dict:
    """Скриншоты первого экрана и страницы целиком (обрезанной). Нужен Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        job.say("  скриншоты пропущены: не установлен Playwright (start.command поставит его при следующем запуске)")
        return {}
    shots = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            ctx = br.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU",
                                 user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36")
            for i, url in enumerate(urls):
                pg = ctx.new_page()
                try:
                    job.say(f"  скриншот {i+1}/{len(urls)}: {url[:70]}")
                    pg.goto(url, wait_until="domcontentloaded", timeout=30000)
                    pg.wait_for_timeout(2500)
                    hero = out_dir / f"s{i+1}_hero.jpg"
                    full = out_dir / f"s{i+1}_full.jpg"
                    pg.screenshot(path=str(hero), type="jpeg", quality=80)
                    h = min(pg.evaluate("document.body ? document.body.scrollHeight : 900") or 900, 5200)
                    pg.set_viewport_size({"width": 1440, "height": int(h)})
                    pg.wait_for_timeout(800)
                    pg.screenshot(path=str(full), type="jpeg", quality=70)
                    _shrink(full, 720)
                    shots[url] = {"hero": hero.name, "full": full.name}
                except Exception as e:
                    job.say(f"    не открылся: {str(e)[:120]}")
                finally:
                    pg.close()
            br.close()
    except Exception as e:
        job.say(f"  скриншоты не получились: {str(e)[:200]} (если Playwright без браузера: python -m playwright install chromium)")
    return shots


def _shrink(path: Path, width: int):
    try:
        from PIL import Image
        im = Image.open(path)
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)))
            im.convert("RGB").save(path, quality=72)
    except Exception:
        pass


def run_research(job, sid):
    from . import brains
    p = load(sid)
    d = pdir(sid)
    year = datetime.now().year
    prompt = f"""Ты — исследователь веб-дизайна. Найди в интернете, как сейчас делают сайты в этой сфере и что сейчас в тренде.
{brief_text(p)}

Сделай:
1) sites: 8–10 сайтов. Примерно половина — лидеры и сильные компании этой сферы (в первую очередь Россия/СНГ, можно мировые),
   половина — эталоны дизайна для такой задачи (Awwwards, Godly, Land-book, Lapa Ninja, SiteInspire, Dribbble-кейсы с живыми сайтами).
   Только реальные рабочие адреса главных страниц (https://…), без выдуманных. Если владелец указал сайты, которые ему нравятся, — включи их.
2) trends: 6–8 актуальных трендов веб-дизайна {year} года, применимых к этой сфере, — с тем, как применить.
3) sphere_patterns: что типично для сайтов этой сферы (структура, контент, доверие).
4) must_have_sections: обязательные блоки/страницы для этой сферы.
5) conversion: приёмы, которые повышают заявки именно в этой сфере.
6) mistakes: частые ошибки сайтов в этой сфере.
7) photo_trends: 5–7 трендов ФОТО и визуала, которые сейчас в хайпе и хорошо смотрятся на сайтах этой сферы
   (стиль съёмки, свет, цвет и обработка, композиция, люди или предметы, плёночность/«живые» кадры, крупные планы, 3D и т.п.):
   what — что это, how_to_shoot — как снять или сгенерировать, where — в каких блоках сайта работает.
   photo_avoid — какие фото выглядят дёшево или устарели (стоковые улыбки, рукопожатия, переобработка…).
8) sources: ссылки, на которые опирался.
Пиши по-русски. Ответ — JSON."""
    job.say("Шаг 1/3 · поиск сайтов и трендов")
    web, meta = brains.ask("site_research", prompt, schema=RESEARCH_SCHEMA, web=True, job=job, timeout=1500)
    sites = [s for s in web.get("sites", []) if str(s.get("url", "")).startswith("http")][:10]
    for r in [x.strip() for x in re.split(r"[\s,]+", p.get("references") or "") if x.strip().startswith("http")]:
        if r not in [s["url"] for s in sites]:
            sites.insert(0, {"name": r, "url": r, "kind": "reference", "why": "нравится владельцу"})
    web["sites"] = sites
    job.progress = 0.35
    shots = {}
    if settings().get("SITE_SHOTS", "1") == "1" and sites:
        job.say("Шаг 2/3 · скриншоты сайтов")
        shots = _screenshot([s["url"] for s in sites], d / "shots", job)
    job.progress = 0.7
    visual = None
    if shots:
        job.say(f"Шаг 3/3 · разбор дизайна по {len(shots)} скриншотам")
        imgs, legend = [], []
        for k, (url, sh) in enumerate(shots.items()):
            imgs += [d / "shots" / sh["hero"], d / "shots" / sh["full"]]
            legend.append(f"сайт {k+1}: {url} — картинки image_{2*k+1} (первый экран) и image_{2*k+2} (страница целиком)")
        vprompt = f"""Ты — арт-директор. Посмотри скриншоты сайтов (каждый файл открой инструментом Read) и разбери дизайн.
Сфера: {p.get('sphere')}. Задача: {brief_text(p)}
{chr(10).join(legend)}

Для каждого сайта: layout (сетка, плотность), hero (что на первом экране), typography, colors, imagery (фото/иллюстрации/3D),
photo_style (как сняты и обработаны фото: свет, цвет, ракурс, люди/предметы, насколько «живые»),
strong (что сильно), weak (что слабо), steal (что конкретно стоит взять нам).
common_visual_language — общий визуальный язык сферы; gaps — чем можно выделиться на фоне всех.
По-русски. Ответ — JSON."""
        try:
            visual, _ = brains.ask("site_research", vprompt, images=imgs, schema=VISUAL_SCHEMA, job=job, timeout=1500)
        except Exception as e:
            job.say(f"  разбор скриншотов не получился: {str(e)[:200]}")
    else:
        job.say("Шаг 3/3 · пропуск: скриншотов нет, концепции будут опираться на текстовый ресёрч")
    research = {**web, "shots": shots, "visual": visual, "created": datetime.now().isoformat(timespec="seconds")}
    update(sid, lambda x: x.__setitem__("research", research))
    job.say(f"Ресёрч готов: сайтов {len(sites)}, скриншотов {len(shots)}, трендов {len(web.get('trends', []))}.")
    return {"sites": len(sites)}


def research_text(p, max_chars=9000) -> str:
    r = p.get("research") or {}
    if not r:
        return "(ресёрча нет)"
    lines = ["Тренды: " + "; ".join(f"{t['name']} — {t.get('how_to_use','')}" for t in r.get("trends", [])),
             "Типично для сферы: " + "; ".join(r.get("sphere_patterns", [])),
             "Обязательные блоки: " + "; ".join(r.get("must_have_sections", [])),
             "Конверсия: " + "; ".join(r.get("conversion", [])),
             "Ошибки сферы: " + "; ".join(r.get("mistakes", [])),
             "Фото в тренде: " + "; ".join(f"{t['name']} — {t.get('what','')} ({t.get('how_to_shoot','')})" for t in r.get("photo_trends", [])),
             "Фото, которые выглядят дёшево: " + "; ".join(r.get("photo_avoid", []))]
    v = r.get("visual") or {}
    if v:
        lines.append("Визуальный язык сферы: " + v.get("common_visual_language", ""))
        lines.append("Чем выделиться: " + "; ".join(v.get("gaps", [])))
        for rv in v.get("reviews", [])[:10]:
            lines.append(f"- {rv.get('url')}: первый экран — {rv.get('hero','')}; фото — {rv.get('photo_style','')}; "
                         f"сильное — {rv.get('strong','')}; взять — {rv.get('steal','')}")
    else:
        lines += [f"- {s['url']}: {s.get('why','')}" for s in r.get("sites", [])]
    return "\n".join(lines)[:max_chars]


# ============================================================================= 3. стратег + превью
CONCEPTS_SCHEMA = {"type": "object", "properties": {"concepts": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "idea": {"type": "string"}, "mood": {"type": "string"},
    "why": {"type": "string"}, "references": {"type": "array", "items": {"type": "string"}},
    "palette": {"type": "array", "items": {"type": "object", "properties": {
        "hex": {"type": "string"}, "role": {"type": "string"}}, "required": ["hex", "role"]}},
    "typography": {"type": "object", "properties": {"heading": {"type": "string"}, "body": {"type": "string"},
                                                    "scale": {"type": "string"}}, "required": ["heading", "body"]},
    "layout": {"type": "string"}, "imagery": {"type": "string"}, "motion": {"type": "string"},
    "hero": {"type": "object", "properties": {"headline": {"type": "string"}, "subheadline": {"type": "string"},
                                              "cta": {"type": "string"}, "visual": {"type": "string"}},
             "required": ["headline", "subheadline", "cta", "visual"]},
    "pages": {"type": "array", "items": {"type": "object", "properties": {
        "slug": {"type": "string"}, "title": {"type": "string"}, "purpose": {"type": "string"},
        "sections": {"type": "array", "items": {"type": "string"}}}, "required": ["slug", "title", "sections"]}},
    "signature": {"type": "string"}},
    "required": ["name", "idea", "palette", "typography", "layout", "hero", "pages"]}}}, "required": ["concepts"]}


def run_concepts(job, sid, n=3):
    from . import brains
    p = load(sid)
    if not p.get("research"):
        job.say("Ресёрча ещё нет — концепции будут без него. Лучше сначала запустить ресёрч.")
    pages_rule = ("Это ЛЕНДИНГ: pages содержит одну страницу slug 'index' с 9–13 секциями по порядку."
                  if p.get("kind") == "landing" else
                  f"Это САЙТ из {p.get('pages_n')} страниц: pages — ровно {p.get('pages_n')} страниц, первая slug 'index' (главная). "
                  f"Обязательно включи: {p.get('pages_wish') or 'на твой выбор по сфере'}. У каждой страницы 5–10 секций.")
    prompt = f"""Ты — креативный директор веб-студии. Предложи {n} РАЗНЫХ концепции сайта.
БРИФ
{brief_text(p)}

БРЕНД-КИТ
{json.dumps(p.get('brand') or {}, ensure_ascii=False)[:3000]}

РЕСЁРЧ
{research_text(p)}

ВКУС ВЛАДЕЛЬЦА
{taste_text(p.get('lab'))[:2000]}

ПРАВИЛА
- Концепции заметно разные: одна — «надёжно и по делу» (лучшие практики сферы), одна — «смело и запоминается»
  (выделиться на фоне конкурентов), одна — на твоё усмотрение. В why объясни, на что из ресёрча опираешься.
- Палитра строится от бренд-кита (цвета бренда сохраняются), шрифты — Google Fonts с кириллицей.
- {pages_rule}
- hero — реальные тексты первого экрана (по-русски, конкретно, без «лидер рынка»), visual — что на первом экране.
- signature — один фирменный приём, по которому сайт запомнят.
По-русски. Ответ — JSON."""
    job.say(f"Стратег придумывает {n} концепции…")
    data, meta = brains.ask("site_strategy", prompt, schema=CONCEPTS_SCHEMA, temperature=0.9, job=job, timeout=900)
    concepts = data.get("concepts", [])[:n]
    if not concepts:
        raise RuntimeError("Стратег не вернул концепций.")
    for i, c in enumerate(concepts):
        c["id"] = f"k{int(time.time())}_{i+1}"
        c["preview"] = None
    update(sid, lambda x: (x.__setitem__("concepts", concepts), x.__setitem__("chosen", None)))
    job.progress = 0.3
    job.say("Рисую первый экран каждой концепции…")
    make_previews(job, sid)
    return {"concepts": len(concepts)}


def _extract_html(text: str) -> str:
    m = re.search(r"```(?:html)?\s*(<!doctype.*?</html>)\s*```", text, re.S | re.I)
    if m:
        return m.group(1)
    m = re.search(r"(<!doctype.*</html>)", text, re.S | re.I)
    return m.group(1) if m else text


def preview_prompt(p, c) -> str:
    return f"""Сверстай ПЕРВЫЙ ЭКРАН (hero) и начало следующей секции сайта по концепции — как живое превью для выбора концепции.
Компания: {p.get('name')} · сфера: {p.get('sphere')}
Концепция: {json.dumps({k: c.get(k) for k in ('name', 'idea', 'mood', 'palette', 'typography', 'layout', 'imagery', 'motion', 'hero', 'signature')}, ensure_ascii=False)}
Логотип: {f"<img src='../logo/{p['logo']}' alt='{p.get('name')}'> высотой 32–44px" if p.get('logo') else "текстовый логотип названием компании в фирменном стиле"}

Требования:
- Один самодостаточный HTML-файл: <!doctype html>…</html>, CSS внутри <style>, шрифты через Google Fonts <link>, без JS-фреймворков.
- Ширина макета 1440px, высота первого экрана ~900px, плюс 300–400px следующей секции. Шапка с навигацией, заголовок, подзаголовок, кнопка.
- Визуал без внешних картинок: CSS-градиенты, SVG-формы/иллюстрации, аккуратные плейсхолдеры с подписью, что будет на фото.
- Тексты по-русски из концепции. Уровень — как у сайта-победителя Awwwards: выверенная типографика, сетка, воздух.
Ответь ТОЛЬКО кодом HTML, без пояснений."""


def make_previews(job, sid, only: int | None = None):
    from . import brains
    p = load(sid)
    d = pdir(sid) / "previews"
    d.mkdir(parents=True, exist_ok=True)
    idx = [only] if only is not None else list(range(len(p["concepts"])))

    def one(i):
        c = p["concepts"][i]
        html, _ = brains.ask("site_strategy", preview_prompt(p, c), temperature=0.7, job=job, timeout=900)
        html = _extract_html(html if isinstance(html, str) else json.dumps(html))
        f = d / f"{c['id']}.html"
        f.write_text(html, encoding="utf-8")
        update(sid, lambda x: x["concepts"][i].__setitem__("preview", f.name))
        job.say(f"  превью «{c.get('name')}» готово")
        return f

    with ThreadPoolExecutor(max_workers=3) as ex:
        for k, fut in enumerate([ex.submit(one, i) for i in idx]):
            try:
                fut.result()
            except Exception as e:
                job.say(f"  превью {k+1} не получилось: {str(e)[:200]}")
            job.progress = 0.3 + 0.7 * (k + 1) / len(idx)
    _thumbs(sid)


def _thumbs(sid):
    """Картинки превью для карточек (если есть Playwright) — иначе карточки показывают живой iframe."""
    p = load(sid)
    d = pdir(sid) / "previews"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page(viewport={"width": 1440, "height": 900})
            for c in p["concepts"]:
                if not c.get("preview"):
                    continue
                f = d / c["preview"]
                pg.goto(f.resolve().as_uri(), wait_until="load", timeout=30000)
                pg.wait_for_timeout(1200)
                out = f.with_suffix(".jpg")
                pg.screenshot(path=str(out), type="jpeg", quality=82)
                c["thumb"] = out.name
            br.close()
        update(sid, lambda x: x.__setitem__("concepts", p["concepts"]))
    except Exception:
        pass


def choose(sid, idx: int, feedback: str = ""):
    return update(sid, lambda p: (p.__setitem__("chosen", int(idx)), p.__setitem__("feedback", feedback)))


# ============================================================================= 4. автор промтов
PACK_SCHEMA = {"type": "object", "properties": {
    "master": {"type": "string"},
    "pages": {"type": "array", "items": {"type": "object", "properties": {
        "slug": {"type": "string"}, "title": {"type": "string"}, "prompt": {"type": "string"}},
        "required": ["slug", "title", "prompt"]}},
    "content": {"type": "string"},
    "photos": {"type": "string"},
    "checklist": {"type": "array", "items": {"type": "string"}}},
    "required": ["master", "pages", "content", "checklist"]}

STACKS = {
    "static": "Статический сайт без сборщиков: HTML5 + современный CSS (custom properties, grid, clamp) + немного ванильного JS. "
              "Файлы: index.html и по файлу на страницу (slug.html), css/style.css, js/main.js, assets/. Открывается двойным кликом.",
    "nextjs": "Next.js (App Router, последняя стабильная версия) + TypeScript + Tailwind CSS. Статический экспорт (output: 'export'). "
              "Страницы в app/<slug>/page.tsx, общие компоненты в components/, дизайн-токены в tailwind.config и CSS-переменных.",
}


def run_prompts(job, sid):
    from . import brains
    p = load(sid)
    if p.get("chosen") is None:
        raise ValueError("Сначала выбери концепцию.")
    c = p["concepts"][p["chosen"]]
    logo = p.get("logo")
    prompt = f"""Ты — ведущий продуктовый дизайнер и тимлид фронтенда. Напиши ИДЕАЛЬНЫЙ пакет промтов, по которому Claude Code (или Codex)
соберёт этот сайт за один проход без уточняющих вопросов. Промты — на русском, технические термины — как есть.

ДАННЫЕ
Бриф: {brief_text(p)}
Бренд-кит: {json.dumps(p.get('brand') or {}, ensure_ascii=False)[:3500]}
Выбранная концепция: {json.dumps(c, ensure_ascii=False)[:6000]}
Правки владельца к концепции: {p.get('feedback') or '(нет)'}
Ресёрч (кратко): {research_text(p, 4000)}
Вкус владельца: {taste_text(p.get('lab'))[:1500]}
Стек: {STACKS.get(p.get('stack') or 'static')}
Логотип: {"лежит в assets/" + logo if logo else "нет — текстовый логотип по названию"}
Фото: {photos_text(p)}

ЧТО НАПИСАТЬ
1) master — главный промт (он же CLAUDE.md проекта), Markdown, разделы:
   «Роль и цель» · «Компания и аудитория» · «Концепция и настроение» · «Дизайн-система» (ВСЕ токены: цвета HEX с ролями,
   шрифты Google Fonts с весами, шкала размеров через clamp, отступы, радиусы, тени, сетка, брейкпоинты 360/768/1024/1440)
   · «Компоненты» (шапка, футер, кнопки и их состояния, карточки, формы, …) · «Анимация» (что, как, prefers-reduced-motion)
   · «Тексты и тон» · «Изображения» (если фото уже есть — используй файлы assets/photos/<id>.jpg из манифеста assets/photos/PHOTOS.json
   с их alt и пропорциями, обработку и кадрирование через CSS object-fit/object-position; для мест без фото — аккуратные
   плейсхолдеры с подписью; без внешних стоков)
   · «Техника» (стек, структура файлов, семантика, SEO-мета и OG, разметка JSON-LD — ОДИН объект
   {"@context": "https://schema.org", "@graph": [...]} и никогда не массив на верхнем уровне, доступность WCAG AA,
   производительность, формы — отправка на заглушку с сообщением об успехе) · «Порядок работы» (сначала дизайн-система и общие компоненты, потом страницы
   по очереди, затем самопроверка) · «Критерии готовности» (чек-лист) · «Чего не делать».
2) pages — по промту на каждую страницу концепции (в порядке концепции): для каждой секции — назначение, раскладка
   на десктопе и мобиле, ТОЧНЫЕ тексты (заголовки, подзаголовки, кнопки, пункты), визуал, поведение.
3) content — все тексты сайта одним документом (Markdown) по страницам — для редактирования владельцем.
4) photos — список фото/иллюстраций, которые нужно снять или сгенерировать (что, где, пропорции).
5) checklist — 12–20 проверяемых пунктов приёмки.
Пиши конкретно: никаких «красивый», «современный» без расшифровки. Это должен быть лучший промт, который можно написать."""
    job.say("Автор промтов пишет пакет для Claude Code…")
    data, meta = brains.ask("site_prompt", prompt, schema=PACK_SCHEMA, temperature=0.5, job=job, timeout=1500)
    d = pdir(sid) / "prompts"
    if d.exists():
        shutil.rmtree(d)
    (d / "pages").mkdir(parents=True)
    (d / "MASTER.md").write_text(data["master"].strip() + "\n", encoding="utf-8")
    files = ["MASTER.md"]
    for i, pg in enumerate(data.get("pages", [])):
        slug = re.sub(r"[^a-z0-9\-]+", "-", (pg.get("slug") or f"page{i+1}").lower()).strip("-") or f"page{i+1}"
        f = d / "pages" / f"{i+1:02d}_{slug}.md"
        f.write_text(f"# Страница: {pg.get('title')} ({slug})\n\n{pg['prompt'].strip()}\n", encoding="utf-8")
        files.append(f"pages/{f.name}")
    (d / "CONTENT.md").write_text(data.get("content", "").strip() + "\n", encoding="utf-8")
    (d / "PHOTOS.md").write_text((data.get("photos") or "").strip() + "\n", encoding="utf-8")
    (d / "CHECKLIST.md").write_text("# Приёмка\n\n" + "\n".join(f"- [ ] {x}" for x in data.get("checklist", [])) + "\n",
                                     encoding="utf-8")
    (d / "HOW_TO_USE.md").write_text(HOW_TO_USE, encoding="utf-8")
    allin = ["# Пакет промтов — всё одним файлом\n", (d / "MASTER.md").read_text(encoding="utf-8")]
    for f in sorted((d / "pages").glob("*.md")):
        allin.append("\n---\n\n" + f.read_text(encoding="utf-8"))
    allin.append("\n---\n\n" + (d / "CHECKLIST.md").read_text(encoding="utf-8"))
    (d / "ALL_IN_ONE.md").write_text("\n".join(allin), encoding="utf-8")
    files += ["CONTENT.md", "PHOTOS.md", "CHECKLIST.md", "HOW_TO_USE.md", "ALL_IN_ONE.md"]
    info = {"files": files, "created": datetime.now().isoformat(timespec="seconds"), "concept": c.get("name"),
            "pages": [x.get("title") for x in data.get("pages", [])], "by": meta.get("provider")}
    update(sid, lambda x: x.__setitem__("prompts", info))
    job.say(f"Пакет готов: MASTER + {len(data.get('pages', []))} страниц(ы) + тексты + чек-лист.")
    return info


HOW_TO_USE = """# Как использовать пакет

## Claude Code
1. Создай пустую папку проекта, положи в неё логотип в `assets/`.
2. Скопируй `MASTER.md` в корень под именем `CLAUDE.md` — Claude Code читает его автоматически.
3. Запусти `claude` в этой папке и отправь: «Собери сайт по CLAUDE.md. Страницы — в папке prompts/pages, тексты — CONTENT.md».
   Или по одной: «Сделай страницу по prompts/pages/01_index.md».
4. В конце: «Проверь сайт по CHECKLIST.md и исправь всё, что не так».

## Codex
То же самое: `MASTER.md` → `AGENTS.md` в корне проекта, дальше страницы по очереди.

## Одним сообщением
Если инструмент принимает только один промт — вставь `ALL_IN_ONE.md`.
"""


def read_prompt_file(sid, name: str) -> str:
    d = (pdir(sid) / "prompts").resolve()
    f = (d / name).resolve()
    if d not in f.parents:
        raise ValueError("bad file")
    return f.read_text(encoding="utf-8")


def write_prompt_file(sid, name: str, text: str):
    d = (pdir(sid) / "prompts").resolve()
    f = (d / name).resolve()
    if d not in f.parents or not f.exists():
        raise ValueError("bad file")
    f.write_text(text, encoding="utf-8")


# ============================================================================= 5. сборка
def _site_pages(build: Path) -> list[str]:
    pages = sorted(x.name for x in build.glob("*.html"))
    if "index.html" in pages:
        pages.remove("index.html")
        pages.insert(0, "index.html")
    if not pages and (build / "out" / "index.html").exists():   # next.js export
        pages = ["out/index.html"]
    return pages


def _count_files(b: Path) -> int:
    return sum(1 for f in b.rglob("*") if f.is_file() and not any(x in f.parts for x in ("_brief", "_review", "node_modules", ".next")))


def _build_prompt(p, n_ph: int, extra: str) -> str:
    stack = p.get("stack") or "static"
    return f"""Собери сайт в текущей папке по CLAUDE.md (главный промт).
Страницы — файлы _brief/pages/*.md по порядку, тексты — _brief/CONTENT.md, приёмка — _brief/CHECKLIST.md.
{"Логотип: assets/" + p["logo"] if p.get("logo") else "Логотипа-файла нет — сделай текстовый логотип."}
{("Фото: в assets/photos лежат " + str(n_ph) + " готовых фото, их места и alt — в assets/photos/PHOTOS.json. Используй именно их, "
  "а плейсхолдеры — только там, где фото нет.") if n_ph else "Фото пока нет — аккуратные плейсхолдеры с подписью, что за фото."}
Стек: {STACKS.get(stack)}
{"Не запускай npm и сборку (их здесь может не быть) — только исходники проекта." if stack == "nextjs" else ""}
Работай экономно: не перечитывай одни и те же файлы, пиши файлы целиком сразу, без лишних черновиков.
JSON-LD для поисковиков — один объект {"@context": "https://schema.org", "@graph": [...]}, не массив (массив ломает скрипты и расширения браузера).
Порядок: 1) дизайн-система и общие стили/компоненты; 2) страницы и секции по очереди, полностью, с настоящими текстами;
3) сверка с чек-листом и исправления. Не задавай вопросов. Не удаляй папку _brief. В конце коротко перечисли созданные файлы.
{("ДОПОЛНИТЕЛЬНО ОТ ВЛАДЕЛЬЦА: " + extra) if extra else ""}"""


CONTINUE_PROMPT = """Сборка сайта в этой папке была прервана ({why}) — продолжи с того места, где остановились.
Главный промт — CLAUDE.md, страницы — _brief/pages/*.md, тексты — _brief/CONTENT.md, приёмка — _brief/CHECKLIST.md.
1) Быстро осмотрись: Glob по проекту, открой только то, что нужно, чтобы понять, что уже готово.
2) Доделай недостающее: незаконченные секции и страницы, общие компоненты, стили, подключение фото и логотипа.
   Готовые файлы не переписывай с нуля — только дописывай и исправляй.
3) Сверь результат с чек-листом и поправь. Если всё уже готово — просто проверь по чек-листу и закончи.
Не задавай вопросов. В конце коротко перечисли, что доделал.{extra}"""


def _register(sid, bdir: str, patch: dict):
    def fn(x):
        bb = next((b for b in x["builds"] if b["dir"] == bdir), None)
        if not bb:
            bb = {"dir": bdir, "created": datetime.now().isoformat(timespec="seconds"), "review": None, "sessions": []}
            x["builds"].append(bb)
        sessions = bb.setdefault("sessions", [])
        if patch.get("session"):
            sessions.append(patch.pop("session"))
        bb.update(patch)
    update(sid, fn)


def _run_sessions(job, sid, bdir: str, first_prompt: str | None, extra: str = ""):
    """Сессии Claude Code над одной сборкой: если сессия упёрлась во время/шаги — автоматически продолжаем."""
    from . import brains
    from .config import settings as _s
    p = load(sid)
    b = pdir(sid) / "builds" / bdir
    minutes = max(10, int_setting("SITE_BUILD_MINUTES", 45))
    resumes = max(0, int_setting("SITE_BUILD_RESUMES", 3))
    model = (_s().get("SITE_BUILD_MODEL") or "").strip() or None
    prompt = first_prompt
    why = "предыдущая сессия не закончила работу"
    total_steps, total_secs, summary = 0, 0, ""
    for k in range(resumes + 1):
        if prompt is None:
            prompt = CONTINUE_PROMPT.format(why=why, extra=("\nДОПОЛНИТЕЛЬНО ОТ ВЛАДЕЛЬЦА: " + extra) if extra else "")
        job.say(f"Сессия {k + 1}: Claude Code ({model or 'модель по умолчанию'}) работает, лимит {minutes} мин…")
        try:
            res = brains.run_claude_code(job, prompt, b, max_turns=int_setting("SITE_BUILD_TURNS", 150),
                                         timeout=minutes * 60, model=model)
            total_steps += res.get("turns") or 0
            total_secs += res["seconds"]
            summary = res["summary"]
            _register(sid, bdir, {"status": "done", "pages": _site_pages(b), "files": _count_files(b),
                                  "summary": summary[:2000], "turns": total_steps, "seconds": total_secs,
                                  "session": {"n": k + 1, "result": "готово", "seconds": res["seconds"]}})
            return True
        except brains.ClaudeCodeStopped as e:
            total_steps += e.steps
            total_secs += e.seconds
            why = {"timeout": "закончилось время сессии", "idle": "Claude долго молчал", "max_turns": "закончились шаги сессии"}.get(e.reason, e.reason)
            _register(sid, bdir, {"status": "partial", "pages": _site_pages(b), "files": _count_files(b),
                                  "summary": f"Сессия {k + 1} остановлена: {why}. Файлов в проекте: {_count_files(b)}.",
                                  "turns": total_steps, "seconds": total_secs,
                                  "session": {"n": k + 1, "result": why, "seconds": e.seconds, "files": len(e.files)}})
            job.say(f"  {e} Файлов за сессию: {len(e.files)}.")
            prompt = None
            if k < resumes:
                job.say("  Продолжаю в новой сессии с того же места…")
        except Exception as e:
            _register(sid, bdir, {"status": "partial", "pages": _site_pages(b), "files": _count_files(b),
                                  "summary": f"Сборка прервалась с ошибкой: {str(e)[:400]}",
                                  "session": {"n": k + 1, "result": "ошибка", "error": str(e)[:300]}})
            raise
    job.say("Сборка не закончена за отведённые сессии — нажми «Продолжить сборку», когда будет удобно.")
    return False


def run_build(job, sid, extra: str = ""):
    p = load(sid)
    if not p.get("prompts"):
        raise ValueError("Сначала сделай пакет промтов.")
    n = 1 + max([int(b["dir"][1:]) for b in p.get("builds", []) if b["dir"][1:].isdigit()] or [0])
    bdir = f"v{n}"
    b = pdir(sid) / "builds" / bdir
    b.mkdir(parents=True, exist_ok=True)
    shutil.copytree(pdir(sid) / "prompts", b / "_brief", dirs_exist_ok=True)
    shutil.copyfile(b / "_brief" / "MASTER.md", b / "CLAUDE.md")
    (b / "assets").mkdir(exist_ok=True)
    if logo_path(p):
        shutil.copyfile(logo_path(p), b / "assets" / p["logo"])
    n_ph = copy_photos(p, b / "assets" / "photos")
    if n_ph:
        job.say(f"  фото для сайта: {n_ph} шт. → assets/photos")
    stack = p.get("stack") or "static"
    _register(sid, bdir, {"status": "running", "stack": stack, "pages": [], "files": 0,
                          "concept": (p["concepts"][p["chosen"]] or {}).get("name") if p.get("chosen") is not None else "",
                          "summary": "Идёт сборка…"})
    done = _run_sessions(job, sid, bdir, _build_prompt(p, n_ph, extra), extra)
    return _after_build(job, sid, bdir, done)


def run_resume(job, sid, bdir: str, extra: str = ""):
    """Продолжить незаконченную сборку с того места, где она остановилась."""
    b = pdir(sid) / "builds" / bdir
    if not b.exists():
        raise ValueError("Сборка не найдена")
    _register(sid, bdir, {"status": "running", "summary": "Продолжаю сборку…"})
    done = _run_sessions(job, sid, bdir, None, extra)
    return _after_build(job, sid, bdir, done)


def _after_build(job, sid, bdir, done):
    p = load(sid)
    bb = next(x for x in p["builds"] if x["dir"] == bdir)
    job.say(f"{'Сборка готова' if done else 'Сборка сохранена незаконченной'}: файлов {bb.get('files')}, "
            f"страниц HTML {len(bb.get('pages') or [])}, {round((bb.get('seconds') or 0) / 60)} мин.")
    job.progress = 0.85
    if done and bb.get("pages") and (bb.get("stack") or "static") == "static":
        try:
            run_review(job, sid, bdir)
        except Exception as e:
            job.say(f"  проверка по скриншотам не получилась: {str(e)[:200]}")
    return {"build": bdir, "done": done, "pages": bb.get("pages")}


REVIEW_SCHEMA = {"type": "object", "properties": {
    "score": {"type": "number"},
    "summary": {"type": "string"},
    "issues": {"type": "array", "items": {"type": "object", "properties": {
        "page": {"type": "string"}, "severity": {"type": "string", "enum": ["high", "medium", "low"]},
        "problem": {"type": "string"}, "fix": {"type": "string"}}, "required": ["problem", "fix"]}}},
    "required": ["score", "summary", "issues"]}


def _shoot_build(b: Path, pages: list[str], job) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        job.say("  проверка пропущена: нет Playwright")
        return []
    shots = []
    out = b / "_review"
    out.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for vw, vh, tag in ((1440, 900, "desktop"), (390, 844, "mobile")):
            pg = br.new_page(viewport={"width": vw, "height": vh})
            for name in pages[:8]:
                try:
                    pg.goto((b / name).resolve().as_uri(), wait_until="load", timeout=30000)
                    pg.wait_for_timeout(1200)
                    h = min(pg.evaluate("document.body ? document.body.scrollHeight : 900") or vh, 6000)
                    pg.set_viewport_size({"width": vw, "height": int(h)})
                    pg.wait_for_timeout(500)
                    f = out / f"{Path(name).stem}_{tag}.jpg"
                    pg.screenshot(path=str(f), type="jpeg", quality=70)
                    _shrink(f, 720 if tag == "desktop" else 390)
                    shots.append(f)
                    pg.set_viewport_size({"width": vw, "height": vh})
                except Exception as e:
                    job.say(f"  {name} ({tag}) не снялся: {str(e)[:100]}")
            pg.close()
        br.close()
    return shots


def run_review(job, sid, bdir: str):
    from . import brains
    p = load(sid)
    b = pdir(sid) / "builds" / bdir
    pages = _site_pages(b)
    job.say("Проверяю сайт по скриншотам (десктоп и мобильный)…")
    shots = _shoot_build(b, pages, job)
    if not shots:
        return None
    checklist = (b / "_brief" / "CHECKLIST.md").read_text(encoding="utf-8") if (b / "_brief" / "CHECKLIST.md").exists() else ""
    c = p["concepts"][p["chosen"]] if p.get("chosen") is not None else {}
    prompt = f"""Ты — строгий арт-директор и QA. Открой каждый скриншот инструментом Read (desktop и mobile версии страниц:
{', '.join(s.name for s in shots)}) и оцени сайт против концепции и чек-листа.
Концепция: {json.dumps({k: c.get(k) for k in ('name', 'idea', 'palette', 'typography', 'layout', 'signature')}, ensure_ascii=False)}
Чек-лист:
{checklist[:3000]}
Ищи: поломанную вёрстку, наезды и обрезки, слабую типографику, плохой контраст, пустые места, несоответствие концепции,
проблемы мобильной версии, недоделанные секции. score — 0–100. issues — конкретные проблемы и как исправить (page — имя файла).
По-русски. Ответ — JSON."""
    data, _ = brains.ask("site_strategy", prompt, images=shots[:16], schema=REVIEW_SCHEMA, job=job, timeout=900)
    data["shots"] = [s.name for s in shots]
    update(sid, lambda x: [bb.__setitem__("review", data) for bb in x["builds"] if bb["dir"] == bdir])
    job.say(f"Оценка проверяющего: {data.get('score')} — {data.get('summary','')[:200]}")
    return data


def run_fix(job, sid, bdir: str, extra: str = "", use_review=True):
    """Доработка существующей сборки: замечания проверяющего + пожелания владельца."""
    from . import brains
    p = load(sid)
    b = pdir(sid) / "builds" / bdir
    bb = next((x for x in p["builds"] if x["dir"] == bdir), None)
    if not bb:
        raise ValueError("Сборка не найдена")
    issues = (bb.get("review") or {}).get("issues", []) if use_review else []
    if not issues and not extra.strip():
        raise ValueError("Нет замечаний — напиши, что поправить.")
    lst = "\n".join(f"- [{i.get('severity','')}] {i.get('page','')}: {i['problem']} → {i['fix']}" for i in issues)
    prompt = f"""Сайт в этой папке уже собран по CLAUDE.md. Внеси правки, ничего не ломая и не переписывая с нуля.
{("Замечания проверяющего:" + chr(10) + lst) if lst else ""}
{("Пожелания владельца: " + extra) if extra.strip() else ""}
После правок перепроверь затронутые страницы. Не задавай вопросов. В конце перечисли, что изменил."""
    job.say("Claude Code вносит правки…")
    from .config import settings as _s
    try:
        res = brains.run_claude_code(job, prompt, b, max_turns=int_setting("SITE_BUILD_TURNS", 150),
                                     timeout=max(10, int_setting("SITE_BUILD_MINUTES", 45)) * 60,
                                     model=(_s().get("SITE_BUILD_MODEL") or "").strip() or None)
    except brains.ClaudeCodeStopped as e:
        res = {"summary": f"Правки не закончены: {e}", "files": e.files, "turns": e.steps, "seconds": e.seconds}
        job.say(f"  {e} Можно нажать «Исправить» ещё раз — Claude продолжит.")
    note = {"at": datetime.now().isoformat(timespec="seconds"), "extra": extra, "issues": len(issues),
            "summary": res["summary"][:1500]}
    update(sid, lambda x: [y.setdefault("fixes", []).append(note) for y in x["builds"] if y["dir"] == bdir])
    if (p.get("stack") or "static") == "static":
        try:
            run_review(job, sid, bdir)
        except Exception as e:
            job.say(f"  повторная проверка не получилась: {str(e)[:200]}")
    return note


# ============================================================================= автопилот и выгрузка
def run_to_concepts(job, sid):
    """Бренд-кит → ресёрч → концепции с превью."""
    class Sub:
        def __init__(s, lo, hi):
            s.lo, s.hi = lo, hi

        def say(s, m):
            job.say(m)

        @property
        def progress(s):
            return job.progress

        @progress.setter
        def progress(s, v):
            job.progress = s.lo + (s.hi - s.lo) * max(0.0, min(1.0, v))
    job.say("Шаг 1 · бренд-кит")
    try:
        run_brand(Sub(0, 0.1), sid)
    except Exception as e:
        job.say(f"  бренд-кит не получился: {str(e)[:200]}")
    job.say("Шаг 2 · ресёрч")
    run_research(Sub(0.1, 0.6), sid)
    job.say("Шаг 3 · концепции")
    run_concepts(Sub(0.6, 1.0), sid)
    return {"ok": True}


def make_zip(sid, what: str) -> Path:
    p = load(sid)
    d = pdir(sid)
    if what == "prompts":
        src = d / "prompts"
        name = f"{p['id']}_prompts.zip"
    else:
        src = d / "builds" / what
        name = f"{p['id']}_{what}.zip"
    if not src.exists():
        raise ValueError("Нечего скачивать")
    out = d / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob("*"):
            if f.is_file() and "_review" not in f.parts and "node_modules" not in f.parts:
                z.write(f, f.relative_to(src))
        if what == "prompts" and logo_path(p):
            z.write(logo_path(p), f"assets/{p['logo']}")
        if what == "prompts":
            tmp = d / "_zip_photos"
            if tmp.exists():
                shutil.rmtree(tmp)
            if copy_photos(p, tmp):
                for f in tmp.iterdir():
                    z.write(f, f"assets/photos/{f.name}")
            shutil.rmtree(tmp, ignore_errors=True)
    return out


# ============================================================================= фото для сайта
ASPECTS = ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4", "2:3", "9:16"]
NB2_T2I = "fal-ai/nano-banana-2"
NB2_EDIT = "fal-ai/nano-banana-2/edit"
PHOTO_USD = 0.12          # Nano Banana 2, 2K, за картинку

PHOTO_PLAN_SCHEMA = {"type": "object", "properties": {
    "style": {"type": "object", "properties": {
        "summary": {"type": "string"}, "light": {"type": "string"}, "color_grade": {"type": "string"},
        "composition": {"type": "string"}, "people": {"type": "string"}, "avoid": {"type": "string"},
        "prompt_suffix_en": {"type": "string"}}, "required": ["summary", "prompt_suffix_en"]},
    "slots": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "page": {"type": "string"}, "section": {"type": "string"},
        "purpose": {"type": "string"}, "aspect": {"type": "string", "enum": ASPECTS},
        "subject_ru": {"type": "string"}, "prompt_en": {"type": "string"}, "alt_ru": {"type": "string"}},
        "required": ["id", "page", "section", "aspect", "subject_ru", "prompt_en", "alt_ru"]}}},
    "required": ["style", "slots"]}

ENHANCE_MODES = {
    "retouch": ("Ретушь", "Retouch this photo so it looks like a frame from a professional photoshoot: correct exposure and white "
                "balance, soft flattering light, clean natural color grading, remove noise and small distractions, subtle "
                "depth of field. Keep EVERYTHING the same: the same people (faces, bodies, clothes), the same products, "
                "interior and composition. Do not add or remove objects. No text, no watermark."),
    "studio": ("Фотосессия", "Turn this into a high-end professional photoshoot image: keep the same people, faces and the same "
               "product/object exactly recognizable, but re-light it with beautiful studio or natural light, place it in a "
               "clean, premium setting that matches the style, add depth of field and an editorial color grade. "
               "Do not change identity, logos or product design. No text, no watermark."),
}


def _photos(p) -> dict:
    return p.get("photos") or {"style": None, "slots": [], "uploads": []}


def photos_text(p) -> str:
    ph = _photos(p)
    chosen = [s for s in ph.get("slots", []) if s.get("chosen")]
    if not chosen:
        return "готовых фото пока нет"
    return (f"{len(chosen)} готовых фото в assets/photos (манифест PHOTOS.json): " +
            "; ".join(f"{s['id']}.jpg — {s['page']}/{s['section']}, {s['aspect']}, «{s.get('alt_ru','')}»" for s in chosen))


def copy_photos(p, out: Path) -> int:
    ph = _photos(p)
    chosen = [s for s in ph.get("slots", []) if s.get("chosen")]
    if not chosen:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    src = pdir(p["id"]) / "photos"
    manifest = []
    for s in chosen:
        f = src / s["chosen"]
        if not f.exists():
            continue
        dst = out / f"{s['id']}{f.suffix.lower() or '.jpg'}"
        shutil.copyfile(f, dst)
        manifest.append({"file": dst.name, "page": s["page"], "section": s["section"], "purpose": s.get("purpose", ""),
                         "aspect": s["aspect"], "alt": s.get("alt_ru", "")})
    (out / "PHOTOS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(manifest)


def run_photo_plan(job, sid):
    from . import brains
    p = load(sid)
    if p.get("chosen") is None:
        raise ValueError("Сначала выбери концепцию.")
    c = p["concepts"][p["chosen"]]
    r = p.get("research") or {}
    prompt = f"""Ты — фотодиректор веб-студии. Составь план фото для сайта: единый стиль съёмки и список мест под фото.
Бриф: {brief_text(p)}
Концепция: {json.dumps({k: c.get(k) for k in ('name', 'idea', 'mood', 'palette', 'imagery', 'hero', 'pages', 'signature')}, ensure_ascii=False)[:5000]}
Правки владельца: {p.get('feedback') or '(нет)'}
Фото в тренде в этой сфере: {json.dumps(r.get('photo_trends', []), ensure_ascii=False)[:2500]}
Как сняты фото у сильных сайтов: {json.dumps([{'url': x.get('url'), 'photo_style': x.get('photo_style')} for x in ((r.get('visual') or {}).get('reviews') or [])], ensure_ascii=False)[:2000]}
Выглядит дёшево: {json.dumps(r.get('photo_avoid', []), ensure_ascii=False)}
Вкус владельца: {taste_text(p.get('lab'))[:1200]}

Сделай:
- style: единый фотостиль сайта (свет, цветокоррекция, композиция, люди, чего избегать) и prompt_suffix_en — английский
  хвост, который добавляется к каждому промту генерации, чтобы все фото были в одном стиле.
- slots: 6–14 мест под фото по страницам и секциям концепции (hero обязательно). id — латиницей (hero, about-team, service-1…),
  aspect — пропорция места на сайте, subject_ru — что в кадре, alt_ru — alt-текст, prompt_en — подробный промт генерации
  (сюжет, люди, место, ракурс, свет, объектив), фотореализм, без текста и логотипов в кадре.
Всё, кроме prompt_en/prompt_suffix_en, — по-русски. Ответ — JSON."""
    job.say("Фотодиректор составляет план фото…")
    data, _ = brains.ask("site_strategy", prompt, schema=PHOTO_PLAN_SCHEMA, temperature=0.7, job=job, timeout=900)
    old = _photos(p)
    slots = []
    for i, sl in enumerate(data.get("slots", [])[:16]):
        sid_ = re.sub(r"[^a-z0-9\-]+", "-", (sl.get("id") or f"photo-{i+1}").lower()).strip("-") or f"photo-{i+1}"
        if sid_ in [x["id"] for x in slots]:
            sid_ += f"-{i+1}"
        slots.append({**sl, "id": sid_, "aspect": sl.get("aspect") if sl.get("aspect") in ASPECTS else "4:3",
                      "variants": [], "chosen": None})
    update(sid, lambda x: x.__setitem__("photos", {"style": data.get("style"), "slots": slots,
                                                  "uploads": old.get("uploads", [])}))
    job.say(f"План: {len(slots)} мест под фото. Стиль: {(data.get('style') or {}).get('summary', '')[:200]}")
    return {"slots": len(slots)}


def _slot(p, slot_id):
    s = next((x for x in _photos(p)["slots"] if x["id"] == slot_id), None)
    if not s:
        raise ValueError("Место под фото не найдено")
    return s


def _add_variant(sid, slot_id, file: str, kind: str, source: str = ""):
    def fn(p):
        ph = _photos(p)
        for s in ph["slots"]:
            if s["id"] == slot_id:
                s.setdefault("variants", []).insert(0, {"file": file, "kind": kind, "source": source,
                                                        "at": datetime.now().isoformat(timespec="seconds")})
                if not s.get("chosen") or kind in ("enhanced",):
                    s["chosen"] = file
        p["photos"] = ph
    update(sid, fn)


def _aspect_size(aspect: str, long_side=1600):
    a, b = (int(x) for x in aspect.split(":"))
    return (long_side, int(long_side * b / a)) if a >= b else (int(long_side * a / b), long_side)


def _demo_photo(out: Path, aspect: str, label: str, palette: list[str]):
    from PIL import Image, ImageDraw
    w, h = _aspect_size(aspect)
    c1 = palette[0] if palette else "#2C4A52"
    c2 = palette[1] if len(palette) > 1 else "#D9B97A"
    rgb = lambda hx: tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))  # noqa: E731
    a, b = rgb(c1), rgb(c2)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a[k] * (1 - t) + b[k] * t * 0.6) for k in range(3)))
    try:
        d.text((40, h - 80), "ДЕМО: " + label[:80], fill=(255, 255, 255))
    except Exception:
        d.text((40, h - 80), "DEMO", fill=(255, 255, 255))
    im.save(out, quality=88)


def _demo_enhance(src: Path, out: Path):
    from PIL import Image, ImageEnhance, ImageFilter
    im = Image.open(src).convert("RGB")
    im = ImageEnhance.Contrast(im).enhance(1.12)
    im = ImageEnhance.Color(im).enhance(1.15)
    im = ImageEnhance.Brightness(im).enhance(1.04)
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=60))
    im.save(out, quality=90)


def _fal_image(job, endpoint: str, args: dict, out: Path, sid: str, detail: str):
    from . import gen
    fal = gen._fal()
    try:
        res = fal.subscribe(endpoint, arguments=args, with_logs=False)
    except Exception as e:
        raise RuntimeError(f"Nano Banana 2: {e}") from e
    imgs = res.get("images") or []
    if not imgs or not imgs[0].get("url"):
        raise RuntimeError(f"Nano Banana 2 не вернула картинку: {str(res)[:200]}")
    gen._download(imgs[0]["url"], out)
    store.log_cost("image", PHOTO_USD, sid, detail)
    return out


def run_generate_photos(job, sid, slot_ids=None):
    from . import gen
    from .config import demo_mode
    p = load(sid)
    ph = _photos(p)
    slots = [s for s in ph["slots"] if (s["id"] in slot_ids if slot_ids else not s.get("chosen"))]
    if not slots:
        raise ValueError("Нет мест для генерации (все уже с фото).")
    if not demo_mode():
        gen._check_limit(PHOTO_USD * len(slots))
    suffix = ((ph.get("style") or {}).get("prompt_suffix_en") or "").strip()
    c = p["concepts"][p["chosen"]] if p.get("chosen") is not None else {}
    palette = [x.get("hex") for x in c.get("palette", []) if str(x.get("hex", "")).startswith("#")]
    d = pdir(sid) / "photos"
    d.mkdir(parents=True, exist_ok=True)
    job.say(f"Генерирую фото: {len(slots)} шт. {'(демо, $0)' if demo_mode() else f'(~${PHOTO_USD * len(slots):.2f})'}")

    def one(s):
        out = d / f"{s['id']}_ai_{uuid.uuid4().hex[:6]}.jpg"
        if demo_mode():
            _demo_photo(out, s["aspect"], s.get("subject_ru", s["id"]), palette)
        else:
            prompt = f"{s['prompt_en'].strip()} {suffix} Photorealistic, no text, no logos, no watermark."
            _fal_image(job, NB2_T2I, {"prompt": prompt, "aspect_ratio": s["aspect"], "resolution": "2K",
                                      "num_images": 1, "output_format": "jpeg"}, out, sid, f"site photo {s['id']}")
        _add_variant(sid, s["id"], out.name, "ai")
        job.say(f"  {s['id']}: готово")

    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for fut in [ex.submit(one, s) for s in slots]:
            try:
                fut.result()
            except Exception as e:
                job.say(f"  не получилось: {str(e)[:200]}")
            done += 1
            job.progress = done / len(slots)
    return {"photos": done}


def add_photo_upload(sid, filename: str, data: bytes, slot_id: str = "") -> dict:
    from . import media
    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"):
        raise ValueError("Фото: jpg, png, webp или heic.")
    d = pdir(sid) / "photos"
    d.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", Path(filename).stem)[:40] or "photo"
    raw = d / f"_raw_{uuid.uuid4().hex[:6]}{ext}"
    raw.write_bytes(data)
    out = d / f"up_{stem}_{uuid.uuid4().hex[:6]}.jpg"
    try:
        media.prepare_photo(raw, out, max_side=2400)
    finally:
        raw.unlink(missing_ok=True)

    def fn(p):
        ph = _photos(p)
        ph.setdefault("uploads", []).insert(0, {"file": out.name, "name": filename, "slot": slot_id or None})
        p["photos"] = ph
    update(sid, fn)
    if slot_id:
        _add_variant(sid, slot_id, out.name, "upload")
    return load(sid)


ASSIGN_SCHEMA = {"type": "object", "properties": {"assign": {"type": "array", "items": {"type": "object", "properties": {
    "upload": {"type": "string"}, "slot": {"type": "string"}, "enhance": {"type": "string", "enum": ["none", "retouch", "studio"]},
    "note": {"type": "string"}}, "required": ["upload", "slot", "enhance"]}}}, "required": ["assign"]}


def run_assign(job, sid, auto_enhance=False):
    """Claude смотрит мои фото и раскладывает их по местам сайта."""
    from . import brains
    p = load(sid)
    ph = _photos(p)
    ups = [u for u in ph.get("uploads", []) if not u.get("slot")][:20]
    if not ups or not ph.get("slots"):
        raise ValueError("Нужны план фото и хотя бы одно своё фото без места.")
    d = pdir(sid) / "photos"
    imgs = [d / u["file"] for u in ups]
    legend = "\n".join(f"image_{i+1} = {u['file']}" for i, u in enumerate(ups))
    slots = [{k: s.get(k) for k in ("id", "page", "section", "aspect", "subject_ru")} for s in ph["slots"]]
    prompt = f"""Ты — фоторедактор. Открой каждое фото (инструмент Read) и разложи их по местам сайта.
Фото:
{legend}
Места: {json.dumps(slots, ensure_ascii=False)}
Стиль сайта: {json.dumps(ph.get('style') or {}, ensure_ascii=False)[:1200]}
Правила: одно фото — одно место; не ставь фото туда, где оно не подходит по смыслу или пропорциям (лучше оставить без места);
enhance — какое улучшение нужно: none (и так хорошо), retouch (свет/цвет/чистка), studio (переснять как фотосессию).
upload — имя файла из списка. note — коротко, почему. Ответ — JSON."""
    data, _ = brains.ask("site_strategy", prompt, images=imgs, schema=ASSIGN_SCHEMA, job=job, timeout=900)
    valid_slots = {s["id"] for s in ph["slots"]}
    names = {u["file"] for u in ups}
    n = 0
    todo = []
    for a in data.get("assign", []):
        if a.get("slot") in valid_slots and a.get("upload") in names:
            _add_variant(sid, a["slot"], a["upload"], "upload")
            update(sid, lambda x: [u.__setitem__("slot", a["slot"]) for u in x["photos"]["uploads"] if u["file"] == a["upload"]])
            job.say(f"  {a['upload']} → {a['slot']} ({a.get('enhance')}) {a.get('note','')}")
            n += 1
            if a.get("enhance") in ENHANCE_MODES:
                todo.append((a["slot"], a["upload"], a["enhance"]))
    update(sid, lambda x: x["photos"].__setitem__("advice", [{"slot": s, "file": f, "mode": m} for s, f, m in todo]))
    if auto_enhance and todo:
        for s, f, m in todo:
            run_enhance(job, sid, s, f, m)
    job.say(f"Разложено фото: {n}. Советов улучшить: {len(todo)}.")
    return {"assigned": n, "enhance": len(todo)}


def run_enhance(job, sid, slot_id: str, file: str, mode: str = "retouch", extra: str = ""):
    """Улучшить фото «как с хорошей фотосессии» (Nano Banana 2 edit)."""
    from . import gen
    from .config import demo_mode
    p = load(sid)
    s = _slot(p, slot_id)
    src = pdir(sid) / "photos" / Path(file).name
    if not src.exists():
        raise ValueError("Фото не найдено")
    mode = mode if mode in ENHANCE_MODES else "retouch"
    out = src.with_name(f"{slot_id}_{mode}_{uuid.uuid4().hex[:6]}.jpg")
    style = (_photos(p).get("style") or {})
    if demo_mode():
        job.say(f"  [демо] {ENHANCE_MODES[mode][0]}: простая цветокоррекция, $0")
        _demo_enhance(src, out)
    else:
        gen._check_limit(PHOTO_USD)
        fal = gen._fal()
        prompt = (f"{ENHANCE_MODES[mode][1]} Style of the website: {style.get('prompt_suffix_en', '')} "
                  f"Use: {s.get('subject_ru','')}. {extra}").strip()
        job.say(f"  {ENHANCE_MODES[mode][0]} для «{slot_id}» (Nano Banana 2, ~${PHOTO_USD:.2f})…")
        _fal_image(job, NB2_EDIT, {"prompt": prompt, "image_urls": [gen._upload(fal, src)], "aspect_ratio": s["aspect"],
                                   "resolution": "2K", "num_images": 1, "output_format": "jpeg"},
                   out, sid, f"site photo enhance {slot_id} {mode}")
    _add_variant(sid, slot_id, out.name, "enhanced", source=src.name)
    job.say(f"  готово: {out.name}")
    return {"file": out.name}


def choose_photo(sid, slot_id, file):
    def fn(p):
        for s in _photos(p)["slots"]:
            if s["id"] == slot_id:
                s["chosen"] = file or None
    return update(sid, fn)


def save_slot(sid, slot_id, data: dict):
    def fn(p):
        for s in _photos(p)["slots"]:
            if s["id"] == slot_id:
                for k in ("prompt_en", "alt_ru", "subject_ru"):
                    if k in data:
                        s[k] = data[k]
                if data.get("aspect") in ASPECTS:
                    s["aspect"] = data["aspect"]
    return update(sid, fn)


def assign_upload(sid, file, slot_id):
    def fn(p):
        for u in _photos(p).get("uploads", []):
            if u["file"] == file:
                u["slot"] = slot_id or None
    update(sid, fn)
    if slot_id:
        _add_variant(sid, slot_id, file, "upload")
    return load(sid)
