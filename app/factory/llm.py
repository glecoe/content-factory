"""Промпты и функции «мозгов»: паспорт изделия, сценарист, контролёр, вкус. Gemini API-хелперы.
Какой провайдер (Claude по подписке или Gemini) отвечает за роль — решает brains.ask()."""
from __future__ import annotations
import json
import re
from pathlib import Path

from .config import settings, MODELS, DEFAULT_NEGATIVE, int_setting
from . import store


def _nc(product) -> dict:
    """Контекст ниши изделия."""
    from . import niches
    return niches.ctx((product or {}).get("niche"))


def _jw(product) -> bool:
    return _nc(product)["id"] == "jewelry"


def _neg(product) -> str:
    return DEFAULT_NEGATIVE if _jw(product) else _nc(product).get("negative_en") or DEFAULT_NEGATIVE


class LLMError(RuntimeError):
    pass


def gemini_hint(e) -> str:
    """Понятная подсказка к частым ошибкам Gemini."""
    msg = str(e)
    if "location is not supported" in msg or "FAILED_PRECONDITION" in msg:
        return (" — Google не пускает к Gemini API из этой страны. Включи VPN в режиме «для всей системы» "
                "(не только в браузере) и перезапусти start.command.")
    if "API_KEY_INVALID" in msg or "API key not valid" in msg:
        return " — ключ Gemini неверный: вставь новый в «Настройках»."
    return ""


def gemini_available() -> bool:
    return bool(settings().get("GEMINI_API_KEY"))


_CLIENT = {"key": None, "client": None}


def _client():
    """Один постоянный клиент: временный объект закрывается раньше, чем уходит запрос."""
    try:
        from google import genai
    except ImportError as e:
        raise LLMError("Не установлен пакет google-genai. Перезапусти start.command — он всё установит.") from e
    key = settings()["GEMINI_API_KEY"]
    if _CLIENT["client"] is None or _CLIENT["key"] != key:
        _CLIENT["client"] = genai.Client(api_key=key)
        _CLIENT["key"] = key
    return _CLIENT["client"]


def _img_part(path: Path):
    from google.genai import types
    return types.Part.from_bytes(data=Path(path).read_bytes(), mime_type="image/jpeg")


FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
RETRY_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded", "high demand", "500", "INTERNAL", "timed out")


def ask_gemini(parts, want_json=True, temperature=0.8):
    """Запрос к Gemini с повторами: при перегрузке ждём и пробуем снова, потом переходим на запасную модель."""
    if not gemini_available():
        raise LLMError("Нет ключа Gemini. Вставь его в «Настройках» или используй ручной режим.")
    import time
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=temperature,
                                      response_mime_type="application/json" if want_json else "text/plain")
    main = settings().get("GEMINI_MODEL") or "gemini-3.8-flash"
    models = [main] + [m for m in FALLBACK_MODELS if m != main]
    last_err = None
    for model in models:
        for attempt, wait in enumerate((0, 4, 10)):
            if wait:
                time.sleep(wait)
            try:
                client = _client()
                resp = client.models.generate_content(model=model, contents=parts, config=cfg)
            except Exception as e:
                last_err = e
                msg = str(e)
                if "404" in msg or "NOT_FOUND" in msg:
                    break                      # такой модели нет — сразу к следующей
                if any(m in msg for m in RETRY_MARKERS):
                    continue                   # перегрузка/лимит — подождать и повторить
                raise LLMError(f"Gemini вернул ошибку: {e}{gemini_hint(e)}") from e
            text = (resp.text or "").strip()
            usage = getattr(resp, "usage_metadata", None)
            tokens = ((getattr(usage, "prompt_token_count", 0) or 0, getattr(usage, "candidates_token_count", 0) or 0)
                      if usage else (0, 0))
            return (parse_json(text) if want_json else text), tokens
    raise LLMError(f"Gemini сейчас перегружен (пробовал модели: {', '.join(models)}). "
                   f"Подожди пару минут и нажми ещё раз. Последняя ошибка: {last_err}")


