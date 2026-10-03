"""Генератор видео: fal.ai (платно) или демо-режим (бесплатно, FFmpeg из фото).

Что нового:
- вертикальная подготовка: квадратное/горизонтальное фото до генерации превращается в кадр 9:16
  (Nano Banana 2 дорисовывает фон или FFmpeg кладёт фото на размытый фон) — иначе Kling отдаёт квадрат,
  и при монтаже под телефон обрезаются бока;
- keyframe_kling: сначала Nano Banana 2 делает фотореалистичный стоп-кадр «кольцо на руке модели»
  по фото изделия, потом Kling оживляет его.
"""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path

from .config import MODELS, clip_cost, demo_mode, settings, NB2_EDIT, NB2_USD
from . import store, media


class GenError(RuntimeError):
    pass


# модели, которые берут один стартовый кадр и отдают видео в его пропорциях
PHOTO_START_MODELS = {"kling_i2v", "seedance_i2v", "veo_i2v"}
VERTICAL_PROMPT = (
    "Extend this jewelry photo to a vertical 9:16 frame. Keep the ring, the stones, the metal, the lighting and the "
    "camera angle exactly as they are — do not redraw, move or resize the ring. Only extend the background naturally "
    "above and below in the same style, colors and lighting. Photorealistic, no text, no logo.")


def prep_cost(shot) -> float:
    """Доплата за подготовку стартового кадра (вертикаль Nano Banana 2), если она понадобится."""
    if shot["model"] in PHOTO_START_MODELS and settings().get("VERTICAL_MODE", "nb2") == "nb2":
        return NB2_USD["1K"]
    return 0.0


def shot_cost(shot) -> float:
    return clip_cost(shot["model"], shot["duration"]) + prep_cost(shot)


def estimate(concepts) -> dict:
    total, rows = 0.0, []
    for c in concepts:
        s = sum(shot_cost(sh) for sh in c["shots"])
        rows.append({"id": c["id"], "title": c["title"], "usd": round(s, 2)})
        total += s
    return {"usd": round(total, 2), "per_concept": rows, "demo": demo_mode()}


def _src_files(product, pdir: Path, source: str):
    photos = [pdir / "prepared" / ph["file"] for ph in product.get("photos", [])]
    if source == "video":
        if not product.get("video"):
            raise GenError("Для кадра B нужно видео кольца на руке — загрузи его на шаге «Изделие».")
        return [pdir / "prepared" / product["video"]["file"]]
    if not photos:
        raise GenError("Нет фото изделия.")
    if source == "photos":
        return photos[:9]
    if source.startswith("photo:"):
        i = int(source.split(":")[1]) - 1
        return [photos[min(max(i, 0), len(photos) - 1)]]
    return photos[:1]


# ------------------------------- fal.ai -------------------------------------
_upload_cache = {}


def _fal():
    try:
        import fal_client  # noqa
    except ImportError as e:
        raise GenError("Не установлен пакет fal-client. Перезапусти start.command — он всё установит.") from e
    import os
    import fal_client
    os.environ["FAL_KEY"] = settings().get("FAL_KEY", "")
    return fal_client


def _upload(fal_client, path: Path) -> str:
    key = (str(path), path.stat().st_mtime)
    if key not in _upload_cache:
        _upload_cache[key] = fal_client.upload_file(str(path))
    return _upload_cache[key]


def _download(url: str, out: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "content-factory/1.0"})
    with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as fh:
        fh.write(r.read())


def _check_limit(est: float):
    limit = float(settings().get("DAILY_LIMIT_USD") or 0)
    if limit and store.spent_today() + est > limit:
        raise GenError(f"Дневной лимит ${limit:.2f} будет превышен (потрачено ${store.spent_today():.2f}, "
                       f"нужно ещё ~${est:.2f}). Увеличь лимит в «Настройках», если это осознанно.")


def _nb2(job, product, prompt: str, images: list[Path], out: Path, resolution="2K") -> Path:
    """Nano Banana 2 edit: картинка(и) + промт → одна картинка 9:16."""
    fal_client = _fal()
    urls = [_upload(fal_client, p) for p in images[:6]]
    try:
        res = fal_client.subscribe(NB2_EDIT, arguments={
            "prompt": prompt, "image_urls": urls, "aspect_ratio": "9:16", "resolution": resolution,
            "num_images": 1, "output_format": "jpeg"}, with_logs=False)
    except Exception as e:
        raise GenError(f"Nano Banana 2 вернула ошибку: {e}") from e
    imgs = res.get("images") or []
    if not imgs or not imgs[0].get("url"):
        raise GenError(f"Nano Banana 2 не вернула картинку: {str(res)[:300]}")
    _download(imgs[0]["url"], out)
    store.log_cost("image", NB2_USD.get(resolution, 0.12), product["id"], f"nano-banana-2 {resolution} 9:16")
    return out


