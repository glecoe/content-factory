"""Лаборатория сайтов · статистика сайтов для «Админки»: посещения, интересы, заявки, продажи.

Откуда берутся данные:
- счётчик на собранном сайте (скрипт из STATS.md пакета промптов) шлёт события на POST /collect студии:
  view (просмотр страницы), interest (клик по элементу с data-interest), lead (заявка отправлена);
- продажа (order) приходит только с сервера сайта — из вебхука об успешной оплате, с секретным ключом;
- офлайн-продажи и заявки владелец добавляет руками в админке;
- демо-данные — для показа админки до запуска сайта; помечены demo и удаляются одной кнопкой.

Данные: data/sites/<id>/stats/events.jsonl (одна строка — одно событие). Ключи сайта — в project.json (stats).
Личные данные посетителей не собираются: только случайный id браузера, страница, источник и метка интереса.
"""
from __future__ import annotations

import hmac
import json
import random
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import sitelab
from .config import settings

_lock = threading.RLock()
TYPES = ("view", "interest", "lead", "order")
MAX_FILE = 50 * 1024 * 1024          # потолок файла событий одного сайта: дальше счётчик молча не пишет
_rate: dict[str, list] = {}          # ip -> [окно, кол-во]
RATE_PER_MIN = 240


def _file(sid: str) -> Path:
    return sitelab.pdir(sid) / "stats" / "events.jsonl"


def keys(sid: str) -> dict:
    """Ключи счётчика сайта (создаются при первом обращении): key — публичный, secret — только для сервера сайта."""
    p = sitelab.load(sid)
    k = p.get("stats") or {}
    if not (k.get("key") and k.get("secret")):
        k = {"key": secrets.token_urlsafe(12), "secret": secrets.token_urlsafe(24)}
        sitelab.update(sid, lambda x: x.__setitem__("stats", k))
    return k


def collect_url() -> str:
    """Адрес приёма событий: первый домен из ALLOWED_HOSTS (студия на сервере), иначе заглушка."""
    for h in (settings().get("ALLOWED_HOSTS") or "").split(","):
        h = h.strip()
        if h:
            return f"https://{h}/collect"
    return "https://studio.example.com/collect"


def _clip(v, n=120) -> str:
    return str(v or "").replace("\n", " ").strip()[:n]


def _source(d: dict) -> str:
    if d.get("utm"):
        return _clip(d["utm"], 40).lower()
    host = (urlparse(str(d.get("ref") or "")).hostname or "").lower()
    if not host:
        return "прямой заход"
    for k, name in (("yandex", "Яндекс"), ("google", "Google"), ("vk.", "ВКонтакте"), ("vk.com", "ВКонтакте"),
                    ("t.me", "Telegram"), ("telegram", "Telegram"), ("instagram", "Instagram"), ("2gis", "2ГИС"),
                    ("avito", "Авито"), ("mail.ru", "Mail.ru")):
        if k in host:
            return name
    return host.removeprefix("www.")[:40]