def parse_json(text: str):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start > 0:
        t = t[start:]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise LLMError(f"Не получилось прочитать JSON: {e}. Проверь, что вставлен ответ целиком.") from e


def _retrying(call):
    """Общий цикл повторов/запасных моделей Gemini для нестандартных запросов."""
    import time
    main = settings().get("GEMINI_MODEL") or "gemini-3.8-flash"
    models = [main] + [m for m in FALLBACK_MODELS if m != main]
    last = None
    for model in models:
        for wait in (0, 4, 10):
            if wait:
                time.sleep(wait)
            try:
                return call(model)
            except Exception as e:
                last = e
                msg = str(e)
                if "404" in msg or "NOT_FOUND" in msg:
                    break
                if any(m in msg for m in RETRY_MARKERS):
                    continue
                raise LLMError(f"Gemini вернул ошибку: {e}{gemini_hint(e)}") from e
    raise LLMError(f"Gemini перегружен, попробуй позже. Последняя ошибка: {last}")


def gemini_search(prompt: str):
    """Ответ Gemini с поиском Google. Возвращает текст и список источников в конце."""
    if not gemini_available():
        raise LLMError("Нет ключа Gemini.")
    from google.genai import types
    cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.4)

    def call(model):
        return _client().models.generate_content(model=model, contents=[prompt], config=cfg)
    resp = _retrying(call)
    text = (resp.text or "").strip()
    srcs = []
    try:
        gm = resp.candidates[0].grounding_metadata
        for ch in (gm.grounding_chunks or []):
            web = getattr(ch, "web", None)
            if web and web.uri:
                srcs.append(f"- {web.title or ''} {web.uri}")
    except Exception:
        pass
    if srcs:
        text += "\n\nИСТОЧНИКИ ПОИСКА:\n" + "\n".join(srcs[:20])
    usage = getattr(resp, "usage_metadata", None)
    tokens = (getattr(usage, "prompt_token_count", 0) or 0, getattr(usage, "candidates_token_count", 0) or 0) if usage else (0, 0)
    return text, tokens


def gemini_video(prompt: str, url: str | None = None, path: Path | None = None):
    """Разбор ролика: публичная ссылка YouTube или локальный файл. Возвращает JSON."""
    if not gemini_available():
        raise LLMError("Для разбора роликов нужен ключ Gemini.")
    import time
    from google.genai import types
    client = _client()
    if url:
        part = types.Part(file_data=types.FileData(file_uri=url))
    else:
        f = client.files.upload(file=str(path))
        for _ in range(60):
            if getattr(f.state, "name", str(f.state)) == "ACTIVE":
                break
            time.sleep(5)
            f = client.files.get(name=f.name)
        part = f
    cfg = types.GenerateContentConfig(temperature=0.3, response_mime_type="application/json")

    def call(model):
        return client.models.generate_content(model=model, contents=[part, prompt], config=cfg)
    resp = _retrying(call)
    return parse_json(resp.text or "")


# ---------------------------------------------------------------------------
# Паспорт изделия (реставратор-lite): русское описание + фото → визуальное описание на английском
# ---------------------------------------------------------------------------
PASSPORT_SCHEMA = {"type": "object", "properties": {
    "visual_en": {"type": "string"}, "metal": {"type": "string"}, "center_stone": {"type": "string"},
    "side_stones": {"type": "string"}, "band": {"type": "string"}, "risks": {"type": "array", "items": {"type": "string"}}},
    "required": ["visual_en"]}


def passport(product: dict, photo_paths):
    c = _nc(product)
    prompt = f"""You are a {c['product_en']} expert preparing a product passport for AI video generation (niche: {c['name']}).
Look at the photos and read the product description (Russian). Describe ONLY what is visible and matters for faithful reproduction.
Description: {product.get('description_ru','')}
Return JSON: {{
 "visual_en": "one dense English sentence for video prompts: {c['passport_en']}",
 "metal": "...", "center_stone": "...", "side_stones": "...", "band": "...",
 "risks": ["details a generative model is likely to distort"]
}}"""
    from . import brains
    return brains.ask("passport", prompt, images=list(photo_paths)[:4], schema=PASSPORT_SCHEMA, temperature=0.2,
                      product=product.get("id", ""))