def vertical_start(job, product, pdir: Path, photo: Path) -> Path:
    """Стартовый кадр 9:16 для фото. Кэшируется: одно фото готовится один раз."""
    mode = settings().get("VERTICAL_MODE", "nb2")
    if mode == "off":
        return photo
    info = media.probe(photo)
    w, h = info.get("width") or 1, info.get("height") or 1
    if h / w >= 1.6:                      # уже вертикальное
        return photo
    vdir = pdir / "prepared" / "vertical"
    vdir.mkdir(parents=True, exist_ok=True)
    if mode == "nb2" and not demo_mode():
        out = vdir / f"{photo.stem}_9x16_ai.jpg"
        if out.exists():
            return out
        try:
            job.say(f"  делаю вертикальный стартовый кадр из {photo.name} (Nano Banana 2, ~${NB2_USD['1K']:.2f})…")
            return _nb2(job, product, VERTICAL_PROMPT, [photo], out, resolution="1K")
        except Exception as e:
            job.say(f"  дорисовать не вышло ({str(e)[:160]}) — кладу фото на размытый фон")
    out = vdir / f"{photo.stem}_9x16_blur.jpg"
    if not out.exists():
        media.vertical_blur_image(photo, out)
    return out


def _arguments(model_key, shot, urls):
    dur = shot["duration"]
    neg = shot.get("negative_prompt") or ""
    p = shot["prompt"]
    if model_key in ("kling_i2v", "keyframe_kling"):
        return {"start_image_url": urls[0], "prompt": p, "duration": str(int(dur)), "generate_audio": False,
                "negative_prompt": neg, "cfg_scale": 0.5}
    if model_key == "kling_edit":
        return {"video_url": urls[0], "prompt": p, "keep_audio": False}
    if model_key == "seedance_i2v":
        return {"image_url": urls[0], "prompt": p, "duration": str(int(dur)), "resolution": "720p",
                "aspect_ratio": "9:16", "generate_audio": False}
    if model_key == "seedance_ref":
        return {"image_urls": urls[:9], "prompt": p, "duration": str(int(dur)), "resolution": "720p",
                "aspect_ratio": "9:16", "generate_audio": False}
    if model_key == "veo_i2v":
        d = min([4, 6, 8], key=lambda x: abs(x - dur))
        return {"image_url": urls[0], "prompt": p, "duration": f"{d}s", "resolution": "720p",
                "aspect_ratio": "9:16", "generate_audio": False, "negative_prompt": neg}
    raise GenError(f"Неизвестная модель {model_key}")


def generate_shot(job, product, pdir: Path, concept_id: str, idx: int, shot: dict, attempt: int = 1) -> dict:
    model_key = shot["model"]
    srcs = _src_files(product, pdir, shot["source"])
    ts = time.strftime("%H%M%S")
    out = pdir / "clips" / f"{concept_id}_s{idx+1}_{model_key}_{ts}.mp4"
    keyframe = None
    start_img = None

    if demo_mode():
        job.say(f"  [демо] кадр {idx+1} ({shot['type']}, {model_key}) — собираю из исходника, $0")
        if MODELS[model_key]["needs"] == "video":
            media.demo_clip_from_video(srcs[0], out, seconds=float(shot["duration"]))
        else:
            src = srcs[0]
            if model_key == "keyframe_kling":    # демо-«ключевой кадр»: фото на размытом фоне
                keyframe = pdir / "clips" / f"{out.stem}_key.jpg"
                media.vertical_blur_image(src, keyframe)
                src = keyframe
            media.demo_clip_from_photo(src, out, seconds=float(shot["duration"]), zoom_in=(idx % 2 == 0))
        cost = 0.0
    else:
        est = shot_cost(shot)
        _check_limit(est)
        fal_client = _fal()
        extra = 0.0
        if model_key == "keyframe_kling":
            keyframe = pdir / "clips" / f"{out.stem}_key.jpg"
            job.say(f"  кадр {idx+1}: ключевой кадр Nano Banana 2 по {len(srcs[:4])} фото (~${NB2_USD['2K']:.2f})…")
            _nb2(job, product, shot.get("keyframe_prompt") or shot["prompt"], srcs[:4], keyframe, resolution="2K")
            extra = NB2_USD["2K"]
            srcs = [keyframe]
        elif model_key in PHOTO_START_MODELS:
            start_img = vertical_start(job, product, pdir, srcs[0])
            srcs = [start_img]
        job.say(f"  загружаю исходники в fal ({len(srcs)} шт.)…")
        urls = [_upload(fal_client, s) for s in srcs]
        args = _arguments(model_key, shot, urls)
        job.say(f"  кадр {idx+1}: {MODELS[model_key]['title']}, ~${clip_cost(model_key, shot['duration']) - MODELS[model_key].get('extra_usd', 0):.2f}. Жду модель (обычно 1–4 мин)…")
        try:
            res = fal_client.subscribe(MODELS[model_key]["endpoint"], arguments=args, with_logs=False)
        except Exception as e:
            raise GenError(f"fal.ai вернул ошибку: {e}") from e
        url = (res.get("video") or {}).get("url") or res.get("url")
        if not url:
            raise GenError(f"fal.ai не вернул ссылку на видео: {str(res)[:300]}")
        _download(url, out)
        cost = clip_cost(model_key, shot["duration"]) - MODELS[model_key].get("extra_usd", 0)
        if model_key == "kling_edit":           # Kling edit считает по длине входного видео
            cost = clip_cost(model_key, media.probe(srcs[0])["duration"])
        store.log_cost("video", cost, product["id"], f"{model_key} {shot['duration']}s")
        cost += extra

    info = media.probe(out)
    if not info.get("width"):
        raise GenError("Модель вернула файл без видео — попробуй ещё раз.")
    thumb = out.with_suffix(".jpg")
    media.thumbnail(out, thumb)
    return {"file": out.name, "thumb": thumb.name, "concept": concept_id, "shot": idx, "type": shot["type"],
            "model": model_key, "prompt": shot["prompt"], "duration": round(info["duration"], 2),
            "width": info.get("width"), "height": info.get("height"),
            "keyframe": keyframe.name if keyframe else None,
            "start_image": f"vertical/{start_img.name}" if start_img and start_img.parent.name == "vertical" else None,
            "attempt": attempt, "usd": round(cost, 3), "demo": demo_mode(), "created": time.strftime("%Y-%m-%d %H:%M")}


