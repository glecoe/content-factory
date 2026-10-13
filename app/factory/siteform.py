"""Лаборатория сайтов · анкета заказчика.

Студия делает анкету по сайту (один HTML-файл без внешних зависимостей). Её можно:
- скачать и отправить заказчику файлом — он заполняет, нажимает «Сохранить ответы» и присылает файл .json обратно;
- открыть по секретной ссылке /form/<token>, когда студия на сервере с доменом, — ответы приходят в студию сами.
Ответы проверяются (обязательные поля, ИНН/ОГРН, почта, телефон, ссылки, логотип) и по выбору переносятся в бриф.

Данные: data/sites/<id>/form/answers.json (+ история answers-<время>.json, логотип logo.<ext>); в project.json — form.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import sitelab, sitelaunch
from .config import settings

FORMAT = "studio-brief/1"
MAX_LOGO = 5 * 1024 * 1024
MAX_TEXT = 4000
LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
GOALS = ["Оставить заявку", "Позвонить", "Записаться", "Купить", "Запросить расчёт", "Написать в мессенджер"]
YES = {"yes": "Да", "no": "Нет", "unsure": "Пока не знаю"}

# Поля анкеты. type: text | textarea | select | radio | number | file; check — формат; show — показывать, если …
SECTIONS = [
    {"id": "company", "title": "О компании", "hint": "Чем подробнее — тем точнее получится сайт с первого раза.", "fields": [
        {"id": "name", "label": "Название компании или бренда", "type": "text", "required": True, "max": 120,
         "placeholder": "Стоматология «Улыбка»"},
        {"id": "sphere", "label": "Чем вы занимаетесь", "type": "textarea", "required": True, "min": 40,
         "help": "Что продаёте или какие услуги оказываете, в каком сегменте, чем отличаетесь от конкурентов.",
         "placeholder": "Частная стоматология: имплантация, виниры, лечение детей. Премиум-сегмент, свой зуботехнический цех…"},
        {"id": "city", "label": "Город или регион работы", "type": "text", "max": 120, "placeholder": "Казань"},
        {"id": "audience", "label": "Кто ваши клиенты", "type": "textarea",
         "placeholder": "Взрослые 30–55 лет, ценят качество и сервис, приходят по рекомендации"},
        {"id": "advantages", "label": "Почему клиенты выбирают вас", "type": "textarea", "help": "3–5 причин: опыт, гарантии, цены, скорость…"},
    ]},
    {"id": "task", "title": "Задача сайта", "fields": [
        {"id": "goal", "label": "Главное действие посетителя на сайте", "type": "select", "required": True,
         "options": {g: g for g in GOALS} | {"other": "Другое"}},
        {"id": "goal_other", "label": "Какое действие", "type": "text", "required": True, "show": {"goal": ["other"]}},
        {"id": "kind", "label": "Формат", "type": "radio", "required": True,
         "options": {"landing": "Лендинг — одна страница", "site": "Сайт из нескольких страниц", "unsure": "Не знаю, посоветуйте"}},
        {"id": "pages_wish", "label": "Какие разделы нужны", "type": "text", "show": {"kind": ["site"]},
         "placeholder": "Главная, Услуги, Цены, Врачи, Отзывы, Контакты"},
        {"id": "pages_n", "label": "Сколько примерно страниц", "type": "number", "min_value": 2, "max_value": 30,
         "show": {"kind": ["site"]}},
        {"id": "services", "label": "Услуги или товары и цены, которые показать на сайте", "type": "textarea",
         "placeholder": "Имплантация — от 35 000 ₽\nВиниры — от 25 000 ₽ за зуб…"},
    ]},
    {"id": "style", "title": "Стиль", "fields": [
        {"id": "references", "label": "Сайты, которые вам нравятся, и чем", "type": "textarea", "check": "urls",
         "help": "Ссылки с новой строки. Можно сайты не из вашей сферы.", "placeholder": "https://example.com — нравится спокойный дизайн"},
        {"id": "dislikes", "label": "Что точно не нравится", "type": "textarea", "placeholder": "Яркие цвета, стоковые фото с улыбающимися людьми"},
        {"id": "colors", "label": "Фирменные цвета или пожелания по цветам", "type": "text", "placeholder": "тёмно-синий и белый"},
        {"id": "logo", "label": "Логотип", "type": "file", "help": "PNG, SVG, JPG или WEBP до 5 МБ. Если логотипа нет — пропустите."},
        {"id": "notes", "label": "Ещё пожелания", "type": "textarea",
         "placeholder": "Нужен калькулятор стоимости, онлайн-запись, версия на английском…"},
    ]},
    {"id": "contacts", "title": "Контакты для сайта", "hint": "Эти данные будут опубликованы на сайте.", "fields": [
        {"id": "phone", "label": "Телефон", "type": "text", "check": "phone", "placeholder": "+7 900 000-00-00"},
        {"id": "email", "label": "Почта", "type": "text", "check": "email", "placeholder": "info@example.ru"},
        {"id": "address", "label": "Адрес", "type": "text", "max": 300},
        {"id": "hours", "label": "Часы работы", "type": "text", "placeholder": "Пн–Пт 9:00–20:00, Сб 10:00–16:00"},
        {"id": "messengers", "label": "Мессенджеры и соцсети", "type": "textarea", "placeholder": "Telegram @ulybka, ВКонтакте vk.com/ulybka"},
    ]},
    {"id": "launch", "title": "Оплата и заявки", "hint": "Нужно, если сайт будет принимать оплату или заявки онлайн.", "fields": [
        {"id": "payments_on", "label": "Нужна онлайн-оплата на сайте?", "type": "radio", "required": True, "options": YES},
        {"id": "sells", "label": "Что будут оплачивать", "type": "select", "options": sitelaunch.SELLS,
         "show": {"payments_on": ["yes"]}},
        {"id": "payments", "label": "Платёжный сервис", "type": "select", "show": {"payments_on": ["yes"]},
         "options": {k: v for k, v in sitelaunch.ENUMS["payments"].items() if k != "none"} | {"unknown": "Ещё не выбрали"}},
        {"id": "forms", "label": "Куда присылать заявки с сайта", "type": "select", "options": sitelaunch.FORMS},
        {"id": "domain", "label": "Домен сайта, если есть", "type": "text", "check": "domain", "placeholder": "ulybka-kazan.ru"},
        {"id": "legal", "label": "Кто продаёт", "type": "select", "options": sitelaunch.LEGAL, "show": {"payments_on": ["yes"]}},
        {"id": "legal_name", "label": "Полное наименование / ФИО ИП", "type": "text", "max": 300,
         "show": {"payments_on": ["yes"]}, "placeholder": "ИП Иванов Иван Иванович"},
        {"id": "inn", "label": "ИНН", "type": "text", "check": "inn", "show": {"payments_on": ["yes"]}},
        {"id": "ogrn", "label": "ОГРН / ОГРНИП", "type": "text", "check": "ogrn", "show": {"payments_on": ["yes"]}},
    ]},
    {"id": "person", "title": "Кто заполнил анкету", "fields": [
        {"id": "contact_name", "label": "Ваше имя", "type": "text", "required": True, "max": 120},
        {"id": "contact_phone", "label": "Телефон или мессенджер для связи", "type": "text", "required": True, "max": 120},
    ]},
]
FIELDS = {f["id"]: f for s in SECTIONS for f in s["fields"]}


# ============================================================================= проверки
def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def inn_ok(inn: str) -> bool:
    d = [int(x) for x in _digits(inn)]
    if len(d) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return sum(a * b for a, b in zip(w, d)) % 11 % 10 == d[9]
    if len(d) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        return (sum(a * b for a, b in zip(w1, d)) % 11 % 10 == d[10] and
                sum(a * b for a, b in zip(w2, d)) % 11 % 10 == d[11])
    return False


def ogrn_ok(ogrn: str) -> bool:
    s = _digits(ogrn)
    if len(s) == 13:
        return int(s[:12]) % 11 % 10 == int(s[12])
    if len(s) == 15:
        return int(s[:14]) % 13 % 10 == int(s[14])
    return False


def _visible(f: dict, a: dict) -> bool:
    return all(str(a.get(k, "")) in v for k, v in (f.get("show") or {}).items())


def check(a: dict, logo: dict | None = None) -> dict:
    """Проверка ответов: {поле: [(уровень, текст)]}, уровень — error | warn."""
    out: dict[str, list] = {}

    def add(fid, level, msg):
        out.setdefault(fid, []).append([level, msg])
    for fid, f in FIELDS.items():
        if f["type"] == "file" or not _visible(f, a):
            continue
        v = str(a.get(fid, "") or "").strip()
        if not v:
            if f.get("required"):
                add(fid, "error", "Не заполнено")
            continue
        if f["type"] in ("select", "radio") and v not in f["options"]:
            add(fid, "error", "Значение не из списка")
        if f.get("min") and len(v) < f["min"]:
            add(fid, "warn", f"Слишком коротко ({len(v)} симв.) — для хорошего сайта нужно хотя бы {f['min']}")
        if len(v) > (f.get("max") or MAX_TEXT):
            add(fid, "warn", f"Слишком длинно — обрежется до {f.get('max') or MAX_TEXT} символов")
        if re.fullmatch(r"(.)\1{3,}|(?i:test|тест|asdf|qwerty|йцукен|\.+|-+|нет|no)", v) and f.get("required"):
            add(fid, "warn", "Похоже на заглушку, а не на ответ")
        if f["type"] == "number":
            try:
                n = int(v)
                if not f["min_value"] <= n <= f["max_value"]:
                    add(fid, "error", f"Должно быть от {f['min_value']} до {f['max_value']}")
            except ValueError:
                add(fid, "error", "Нужно число")
        c = f.get("check")
        if c == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}", v):
            add(fid, "error", "Не похоже на адрес почты")
        if c == "phone" and not 10 <= len(_digits(v)) <= 15:
            add(fid, "error", "В телефоне должно быть 10–15 цифр")
        if c == "inn":
            if not inn_ok(v):
                add(fid, "error", "ИНН не проходит проверку контрольной суммы")
            elif a.get("legal") == "ooo" and len(_digits(v)) != 10:
                add(fid, "error", "У ООО ИНН из 10 цифр")
            elif a.get("legal") in ("ip", "npd") and len(_digits(v)) != 12:
                add(fid, "error", "У ИП и самозанятого ИНН из 12 цифр")
        if c == "ogrn":
            if not ogrn_ok(v):
                add(fid, "error", "ОГРН/ОГРНИП не проходит проверку контрольной суммы")
            elif a.get("legal") == "ooo" and len(_digits(v)) != 13:
                add(fid, "warn", "У ООО ОГРН из 13 цифр")
            elif a.get("legal") == "ip" and len(_digits(v)) != 15:
                add(fid, "warn", "У ИП ОГРНИП из 15 цифр")
        if c == "domain" and not re.fullmatch(r"(?:https?://)?(?:[a-zа-яё0-9\-]+\.)+[a-zа-яё]{2,}/?", v.lower()):
            add(fid, "error", "Не похоже на домен (пример: ulybka-kazan.ru)")
        if c == "urls":
            bad = [u for u in re.findall(r"\S+\.\S+", v) if u.startswith(("http", "www")) and not urlparse(
                u if u.startswith("http") else "https://" + u).hostname]
            if bad:
                add(fid, "warn", "Не все ссылки читаются: " + ", ".join(bad[:3]))
            if not re.search(r"https?://|www\.|\w\.(ru|com|рф|net|org|io|by|kz)\b", v):
                add(fid, "warn", "Нет ни одной ссылки — без примеров сложнее попасть в вкус")
    if a.get("payments_on") == "yes":
        if a.get("legal") == "npd" and a.get("payments") in ("tbank", "cloudpayments"):
            add("payments", "warn", "Самозанятым этот сервис обычно недоступен — подойдут Robokassa или ЮKassa")
        for fid in ("legal_name", "inn"):
            if not str(a.get(fid) or "").strip():
                add(fid, "warn", "Понадобится для подключения оплаты")
    if not any(str(a.get(k) or "").strip() for k in ("phone", "email", "messengers")):
        add("phone", "warn", "Нет ни одного контакта для сайта: телефона, почты или мессенджера")
    if logo:
        if Path(logo.get("name", "")).suffix.lower() not in LOGO_EXT:
            add("logo", "error", "Логотип: PNG, SVG, JPG или WEBP")
        elif logo.get("size", 0) > MAX_LOGO:
            add("logo", "error", "Логотип больше 5 МБ")
    return out


# ============================================================================= ответы → бриф
def to_brief(a: dict, p: dict) -> dict:
    """Что анкета предлагает записать в бриф сайта: {поле брифа: значение}."""
    t = lambda k, n=MAX_TEXT: str(a.get(k) or "").strip()[:n]  # noqa: E731
    out = {}
    if t("name"):
        out["name"] = t("name", 120)
    sphere = t("sphere")
    if t("city"):
        sphere += f"\nГород: {t('city')}"
    if sphere.strip():
        out["sphere"] = sphere.strip()
    if t("audience"):
        out["audience"] = t("audience")
    goal = t("goal_other", 200) if a.get("goal") == "other" else t("goal", 200)
    if goal:
        out["goal"] = goal
    if a.get("kind") in ("landing", "site"):
        out["kind"] = a["kind"]
    if a.get("kind") == "site":
        if t("pages_wish"):
            out["pages_wish"] = t("pages_wish", 500)
        try:
            out["pages_n"] = max(2, min(30, int(a.get("pages_n"))))
        except (TypeError, ValueError):
            pass
    if t("references"):
        out["references"] = t("references")
    notes = []
    for k, title in (("advantages", "Почему выбирают"), ("services", "Услуги / товары и цены"), ("dislikes", "Не нравится"),
                     ("colors", "Цвета"), ("notes", "Пожелания"), ("hours", "Часы работы"),
                     ("messengers", "Мессенджеры и соцсети")):
        if t(k):
            notes.append(f"{title}: {t(k)}")
    if a.get("kind") == "unsure":
        notes.append("Формат заказчик не выбрал — просит посоветовать (лендинг или сайт).")
    if notes:
        out["notes"] = "\n".join(notes)[:MAX_TEXT]
    L = sitelaunch.get(p)
    comp = dict(L["company"])
    for k, src in (("legal_name", "legal_name"), ("inn", "inn"), ("ogrn", "ogrn"), ("address", "address"),
                   ("email", "email"), ("phone", "phone")):
        if t(src, 300):
            comp[k] = t(src, 300)
    launch = {**L, "company": comp}
    if a.get("payments_on") == "yes":
        launch["on"] = True
        for k in ("sells", "legal"):
            if a.get(k):
                launch[k] = a[k]
        if a.get("payments") and a["payments"] != "unknown":
            launch["payments"] = a["payments"]
    if a.get("forms"):
        launch["forms"] = a["forms"]
    if t("domain", 120):
        launch["domain"] = t("domain", 120)
    launch = sitelaunch.clean(launch)
    if launch != sitelaunch.clean(L):
        out["launch"] = launch
    return out


BRIEF_LABELS = {"name": "Название", "sphere": "Сфера деятельности", "audience": "Аудитория", "goal": "Главное действие",
                "kind": "Формат", "pages_n": "Страниц", "pages_wish": "Разделы", "references": "Сайты, которые нравятся",
                "notes": "Пожелания", "launch": "Запуск: оплата, заявки, реквизиты", "logo": "Логотип"}
# из каких вопросов анкеты собирается поле брифа — чтобы показать ошибки рядом
SOURCES = {"name": ["name"], "sphere": ["sphere", "city"], "audience": ["audience"], "goal": ["goal", "goal_other"],
           "kind": ["kind"], "pages_n": ["pages_n"], "pages_wish": ["pages_wish"], "references": ["references"],
           "notes": ["advantages", "services", "dislikes", "colors", "notes", "hours", "messengers"],
           "launch": ["payments_on", "sells", "payments", "forms", "domain", "legal", "legal_name", "inn", "ogrn",
                      "address", "email", "phone"], "logo": ["logo"]}


def _launch_text(L: dict) -> str:
    if not L:
        return ""
    E = sitelaunch.ENUMS
    parts = [("оплата онлайн: " + E["payments"].get(L.get("payments"), "")) if L.get("on") else "без онлайн-оплаты",
             "заявки: " + E["forms"].get(L.get("forms"), "")]
    if L.get("on"):
        parts.append(E["legal"].get(L.get("legal"), ""))
    if L.get("domain"):
        parts.append("домен " + L["domain"])
    c = L.get("company") or {}
    parts += [x for x in (c.get("legal_name"), c.get("inn") and "ИНН " + c["inn"], c.get("ogrn") and "ОГРН " + c["ogrn"],
                          c.get("address"), c.get("email"), c.get("phone")) if x]
    return " · ".join(x for x in parts if x)


def _show(k, v) -> str:
    if k == "launch":
        return _launch_text(v)
    if k == "kind":
        return {"landing": "лендинг", "site": "сайт из нескольких страниц"}.get(v, str(v or ""))
    return str(v if v is not None else "")


# ============================================================================= хранение
def _dir(sid: str) -> Path:
    d = sitelab.pdir(sid) / "form"
    d.mkdir(parents=True, exist_ok=True)
    return d


_sends: dict[str, list] = {}


def rate_ok(ip: str, per_hour: int = 20) -> bool:
    """Не больше per_hour отправок анкеты в час с одного адреса."""
    now = time.time()
    r = [t for t in _sends.get(ip, []) if now - t < 3600]
    if len(_sends) > 5000:
        _sends.clear()
    _sends[ip] = r + [now]
    return len(r) < per_hour


def token(sid: str, renew=False) -> str:
    p = sitelab.load(sid)
    f = p.get("form") or {}
    if renew or not f.get("token"):
        f = {**f, "token": secrets.token_urlsafe(18), "created": datetime.now().isoformat(timespec="seconds")}
        sitelab.update(sid, lambda x: x.__setitem__("form", f))
    return f["token"]


def by_token(tok: str) -> str | None:
    if not re.fullmatch(r"[\w\-]{16,64}", tok or ""):
        return None
    for p in sitelab.list_projects(None):
        f = (sitelab.load(p["id"]).get("form") or {})
        if f.get("token") and secrets.compare_digest(f["token"], tok):
            return p["id"]
    return None


def public_url(sid: str) -> str:
    tok = token(sid)
    for h in (settings().get("ALLOWED_HOSTS") or "").split(","):
        if h.strip():
            return f"https://{h.strip()}/form/{tok}"
    return f"http://localhost:{settings().get('PORT') or 8765}/form/{tok}"


def _clean_answers(raw: dict) -> dict:
    a = raw.get("answers") if isinstance(raw.get("answers"), dict) else {}
    out = {}
    for fid, f in FIELDS.items():
        if f["type"] == "file":
            continue
        v = a.get(fid)
        if v is None:
            continue
        out[fid] = str(v)[: (f.get("max") or MAX_TEXT) + 1000]   # с запасом — чтобы проверка увидела «слишком длинно»
    return out


def save_answers(sid: str, raw: dict, via: str) -> dict:
    """Сохранить ответы (из файла или по ссылке). Логотип декодируется и проверяется отдельно."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ValueError("Это не файл ответов анкеты студии")
    sitelab.load(sid)
    a = _clean_answers(raw)
    if not any(a.values()):
        raise ValueError("Анкета пустая")
    logo = None
    lg = raw.get("logo")
    if isinstance(lg, dict) and lg.get("data"):
        name = re.sub(r"[^\w.\-]+", "_", str(lg.get("name") or "logo.png"))[:80]
        data = str(lg["data"]).split(",", 1)[-1]
        if len(data) > MAX_LOGO * 4 // 3 + 16:
            logo = {"name": name, "size": MAX_LOGO + 1}
        else:
            try:
                blob = base64.b64decode(data, validate=True)
            except ValueError:
                raise ValueError("Логотип в анкете повреждён") from None
            ext = Path(name).suffix.lower()
            logo = {"name": name, "size": len(blob)}
            if ext in LOGO_EXT and len(blob) <= MAX_LOGO:
                d = _dir(sid)
                for old in d.glob("logo.*"):
                    old.unlink()
                (d / f"logo{ext}").write_bytes(blob)
                logo["file"] = f"logo{ext}"
    rec = {"format": FORMAT, "received": datetime.now().isoformat(timespec="seconds"), "via": via,
           "submitted": str(raw.get("submitted") or "")[:40], "answers": a, "logo": logo}
    d = _dir(sid)
    f = d / "answers.json"
    if f.exists():
        f.replace(d / f"answers-{int(time.time())}.json")
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    sitelab.update(sid, lambda x: x.__setitem__("form", {**(x.get("form") or {}), "received": rec["received"],
                                                          "via": via, "applied": None}))
    return review(sid)


