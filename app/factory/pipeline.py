"""Сценарии работы завода: то, что вызывают кнопки в интерфейсе."""
from __future__ import annotations

import time
from pathlib import Path

from . import store, media, llm, gen, montage, brains, publish
from .config import MUSIC, demo_mode, int_setting, settings, provider


class SubJob:
    """Обёртка задачи для шага автопилота: свой отрезок прогресс-бара, общий журнал."""
    def __init__(self, job, lo, hi):
        self.job, self.lo, self.hi = job, lo, hi

    def say(self, msg):
        self.job.say(msg)

    @property
    def progress(self):
        return self.job.progress

    @progress.setter
    def progress(self, v):
        self.job.progress = self.lo + (self.hi - self.lo) * max(0.0, min(1.0, v))


def _who(role):
    return "Claude (подписка)" if provider(role) == "claude" else "Gemini"


def _pdir(pid) -> Path:
    return store.pdir(pid)


# ------------------------------ Изделие -------------------------------------
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def add_file(pid: str, filename: str, data: bytes, label: str = "") -> dict:
    d = _pdir(pid)
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-") or "file"
    ext = Path(safe).suffix.lower()
    raw = d / "inputs" / f"{int(time.time()*1000)}_{safe}"
    raw.write_bytes(data)
    if ext in PHOTO_EXT:
        out = d / "prepared" / (raw.stem + ".jpg")
        media.prepare_photo(raw, out)
        item = {"file": out.name, "label": label, "orig": raw.name}
        store.update_product(pid, lambda p: p["photos"].append(item))
        return {"kind": "photo", **item}
    if ext in VIDEO_EXT:
        out = d / "prepared" / (raw.stem + "_5s.mp4")
        media.prepare_video(raw, out, seconds=5.0)
        info = media.probe(out)
        # реставратор-lite: кадры из видео как дополнительные ракурсы
        frames = media.best_frames_from_video(out, d / "frames", n=4)
        item = {"file": out.name, "orig": raw.name, "duration": round(info["duration"], 2),
                "width": info["width"], "height": info["height"], "frames": [f.name for f in frames]}
        store.update_product(pid, lambda p: p.__setitem__("video", item))
        return {"kind": "video", **item}
    raw.unlink(missing_ok=True)
    raise ValueError(f"Неподдерживаемый формат: {ext}. Фото: jpg/png/heic, видео: mp4/mov.")


def remove_file(pid: str, kind: str, name: str):
    def fn(p):
        if kind == "photo":
            p["photos"] = [x for x in p["photos"] if x["file"] != name]
        elif kind == "video":
            p["video"] = None
    return store.update_product(pid, fn)


def photo_paths(p) -> list[Path]:
    d = _pdir(p["id"])
    return [d / "prepared" / ph["file"] for ph in p.get("photos", [])]


def ref_photos(p) -> list[Path]:
    """Эталон для контролёра: фото + кадры из видео."""
    d = _pdir(p["id"])
    refs = photo_paths(p)
    if p.get("video"):
        refs += [d / "frames" / f for f in p["video"].get("frames", [])[:2]]
    return refs


def run_passport(job, pid):
    p = store.load_product(pid)
    if not p.get("photos"):
        raise ValueError("Сначала загрузи фото изделия.")
    job.say(f"{_who('passport')} изучает фото и описание…")
    data, meta = llm.passport(p, ref_photos(p))
    store.update_product(pid, lambda x: x.update({"visual_en": data.get("visual_en", ""), "passport": data}))
    job.say("Паспорт: " + data.get("visual_en", ""))
    return data


# ------------------------------ Сценарист -----------------------------------
def brief(pid) -> str:
    return llm.build_brief(store.load_product(pid))