def _append(sid: str, ev: dict):
    f = _file(sid)
    with _lock:
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists() and f.stat().st_size > MAX_FILE:
            return
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def rate_ok(ip: str) -> bool:
    now = int(time.time() // 60)
    with _lock:
        r = _rate.get(ip)
        if not r or r[0] != now:
            if len(_rate) > 20000:
                _rate.clear()
            r = _rate[ip] = [now, 0]
        r[1] += 1
        return r[1] <= RATE_PER_MIN


def collect(d: dict) -> bool:
    """Событие со счётчика или с сервера сайта. False — отклонено (неизвестный сайт, неверный ключ, мусор)."""
    sid, typ = str(d.get("site") or ""), str(d.get("type") or "")
    if typ not in TYPES:
        return False
    try:
        p = sitelab.load(sid)
    except Exception:
        return False
    k = p.get("stats") or {}
    if typ == "order":     # продажа — только с сервера сайта, по секретному ключу
        if not k.get("secret") or not hmac.compare_digest(str(d.get("secret") or "").encode(), k["secret"].encode()):
            return False
    elif not k.get("key") or not hmac.compare_digest(str(d.get("key") or "").encode(), k["key"].encode()):
        return False
    ev = {"ts": round(time.time(), 1), "type": typ, "page": _clip(d.get("page"), 80) or "/",
          "src": _source(d), "vid": _clip(d.get("vid"), 24)}
    if typ == "interest":
        ev["label"] = _clip(d.get("label"), 60)
        if not ev["label"]:
            return False
    if typ == "lead":
        ev["label"] = _clip(d.get("form") or d.get("label"), 60)
    if typ == "order":
        try:
            ev["amount"] = max(0.0, min(float(d.get("amount") or 0), 1e9))
        except (TypeError, ValueError):
            return False
        ev["label"] = _clip(d.get("label") or d.get("items"), 80)
        ev["order"] = _clip(d.get("order"), 40)
    _append(sid, ev)
    return True


def add_manual(sid: str, data: dict) -> dict:
    """Продажа или заявка, внесённая владельцем (офлайн, по телефону, из мессенджера)."""
    sitelab.load(sid)
    typ = data.get("type")
    if typ not in ("order", "lead"):
        raise ValueError("Можно добавить продажу или заявку")
    day = str(data.get("date") or "")[:10]
    try:
        ts = datetime.fromisoformat(day).replace(hour=12).timestamp() if day else time.time()
    except ValueError:
        raise ValueError("Дата в формате ГГГГ-ММ-ДД") from None
    ev = {"ts": round(ts, 1), "type": typ, "page": "", "src": _clip(data.get("src"), 40) or "вручную",
          "label": _clip(data.get("label"), 80), "manual": True}
    if typ == "order":
        try:
            ev["amount"] = max(0.0, float(str(data.get("amount") or 0).replace(",", ".").replace(" ", "")))
        except ValueError:
            raise ValueError("Сумма — числом") from None
    _append(sid, ev)
    return ev


def events(sid: str, since: float = 0) -> list[dict]:
    f = _file(sid)
    out = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("ts", 0) >= since:
                out.append(e)
    return out


# ----------------------------------------------------------------------------- демо-данные
DEMO_INTERESTS = ["Цены", "Услуги", "Портфолио", "Отзывы", "Акция месяца", "Консультация", "Доставка", "Гарантия",
                  "Контакты", "О компании"]
DEMO_SOURCES = [("Яндекс", 34), ("прямой заход", 22), ("Google", 12), ("ВКонтакте", 10), ("Telegram", 9),
                ("2ГИС", 7), ("Авито", 6)]
DEMO_PAGES = ["/", "/uslugi", "/ceny", "/portfolio", "/kontakty", "/otzyvy"]


def demo(sid: str, days: int = 30) -> int:
    """Правдоподобные события за последние days дней (помечены demo)."""
    p = sitelab.load(sid)
    rnd = random.Random(sid + str(time.time()))
    base = rnd.randint(25, 140)
    price = rnd.choice([1900, 3500, 4900, 7500, 12000, 24000])
    interests = rnd.sample(DEMO_INTERESTS, 7)
    weights = [rnd.random() ** 1.6 + 0.05 for _ in interests]
    pages = DEMO_PAGES if p.get("kind") != "landing" else ["/"]
    src_names, src_w = zip(*DEMO_SOURCES)
    rows, now = [], datetime.now()
    for back in range(days - 1, -1, -1):
        day = now - timedelta(days=back)
        growth = 0.7 + 0.6 * (days - back) / max(days, 1)
        weekend = 0.75 if day.weekday() >= 5 else 1.0
        visitors = max(1, int(base * growth * weekend * rnd.uniform(0.75, 1.25)))
        for _ in range(visitors):
            vid = secrets.token_hex(6)
            ts = day.replace(hour=rnd.randint(8, 23), minute=rnd.randint(0, 59), second=0).timestamp()
            if ts > time.time():
                ts = time.time() - rnd.randint(60, 3600)
            src = rnd.choices(src_names, src_w)[0]
            for page in rnd.sample(pages, min(len(pages), rnd.choice([1, 1, 2, 3]))):
                rows.append({"ts": ts, "type": "view", "page": page, "src": src, "vid": vid, "demo": True})
            if rnd.random() < 0.35:
                rows.append({"ts": ts + 20, "type": "interest", "page": "/", "src": src, "vid": vid, "demo": True,
                             "label": rnd.choices(interests, weights)[0]})
            if rnd.random() < 0.045:
                rows.append({"ts": ts + 60, "type": "lead", "page": "/", "src": src, "vid": vid, "demo": True,
                             "label": "Форма заявки"})
            if rnd.random() < 0.02:
                rows.append({"ts": ts + 90, "type": "order", "page": "/", "src": src, "vid": vid, "demo": True,
                             "amount": float(round(price * rnd.uniform(0.6, 2.2), -1)),
                             "label": rnd.choices(interests, weights)[0], "order": "demo-" + secrets.token_hex(3)})
    rows.sort(key=lambda e: e["ts"])
    f = _file(sid)
    with _lock:
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fh:
            for e in rows:
                e["ts"] = round(e["ts"], 1)
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return len(rows)


def clear_demo(sid: str) -> int:
    f = _file(sid)
    with _lock:
        if not f.exists():
            return 0
        keep, n = [], 0
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("demo"):
                    n += 1
                    continue
            except Exception:
                pass
            keep.append(line)
        f.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
        return n


# ----------------------------------------------------------------------------- сводка для админки
def _totals(evs: list[dict]) -> dict:
    views = [e for e in evs if e["type"] == "view"]
    visitors = len({e.get("vid") for e in views if e.get("vid")}) or len(views)
    leads = sum(1 for e in evs if e["type"] == "lead")
    orders = [e for e in evs if e["type"] == "order"]
    revenue = round(sum(e.get("amount", 0) for e in orders), 2)
    return {"views": len(views), "visitors": visitors, "leads": leads, "orders": len(orders), "revenue": revenue,
            "avg_check": round(revenue / len(orders), 2) if orders else 0,
            "interests": sum(1 for e in evs if e["type"] == "interest"),
            # конверсия — только по действиям на сайте: ручные продажи и заявки посетителей сайта не добавляют
            "conversion": round(100 * sum(1 for e in evs if e["type"] in ("lead", "order") and not e.get("manual"))
                                / visitors, 2) if visitors else 0}


def _top(counter: dict, n=10) -> list:
    return [{"name": k, "n": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])[:n]]


