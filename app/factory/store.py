"""Simple file storage: every product is a folder with product.json."""
from __future__ import annotations
import json
import re
import threading
import time
import uuid
from datetime import datetime, date
from pathlib import Path

from .config import PRODUCTS, DATA

_lock = threading.RLock()
COSTS = DATA / "costs.jsonl"
RATINGS = DATA / "ratings.jsonl"
TASTE = DATA / "taste.md"


def _slug(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return (t[:30] or "ring") + "-" + uuid.uuid4().hex[:6]


def pdir(pid: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", pid or ""):
        raise ValueError("bad product id")
    return PRODUCTS / pid


def list_products(niche: str | None = "__all__"):
    """Изделия; niche=None/"__all__" — все, иначе только этой ниши (старые без ниши = jewelry)."""
    out = []
    for d in sorted(PRODUCTS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        f = d / "product.json"
        if f.exists():
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                n = p.get("niche") or "jewelry"
                if niche not in (None, "__all__") and n != niche:
                    continue
                out.append({"id": p["id"], "name": p.get("name"), "price": p.get("price"), "niche": n,
                            "videos": len(p.get("videos", [])), "clips": len(p.get("clips", []))})
            except Exception:
                pass
    return out


def create_product(data: dict) -> dict:
    with _lock:
        pid = _slug(data.get("name") or "ring")
        d = pdir(pid)
        for sub in ("inputs", "prepared", "clips", "videos", "frames", "cards"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        p = {
            "id": pid, "created": datetime.now().isoformat(timespec="seconds"),
            "name": data.get("name", ""), "description_ru": data.get("description_ru", ""),
            "visual_en": data.get("visual_en", ""), "price": data.get("price", ""),
            "promo": data.get("promo", ""), "link": data.get("link", ""),
            "brand": data.get("brand", ""), "niche": _niche_id(data.get("niche")),
            "photos": [], "video": None, "concepts": [], "clips": [], "videos": [], "qa": {},
        }
        save_product(p)
        return p


def load_product(pid: str) -> dict:
    return json.loads((pdir(pid) / "product.json").read_text(encoding="utf-8"))


def save_product(p: dict):
    with _lock:
        f = pdir(p["id"]) / "product.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)


def update_product(pid: str, fn):
    """Atomic read-modify-write."""
    with _lock:
        p = load_product(pid)
        fn(p)
        save_product(p)
        return p


# ---------------- costs ----------------
def log_cost(kind: str, usd: float, product: str = "", detail: str = ""):
    with _lock:
        with COSTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "date": date.today().isoformat(), "kind": kind,
                                 "usd": round(usd, 4), "product": product, "detail": detail},
                                ensure_ascii=False) + "\n")


def costs_summary():
    total = today = 0.0
    by_kind, by_product, rows = {}, {}, []
    if COSTS.exists():
        for line in COSTS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows.append(r)
            total += r["usd"]
            if r["date"] == date.today().isoformat():
                today += r["usd"]
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + r["usd"]
            if r.get("product"):
                by_product[r["product"]] = by_product.get(r["product"], 0) + r["usd"]
    return {"total": round(total, 2), "today": round(today, 2),
            "by_kind": {k: round(v, 2) for k, v in by_kind.items()},
            "by_product": {k: round(v, 2) for k, v in by_product.items()},
            "last": rows[-15:][::-1]}


def spent_today() -> float:
    return costs_summary()["today"]


# ---------------- ratings & taste ----------------
def _niche_id(nid=None) -> str:
    from . import niches
    return niches.resolve(nid)


def niche_of(pid: str) -> str:
    try:
        return load_product(pid).get("niche") or "jewelry"
    except Exception:
        return _niche_id(None)


def add_rating(r: dict):
    from . import niches
    r = dict(r)
    r["ts"] = time.time()
    r["niche"] = _niche_id(r.get("niche"))
    with _lock:
        with niches.ratings_path(r["niche"]).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def ratings(niche: str | None = None):
    from . import niches
    f = niches.ratings_path(_niche_id(niche))
    out = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    # последний голос по ролику — главный
    latest = {}
    for r in out:
        latest[(r.get("product"), r.get("video"))] = r
    return list(latest.values())


TASTE_DEFAULT = Path(__file__).with_name("taste_default.md")


def taste_text(niche: str | None = None) -> str:
    """Профиль вкуса ниши; пока своего нет — стартовый."""
    from . import niches
    f = niches.taste_path(niche)
    if f.exists() and f.read_text(encoding="utf-8").strip():
        return f.read_text(encoding="utf-8")
    if _niche_id(niche) == "jewelry" and TASTE_DEFAULT.exists():
        return TASTE_DEFAULT.read_text(encoding="utf-8")
    return niches.TASTE_GENERIC


def save_taste(text: str, niche: str | None = None):
    from . import niches
    niches.taste_path(niche).write_text(text, encoding="utf-8")