def run_scenario(job, pid, n_concepts=None):
    p = store.load_product(pid)
    if not p.get("photos"):
        raise ValueError("Сначала загрузи фото изделия.")
    job.say(f"{_who('scenario')} пишет концепты по фото, трендам недели и профилю вкуса…")
    data, meta = llm.scenario_auto(p, ref_photos(p), job=job, n_concepts=n_concepts)
    ids = _save_concepts(pid, data)
    job.say(f"Концептов: {len(data['concepts'])}" + "".join(
        f"\n  · {c['title']}" + (f" (тренд: {c['trend']})" if c.get("trend") else "") for c in data["concepts"]))
    return {"concepts": ids}


def save_manual_scenario(pid, text: str):
    p = store.load_product(pid)
    data = llm.normalize_concepts(llm.parse_json(text), p)
    _save_concepts(pid, data)
    return data


def add_template_concept(pid):
    p = store.load_product(pid)
    if not p.get("photos"):
        raise ValueError("Сначала загрузи фото изделия.")
    n = len(p.get("concepts", [])) + 1
    data = llm.normalize_concepts({"concepts": [llm.template_concept(p, n)]}, p)
    _save_concepts(pid, data)
    return store.load_product(pid)


def save_concepts(pid, concepts):
    p = store.load_product(pid)
    data = llm.normalize_concepts({"concepts": concepts, "visual_en": p.get("visual_en", "")}, p)
    # сохраняем исходные id, чтобы клипы не «потерялись»
    for c_old, c_new in zip(concepts, data["concepts"]):
        c_new["id"] = c_old.get("id") or c_new["id"]
    store.update_product(pid, lambda x: x.__setitem__("concepts", data["concepts"]))
    return data


def _save_concepts(pid, data):
    ids = []

    def fn(p):
        used = {c["id"] for c in p.get("concepts", [])} | {c["concept"] for c in p.get("clips", [])}
        k = 1
        for c in data["concepts"]:
            while f"c{k}" in used:
                k += 1
            c["id"] = f"c{k}"
            used.add(c["id"])
            ids.append(c["id"])
        p["concepts"] = p.get("concepts", []) + data["concepts"]
        if data.get("visual_en") and not p.get("visual_en"):
            p["visual_en"] = data["visual_en"]
    store.update_product(pid, fn)
    return ids


# ------------------------------ Генерация -----------------------------------
def estimate(pid, concept_ids):
    p = store.load_product(pid)
    cs = [c for c in p["concepts"] if c["id"] in concept_ids]
    return gen.estimate(cs)


def run_generate(job, pid, concept_ids, qa=True):
    p = store.load_product(pid)
    cs = [c for c in p["concepts"] if c["id"] in concept_ids]
    if not cs:
        raise ValueError("Выбери хотя бы один концепт.")
    total = sum(len(c["shots"]) for c in cs)
    retries = max(0, int_setting("AUTO_RETRY", 1)) if qa else 0
    done, rejected = 0, 0
    job.say(f"Режим: {'ДЕМО (бесплатно)' if demo_mode() else 'fal.ai (платно)'}. Кадров: {total}"
            + (f", авто-переделка брака: до {retries} раз" if retries and not demo_mode() else ""))
    for c in cs:
        job.say(f"Концепт «{c['title']}»")
        for i, shot in enumerate(c["shots"]):
            attempt = 1
            while True:
                clip = gen.generate_shot(job, store.load_product(pid), _pdir(pid), c["id"], i, shot, attempt=attempt)
                store.update_product(pid, lambda x: x["clips"].append(clip))
                verdict = _qa_one(job, pid, clip) if qa else None
                if verdict != "reject":
                    break
                rejected += 1
                if attempt > retries:
                    job.say("  кадр остался в браке — посмотри его на шаге «Кадры» и реши сам")
                    break
                attempt += 1
                reject_clip(pid, clip["file"], True)
                job.say(f"  контролёр забраковал — переделываю (попытка {attempt})")
            done += 1
            job.progress = done / total
    return {"clips": done, "rejected": rejected}


