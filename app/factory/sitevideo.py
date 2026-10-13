"""Лаборатория сайтов · видео: свои видео, улучшение через ИИ и генерация из фото — по аналогии с фото.

Места под видео (слоты) предлагает фотодиректор вместе с планом фото или добавляет владелец.
Улучшение:
  grade   — цвет, контраст, резкость (FFmpeg, бесплатно);
  upscale — качество ×2 до Full HD (Topaz на fal.ai, ~$0.02 за секунду);
  studio  — «как с дорогой съёмки»: тот же сюжет, новый свет и цвет (Kling O3 video-to-video, $0.168 за секунду).
Генерация: Kling 3.0 Pro из выбранного фото ($0.112 за секунду).
Цены — страницы моделей fal.ai на 10.10.2026.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
V_ASPECTS = ["16:9", "9:16", "1:1"]
KLING_I2V = "fal-ai/kling-video/v3/pro/image-to-video"
KLING_EDIT = "fal-ai/kling-video/o3/pro/video-to-video/edit"
TOPAZ = "fal-ai/topaz/upscale/video"
USD = {"generate": 0.112, "studio": 0.168, "upscale": 0.02, "grade": 0.0}
MODES = {"grade": "Цвет и резкость", "upscale": "Качество ×2", "studio": "Как дорогая съёмка"}
MAX_SECONDS = 60          # своё видео обрезается до минуты (для сайта больше не нужно)

STUDIO_PROMPT = ("@Video1 Re-render this exact video as a high-end professional commercial shoot. Keep the same people, faces, "
                 "products, objects, actions, framing and camera movement. Improve only the look: soft flattering premium "
                 "lighting, clean cinematic color grade, crisp detail, no noise or flicker. Do not add or remove objects, "
                 "do not change logos or product design. No text, no watermark.")


def _sl():
    from . import sitelab
    return sitelab


def _videos(p) -> dict:
    v = p.get("videos") or {}
    return {"slots": v.get("slots") or [], "uploads": v.get("uploads") or []}


def vdir(sid) -> Path:
    d = _sl().pdir(sid) / "videos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    n = Path(str(name or "")).name
    if not re.fullmatch(r"[\w.\-]+", n):
        raise ValueError("Некорректное имя файла")
    return n


_TR = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeejziiklmnoprstufhccss_y_eua")


def _clean_slot_id(x: str, taken) -> str:
    sid_ = re.sub(r"[^a-z0-9\-]+", "-", (x or "video").lower().translate(_TR)).strip("-")[:40] or "video"
    base, i = sid_, 2
    while sid_ in taken:
        sid_, i = f"{base}-{i}", i + 1
    return sid_


# ------------------------------------------------------------------ тексты и передача в сборку
def videos_text(p) -> str:
    ch = [s for s in _videos(p)["slots"] if s.get("chosen")]
    if not ch:
        return "готовых видео нет"
    return (f"{len(ch)} готовых видео в assets/videos (манифест VIDEOS.json): " +
            "; ".join(f"{s['id']}.mp4 + {s['id']}.jpg — {s.get('page', '')}/{s.get('section', '')}, {s.get('aspect')}, "
                      f"«{s.get('subject_ru', '')}»" for s in ch))


def copy_videos(p, out: Path) -> int:
    ch = [s for s in _videos(p)["slots"] if s.get("chosen")]
    if not ch:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    src = _sl().pdir(p["id"]) / "videos"
    manifest = []
    for s in ch:
        f = src / s["chosen"]
        if not f.exists():
            continue
        shutil.copyfile(f, out / f"{s['id']}.mp4")
        poster = src / (Path(s["chosen"]).stem + ".jpg")
        if poster.exists():
            shutil.copyfile(poster, out / f"{s['id']}.jpg")
        manifest.append({"file": f"{s['id']}.mp4", "poster": f"{s['id']}.jpg", "page": s.get("page", ""),
                         "section": s.get("section", ""), "purpose": s.get("purpose", ""), "aspect": s.get("aspect"),
                         "alt": s.get("subject_ru", ""), "loop": True, "muted": True})
    (out / "VIDEOS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(manifest)


# ------------------------------------------------------------------ места под видео
def set_plan_slots(sid, slots: list):
    """Места под видео из плана фотодиректора (старые варианты и загрузки сохраняются)."""
    def fn(p):
        v = _videos(p)
        keep = {s["id"]: s for s in v["slots"]}
        new, taken = [], set()
        for s in (slots or [])[:4]:
            i = _clean_slot_id(s.get("id") or "video", taken)
            taken.add(i)
            old = keep.get(i, {})
            new.append({"id": i, "page": str(s.get("page", ""))[:60], "section": str(s.get("section", ""))[:80],
                        "purpose": str(s.get("purpose", ""))[:300], "aspect": s.get("aspect") if s.get("aspect") in V_ASPECTS else "16:9",
                        "subject_ru": str(s.get("subject_ru", ""))[:300], "prompt_en": str(s.get("prompt_en", ""))[:1500],
                        "duration": 10 if int(s.get("duration") or 5) >= 8 else 5,
                        "variants": old.get("variants", []), "chosen": old.get("chosen")})
        for s in v["slots"]:            # места, добавленные владельцем, не теряем
            if s.get("manual") and s["id"] not in taken:
                new.append(s)
        p["videos"] = {**v, "slots": new}
    return _sl().update(sid, fn)


def add_slot(sid, data: dict):
    def fn(p):
        v = _videos(p)
        i = _clean_slot_id(data.get("id") or data.get("section") or "video", {s["id"] for s in v["slots"]})
        v["slots"].append({"id": i, "page": str(data.get("page", ""))[:60], "section": str(data.get("section", ""))[:80],
                           "purpose": "", "aspect": data.get("aspect") if data.get("aspect") in V_ASPECTS else "16:9",
                           "subject_ru": str(data.get("subject_ru", ""))[:300], "prompt_en": str(data.get("prompt_en", ""))[:1500],
                           "duration": 5, "variants": [], "chosen": None, "manual": True})
        p["videos"] = v
    return _sl().update(sid, fn)


def save_slot(sid, slot_id, data: dict):
    def fn(p):
        v = _videos(p)
        for s in v["slots"]:
            if s["id"] == slot_id:
                for k in ("prompt_en", "subject_ru", "section", "page"):
                    if k in data:
                        s[k] = str(data[k])[:1500]
                if data.get("aspect") in V_ASPECTS:
                    s["aspect"] = data["aspect"]
                if str(data.get("duration", "")) in ("5", "10"):
                    s["duration"] = int(data["duration"])
        p["videos"] = v
    return _sl().update(sid, fn)


def remove_slot(sid, slot_id):
    def fn(p):
        v = _videos(p)
        v["slots"] = [s for s in v["slots"] if s["id"] != slot_id]
        for u in v["uploads"]:
            if u.get("slot") == slot_id:
                u["slot"] = None
        p["videos"] = v
    return _sl().update(sid, fn)


def _slot(p, slot_id):
    s = next((x for x in _videos(p)["slots"] if x["id"] == slot_id), None)
    if not s:
        raise ValueError("Место под видео не найдено")
    return s


def _add_variant(sid, slot_id, file: str, kind: str, source: str = "", seconds: float = 0):
    def fn(p):
        v = _videos(p)
        for s in v["slots"]:
            if s["id"] == slot_id:
                s.setdefault("variants", []).insert(0, {"file": file, "kind": kind, "source": source, "seconds": round(seconds, 1),
                                                        "at": datetime.now().isoformat(timespec="seconds")})
                if not s.get("chosen") or kind in ("enhanced", "ai"):
                    s["chosen"] = file
        p["videos"] = v
    _sl().update(sid, fn)


def choose(sid, slot_id, file):
    def fn(p):
        v = _videos(p)
        for s in v["slots"]:
            if s["id"] == slot_id:
                s["chosen"] = _safe_name(file) if file else None
        p["videos"] = v
    return _sl().update(sid, fn)


def assign_upload(sid, file, slot_id):
    file = _safe_name(file)

    def fn(p):
        v = _videos(p)
        for u in v["uploads"]:
            if u["file"] == file:
                u["slot"] = slot_id or None
        p["videos"] = v
    p = _sl().update(sid, fn)
    if slot_id:
        _slot(p, slot_id)
        u = next((x for x in _videos(p)["uploads"] if x["file"] == file), {})
        _add_variant(sid, slot_id, file, "upload", seconds=u.get("seconds", 0))
    return _sl().load(sid)


# ------------------------------------------------------------------ FFmpeg
def _x264(crf=23):
    from . import media
    if media.video_encoder() == "libx264":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-profile:v", "high"]
    return media.venc_args()


def prepare_web(src: Path, dst: Path, max_seconds=MAX_SECONDS, min_short=0, vf_extra="") -> dict:
    """Видео для сайта: H.264, до Full HD, до 30 к/с, без звука, быстрый старт; + постер .jpg рядом."""
    from . import media
    info = media.probe(src)
    if not info.get("width"):
        raise ValueError("В файле нет видео-дорожки")
    w, h = int(info["width"]), int(info["height"])
    long_side = max(w, h)
    scale = min(1.0, 1920 / long_side)
    if min_short and min(w, h) * scale < min_short:
        scale = min_short / min(w, h)
    tw, th = int(w * scale) // 2 * 2, int(h * scale) // 2 * 2
    t = min(max_seconds, info["duration"] or max_seconds)
    vf = f"scale={tw}:{th}:flags=lanczos,fps='min(30,source_fps)'" + (f",{vf_extra}" if vf_extra else "")
    try:
        media.run(["ffmpeg", "-y", "-i", str(src), "-t", f"{t:.2f}", "-an", "-vf", vf, *_x264(),
                   "-movflags", "+faststart", str(dst)], timeout=1800)
    except media.MediaError:     # старые FFmpeg не знают source_fps
        media.run(["ffmpeg", "-y", "-i", str(src), "-t", f"{t:.2f}", "-an", "-vf",
                   f"scale={tw}:{th}:flags=lanczos,fps=30" + (f",{vf_extra}" if vf_extra else ""), *_x264(),
                   "-movflags", "+faststart", str(dst)], timeout=1800)
    poster(dst)
    out = media.probe(dst)
    return {"seconds": round(out["duration"], 1), "width": out["width"], "height": out["height"]}


def poster(video: Path) -> Path:
    from . import media
    out = video.with_suffix(".jpg")
    d = media.probe(video)["duration"] or 1
    media.run(["ffmpeg", "-y", "-ss", f"{min(0.8, d / 3):.2f}", "-i", str(video), "-frames:v", "1",
               "-vf", "scale='min(1600,iw)':-2", "-q:v", "3", str(out)])
    return out


GRADE = "eq=contrast=1.07:saturation=1.10:brightness=0.01,unsharp=5:5:0.6:5:5:0.0"


# ------------------------------------------------------------------ загрузка своих видео
def add_upload(sid, filename: str, data: bytes, slot_id: str = "") -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise ValueError("Видео: mp4, mov, m4v или webm.")
    if not data:
        raise ValueError("Пустой файл")
    d = vdir(sid)
    stem = re.sub(r"[^\w\-]+", "_", Path(filename).stem)[:40] or "video"
    raw = d / f"_raw_{uuid.uuid4().hex[:8]}{ext}"
    out = d / f"vup_{stem}_{uuid.uuid4().hex[:6]}.mp4"
    try:
        raw.write_bytes(data)
        info = prepare_web(raw, out)
    except Exception as e:
        out.unlink(missing_ok=True)
        out.with_suffix(".jpg").unlink(missing_ok=True)
        raise ValueError("Не получилось прочитать видео — файл повреждён или формат не поддерживается.") from e
    finally:
        raw.unlink(missing_ok=True)

    def fn(p):
        v = _videos(p)
        v["uploads"].insert(0, {"file": out.name, "name": str(filename)[:120], "slot": slot_id or None, **info})
        p["videos"] = v
    _sl().update(sid, fn)
    if slot_id:
        _add_variant(sid, slot_id, out.name, "upload", seconds=info["seconds"])
    return _sl().load(sid)


# ------------------------------------------------------------------ ИИ: генерация и улучшение
def _fal_video(job, endpoint: str, args: dict, out: Path, sid: str, usd: float, detail: str):
    from . import gen, store
    fal = gen._fal()
    try:
        res = fal.subscribe(endpoint, arguments=args, with_logs=False)
    except Exception as e:
        raise RuntimeError(f"fal.ai ({endpoint.split('/')[1]}): {e}") from e
    url = ((res or {}).get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"Модель не вернула видео: {str(res)[:200]}")
    gen._download(url, out)
    store.log_cost("video", usd, sid, detail)
    return out


def _crop_to_aspect(src: Path, aspect: str, out: Path) -> Path:
    from PIL import Image
    a, b = (int(x) for x in aspect.split(":"))
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if w / h > a / b:
        nw = int(h * a / b)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * b / a)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im.save(out, quality=92)
    return out


def _photo_sources(p) -> dict:
    """Фото, из которых можно сделать видео: выбранные в местах под фото и свои загрузки."""
    sl = _sl()
    ph = sl._photos(p)
    out = {}
    for s in ph.get("slots", []):
        if s.get("chosen"):
            out[s["chosen"]] = f"фото · {s['id']}"
    for u in ph.get("uploads", []):
        out.setdefault(u["file"], f"своё · {u.get('name') or u['file']}")
    return out


def _demo_from_photo(photo: Path, out: Path, aspect: str, seconds: int):
    from . import media
    a, b = (int(x) for x in aspect.split(":"))
    W = 1280 if a >= b else int(1280 * a / b) // 2 * 2
    H = int(W * b / a) // 2 * 2
    frames = int(seconds * 25)
    vf = (f"scale={W * 4 // 3}:{H * 4 // 3}:force_original_aspect_ratio=increase,crop={W * 4 // 3}:{H * 4 // 3},"
          f"zoompan=z='min(zoom+0.0010,1.2)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=25,format=yuv420p")
    media.run(["ffmpeg", "-y", "-loop", "1", "-i", str(photo), "-vf", vf, "-t", str(seconds), *_x264(), str(out)])


def run_generate(job, sid, slot_id: str, photo: str = "", duration: int = 0, extra: str = ""):
    """Видео из фото (Kling 3.0 Pro): фото обрезается под пропорции места, промпт — движение и атмосфера."""
    from . import gen
    from .config import demo_mode
    sl = _sl()
    p = sl.load(sid)
    s = _slot(p, slot_id)
    srcs = _photo_sources(p)
    photo = _safe_name(photo) if photo else ""
    if not photo:
        same = next((x for x in sl._photos(p).get("slots", []) if x.get("chosen") and
                     (x.get("section") == s.get("section") or x["id"].startswith("hero") and slot_id.startswith("hero"))), None)
        photo = (same or {}).get("chosen") or next(iter(srcs), "")
    if not photo or photo not in srcs:
        raise ValueError("Нужно фото, из которого делать видео: выбери фото в месте под фото или загрузи своё.")
    src = sl.pdir(sid) / "photos" / photo
    dur = 10 if int(duration or s.get("duration") or 5) >= 8 else 5
    d = vdir(sid)
    out = d / f"{slot_id}_ai_{uuid.uuid4().hex[:6]}.mp4"
    tmp = d / f"_start_{uuid.uuid4().hex[:6]}.jpg"
    try:
        _crop_to_aspect(src, s["aspect"], tmp)
        if demo_mode():
            job.say(f"  [демо] видео из фото без ИИ (медленный наезд), {dur} с, $0")
            _demo_from_photo(tmp, out, s["aspect"], dur)
        else:
            usd = USD["generate"] * dur
            gen._check_limit(usd)
            fal = gen._fal()
            style = (sl._photos(p).get("style") or {}).get("prompt_suffix_en", "")
            prompt = (f"{s.get('prompt_en') or s.get('subject_ru') or 'Subtle cinematic motion'}. {extra} "
                      f"Slow, smooth, premium camera movement; natural motion; {style}. No text, no logos, no watermark.").strip()
            job.say(f"  Kling 3.0 Pro: видео {dur} с из «{photo}» (~${usd:.2f})…")
            _fal_video(job, KLING_I2V, {"start_image_url": gen._upload(fal, tmp), "prompt": prompt, "duration": str(dur),
                                        "generate_audio": False, "negative_prompt": "blur, distortion, warped faces, text, watermark",
                                        "cfg_scale": 0.5}, out, sid, usd, f"site video {slot_id} kling i2v {dur}s")
        raw = out.with_name("_gen_" + out.name)
        out.rename(raw)
        try:
            info = prepare_web(raw, out)
        finally:
            raw.unlink(missing_ok=True)
    finally:
        tmp.unlink(missing_ok=True)
    _add_variant(sid, slot_id, out.name, "ai", source=photo, seconds=info["seconds"])
    job.say(f"  готово: {out.name}")
    return {"file": out.name}


def estimate(mode: str, seconds: float) -> float:
    return round(USD.get(mode, 0) * max(0.0, seconds), 2)


def run_enhance(job, sid, slot_id: str, file: str, mode: str = "grade", extra: str = "", seconds: int = 0):
    """Улучшить видео: grade (бесплатно), upscale (Topaz), studio (Kling O3 video-to-video)."""
    from . import gen, media
    from .config import demo_mode
    sl = _sl()
    p = sl.load(sid)
    _slot(p, slot_id)
    mode = mode if mode in MODES else "grade"
    src = vdir(sid) / _safe_name(file)
    if not src.exists():
        raise ValueError("Видео не найдено")
    info = media.probe(src)
    d = vdir(sid)
    out = d / f"{slot_id}_{mode}_{uuid.uuid4().hex[:6]}.mp4"
    raw = d / f"_enh_{uuid.uuid4().hex[:6]}.mp4"
    work = d / f"_in_{uuid.uuid4().hex[:6]}.mp4"
    try:
        if mode == "grade" or demo_mode():
            if mode != "grade":
                job.say(f"  [демо] {MODES[mode]}: только цвет и резкость через FFmpeg, $0")
            res = prepare_web(src, out, vf_extra=GRADE)
        elif mode == "upscale":
            long_side = max(info["width"], info["height"])
            factor = round(min(2.0, 1920 / long_side), 2)
            if factor < 1.1:
                raise ValueError("Видео уже в Full HD — апскейл не нужен. Попробуй «Как дорогая съёмка» или «Цвет и резкость».")
            t = min(info["duration"], MAX_SECONDS)
            usd = estimate("upscale", t)
            gen._check_limit(usd)
            fal = gen._fal()
            job.say(f"  Topaz: качество ×{factor} для {t:.0f} с (~${usd:.2f})…")
            _fal_video(job, TOPAZ, {"video_url": gen._upload(fal, src), "model": "Proteus", "upscale_factor": factor,
                                    "H264_output": True}, raw, sid, usd, f"site video upscale {slot_id}")
            res = prepare_web(raw, out)
        else:   # studio
            t = max(3.0, min(float(seconds or 10), info["duration"], 15.0))
            if info["duration"] < 3:
                raise ValueError("Для «Как дорогая съёмка» нужно видео от 3 секунд.")
            usd = estimate("studio", t)
            gen._check_limit(usd)
            prepare_web(src, work, max_seconds=t, min_short=720)
            fal = gen._fal()
            style = (sl._photos(p).get("style") or {}).get("prompt_suffix_en", "")
            prompt = f"{STUDIO_PROMPT} Look of the website: {style}. {extra}".strip()
            job.say(f"  Kling O3: «как дорогая съёмка», {t:.0f} с (~${usd:.2f})…")
            _fal_video(job, KLING_EDIT, {"video_url": gen._upload(fal, work), "prompt": prompt, "keep_audio": False},
                       raw, sid, usd, f"site video studio {slot_id}")
            res = prepare_web(raw, out)
    finally:
        for f in (raw, work, work.with_suffix(".jpg")):
            f.unlink(missing_ok=True)
    _add_variant(sid, slot_id, out.name, "enhanced", source=src.name, seconds=res["seconds"])
    job.say(f"  готово: {out.name} ({res['width']}×{res['height']}, {res['seconds']} с)")
    return {"file": out.name}
