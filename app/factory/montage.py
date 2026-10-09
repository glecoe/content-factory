"""Монтажёр: клипы → ролик 9:16 с переходами, музыкой и финальной плашкой.

План монтажа (порядок, обрезка, переходы, музыка) пишет «мозг» роли «Монтажёр» (Claude/Gemini),
рендерит FFmpeg. Если ИИ недоступен — простой план по правилам.
Рендер устойчивый: у каждого монтажа своя рабочая папка, единый таймбейс, проверка длины видео,
а если склейка с переходами всё же сломалась — повтор простой склейкой без переходов.
"""
from __future__ import annotations

import json
import random
import shutil
import time
import uuid
from pathlib import Path

from .config import MUSIC, settings
from . import media, store
from .media import W, H, FPS

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
TRANSITIONS = ["fade", "fadeblack", "fadewhite", "dissolve", "smoothleft", "smoothup", "circleopen", "radial",
               "slideleft", "wipeleft"]


class MontageError(RuntimeError):
    pass


def music_tracks():
    return sorted([p.name for p in MUSIC.iterdir() if p.suffix.lower() in AUDIO_EXT])


# ----------------------------------------------------------------------------- рендер
def _normalize(src: Path, dst: Path, start: float, length: float, fit: str):
    """Клип → 1080×1920, 30 к/с, единый таймбейс, без звука, ровно `length` секунд (или сколько есть)."""
    info = media.probe(src)
    have = max(0.5, (info.get("video_duration") or info["duration"] or length) - start)
    length = max(1.0, min(length, have))
    fc = (media.fit_filter(fit, W, H, "0:v", "f") +
          f";[f]trim=start={start:.3f}:duration={length:.3f},setpts=PTS-STARTPTS,fps={FPS},settb=AVTB,format=yuv420p[v]")
    media.run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-an",
               "-r", str(FPS), *media.venc_args(), str(dst)])
    return media.probe(dst)["video_duration"]


def _still(png: Path, dst: Path, seconds: float):
    n = int(seconds * FPS)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"zoompan=z='min(zoom+0.00035,1.03)':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
          "settb=AVTB,setsar=1,format=yuv420p")
    media.run(["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
               *media.venc_args(), str(dst)])
    return media.probe(dst)["video_duration"]


def _audio_chain(n_in, music, total):
    if music and music.exists():
        fade_st = max(total - 1.5, 0)
        return (["-stream_loop", "-1", "-i", str(music)],
                f"[{n_in}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.4,"
                f"afade=t=out:st={fade_st:.3f}:d=1.5,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[aout]")
    return (["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"], f"[{n_in}:a]anull[aout]")


def _render(parts, durs, out, music, transition, xfade, use_xfade=True):
    inputs, fc = [], []
    for p in parts:
        inputs += ["-i", str(p)]
    if use_xfade and len(parts) > 1:
        prev, acc = "[0:v]", durs[0]
        for i in range(1, len(parts)):
            tr = transition[i - 1] if isinstance(transition, list) else transition
            off = max(0.1, acc - xfade)
            fc.append(f"{prev}[{i}:v]xfade=transition={tr}:duration={xfade}:offset={off:.3f}[x{i}]")
            prev, acc = f"[x{i}]", off + durs[i]
        fc.append(f"{prev}format=yuv420p[vout]")
        total = acc
    else:
        fc.append("".join(f"[{i}:v]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0,format=yuv420p[vout]")
        total = sum(durs)
    a_in, a_fc = _audio_chain(len(parts), music, total)
    inputs += a_in
    fc.append(a_fc)
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
           "-t", f"{total:.3f}", "-r", str(FPS), *media.venc_args(), "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)]
    media.run(cmd, timeout=900)
    return total


def build(job, clips, out: Path, endcard: Path | None, music: Path | None, transition="fade", xfade=0.35,
          lengths=None, starts=None, end_len=2.5, fit=None):
    """clips — пути к клипам в нужном порядке; lengths/starts — обрезка каждого клипа (сек)."""
    fit = fit or settings().get("MONTAGE_FIT", "crop")
    work = out.parent / f"_work_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        parts, durs = [], []
        for i, c in enumerate(clips):
            n = work / f"n{i}.mp4"
            ln = float((lengths or [])[i]) if lengths and i < len(lengths) and lengths[i] else 4.0
            st = float((starts or [])[i]) if starts and i < len(starts) and starts[i] else 0.0
            d = _normalize(c, n, st, ln, fit)
            parts.append(n)
            durs.append(d)
            job.say(f"  клип {i+1}: {d:.1f} сек")
        if endcard and endcard.exists():
            e = work / "end.mp4"
            durs.append(_still(endcard, e, end_len))
            parts.append(e)
        xf = min(xfade, min(durs) / 3)
        job.say(f"  рендер: {len(parts)} фрагмента, переходы «{transition if isinstance(transition, str) else ', '.join(transition)}»")
        total = _render(parts, durs, out, music, transition, xf, use_xfade=True)
        got = media.probe(out)
        if abs(got["video_duration"] - total) > 0.6:
            job.say(f"  ⚠ видео {got['video_duration']:.1f} с вместо {total:.1f} с — пересобираю простой склейкой")
            total = _render(parts, durs, out, music, transition, xf, use_xfade=False)
            got = media.probe(out)
            if abs(got["video_duration"] - total) > 0.6:
                raise MontageError(f"Ролик собрался неправильно: видео {got['video_duration']:.1f} с, ожидалось {total:.1f} с.")
        return round(total, 2)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ----------------------------------------------------------------------------- план
PLAN_SCHEMA = {"type": "object", "properties": {"variants": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"},
    "order": {"type": "array", "items": {"type": "integer"}},
    "lengths": {"type": "array", "items": {"type": "number"}},
    "starts": {"type": "array", "items": {"type": "number"}},
    "transitions": {"type": "array", "items": {"type": "string", "enum": TRANSITIONS}},
    "music": {"type": "string"},
    "why": {"type": "string"}},
    "required": ["name", "order", "lengths", "transitions", "music"]}}}, "required": ["variants"]}