# ------------------------------- фото для финального кадра ------------------
HERO_STYLES = {
    "velvet": ("Изумрудный бархат", "lying on deep emerald-green velvet, warm golden side light, rich dark moody background, "
               "sparkling highlights on the stones"),
    "stone": ("Травертин и дневной свет", "standing on a warm beige travertine stone plinth, soft window daylight, "
              "a long gentle shadow, calm warm beige background"),
    "silk": ("Шёлк и утро", "resting on soft folds of ivory silk, diffused morning light, airy pastel cream background"),
    "noir": ("Чёрное зеркало", "on a black mirror surface with a subtle reflection, a single soft spotlight from above, "
             "deep black background, crisp sparkles"),
    "petals": ("Лепестки", "on cream linen among a few blush rose petals, natural soft light, romantic airy mood"),
}

HERO_PROMPT = ("Luxury jewelry advertising photograph, vertical 9:16. The ring is an exact copy of the ring in the reference "
               "photos: identical shape, center stone cut and color, side stones, metal color and proportions — do not "
               "redesign it. {ring}. Scene: the ring {scene}. Composition: the ring slightly above the center, about one third "
               "of the frame width, sharp focus on the center stone, shallow depth of field. Keep the top fifth and the bottom "
               "third of the frame calm and uncluttered (soft background only) — that space is reserved for typography. "
               "Editorial, photorealistic, high-end catalog quality. No text, no letters, no logo, no watermark, no hands, no people.")


def make_heroes(job, product, pdir: Path, styles: list[str]) -> list[str]:
    """Красивые фото кольца для финального кадра (Nano Banana 2 по фото изделия). Возвращает имена файлов в cards/."""
    photos = [pdir / "prepared" / ph["file"] for ph in product.get("photos", [])]
    if not photos:
        raise GenError("Сначала загрузи фото изделия.")
    cards = pdir / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    ring = (product.get("visual_en") or "").strip().rstrip(".") or "the ring from the reference photos"
    out = []
    if not demo_mode():
        _check_limit(NB2_USD["2K"] * len(styles))
    for k, st in enumerate(styles):
        title, scene = HERO_STYLES.get(st, HERO_STYLES["velvet"])
        f = cards / f"hero_{st}_{time.strftime('%m%d_%H%M%S')}_{k}.jpg"
        if demo_mode():
            job.say(f"  [демо] «{title}»: беру фото изделия на размытом фоне, $0")
            media.vertical_blur_image(photos[k % len(photos)], f)
        else:
            job.say(f"  «{title}»: Nano Banana 2 снимает кольцо (~${NB2_USD['2K']:.2f})…")
            _nb2(job, product, HERO_PROMPT.format(ring=ring, scene=scene), photos[:4], f, resolution="2K")
        out.append(f.name)
    return out
