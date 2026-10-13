"""Агент ресёрча трендов.

Шаги одного прогона:
 1. Поиск в интернете: Claude (WebSearch/WebFetch, по подписке) или Gemini с поиском Google.
 2. Разбор роликов-референсов: ссылки YouTube/Shorts и загруженные видео → Gemini смотрит видео.
 3. (по желанию) Apify: любые акторы-сборщики (TikTok Creative Center, Pinterest Trends…) с твоим токеном.
 4. Синтез: из всего этого — бриф недели, который получает сценарист.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import RESEARCH, settings
from . import store

# Всё хранится внутри ниши: data/niches/<id>/research/
def _paths(nid):
    from . import niches
    d = niches.research_dir(niches.resolve(nid))
    return {"config": d / "config.json", "breakdowns": d / "breakdowns.json", "briefs": d / "briefs",
            "refs": d / "refs", "active": d / "active.txt"}

DEFAULT_CONFIG = {
    "niche": "Ювелирные украшения: кольца с драгоценными камнями (изумруд, бриллианты), золото 585. Продажа через свой интернет-магазин.",
    "audience": "Женщины 25–45 лет, покупают себе и в подарок; мужчины, выбирающие подарок/помолвку.",
    "markets": "Россия и СНГ",
    "platforms": "VK Клипы, YouTube Shorts, Telegram, TikTok, Pinterest, Instagram Reels (как источник трендов)",
    "competitors": "SUNLIGHT\nSOKOLOV\n585*ЗОЛОТОЙ\nPandora\nTiffany & Co.\nCartier",
    "keywords": "кольцо с изумрудом, помолвочное кольцо, jewelry reels, ring macro video, stacking rings, quiet luxury jewelry",
    "reference_links": "",
    "apify_tasks": [],
}

WEB_SCHEMA = {"type": "object", "properties": {
    "trends": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "evidence": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}},
        "required": ["name", "evidence"]}},
    "formats": {"type": "array", "items": {"type": "string"}},
    "hooks": {"type": "array", "items": {"type": "string"}},
    "visual_styles": {"type": "array", "items": {"type": "string"}},
    "music": {"type": "array", "items": {"type": "string"}},
    "competitors": {"type": "array", "items": {"type": "object", "properties": {
        "name": {"type": "string"}, "observation": {"type": "string"}, "source": {"type": "string"}}, "required": ["name", "observation"]}},
    "sources": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "url": {"type": "string"}}, "required": ["url"]}}},
    "required": ["trends", "hooks"]}

BREAKDOWN_SCHEMA_TEXT = """{
 "title": "о чём ролик (RU)",
 "hook": "что происходит в первые 1–2 секунды и почему не пролистывают (RU)",
 "shots": [{"t": "0–2с", "what": "что в кадре (RU)", "camera": "движение камеры", "light": "свет"}],
 "pace": "темп монтажа, число склеек (RU)",
 "text_on_screen": "текст в кадре (RU) или пусто",
 "music": "музыка/звук (RU)",
 "why_it_works": "почему ролик работает (RU)",
 "ideas_for_us": ["что взять для роликов колец (RU)"]
}"""

BRIEF_SCHEMA = {"type": "object", "properties": {
    "summary_ru": {"type": "string"},
    "top_trends": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "why": {"type": "string"}, "how_to_use": {"type": "string"}}, "required": ["title", "how_to_use"]}},
    "hooks": {"type": "array", "items": {"type": "string"}},
    "shot_ideas": {"type": "array", "items": {"type": "object", "properties": {
        "type": {"type": "string"}, "idea_en": {"type": "string"}, "why": {"type": "string"}}, "required": ["idea_en"]}},
    "visual": {"type": "object", "properties": {
        "light": {"type": "string"}, "colors": {"type": "string"}, "backgrounds": {"type": "string"}}},
    "music_moods": {"type": "array", "items": {"type": "string"}},
    "do": {"type": "array", "items": {"type": "string"}},
    "dont": {"type": "array", "items": {"type": "string"}},
    "experiments": {"type": "array", "items": {"type": "string"}},
    "sources": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "url": {"type": "string"}}, "required": ["url"]}}},
    "required": ["summary_ru", "top_trends", "hooks", "shot_ideas", "do", "dont"]}


# ----------------------------------------------------------------------------- конфиг и хранилище
def load_config(nid=None) -> dict:
    from . import niches
    nid = niches.resolve(nid)
    f = _paths(nid)["config"]
    base = dict(DEFAULT_CONFIG)
    if nid != "jewelry":        # для новых ниш — из контекста ниши
        n = niches.ctx(nid)
        base.update({"niche": n.get("description") or n.get("name"), "audience": n.get("audience", ""),
                     "markets": n.get("markets", ""), "competitors": "", "keywords": ""})
    if f.exists():
        try:
            base.update(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    base["_nid"] = nid
    return base


def save_config(nid, c: dict) -> dict:
    cur = load_config(nid)
    for k in DEFAULT_CONFIG:
        if k in c:
            cur[k] = c[k]
    if isinstance(cur.get("apify_tasks"), str):
        try:
            cur["apify_tasks"] = json.loads(cur["apify_tasks"] or "[]")
        except json.JSONDecodeError as e:
            raise ValueError(f"Задачи Apify — неверный JSON: {e}")
    _paths(nid)["config"].write_text(json.dumps({k: v for k, v in cur.items() if k != "_nid"}, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return cur


def _breakdowns(nid=None) -> dict:
    f = _paths(nid)["breakdowns"]
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_breakdowns(nid, b):
    _paths(nid)["breakdowns"].write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")


def list_refs(nid=None):
    return sorted([p.name for p in _paths(nid)["refs"].iterdir() if p.suffix.lower() in (".mp4", ".mov", ".m4v", ".webm")])


REF_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def add_ref(nid, filename: str, data: bytes) -> str:
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-") or "ref.mp4"
    if Path(safe).suffix.lower() not in REF_EXT or safe.startswith("."):
        raise ValueError("Референс — только видео: mp4, mov, m4v или webm.")
    if not data:
        raise ValueError("Пустой файл")
    out = _paths(nid)["refs"] / f"{int(time.time())}_{safe}"
    out.write_bytes(data)
    return out.name


def list_briefs(nid=None):
    out = []
    for f in sorted(_paths(nid)["briefs"].glob("*.json"), reverse=True):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": f.stem, "created": b.get("created"), "summary": (b.get("brief") or {}).get("summary_ru", "")[:240]})
        except Exception:
            pass
    return out


def load_brief(nid, bid: str) -> dict:
    if not bid.replace("_", "").replace("-", "").isalnum():
        raise ValueError("bad brief id")
    return json.loads((_paths(nid)["briefs"] / f"{bid}.json").read_text(encoding="utf-8"))


def active_id(nid=None) -> str:
    P = _paths(nid)
    if P["active"].exists():
        v = P["active"].read_text().strip()
        if (P["briefs"] / f"{v}.json").exists():
            return v
    b = list_briefs(nid)
    return b[0]["id"] if b else ""


def set_active(nid, bid: str):
    load_brief(nid, bid)
    _paths(nid)["active"].write_text(bid)


def active_brief_text(nid=None, max_chars=3500) -> str:
    bid = active_id(nid)
    if not bid:
        return ""
    b = load_brief(nid, bid).get("brief") or {}
    lines = [f"Бриф от {bid}: {b.get('summary_ru','')}"]
    if b.get("top_trends"):
        lines.append("Тренды: " + "; ".join(f"{t.get('title')} — {t.get('how_to_use','')}" for t in b["top_trends"][:6]))
    if b.get("hooks"):
        lines.append("Хуки: " + "; ".join(b["hooks"][:6]))
    if b.get("shot_ideas"):
        lines.append("Идеи кадров: " + "; ".join(f"[{s.get('type','')}] {s.get('idea_en','')}" for s in b["shot_ideas"][:6]))
    v = b.get("visual") or {}
    if v:
        lines.append(f"Свет: {v.get('light','')}. Цвета: {v.get('colors','')}. Фоны: {v.get('backgrounds','')}.")
    if b.get("music_moods"):
        lines.append("Музыка: " + "; ".join(b["music_moods"][:5]))
    if b.get("do"):
        lines.append("Делать: " + "; ".join(b["do"][:6]))
    if b.get("dont"):
        lines.append("Не делать: " + "; ".join(b["dont"][:6]))
    if b.get("experiments"):
        lines.append("Эксперименты: " + "; ".join(b["experiments"][:4]))
    return "\n".join(lines)[:max_chars]


# ----------------------------------------------------------------------------- шаги
def web_scan(job, cfg) -> dict:
    from . import brains
    today = datetime.now().strftime("%d.%m.%Y")
    prompt = f"""Сегодня {today}. Ты — ресёрчер трендов коротких видео для бренда этой ниши.