def plan_variants(concept, clips_by_shot, n_variants=2):
    """Простой план без ИИ: другой порядок/хук, другой переход и другая музыка."""
    order = sorted(clips_by_shot)
    tracks = music_tracks()
    rnd = random.Random(concept["id"] + time.strftime("%Y%m%d%H%M%S"))
    rnd.shuffle(tracks)
    variants = [{"name": "v1 · как в сценарии", "order": order, "transition": "fade",
                 "music": tracks[0] if tracks else None}]
    if n_variants > 1:
        hook_first = sorted(order, key=lambda i: 0 if clips_by_shot[i]["type"] in ("B", "C") else 1)
        if hook_first == order:
            hook_first = order[1:] + order[:1]
        variants.append({"name": "v2 · рука первой, другая музыка", "order": hook_first, "transition": "fadeblack",
                         "music": tracks[1 % len(tracks)] if tracks else None})
    for k in range(2, n_variants):
        o = order[:]
        rnd.shuffle(o)
        variants.append({"name": f"v{k+1} · другой порядок", "order": o, "transition": rnd.choice(TRANSITIONS),
                         "music": tracks[k % len(tracks)] if tracks else None})
    return variants[:n_variants]


def ai_plan(job, product, concept, clips_by_shot, n_variants=2):
    """План монтажа от «мозга» роли montage. Возвращает список вариантов (или None)."""
    from . import brains, research
    tracks = music_tracks()
    qa = product.get("qa", {})
    shots = []
    for i, c in sorted(clips_by_shot.items()):
        sh = concept["shots"][i] if i < len(concept.get("shots", [])) else {}
        q = qa.get(c["file"]) or {}
        shots.append({"index": i, "type": c["type"], "duration": c["duration"], "model": c["model"],
                      "prompt": (sh.get("prompt") or c.get("prompt") or "")[:400],
                      "qa_score": q.get("score"), "qa_issues": q.get("issues_ru", [])})
    nid = product.get("niche")
    from . import niches
    liked = [r for r in store.ratings(nid) if r.get("like")][-8:]
    prompt = f"""Ты — монтажёр коротких рекламных роликов, ниша «{niches.ctx(nid)['name']}» (вертикаль 9:16, 10–15 секунд, в конце плашка с ценой 2.5 с — её добавят сами).
Сделай {n_variants} РАЗНЫХ варианта монтажа одного концепта.

КОНЦЕПТ: {concept.get('title')} — {concept.get('idea')}
Хук: {concept.get('hook')} · Настроение музыки: {concept.get('music_mood')} · Тренд: {concept.get('trend','')}

КЛИПЫ (index — номер кадра):
{json.dumps(shots, ensure_ascii=False, indent=1)}

МУЗЫКА (выбирай точное имя файла из списка или пустую строку): {json.dumps(tracks, ensure_ascii=False)}
ПЕРЕХОДЫ: {', '.join(TRANSITIONS)}

ПРОФИЛЬ ВКУСА:
{store.taste_text(nid)[:1800] or '(пусто)'}

ПОНРАВИВШИЕСЯ РАНЕЕ МОНТАЖИ: {json.dumps([{k: r.get(k) for k in ('variant', 'music', 'tags', 'comment')} for r in liked], ensure_ascii=False)}

ТРЕНДЫ: {research.active_brief_text(nid, 1200) or '(нет брифа)'}

Правила: order — все index клипов в нужном порядке (каждый ровно один раз); lengths — длина каждого клипа в секундах (2.5–5, не больше его duration), в порядке order;
starts — с какой секунды брать клип (0, если начало хорошее); transitions — переход ПЕРЕД каждым следующим фрагментом (их число = число клипов, последний — перед плашкой);
первые 1.5 секунды должны цеплять (самый эффектный кадр первым хотя бы в одном варианте); варианты должны отличаться порядком/темпом/музыкой.
name — коротко по-русски, why — одна фраза, зачем этот вариант."""
    data, meta = brains.ask("montage", prompt, schema=PLAN_SCHEMA, temperature=0.8, product=product["id"], job=job,
                            timeout=600)
    out = []
    valid = set(clips_by_shot)
    for v in (data or {}).get("variants", [])[:n_variants]:
        order = [int(i) for i in v.get("order", []) if int(i) in valid]
        order = list(dict.fromkeys(order)) + [i for i in sorted(valid) if i not in order]
        lens = [float(x) for x in (v.get("lengths") or [])]
        lens = [max(2.0, min(5.0, lens[k] if k < len(lens) else 4.0, clips_by_shot[i]["duration"])) for k, i in enumerate(order)]
        sts = [float(x) for x in (v.get("starts") or [])]
        sts = [max(0.0, min(sts[k] if k < len(sts) else 0.0, clips_by_shot[i]["duration"] - lens[k])) for k, i in enumerate(order)]
        trs = [t for t in (v.get("transitions") or []) if t in TRANSITIONS] or ["fade"]
        trs = (trs * len(order))[:len(order)]
        music = v.get("music") if v.get("music") in tracks else (tracks[len(out) % len(tracks)] if tracks else None)
        out.append({"name": (v.get("name") or f"v{len(out)+1}")[:60], "order": order, "lengths": lens, "starts": sts,
                    "transition": trs, "music": music, "why": v.get("why", ""), "planner": meta.get("provider")})
    return out or None