# ---------------------------------------------------------------------------
# Сценарист
# ---------------------------------------------------------------------------
SHOT_RULES = """RULES FOR RING FIDELITY (most important):
- The ring is a rigid, unchanging object. Every prompt must restate the ring's exact look (use the passport sentence) and say that its geometry, stones, metal color and size on the finger stay identical to the source image/video.
- Minimal motion: slow wrist tilt ≤ 15°, slow push-in, light sweeps. No fast moves, no hand flips, no taking the ring off.
- One action per shot. Macro/close-up framing, shallow depth of field, focus locked on the center stone.
- Photorealistic luxury jewelry commercial look. No text, no logos in the video (text is added at montage).
- Kling edit prompts must refer to the source video as @Video1 and start with "Keep the ring and the hand movement exactly as in @Video1".
- Seedance reference prompts refer to photos as @Image1, @Image2… in the order of the listed sources."""


GENERIC_RULES = """RULES FOR PRODUCT FIDELITY (most important):
- The {p} is a rigid, unchanging object. Every prompt must restate its exact look (use the passport sentence) and say that its {fid} stay identical to the source image/video.
- Minimal motion: slow tilt ≤ 15°, slow push-in, light sweeps. No fast moves, no flips, no hiding the {p}.
- One action per shot. Close-up framing, shallow depth of field, focus locked on the key detail of the {p}.
- Photorealistic {look} look. No text, no logos in the video (text is added at montage).
- Kling edit prompts must refer to the source video as @Video1 and start with "Keep the {p} and the movement exactly as in @Video1".
- Seedance reference prompts refer to photos as @Image1, @Image2… in the order of the listed sources."""


def shot_rules(product) -> str:
    if _jw(product):
        return SHOT_RULES
    c = _nc(product)
    return GENERIC_RULES.format(p=c["product_en"], fid=c["fidelity_en"], look=c["look_en"])


def build_brief(product: dict, n_concepts=None) -> str:
    n_concepts = n_concepts or max(1, min(8, int_setting("CONCEPTS_N", 3)))
    from . import research
    c = _nc(product)
    jw = c["id"] == "jewelry"
    P, U = c["product_ru"], c["use_ru"]
    trends = research.active_brief_text(c["id"]) or "(ресёрч трендов ещё не запускался — опирайся на профиль вкуса и общие правила)"
    photos = product.get("photos", [])
    src_lines = [f"photo:{i+1} — {ph.get('label') or 'фото ' + ('кольца' if jw else 'товара')}" for i, ph in enumerate(photos)]
    if product.get("video"):
        src_lines.append("video — короткое видео " + ("кольца на руке" if jw else f"товара {U}") + " (для Kling edit)")
    models = "\n".join(f"- {k}: {m['title']}; needs {m['needs']}; durations {m['durations']}; ${m['usd_per_sec']}/sec; paths {','.join(m['paths'])}"
                       for k, m in MODELS.items())
    taste = store.taste_text(c["id"]).strip() or "(пока нет — это первые ролики)"
    types = TYPES_JW if jw else TYPES_GEN.format(p=P, u=U)
    struct = STRUCT_JW if jw else STRUCT_GEN.format(p=P, u=U)
    return f"""Ты — сценарист контент-завода рекламных роликов. Придумай {n_concepts} концепта коротких роликов 9:16 (10–15 секунд) для соцсетей.

{_niche_block(c)}

ИЗДЕЛИЕ
Название: {product.get('name','')}
Описание (RU): {product.get('description_ru','')}
Паспорт для промптов (EN): {product.get('visual_en') or '(нет — составь сам по описанию)'}
Цена: {product.get('price','')} · Промокод: {product.get('promo','')}

ИСТОЧНИКИ (что можно подать в модель)
{chr(10).join(src_lines) or '(нет файлов)'}

МОДЕЛИ
{models}

ТИПЫ КАДРОВ
{types}

ПРОФИЛЬ ВКУСА ВЛАДЕЛЬЦА
{taste}

ТРЕНДЫ НЕДЕЛИ (бриф ресёрчера)
{trends}

{shot_rules(product)}

ТРЕБОВАНИЯ
- СТРУКТУРА КАЖДОГО РОЛИКА — ровно 3 РАЗНЫХ кадра, потом монтажёр сам добавит финальную плашку:
{struct}
  Два кадра из фото должны использовать разные photo:N и разные движения камеры. Порядок кадров выбирай сам под хук.
- Около 70% концептов — по профилю вкуса, остальные — эксперимент (mode: "experiment"). Эксперименты строй на трендах недели.
- В поле trend укажи, какой тренд/хук из брифа использован (или пусто).
- Концепты должны заметно отличаться друг от друга: разные хуки, свет, фон, движение камеры.
- Промпты кадров — на английском, всё остальное — на русском.
- Бюджет: предпочитай kling_i2v/kling_edit; seedance только для самого сложного кадра.

Ответь ТОЛЬКО JSON без пояснений:
{{
 "visual_en": "паспорт товара одной фразой на английском",
 "concepts": [
  {{
   "title": "короткое название (RU)",
   "idea": "идея в 1–2 предложениях (RU)",
   "mode": "taste | experiment",
   "hook": "что происходит в первые 2 секунды (RU)",
   "music_mood": "настроение музыки (RU)",
   "trend": "какой тренд из брифа использован (RU) или пусто",
   "shots": [
    {{"type": "A|B|C|D", "model": "kling_i2v|kling_edit|keyframe_kling|seedance_i2v|seedance_ref|veo_i2v",
      "source": "photo:1 | video | photos", "duration": 5,
      "prompt": "English prompt", "negative_prompt": "English, optional", "keyframe_prompt": "English, только для keyframe_kling"}}
   ]
  }}
 ]
}}"""