def _qa_one(job, pid, clip):
    """Проверка кадра контролёром. Возвращает verdict или None."""
    p = store.load_product(pid)
    if clip.get("demo"):
        job.say("  проверка качества пропущена: демо-клип собран из твоего же фото")
        return None
    if not llm.qa_available():
        return None
    try:
        d = _pdir(pid)
        frames = media.extract_frames(d / "clips" / clip["file"], d / "frames", n=3)
        res, _ = llm.qa_clip(p, ref_photos(p), frames)
        store.update_product(pid, lambda x: x["qa"].__setitem__(clip["file"], res))
        job.say(f"  контролёр: {res.get('verdict')} ({res.get('score')}) — {res.get('summary_ru','')}")
        return res.get("verdict")
    except Exception as e:
        job.say(f"  контролёр не смог проверить: {e}")
        return None


def run_qa(job, pid, clip_file):
    p = store.load_product(pid)
    clip = next((c for c in p["clips"] if c["file"] == clip_file), None)
    if not clip:
        raise ValueError("Клип не найден")
    if not llm.qa_available():
        raise ValueError("Для проверки нужен Gemini или Claude.")
    d = _pdir(pid)
    frames = media.extract_frames(d / "clips" / clip["file"], d / "frames", n=3)
    res, _ = llm.qa_clip(p, ref_photos(p), frames)
    store.update_product(pid, lambda x: x["qa"].__setitem__(clip_file, res))
    job.say(f"Контролёр: {res.get('verdict')} ({res.get('score')}) — {res.get('summary_ru','')}")
    return res


def reject_clip(pid, clip_file, rejected: bool):
    def fn(p):
        for c in p["clips"]:
            if c["file"] == clip_file:
                c["rejected"] = rejected
    return store.update_product(pid, fn)


# ------------------------------ Монтаж --------------------------------------
def save_endcard(pid, png: bytes) -> str:
    f = _pdir(pid) / "cards" / "endcard.png"
    f.write_bytes(png)
    return f.name


ENDCARD_DEFAULT = {"template": "editorial", "palette": "gold", "hero": None, "tagline": "",
                   "cta": "Ссылка в описании", "show_price": True, "show_promo": True}


def endcard_cfg(p) -> dict:
    return {**ENDCARD_DEFAULT, **(p.get("endcard") or {})}


def save_endcard_cfg(pid, cfg: dict):
    keys = set(ENDCARD_DEFAULT)
    return store.update_product(pid, lambda p: p.__setitem__("endcard", {**endcard_cfg(p), **{k: v for k, v in cfg.items() if k in keys}}))


def run_hero(job, pid, styles):
    p = store.load_product(pid)
    styles = [s for s in (styles or []) if s in gen.HERO_STYLES][:4] or ["velvet", "stone"]
    files = gen.make_heroes(job, p, _pdir(pid), styles)

    def fn(x):
        x["heroes"] = files + [h for h in x.get("heroes", []) if h not in files]
        cfg = endcard_cfg(x)
        cfg["hero"] = files[0]
        x["endcard"] = cfg
    store.update_product(pid, fn)
    job.say(f"Готово фото: {len(files)}. Первое уже стоит в финальном кадре — выбери любое на вкладке «Ролики».")
    return {"heroes": files}


def add_hero_upload(pid, filename, data: bytes):
    d = _pdir(pid) / "cards"
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._-") or "hero.jpg"
    raw = d / f"up_{int(time.time())}_{safe}"
    raw.write_bytes(data)
    out = d / f"hero_own_{int(time.time())}.jpg"
    media.prepare_photo(raw, out, max_side=2400)
    raw.unlink(missing_ok=True)

    def fn(x):
        x["heroes"] = [out.name] + x.get("heroes", [])
        cfg = endcard_cfg(x)
        cfg["hero"] = out.name
        x["endcard"] = cfg
    return store.update_product(pid, fn)


TAGLINE_SCHEMA = {"type": "object", "properties": {"taglines": {"type": "array", "items": {"type": "string"}}},
                  "required": ["taglines"]}


