"""Пакет публикации ролика: тексты для VK Клипов, Telegram и YouTube Shorts, хэштеги и ссылки с UTM.

Ссылки с UTM собираются кодом (не ИИ), чтобы их нельзя было «придумать» с ошибкой:
по utm_campaign/utm_content на сайте видно, какой ролик привёл покупателя.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from . import store

PLATFORMS = {"vk": "VK Клипы", "telegram": "Telegram", "youtube": "YouTube Shorts"}

PACK_SCHEMA = {"type": "object", "properties": {
    "vk": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "telegram": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "youtube": {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
                "required": ["title", "description"]},
    "hashtags": {"type": "array", "items": {"type": "string"}},
    "cover_text": {"type": "string"}},
    "required": ["vk", "telegram", "youtube", "hashtags"]}


def utm_link(link: str, platform: str, product_id: str, video_file: str) -> str:
    if not link:
        return ""
    u = urlparse(link if "://" in link else "https://" + link)
    q = dict(parse_qsl(u.query))
    q.update({"utm_source": platform, "utm_medium": "video", "utm_campaign": product_id,
              "utm_content": Path(video_file).stem})
    return urlunparse(u._replace(query=urlencode(q)))


def build_pack(job, pid: str, video_file: str) -> dict:
    from . import brains, research
    p = store.load_product(pid)
    v = next((x for x in p["videos"] if x["file"] == video_file), None)
    if not v:
        raise ValueError("Ролик не найден")
    concept = next((c for c in p["concepts"] if c["id"] == v["concept"]), {})
    from . import niches
    c = niches.ctx(p.get("niche"))
    prompt = f"""Ты — SMM-редактор магазина. Ниша: {c['name']} — {c.get('description','')[:300]}. Тон: {c.get('tone','')}. Напиши тексты к короткому вертикальному ролику ({v.get('duration')} сек).
ИЗДЕЛИЕ: {p.get('name')} · цена {p.get('price') or 'не указана'} · промокод {p.get('promo') or 'нет'}
Описание: {p.get('description_ru','')[:1200]}
РОЛИК: {concept.get('title','')} — {concept.get('idea','')} · хук: {concept.get('hook','')}
ТРЕНДЫ НЕДЕЛИ: {research.active_brief_text(p.get('niche'), 900) or '(нет)'}
ПРОФИЛЬ ВКУСА: {store.taste_text(p.get('niche'))[:800] or '(нет)'}

Требования:
- vk.text: 2–4 коротких предложения, живо, без канцелярита; призыв перейти по ссылке; промокод, если есть. Ссылку НЕ пиши — её вставит система.
- telegram.text: чуть подробнее (до 600 знаков), можно 1–2 эмодзи, без ссылки.
- youtube.title: до 70 знаков, с ключевым словом (название товара, материал и т.п.), без кликбейта; youtube.description: 2–3 предложения без ссылки.
- hashtags: 5–8 штук на русском, без пробелов, со знаком #.
- cover_text: 2–4 слова для обложки.
- Не обещай того, чего нет в описании (скидок, сертификатов, сроков). Не упоминай ИИ и нейросети.
Пиши по-русски."""
    data, meta = brains.ask("publish", prompt, schema=PACK_SCHEMA, temperature=0.8, product=pid, job=job, timeout=400)
    tags = " ".join(t if t.startswith("#") else "#" + t for t in data.get("hashtags", [])[:8])
    links = {k: utm_link(p.get("link", ""), k, pid, video_file) for k in PLATFORMS}
    promo = f"\nПромокод: {p['promo']}" if p.get("promo") and p["promo"] not in (data.get("vk", {}).get("text", "")) else ""

    def compose(body, plat):
        parts = [body.strip() + promo]
        if links[plat]:
            parts.append(links[plat])
        if tags:
            parts.append(tags)
        return "\n\n".join(parts)

    pack = {
        "vk": compose(data["vk"]["text"], "vk"),
        "telegram": compose(data["telegram"]["text"], "telegram"),
        "youtube_title": data["youtube"]["title"][:100],
        "youtube": compose(data["youtube"]["description"], "youtube"),
        "cover_text": data.get("cover_text", ""),
        "links": links, "by": meta.get("provider"),
    }
    store.update_product(pid, lambda x: [vv.__setitem__("pack", pack) for vv in x["videos"] if vv["file"] == video_file])
    job.say("Тексты публикации готовы.")
    return pack