def summary(lab: str | None, days: int = 30, site: str = "") -> dict:
    """Сводка по сайтам направления (lab="__all__" — по всем) за последние days дней и сравнение с предыдущими."""
    days = max(1, min(int(days or 30), 365))
    start = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time()).timestamp()
    prev_start = start - days * 86400
    projects = sitelab.list_projects(lab)
    labs = {l["id"]: l["name"] for l in sitelab.list_labs()}
    cur_all, prev_all, rows = [], [], []
    for p in projects:
        if site and p["id"] != site:
            continue
        evs = events(p["id"], prev_start)
        cur = [e for e in evs if e["ts"] >= start]
        prev = [e for e in evs if e["ts"] < start]
        cur_all += [dict(e, site=p["id"]) for e in cur]
        prev_all += prev
        t = _totals(cur)
        rows.append({"id": p["id"], "name": p["name"], "lab": labs.get(p["lab"], p["lab"]), "stage": p["stage"],
                     "logo": p.get("logo"), **t, "last": max((e["ts"] for e in evs), default=None),
                     "demo": any(e.get("demo") for e in cur),
                     "connected": bool(sitelab.load(p["id"]).get("stats"))})
    rows.sort(key=lambda r: (-r["revenue"], -r["views"]))
    series = {}
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        series[d] = {"date": d, "views": 0, "visitors": set(), "leads": 0, "orders": 0, "revenue": 0.0}
    interests, sources, pages, products = {}, {}, {}, {}
    for e in cur_all:
        d = series.get(date.fromtimestamp(e["ts"]).isoformat())
        t = e["type"]
        if t == "view":
            pages[e.get("page") or "/"] = pages.get(e.get("page") or "/", 0) + 1
            if e.get("vid") and d:
                d["visitors"].add(e["vid"])
            if d:
                d["views"] += 1
            # источник считаем по уникальным посетителям, а не по просмотрам
            sources.setdefault(e.get("src") or "прямой заход", set()).add(e.get("vid") or id(e))
        elif t == "interest":
            interests[e.get("label") or "—"] = interests.get(e.get("label") or "—", 0) + 1
        elif t == "lead" and d:
            d["leads"] += 1
        elif t == "order":
            if d:
                d["orders"] += 1
                d["revenue"] += e.get("amount", 0)
            if e.get("label"):
                products[e["label"]] = products.get(e["label"], 0) + e.get("amount", 0)
    for d in series.values():
        d["visitors"] = len(d["visitors"])
        d["revenue"] = round(d["revenue"], 2)
    recent = sorted((e for e in cur_all if e["type"] in ("order", "lead")), key=lambda e: -e["ts"])[:15]
    names = {p["id"]: p["name"] for p in projects}
    return {"days": days, "totals": _totals(cur_all), "prev": _totals(prev_all), "sites": rows,
            "series": list(series.values()), "interests": _top(interests), "sources": _top({k: len(v) for k, v in sources.items()}),
            "pages": _top(pages, 8), "products": [{"name": x["name"], "n": round(x["n"], 2)} for x in _top(products, 8)],
            "recent": [{"ts": e["ts"], "type": e["type"], "site": names.get(e["site"], e["site"]), "label": e.get("label", ""),
                        "amount": e.get("amount"), "src": e.get("src"), "manual": bool(e.get("manual")),
                        "demo": bool(e.get("demo"))} for e in recent],
            "has_demo": any(r["demo"] for r in rows)}