def run_tagline(job, pid):
    p = store.load_product(pid)
    prompt = f"""Придумай 6 коротких слоганов (2–5 слов) для финального кадра рекламного ролика кольца.
Изделие: {p.get('name')} · {p.get('description_ru','')[:600]}
Профиль вкуса: {store.taste_text()[:600] or '(нет)'}
Стиль: тихая роскошь, без восклицательных знаков, без «лучший/уникальный», можно поэтично. По-русски."""
    data, meta = brains.ask("publish", prompt, schema=TAGLINE_SCHEMA, temperature=1.0, product=pid, job=job, timeout=300)
    tl = [t.strip().strip('«»"') for t in data.get("taglines", []) if t.strip()][:6]
    store.update_product(pid, lambda x: x.__setitem__("taglines", tl))
    job.say("Слоганы: " + " · ".join(tl))
    return {"taglines": tl}


def pick_clips(p, concept_id):
    """Последний годный клип для каждого кадра концепта."""
    by_shot = {}
    for c in p["clips"]:
        if c["concept"] != concept_id or c.get("rejected"):
            continue
        qa = p.get("qa", {}).get(c["file"])
        if qa and qa.get("verdict") == "reject" and not c.get("force"):
            continue
        by_shot[c["shot"]] = c
    return by_shot


def run_montage(job, pid, concept_id, n_variants=2, use_ai=True):
    p = store.load_product(pid)
    concept = next((c for c in p["concepts"] if c["id"] == concept_id), None)
    if not concept:
        raise ValueError("Концепт не найден")
    by_shot = pick_clips(p, concept_id)
    if not by_shot:
        raise ValueError("Нет годных клипов для этого концепта — сначала сгенерируй кадры.")
    d = _pdir(pid)
    endcard = d / "cards" / "endcard.png"
    if not endcard.exists():
        job.say("  плашки нет — ролик будет без неё (плашка рисуется в браузере при нажатии «Смонтировать»)")
    plan = None
    if use_ai and (brains.available("claude") or brains.available("gemini")):
        try:
            job.say(f"Монтажёр ({_who('montage')}) составляет план {n_variants} версий…")
            plan = montage.ai_plan(job, p, concept, by_shot, n_variants)
        except Exception as e:
            job.say(f"  план от ИИ не получился ({str(e)[:200]}) — монтирую по правилам")
    plan = plan or montage.plan_variants(concept, by_shot, n_variants)
    made = []
    for v in plan:
        name = f"{concept_id}_{time.strftime('%m%d_%H%M%S')}_{len(made)+1}.mp4"
        out = d / "videos" / name
        music = MUSIC / v["music"] if v.get("music") else None
        job.say(f"Монтирую «{v['name']}» · музыка: {v.get('music') or 'без музыки (положи треки в data/music)'}"
                + (f"\n  идея: {v['why']}" if v.get("why") else ""))
        dur = montage.build(job, [d / "clips" / by_shot[i]["file"] for i in v["order"]], out,
                            endcard if endcard.exists() else None, music, transition=v["transition"],
                            lengths=v.get("lengths"), starts=v.get("starts"), end_len=3.0)
        thumb = out.with_suffix(".jpg")
        media.thumbnail(out, thumb)
        item = {"file": name, "thumb": thumb.name, "concept": concept_id, "concept_title": concept["title"],
                "variant": v["name"], "why": v.get("why", ""), "planner": v.get("planner") or "правила",
                "music": v.get("music"), "duration": dur,
                "transitions": v["transition"] if isinstance(v["transition"], list) else [v["transition"]],
                "clips": [by_shot[i]["file"] for i in v["order"]],
                "models": sorted({by_shot[i]["model"] for i in v["order"]}),
                "cost_usd": round(sum(by_shot[i].get("usd", 0) for i in v["order"]), 3),
                "trend": concept.get("trend", ""), "mode": concept.get("mode"),
                "created": time.strftime("%Y-%m-%d %H:%M")}
        store.update_product(pid, lambda x: x["videos"].append(item))
        made.append(item)
        job.progress = len(made) / len(plan)
    return {"videos": [m["file"] for m in made]}


def run_publish(job, pid, video_file):
    job.say(f"{_who('publish')} пишет тексты для VK, Telegram и YouTube…")
    return publish.build_pack(job, pid, video_file)