Ниша: {cfg['niche']}
Аудитория: {cfg['audience']}
Рынки: {cfg['markets']}
Площадки: {cfg['platforms']}
Конкуренты (посмотри, что они публикуют и рекламируют): {cfg['competitors'].replace(chr(10), ', ')}
Ключевые слова: {cfg['keywords']}

Найди в интернете (поиск + чтение страниц), что СЕЙЧАС (последние 30–60 дней) работает в коротких вертикальных роликах и рекламе товаров этой ниши:
- визуальные тренды (свет, фоны, цвета металла и камней, стилистика: quiet luxury, macro, ASMR и т.п.);
- форматы роликов и хуки первых 2 секунд;
- что делают конкуренты в соцсетях и рекламе;
- музыка/звук;
- сезонные поводы на ближайший месяц (праздники, распродажи, помолвки).
Опирайся на свежие источники (статьи о трендах, отчёты площадок, библиотеки рекламы, Pinterest Trends, TikTok Creative Center, посты брендов).
Для каждого тренда укажи доказательство и ссылки. Не выдумывай: если данных нет — так и пиши.
Ответ — JSON со структурой: trends[{{name, evidence, sources[]}}], formats[], hooks[], visual_styles[], music[], competitors[{{name, observation, source}}], sources[{{title, url}}]."""
    data, meta = brains.ask("research", prompt, schema=WEB_SCHEMA, web=True, job=job, timeout=1500)
    job.say(f"  интернет: трендов {len(data.get('trends', []))}, источников {len(data.get('sources', []))} ({meta.get('provider')})")
    return data


def breakdown_refs(job, cfg, items=None, force=False) -> list:
    from . import llm
    nid = cfg.get("_nid")
    cache = _breakdowns(nid)
    out = []
    if items is None:
        links = [l.strip() for l in (cfg.get("reference_links") or "").splitlines() if l.strip().startswith("http")]
        items = [("url", l) for l in links] + [("file", f) for f in list_refs(nid)]
    if items and not llm.gemini_available():
        job.say("  разбор роликов пропущен: нужен ключ Gemini (он смотрит видео)")
        return []
    prompt = (f"Ты разбираешь короткий рекламный/контентный ролик для бренда. Ниша: {cfg.get('niche','')}. Посмотри видео целиком и верни JSON:\n"
              + BREAKDOWN_SCHEMA_TEXT)
    for kind, ref in items:
        key = ref if kind == "url" else "file:" + ref
        if key in cache and not force:
            out.append(cache[key])
            continue
        try:
            job.say(f"  смотрю ролик: {ref[:80]}")
            if kind == "url":
                if "youtu" not in ref:
                    job.say("    пропуск: напрямую Gemini смотрит только YouTube; ролики TikTok/Instagram скачай и загрузи файлом")
                    continue
                res = llm.gemini_video(prompt, url=ref)
            else:
                res = llm.gemini_video(prompt, path=_paths(nid)["refs"] / ref)
            res["ref"] = ref
            res["analyzed"] = datetime.now().isoformat(timespec="seconds")
            cache[key] = res
            _save_breakdowns(nid, cache)
            out.append(res)
        except Exception as e:
            job.say(f"    не получилось: {str(e)[:200]}")
    job.say(f"  разобрано роликов: {len(out)}")
    return out


# поля, которые реально нужны для анализа трендов (TikTok, Instagram, YouTube, Pinterest и т.п.)
_KEEP = {"text", "caption", "title", "description", "desc", "url", "webVideoUrl", "inputUrl", "link",
         "playCount", "videoPlayCount", "videoViewCount", "viewCount", "views", "diggCount", "likesCount", "likes",
         "commentCount", "commentsCount", "shareCount", "sharesCount", "collectCount", "saveCount",
         "createTimeISO", "timestamp", "date", "uploadDate", "hashtags", "name", "musicMeta", "musicName",
         "musicAuthor", "musicInfo", "song_name", "artist_name", "videoMeta", "duration", "authorMeta",
         "ownerUsername", "channelName", "type", "productType", "searchHashtag", "query"}
_VIEWS = ("playCount", "videoPlayCount", "videoViewCount", "viewCount", "views", "diggCount", "likesCount")


def _compact(v, depth=0):
    if isinstance(v, dict):
        out = {k: _compact(x, depth + 1) for k, x in v.items() if k in _KEEP and x not in (None, "", [], {})}
        return out
    if isinstance(v, list):
        return [_compact(x, depth + 1) for x in v[:12]]
    if isinstance(v, str):
        return v[:280]
    return v


def _popularity(item):
    for k in _VIEWS:
        try:
            if item.get(k):
                return float(item[k])
        except (TypeError, ValueError):
            pass
    return 0.0


def compact_items(items, top=30):
    """Сжать выдачу актора: только важные поля, самые популярные сверху."""
    rows = [i for i in items if isinstance(i, dict)]
    rows.sort(key=_popularity, reverse=True)
    return [_compact(i) for i in rows[:top]]


def run_apify(job, cfg) -> list:
    token = settings().get("APIFY_TOKEN", "").strip()
    tasks = cfg.get("apify_tasks") or []
    if not token or not tasks:
        return []
    results = []
    for t in tasks:
        actor = str(t.get("actor", "")).strip().replace("/", "~")
        if not actor:
            continue
        job.say(f"  Apify: {t.get('name') or actor}")
        url = (f"https://api.apify.com/v2/acts/{urllib.parse.quote(actor, safe='~')}/run-sync-get-dataset-items"
               f"?timeout=240&maxItems={int(t.get('max_items', 50))}&format=json")
        req = urllib.request.Request(url, data=json.dumps(t.get("input") or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                items = json.loads(r.read().decode("utf-8", "ignore"))
            if isinstance(items, dict) and items.get("error"):
                raise RuntimeError(items["error"].get("message") or items["error"])
            results.append({"task": t.get("name") or actor, "items": compact_items(items)})
            job.say(f"    получено записей: {len(items)}, в бриф идут {min(len(items), 30)} самых популярных")
        except Exception as e:
            job.say(f"    ошибка Apify: {str(e)[:200]}")
    return results


def synthesize(job, cfg, web, breakdowns, apify) -> dict:
    from . import brains
    nid = cfg.get("_nid")
    prev = active_brief_text(nid, 1500)
    apify_txt = json.dumps(apify, ensure_ascii=False)[:30000] if apify else "(нет)"
    prompt = f"""Ты — креативный стратег контент-завода рекламных роликов. Собери БРИФ НЕДЕЛИ для сценариста.