def site_info(sid: str) -> dict:
    """Подключение счётчика: адрес, ключи и готовый код для сайта."""
    k = keys(sid)
    return {"url": collect_url(), "key": k["key"], "secret": k["secret"], "snippet": snippet(sid, k["key"]),
            "server": server_example(sid)}


def snippet(sid: str, key: str) -> str:
    url = collect_url()
    return f"""<script>
/* Счётчик студии: просмотры, интересы (data-interest) и заявки. Без cookies и личных данных. */
(function () {{
  var U = {json.dumps(url)}, S = {json.dumps(sid)}, K = {json.dumps(key)}, vid;
  try {{ vid = localStorage.getItem("st_vid") || Math.random().toString(36).slice(2, 14); localStorage.setItem("st_vid", vid); }}
  catch (e) {{ vid = Math.random().toString(36).slice(2, 14); }}
  var utm = new URLSearchParams(location.search).get("utm_source") || "";
  function send(type, data) {{
    var d = data || {{}}; d.site = S; d.key = K; d.type = type; d.vid = vid; d.page = location.pathname;
    d.ref = document.referrer; d.utm = utm;
    var b = JSON.stringify(d);
    if (!(navigator.sendBeacon && navigator.sendBeacon(U, b))) fetch(U, {{ method: "POST", body: b, keepalive: true, mode: "no-cors" }}).catch(function () {{}});
  }}
  window.studioStats = send;
  send("view");
  document.addEventListener("click", function (e) {{
    var el = e.target.closest && e.target.closest("[data-interest]");
    if (el) send("interest", {{ label: el.getAttribute("data-interest") }});
  }});
}})();
</script>"""


def server_example(sid: str) -> str:
    return f"""// На сервере сайта, после подтверждённой оплаты (вебхук payment.succeeded и т.п.):
await fetch(process.env.STUDIO_STATS_URL, {{   // {collect_url()}
  method: "POST",
  body: JSON.stringify({{ site: "{sid}", secret: process.env.STUDIO_STATS_SECRET, type: "order",
                         amount: 4900, order: orderId, label: "Название товара или услуги" }}),
}}).catch(() => {{}});   // статистика не должна ломать оплату"""


def pack_text(sid: str) -> str:
    """STATS.md для пакета промптов: как встроить счётчик в сайт."""
    k = keys(sid)
    return f"""# Статистика для админки студии

Встрой счётчик студии — по нему владелец видит в «Админке» посещения, интересы, заявки и продажи.

## 1. Счётчик на каждой странице
Вставь перед `</body>` каждой страницы (в Next.js — один раз в корневом layout через `next/script`,
`strategy="afterInteractive"`, содержимое — тело скрипта без тегов):

```html
{snippet(sid, k['key'])}
```

Если у сайта есть Content-Security-Policy — добавь домен `{urlparse(collect_url()).hostname}` в `connect-src`.

## 2. Интересы
Повесь `data-interest="<понятное название>"` на ключевые элементы: карточки и кнопки услуг/товаров, тарифы,
«Подробнее», вкладки, кнопки мессенджеров и телефона. Название — по-русски, как его поймёт владелец
(например `data-interest="Имплантация"`, `data-interest="Тариф Стандарт"`, `data-interest="Звонок"`).

## 3. Заявки
После УСПЕШНОЙ отправки любой формы вызови `window.studioStats && window.studioStats("lead", {{ form: "<название формы>" }})`.
Личные данные (имя, телефон, почту) в счётчик НЕ передавай.

## 4. Продажи (только если на сайте есть онлайн-оплата и сервер)
В обработчике подтверждённой оплаты на сервере (не в браузере!) отправь событие продажи. Ключ — из переменных окружения,
в код и в репозиторий его не пиши:

```js
{server_example(sid)}
```

В `.env.example` добавь `STUDIO_STATS_URL={collect_url()}` и `STUDIO_STATS_SECRET=` (значение владелец возьмёт в «Админке» студии).
"""


def write_pack_file(sid: str):
    d = sitelab.pdir(sid) / "prompts"
    if d.exists():
        (d / "STATS.md").write_text(pack_text(sid), encoding="utf-8")