TYPES_JW = """A — макро / вращение / игра света (photo → kling_i2v, seedance_i2v или veo_i2v)
B — кольцо на руке из видео сборщика (video → kling_edit) — самый надёжный для руки
C — кольцо на ИИ-модели (photos → keyframe_kling: сначала фотореалистичный ключевой кадр Nano Banana 2 по фото кольца, потом оживление Kling; или photos → seedance_ref). Для keyframe_kling заполни keyframe_prompt — описание стоп-кадра (EN).
D — атмосфера без кольца (photo → veo_i2v как настроение; используй редко)"""
TYPES_GEN = """A — крупный план / вращение / игра света на товаре ({p}) (photo → kling_i2v, seedance_i2v или veo_i2v)
B — товар {u} из видео сборщика (video → kling_edit) — самый надёжный кадр «в использовании»
C — товар {u} в ИИ-сцене (photos → keyframe_kling: сначала фотореалистичный ключевой кадр Nano Banana 2 по фото товара, потом оживление Kling; или photos → seedance_ref). Для keyframe_kling заполни keyframe_prompt — описание стоп-кадра (EN).
D — атмосфера без товара (photo → veo_i2v как настроение; используй редко)"""
STRUCT_JW = """  1) красивый кадр из ФОТО (тип A): макро кольца, например медленный наезд на центральный камень;
  2) второй красивый кадр из ДРУГОГО фото (тип A): другой ракурс и другое движение — облёт, проход света, отъезд;
  3) кольцо на руке (тип B из video через kling_edit; если видео нет — тип C из фото)."""
STRUCT_GEN = """  1) красивый кадр из ФОТО (тип A): крупный план товара ({p}), например медленный наезд на главную деталь;
  2) второй красивый кадр из ДРУГОГО фото (тип A): другой ракурс и другое движение — облёт, проход света, отъезд;
  3) товар {u} (тип B из video через kling_edit; если видео нет — тип C из фото)."""


def _niche_block(c) -> str:
    if c["id"] == "jewelry":
        return ""
    return (f"НИША: {c.get('name')}\nЧто продаём: {c.get('description','')}\nАудитория: {c.get('audience','')}\n"
            f"Тон: {c.get('tone','')}\nСтиль рекламы (EN): {c.get('look_en','')}\n")