def load_answers(sid: str) -> dict | None:
    f = sitelab.pdir(sid) / "form" / "answers.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def review(sid: str) -> dict:
    """Ответы, ошибки и что именно изменится в брифе — для экрана проверки."""
    p = sitelab.load(sid)
    info = {"form": p.get("form") or {}, "answers": None}
    rec = load_answers(sid)
    if not rec:
        return info
    a = rec["answers"]
    issues = check(a, rec.get("logo"))
    prop = to_brief(a, p)
    if (rec.get("logo") or {}).get("file"):
        prop["logo"] = rec["logo"]["name"]
    rows = []
    for k, v in prop.items():
        cur = p.get(k) if k != "launch" else sitelaunch.clean(sitelaunch.get(p))
        errs = [m for src in SOURCES.get(k, []) for m in issues.get(src, [])]
        rows.append({"key": k, "label": BRIEF_LABELS.get(k, k), "new": _show(k, v), "cur": _show(k, cur) if k != "logo" else (p.get("logo") or ""),
                     "same": (cur == v) if k != "logo" else False, "issues": errs,
                     "ok": not any(e[0] == "error" for e in errs)})
    qa = [{"section": s["title"], "items": [{"id": f["id"], "label": f["label"],
                                             "value": (rec.get("logo") or {}).get("name", "") if f["type"] == "file" else
                                             _answer_text(f, a.get(f["id"], "")),
                                             "issues": issues.get(f["id"], [])}
                                            for f in s["fields"] if _visible(f, a)]} for s in SECTIONS]
    n_err = sum(1 for v in issues.values() for m in v if m[0] == "error")
    n_warn = sum(1 for v in issues.values() for m in v if m[0] == "warn")
    return {**info, "answers": qa, "rows": rows, "received": rec["received"], "via": rec["via"],
            "who": " · ".join(x for x in (a.get("contact_name"), a.get("contact_phone")) if x), "errors": n_err, "warnings": n_warn}