Ниша: {cfg['niche']}
Аудитория: {cfg['audience']}

ПРОФИЛЬ ВКУСА ВЛАДЕЛЬЦА (учитывай, но 30% роликов — эксперименты по трендам):
{store.taste_text(nid)[:2500] or '(пусто)'}

ПРЕДЫДУЩИЙ БРИФ (не повторяй дословно, отметь, что изменилось):
{prev or '(нет)'}

РЕЗУЛЬТАТЫ ПОИСКА В ИНТЕРНЕТЕ:
{json.dumps(web, ensure_ascii=False)[:14000]}

РАЗБОРЫ РОЛИКОВ-РЕФЕРЕНСОВ:
{json.dumps(breakdowns, ensure_ascii=False)[:14000] or '(нет)'}

ДАННЫЕ СБОРЩИКОВ (Apify: реальные ролики из соцсетей, отсортированы по просмотрам — ищи в них повторяющиеся приёмы, хуки, музыку, длительность):
{apify_txt}

ОГРАНИЧЕНИЯ ПРОИЗВОДСТВА: ролики 10–15 сек, 3 кадра (2 из фото товара + товар в использовании), движения медленные, товар нельзя искажать; текст только на финальной плашке.
Сделай бриф практичным: каждый тренд — с тем, как применить его в наших 3 кадрах. shot_ideas пиши как готовые описания кадров на английском (тип A/B/C/D).
Ответ — JSON: summary_ru, top_trends[{{title, why, how_to_use}}], hooks[], shot_ideas[{{type, idea_en, why}}], visual{{light, colors, backgrounds}}, music_moods[], do[], dont[], experiments[], sources[{{title, url}}]."""
    data, meta = brains.ask("research", prompt, schema=BRIEF_SCHEMA, job=job, timeout=900)
    return data


def run(job, nid=None):
    cfg = load_config(nid)
    nid = cfg["_nid"]
    job.say("Шаг 1/4 · поиск трендов в интернете")
    try:
        web = web_scan(job, cfg)
    except Exception as e:
        job.say(f"  поиск не удался: {str(e)[:300]}")
        web = {}
    job.progress = 0.35
    job.say("Шаг 2/4 · разбор роликов-референсов")
    bds = breakdown_refs(job, cfg)
    job.progress = 0.6
    job.say("Шаг 3/4 · сборщики данных (Apify)")
    apify = run_apify(job, cfg)
    if not apify:
        job.say("  пропуск: токен или задачи Apify не заданы")
    job.progress = 0.75
    if not web and not bds and not apify:
        raise RuntimeError("Нет ни одного источника данных: проверь Claude/Gemini в «Настройках».")
    job.say("Шаг 4/4 · синтез брифа недели")
    brief = synthesize(job, cfg, web, bds, apify)
    bid = datetime.now().strftime("%Y-%m-%d_%H%M")
    _paths(nid)["briefs"].joinpath(f"{bid}.json").write_text(json.dumps({
        "created": datetime.now().isoformat(timespec="seconds"), "config": cfg,
        "web": web, "breakdowns": bds, "apify": [{"task": a["task"], "n": len(a["items"])} for a in apify],
        "brief": brief}, ensure_ascii=False, indent=2), encoding="utf-8")
    set_active(nid, bid)
    job.say(f"Бриф {bid} готов и стал активным: его получит сценарист.")
    return {"brief": bid}


def analyze_one(job, nid, ref: str, kind: str = "url"):
    """Разобрать один ролик по кнопке (ссылка YouTube или загруженный файл)."""
    res = breakdown_refs(job, load_config(nid), items=[(kind, ref)], force=True)
    if not res:
        raise RuntimeError("Ролик не разобран — подробности выше в журнале.")
    return {"breakdowns": len(res)}


def delete_ref(nid, name: str):
    f = _paths(nid)["refs"] / Path(str(name)).name
    if Path(str(name)).name in ("", ".", "..") :
        raise ValueError("bad name")
    if f.is_file():
        f.unlink()
    b = _breakdowns(nid)
    b.pop("file:" + Path(name).name, None)
    _save_breakdowns(nid, b)


def all_breakdowns(nid=None):
    return list(_breakdowns(nid).values())[::-1]