# ---------------------------------------------------------------------------
# Шаблоны кадров и обязательная структура ролика: 2 кадра из фото + 1 на руке
# ---------------------------------------------------------------------------
def _ring(product):
    fallback = "the ring from the image" if _jw(product) else f"the {_nc(product)['product_en']} from the image"
    return (product.get("visual_en") or fallback).strip().rstrip(".")


PHOTO_MOVES = [
    ("slow macro push-in toward the center stone, focus locked on the stone",
     "Soft warm light slowly glides across the stones, tiny sparkles and glints on the metal."),
    ("slow elegant orbit of about 15 degrees around the ring, shallow depth of field",
     "A soft light sweep from left to right makes the stones sparkle; deep rich shadows."),
    ("slow pull-back revealing the whole ring on a soft ivory silk surface",
     "Warm evening light, gentle bokeh highlights in the background."),
]


GEN_MOVES = [
    ("slow close-up push-in toward the key detail, focus locked on it", "Soft warm light slowly glides across the surface."),
    ("slow elegant orbit of about 15 degrees around the product, shallow depth of field", "A soft light sweep from left to right; deep rich shadows."),
    ("slow pull-back revealing the whole product on a clean premium surface", "Soft natural light, gentle bokeh in the background."),
]


def photo_shot(product, photo_idx: int, move_idx: int) -> dict:
    if not _jw(product):
        c = _nc(product)
        move, light = GEN_MOVES[move_idx % len(GEN_MOVES)]
        item = _ring(product)
        prompt = (f"{c['look_en'].capitalize()}, close-up of {item}. Camera: {move}. {light} The {c['product_en']} is a rigid, "
                  f"unchanging object: its {c['fidelity_en']} stay exactly identical to the source image in every frame. "
                  f"Do not redraw, reshape or reinterpret it. Clean background, photorealistic, smooth motion, no text, no logo.")
        return {"type": "A", "model": "kling_i2v", "source": f"photo:{photo_idx}", "duration": 5,
                "prompt": prompt, "negative_prompt": _neg(product)}
    move, light = PHOTO_MOVES[move_idx % len(PHOTO_MOVES)]
    ring = _ring(product)
    prompt = (f"Luxury jewelry commercial, extreme close-up macro of {ring}. Camera: {move}. {light} "
              f"The ring is a rigid, unchanging object: its geometry, proportions, stones, stone color and metal color stay "
              f"exactly identical to the source image in every frame. Do not redraw, reshape or reinterpret the ring. "
              f"Elegant dark background, photorealistic, smooth motion, no text, no logo.")
    return {"type": "A", "model": "kling_i2v", "source": f"photo:{photo_idx}", "duration": 5,
            "prompt": prompt, "negative_prompt": DEFAULT_NEGATIVE}


def hand_shot(product) -> dict:
    if not _jw(product):
        c = _nc(product)
        item = _ring(product)
        if product.get("video"):
            prompt = (f"Keep the {c['product_en']} and the movement exactly as in @Video1. Do not change the {c['product_en']} in any way: "
                      f"{item} keeps the same {c['fidelity_en']}. Change only: the scene becomes premium and clean, soft flattering "
                      f"light, tidy background with gentle bokeh, people look well-groomed. Photorealistic {c['look_en']}.")
            return {"type": "B", "model": "kling_edit", "source": "video", "duration": 5, "prompt": prompt,
                    "negative_prompt": _neg(product)}
        prompt = (f"{c['model_en'].capitalize()}, with {item} {c['use_en']}, the exact {c['product_en']} from @Image1 — identical "
                  f"{c['fidelity_en']}. Minimal slow movement toward the camera. Static camera, shallow depth of field, soft light. "
                  f"Photorealistic {c['look_en']}.")
        return {"type": "C", "model": "seedance_ref", "source": "photos", "duration": 5, "prompt": prompt,
                "negative_prompt": _neg(product)}
    ring = _ring(product)
    if product.get("video"):
        prompt = (f"Keep the ring and the hand movement exactly as in @Video1. Do not change the ring in any way: {ring} keeps the "
                  f"same shape, stones, metal color and size on the finger. Change only: skin becomes smooth and well-groomed, "
                  f"nails get an elegant nude manicure, background becomes a soft warm blurred evening interior with bokeh lights, "
                  f"lighting becomes a warm soft key light from the left that makes the stones sparkle. Photorealistic luxury jewelry commercial.")
        return {"type": "B", "model": "kling_edit", "source": "video", "duration": 5, "prompt": prompt,
                "negative_prompt": DEFAULT_NEGATIVE}
    prompt = (f"A woman's hand with elegant nude manicure wearing {ring} on the ring finger, the exact ring from @Image1. "
              f"The ring is an exact copy of the references: identical geometry, stones, colors and size on the finger. "
              f"The hand slowly tilts toward the camera, minimal movement. Static macro camera, shallow depth of field, "
              f"soft warm light, sparkling stones, warm bokeh background. Photorealistic luxury jewelry commercial.")
    return {"type": "C", "model": "seedance_ref", "source": "photos", "duration": 5, "prompt": prompt,
            "negative_prompt": DEFAULT_NEGATIVE}