def _answer_text(f, v) -> str:
    v = str(v or "")
    return str(f.get("options", {}).get(v, v)) if f["type"] in ("select", "radio") else v


def apply(sid: str, keys: list[str]) -> dict:
    """Перенести выбранные поля анкеты в бриф."""
    rec = load_answers(sid)
    if not rec:
        raise ValueError("Ответов анкеты нет")
    p = sitelab.load(sid)
    prop = to_brief(rec["answers"], p)
    data = {k: v for k, v in prop.items() if k in keys and k != "logo"}
    if data:
        if "kind" in data and data["kind"] == "landing":
            data["pages_n"] = 1
        sitelab.update_brief(sid, data)
    lg = rec.get("logo") or {}
    if "logo" in keys and lg.get("file"):
        f = _dir(sid) / lg["file"]
        if f.exists():
            sitelab.add_logo(sid, lg["file"], f.read_bytes())
    sitelab.update(sid, lambda x: x.__setitem__("form", {**(x.get("form") or {}),
                                                          "applied": datetime.now().isoformat(timespec="seconds")}))
    return sitelab.load(sid)


def clear(sid: str):
    d = sitelab.pdir(sid) / "form"
    for f in ("answers.json",):
        if (d / f).exists():
            (d / f).replace(d / f"answers-{int(time.time())}.json")
    sitelab.update(sid, lambda x: x.__setitem__("form", {**(x.get("form") or {}), "received": None, "applied": None}))