# ------------------------------ Автопилот -----------------------------------
def run_autopilot(job, pid, n_variants=2, n_concepts=None):
    """Одна кнопка: паспорт → сценарий → кадры (с контролем и переделкой) → монтаж всех концептов."""
    p = store.load_product(pid)
    if not p.get("photos"):
        raise ValueError("Сначала загрузи фото изделия.")
    if not p.get("visual_en"):
        job.say("Шаг 1 · паспорт изделия")
        try:
            run_passport(SubJob(job, 0, 0.05), pid)
        except Exception as e:
            job.say(f"  паспорт не составлен ({str(e)[:200]}) — сценарист опишет кольцо сам")
    job.say("Шаг 2 · сценарист")
    res = run_scenario(SubJob(job, 0.05, 0.2), pid, n_concepts)
    ids = res["concepts"]
    est = estimate(pid, ids)
    if not est["demo"]:
        limit = float(settings().get("DAILY_LIMIT_USD") or 0)
        need = est["usd"] * (1 + 0.5 * min(1, int_setting("AUTO_RETRY", 1)))
        job.say(f"  оценка кадров: ${est['usd']:.2f} (с запасом на переделки ~${need:.2f})")
        if limit and store.spent_today() + est["usd"] > limit:
            raise ValueError(f"Оценка ${est['usd']:.2f} не влезает в дневной лимит ${limit:.2f} "
                             f"(уже потрачено ${store.spent_today():.2f}). Концепты сохранены — запусти генерацию вручную "
                             "или увеличь лимит.")
    job.say("Шаг 3 · генерация кадров")
    run_generate(SubJob(job, 0.2, 0.8), pid, ids, qa=True)
    job.say("Шаг 4 · монтаж")
    made = []
    for k, cid in enumerate(ids):
        try:
            r = run_montage(SubJob(job, 0.8 + 0.2 * k / len(ids), 0.8 + 0.2 * (k + 1) / len(ids)), pid, cid, n_variants)
            made += r["videos"]
        except Exception as e:
            job.say(f"  концепт {cid} не смонтирован: {str(e)[:200]}")
    job.say(f"Автопилот: концептов {len(ids)}, роликов {len(made)}. Оцени их на шаге «Ролики».")
    return {"concepts": ids, "videos": made}


# ------------------------------ Вкус ----------------------------------------
def rate(pid, video_file, like, tags, comment):
    p = store.load_product(pid)
    v = next((x for x in p["videos"] if x["file"] == video_file), None)
    if not v:
        raise ValueError("Ролик не найден")
    concept = next((c for c in p["concepts"] if c["id"] == v["concept"]), {})
    store.add_rating({"product": pid, "video": video_file, "like": like, "tags": tags, "comment": comment,
                      "concept_title": v.get("concept_title"), "idea": concept.get("idea"),
                      "hook": concept.get("hook"), "mode": concept.get("mode"), "variant": v.get("variant"),
                      "music": v.get("music"), "models": v.get("models"),
                      "shots": [{"type": s["type"], "model": s["model"], "prompt": s["prompt"][:300]}
                                for s in concept.get("shots", [])]})
    store.update_product(pid, lambda x: [vv.update({"like": like, "tags": tags, "comment": comment})
                                         for vv in x["videos"] if vv["file"] == video_file])


def run_taste(job, _pid=None):
    rows = store.ratings()
    if not rows:
        raise ValueError("Пока нет оценок — оцени хотя бы пару роликов.")
    if brains.available("claude") or brains.available("gemini"):
        job.say(f"{_who('taste')} обновляет профиль по {len(rows)} оценкам…")
        try:
            text, meta = llm.taste_update(rows, store.taste_text())
        except Exception as e:
            job.say(f"  ИИ не ответил ({str(e)[:200]}) — собираю профиль простым способом")
            text = llm.taste_fallback(rows)
    else:
        job.say("Ни Claude, ни Gemini не подключены — собираю профиль простым способом.")
        text = llm.taste_fallback(rows)
    store.save_taste(text)
    return {"taste": text}