def keyframe_default(product) -> str:
    if not _jw(product):
        c = _nc(product)
        return (f"Photorealistic vertical 9:16 advertising photo ({c['look_en']}): {c['model_en']}, with {_ring(product)} "
                f"{c['use_en']} — the exact {c['product_en']} from the reference photos, identical {c['fidelity_en']}. "
                f"Soft flattering light, shallow depth of field, clean premium background. No text.")
    return (f"Photorealistic vertical 9:16 luxury jewelry advertising photo: close-up of a young woman's elegant hand with "
            f"a nude manicure, wearing {_ring(product)} on the ring finger — the exact ring from the reference photos, "
            f"identical geometry, stones, colors and proportions, realistic size on the finger. Soft warm key light, "
            f"sparkling stones, shallow depth of field, warm bokeh background, natural skin texture. No text.")


def _is_hand(sh):
    return sh["type"] in ("B", "C") or sh["model"] in ("kling_edit", "seedance_ref", "keyframe_kling")


def enforce_structure(shots: list, product: dict) -> list:
    """Ровно 3 разных кадра: 2 красивых кадра из разных фото + 1 кольцо на руке."""
    n_photos = max(len(product.get("photos", [])), 1)
    photo = [s for s in shots if not _is_hand(s) and str(s["source"]).startswith("photo:")]
    hand = [s for s in shots if _is_hand(s)]
    # два кадра из фото, по возможности из разных фото
    used, fixed = set(), []
    for s in photo:
        if len(fixed) == 2:
            break
        idx = int(s["source"].split(":")[1])
        if idx in used and n_photos > len(used):
            idx = next(i for i in range(1, n_photos + 1) if i not in used)
            s = dict(s, source=f"photo:{idx}")
        used.add(idx)
        fixed.append(dict(s, type="A"))
    move = 0
    while len(fixed) < 2:
        free = [i for i in range(1, n_photos + 1) if i not in used] or [1]
        used.add(free[0])
        fixed.append(photo_shot(product, free[0], move + len(fixed)))
        move += 1
    # кадр на руке: что выбрал сценарист (видео сборщика или ИИ-модель); если ничего — из видео, а без видео — ИИ-модель
    h = hand[0] if hand else hand_shot(product)
    # порядок: сохраняем исходный, если сценарист поставил руку первой (хук)
    hand_first = bool(shots) and _is_hand(shots[0])
    return [h] + fixed if hand_first else [fixed[0], h, fixed[1]]


def template_concept(product: dict, n: int = 1) -> dict:
    """Концепт по шаблону — работает без Gemini."""
    photos = max(len(product.get("photos", [])), 1)
    a1 = photo_shot(product, 1, n - 1)
    a2 = photo_shot(product, 2 if photos > 1 else 1, n)
    jw = _jw(product)
    u = _nc(product)["use_ru"]
    return {"title": f"Шаблон: макро + {'рука' if jw else u} + ракурс #{n}",
            "idea": ("Два красивых кадра из фото и кольцо на руке" if jw else f"Два красивых кадра из фото и товар {u}") +
                    ", в конце плашка с ценой и промокодом.",
            "mode": "taste", "hook": "Медленный наезд на камень" if jw else "Медленный наезд на главную деталь",
            "music_mood": "спокойная дорогая музыка",
            "shots": [a1, hand_shot(product), a2]}