def import_file(raw: dict, lab: str | None) -> dict:
    """Файл ответов на главной лаборатории: в свой сайт, если он есть, иначе — новый сайт в текущем направлении."""
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ValueError("Это не файл ответов анкеты студии")
    sid = str(raw.get("site") or "")
    try:
        sitelab.load(sid)
        created = False
    except Exception:
        name = str((raw.get("answers") or {}).get("name") or "Новый заказчик")[:120]
        sid = sitelab.create({"name": name, "lab": lab})["id"]
        created = True
    save_answers(sid, raw, "файл")
    return {"site": sid, "created": created}


# ============================================================================= страница анкеты
TEMPLATE = Path(__file__).with_name("form_template.html")


def page(sid: str, mode: str) -> str:
    """HTML анкеты. mode: file — для отправки файлом, link — открывается по ссылке студии."""
    p = sitelab.load(sid)
    sphere, _, city = (p.get("sphere") or "").partition("\nГород: ")    # город при переносе дописывается к сфере
    pre = {"name": p.get("name") if p.get("name") not in ("Новый сайт", "Новый заказчик") else "",
           "sphere": sphere.strip(), "city": city.strip(), "audience": p.get("audience") or ""}
    cfg = {"format": FORMAT, "site": sid, "mode": mode, "token": token(sid) if mode == "link" else "",
           "sections": SECTIONS, "prefill": {k: v for k, v in pre.items() if v},
           "title": p.get("name") if pre["name"] else "", "max_logo": MAX_LOGO}
    data = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__CONFIG__*/null", data)


def file_path(sid: str) -> Path:
    p = sitelab.load(sid)
    f = _dir(sid) / f"Анкета — {re.sub(r'[^0-9A-Za-zА-Яа-яЁё]+', ' ', p.get('name') or 'сайт').strip()[:60] or 'сайт'}.html"
    for old in _dir(sid).glob("Анкета — *.html"):
        old.unlink()
    f.write_text(page(sid, "file"), encoding="utf-8")
    sitelab.update(sid, lambda x: x.__setitem__("form", {**(x.get("form") or {}),
                                                          "downloaded": datetime.now().isoformat(timespec="seconds")}))
    return f