def normalize_concepts(data: dict, product: dict) -> dict:
    """Validate/clean scenario JSON (from Gemini or pasted by hand)."""
    if isinstance(data, list):
        data = {"concepts": data}
    concepts = []
    has_video = bool(product.get("video"))
    n_photos = len(product.get("photos", []))
    for i, c in enumerate(data.get("concepts", [])):
        shots = []
        for s in c.get("shots", []):
            model = s.get("model") if s.get("model") in MODELS else "kling_i2v"
            src = str(s.get("source") or "photo:1")
            if model == "kling_edit" and not has_video:
                model, src = "kling_i2v", "photo:1"
            if MODELS[model]["needs"] == "photo" and not src.startswith("photo:"):
                src = "photo:1"
            if src.startswith("photo:"):
                try:
                    k = int(src.split(":")[1])
                except ValueError:
                    k = 1
                src = f"photo:{min(max(k,1), max(n_photos,1))}"
            if MODELS[model]["needs"] == "photos":
                src = "photos"
            if MODELS[model]["needs"] == "video":
                src = "video"
            dur = s.get("duration") or 5
            allowed = MODELS[model]["durations"]
            dur = min(allowed, key=lambda d: abs(d - float(dur)))
            prompt = (s.get("prompt") or "").strip()
            if model == "kling_edit" and "@Video1" not in prompt:
                prompt = ("Keep the ring and the hand movement exactly as in @Video1. " if _jw(product) else
                          f"Keep the {_nc(product)['product_en']} and the movement exactly as in @Video1. ") + prompt
            sh = {"type": s.get("type", "A"), "model": model, "source": src, "duration": dur,
                  "prompt": prompt, "negative_prompt": s.get("negative_prompt") or _neg(product)}
            if model == "keyframe_kling":
                sh["keyframe_prompt"] = (s.get("keyframe_prompt") or "").strip() or keyframe_default(product)
            shots.append(sh)
        shots = enforce_structure(shots, product)
        if shots:
            concepts.append({"id": f"c{i+1}", "title": c.get("title", f"Концепт {i+1}"), "idea": c.get("idea", ""),
                             "mode": c.get("mode", "taste"), "hook": c.get("hook", ""),
                             "music_mood": c.get("music_mood", ""), "trend": c.get("trend", ""), "shots": shots})
    if not concepts:
        raise LLMError("В ответе нет ни одного концепта с кадрами.")
    return {"visual_en": data.get("visual_en", ""), "concepts": concepts}


SHOT_SCHEMA = {"type": "object", "properties": {
    "type": {"type": "string", "enum": ["A", "B", "C", "D"]},
    "model": {"type": "string", "enum": list(MODELS)},
    "source": {"type": "string"}, "duration": {"type": "number"},
    "prompt": {"type": "string"}, "negative_prompt": {"type": "string"}, "keyframe_prompt": {"type": "string"}},
    "required": ["type", "model", "source", "duration", "prompt"]}
SCENARIO_SCHEMA = {"type": "object", "properties": {
    "visual_en": {"type": "string"},
    "concepts": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "idea": {"type": "string"}, "mode": {"type": "string", "enum": ["taste", "experiment"]},
        "hook": {"type": "string"}, "music_mood": {"type": "string"}, "trend": {"type": "string"},
        "shots": {"type": "array", "items": SHOT_SCHEMA}},
        "required": ["title", "idea", "mode", "hook", "shots"]}}},
    "required": ["concepts"]}


def scenario_auto(product: dict, photo_paths, job=None, n_concepts=None):  # noqa: D401
    from . import brains
    brief = build_brief(product, n_concepts)
    data, meta = brains.ask("scenario", brief, images=list(photo_paths)[:4], schema=SCENARIO_SCHEMA,
                            temperature=0.9, product=product.get("id", ""), job=job)
    return normalize_concepts(data, product), meta


# ---------------------------------------------------------------------------
# Контролёр качества
# ---------------------------------------------------------------------------
QA_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["ok", "reject"]}, "score": {"type": "number"},
    "issues_ru": {"type": "array", "items": {"type": "string"}}, "summary_ru": {"type": "string"}},
    "required": ["verdict", "score", "summary_ru"]}


def qa_available() -> bool:
    if gemini_available():
        return True
    from . import brains
    return brains.claude_available()


def qa_clip(product: dict, ref_photos, frames):
    if not _jw(product):
        c = _nc(product)
        prompt = f"""You are a strict product QA inspector. The first {len(ref_photos)} images are REFERENCE photos of the real {c['product_en']}.
The next {len(frames)} images are frames from an AI-generated video that must show exactly the same {c['product_en']}.
Product passport: {product.get('visual_en') or product.get('description_ru','')}
Check: 1) {c['fidelity_en']} identical to the reference, 2) no extra or missing parts, labels not warped, 3) realistic scale and use ({c['use_en']}), 4) people/hands anatomy if present, 5) artifacts/flicker/text.
Return JSON: {{"verdict": "ok" | "reject", "score": 0-100, "issues_ru": ["короткие причины на русском"], "summary_ru": "одна фраза"}}"""
    else:
        prompt = f"""You are a strict jewelry QA inspector. The first {len(ref_photos)} images are REFERENCE photos of the real ring.
The next {len(frames)} images are frames from an AI-generated video that must show exactly the same ring.
Ring passport: {product.get('visual_en') or product.get('description_ru','')}
Check: 1) ring shape/proportions, 2) center stone shape, size and color, 3) side stones (halo/pavé) present and small, 4) metal color, 5) ring size relative to finger, 6) hand anatomy (five natural fingers), 7) artifacts/flicker/text.
Return JSON: {{"verdict": "ok" | "reject", "score": 0-100, "issues_ru": ["короткие причины на русском"], "summary_ru": "одна фраза"}}"""
    if gemini_available():
        parts = [prompt] + [_img_part(p) for p in ref_photos[:3]] + [_img_part(f) for f in frames]
        return ask_gemini(parts, temperature=0.1)
    from . import brains
    if brains.claude_available():
        data, meta = brains.ask_claude(prompt + "\nПервые файлы — эталон, последние — кадры ролика.",
                                       images=list(ref_photos[:3]) + list(frames), schema=QA_SCHEMA)
        return data, (0, 0)
    raise LLMError("Для проверки кадров нужен Gemini или Claude.")


# ---------------------------------------------------------------------------
# Профиль вкуса
# ---------------------------------------------------------------------------
def taste_update(rows, current: str, niche: str | None = None):
    from . import niches
    prompt = f"""Ты ведёшь профиль вкуса владельца контент-завода рекламных роликов. Ниша: {niches.ctx(niche).get('name')}.
Текущий профиль:
{current or '(пусто)'}

Новые оценки (like=true — понравилось), с концептом, тегами и комментарием:
{json.dumps(rows, ensure_ascii=False, indent=1)[:12000]}

Обнови профиль: 5–12 коротких пунктов на русском — что нравится, что не нравится (свет, темп, хук, кадры, музыка, модели, типы кадров), и 1–2 гипотезы для экспериментов. Пиши конкретно. Верни только текст профиля."""
    from . import brains
    text, meta = brains.ask("taste", prompt, temperature=0.4)
    return text, meta


def taste_fallback(rows) -> str:
    likes = [r for r in rows if r.get("like")]
    dislikes = [r for r in rows if r.get("like") is False]
    lines = ["# Профиль вкуса (собран без ИИ)", ""]
    if likes:
        lines.append("Нравится:")
        lines += [f"- {r.get('concept_title','')}: {r.get('comment','')} {' '.join('#'+t for t in r.get('tags', []))}".strip() for r in likes[-10:]]
    if dislikes:
        lines.append("")
        lines.append("Не нравится:")
        lines += [f"- {r.get('concept_title','')}: {r.get('comment','')} {' '.join('#'+t for t in r.get('tags', []))}".strip() for r in dislikes[-10:]]
    return "\n".join(lines)
