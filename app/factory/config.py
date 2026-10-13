"""Paths, settings (.env) and the catalog of video models with prices."""
from __future__ import annotations
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # content-factory/
APP = ROOT / "app"
DATA = ROOT / "data"
PRODUCTS = DATA / "products"
MUSIC = DATA / "music"
RESEARCH = DATA / "research"
LIBRARY = ROOT / "library"                          # библиотека съёмки «По изделиям» (в git через LFS)
SITES = DATA / "sites"
ENV_FILE = ROOT / ".env"

for p in (DATA, PRODUCTS, MUSIC, RESEARCH, RESEARCH / "refs", RESEARCH / "briefs", SITES):
    p.mkdir(parents=True, exist_ok=True)

# Роли «мозгов» и провайдер по умолчанию. claude = подписка через Claude Code (OAuth), gemini = Gemini API.
ROLES = {
    "scenario": ("Сценарист", "claude"),
    "research": ("Ресёрч трендов", "claude"),
    "montage": ("Монтажёр (план)", "claude"),
    "taste": ("Куратор вкуса", "claude"),
    "publish": ("Тексты публикаций", "claude"),
    "passport": ("Паспорт изделия по фото", "gemini"),
    # Лаборатория сайтов
    "site_brand": ("Сайты · бренд-кит", "claude"),
    "site_research": ("Сайты · ресёрч", "claude"),
    "site_strategy": ("Сайты · стратег и превью", "claude"),
    "site_prompt": ("Сайты · автор промптов", "claude"),
}

DEFAULTS = {
    "FAL_KEY": "",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-3.8-flash",
    "DEMO_MODE": "1",            # 1 = клипы собираются из фото через FFmpeg, без fal.ai
    "DAILY_LIMIT_USD": "10",     # защита от случайных трат
    "USD_RUB": "84.41",
    # Claude через подписку (Claude Code CLI)
    "CLAUDE_BIN": "",            # путь к claude; пусто = найти автоматически
    "CLAUDE_MODEL": "opus",      # opus | sonnet | haiku | полное имя модели
    "CLAUDE_CODE_OAUTH_TOKEN": "",   # для сервера: токен из `claude setup-token`
    **{f"PROVIDER_{r.upper()}": d for r, (_, d) in ROLES.items()},
    # Конвейер
    "CONCEPTS_N": "3",
    "AUTO_RETRY": "1",           # сколько раз переделывать кадр, который контролёр забраковал
    "VERTICAL_MODE": "nb2",      # nb2 = дорисовать фото до 9:16 (Nano Banana 2), blur = размытый фон, off
    "MONTAGE_FIT": "crop",       # crop = обрезать под 9:16, blur = вписать на размытый фон
    "APIFY_TOKEN": "",
    "LIBRARY_DIR": "",           # своя папка библиотеки; пусто = library/ в проекте
    # Лаборатория сайтов
    "SITE_SHOTS": "1",           # 1 = делать скриншоты сайтов-референсов (нужен Playwright)
    "SITE_BUILD_TURNS": "150",   # шагов Claude Code на одну сессию сборки
    "SITE_BUILD_MINUTES": "45",  # минут на одну сессию сборки; потом — автоматическое продолжение
    "SITE_BUILD_RESUMES": "3",   # сколько раз продолжать прерванную сборку автоматически
    "SITE_BUILD_MODEL": "sonnet",  # модель для сборки кода: sonnet — быстрее, opus — тщательнее
    # Сервер
    "HOST": "127.0.0.1",
    "PORT": "8765",
    "AUTH_USER": "admin",
    "AUTH_PASSWORD": "",
    "ALLOWED_HOSTS": "",         # домены/адреса, по которым открывают студию на сервере (через запятую), напр. studio.example.com
    "PUBLIC_HTTP": "0",          # 1 = разрешить HOST=0.0.0.0 без HTTPS-прокси (не рекомендуется)
}

SECRET_KEYS = {"FAL_KEY", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "APIFY_TOKEN", "AUTH_PASSWORD"}

# Эти настройки меняются ТОЛЬКО руками в .env (или переменными окружения CF_*), не через интерфейс/API:
# они управляют запуском программ, доступом к файлам и открытием сервера в сеть.
ENV_ONLY = {"CLAUDE_BIN", "LIBRARY_DIR", "HOST", "PORT", "AUTH_USER", "AUTH_PASSWORD", "ALLOWED_HOSTS", "PUBLIC_HTTP"}

_ENUMS = {"DEMO_MODE": {"0", "1"}, "SITE_SHOTS": {"0", "1"}, "VERTICAL_MODE": {"nb2", "blur", "off"},
          "MONTAGE_FIT": {"crop", "blur"}, **{f"PROVIDER_{r.upper()}": {"claude", "gemini"} for r in ROLES}}
_NUMS = {"DAILY_LIMIT_USD": (0, 10000), "USD_RUB": (1, 100000), "CONCEPTS_N": (1, 12), "AUTO_RETRY": (0, 5),
         "SITE_BUILD_TURNS": (10, 1000), "SITE_BUILD_MINUTES": (10, 240), "SITE_BUILD_RESUMES": (0, 10)}
_NAMES = {"GEMINI_MODEL", "CLAUDE_MODEL", "SITE_BUILD_MODEL"}


def validate_setting(k: str, v) -> str | None:
    """Проверка значения из интерфейса. Возвращает нормализованную строку или бросает ValueError."""
    if k not in DEFAULTS or k in ENV_ONLY:
        raise ValueError(f"Настройку {k} можно менять только в файле .env")
    v = str(v).strip()
    if any(c in v for c in "\r\n\x00"):
        raise ValueError(f"{k}: недопустимые символы")
    if k in _ENUMS:
        if v not in _ENUMS[k]:
            raise ValueError(f"{k}: недопустимое значение")
    elif k in _NUMS:
        if v == "":
            return None                  # пустое поле — не менять
        try:
            x = float(v.replace(",", "."))
        except ValueError:
            raise ValueError(f"{k}: нужно число") from None
        lo, hi = _NUMS[k]
        if not (lo <= x <= hi):
            raise ValueError(f"{k}: допустимо от {lo} до {hi}")
        v = str(int(x)) if x == int(x) else str(x)
    elif k in _NAMES:
        if v and not re.fullmatch(r"[\w.\-:\[\]/]{1,100}", v):
            raise ValueError(f"{k}: некорректное имя модели")
    elif k in SECRET_KEYS:
        if v and not re.fullmatch(r"[\x21-\x7e]{1,600}", v):
            raise ValueError(f"{k}: ключ должен быть одной строкой без пробелов")
    return v

_settings = {}


def load_settings():
    s = dict(DEFAULTS)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip().strip('"').strip("'")
    # переменные окружения сильнее файла (удобно на сервере)
    for k in DEFAULTS:
        if os.environ.get("CF_" + k):
            s[k] = os.environ["CF_" + k]
    _settings.clear()
    _settings.update(s)
    if s.get("FAL_KEY"):
        os.environ["FAL_KEY"] = s["FAL_KEY"]
    return s


def settings():
    if not _settings:
        load_settings()
    return _settings


def save_settings(updates: dict):
    s = settings()
    for k, v in updates.items():
        if k in DEFAULTS and v is not None:
            v = str(v).strip()
            if any(c in v for c in "\r\n\x00"):
                raise ValueError(f"{k}: недопустимые символы")
            s[k] = v
    lines = ["# Настройки контент-завода. Файл хранится только на этом компьютере/сервере."]
    for k in DEFAULTS:
        v = str(s.get(k, ""))
        if os.environ.get("CF_" + k) and k in SECRET_KEYS:
            continue                     # секрет из окружения сервера не переписываем в файл
        lines.append(f"{k}={v.replace(chr(13), '').replace(chr(10), '')}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    return load_settings()


def demo_mode() -> bool:
    s = settings()
    return s.get("DEMO_MODE", "1") == "1" or not s.get("FAL_KEY")


def provider(role: str) -> str:
    v = settings().get(f"PROVIDER_{role.upper()}") or ROLES.get(role, ("", "gemini"))[1]
    return v if v in ("claude", "gemini") else "gemini"


def int_setting(key, default=0):
    try:
        return int(float(settings().get(key) or default))
    except ValueError:
        return default


def public_settings():
    s = settings()
    return {
        "fal_key_set": bool(s.get("FAL_KEY")),
        "gemini_key_set": bool(s.get("GEMINI_API_KEY")),
        "apify_set": bool(s.get("APIFY_TOKEN")),
        "oauth_token_set": bool(s.get("CLAUDE_CODE_OAUTH_TOKEN")),
        "password_set": bool(s.get("AUTH_PASSWORD")),
        "gemini_model": s.get("GEMINI_MODEL"),
        "claude_model": s.get("CLAUDE_MODEL"),
        "claude_bin": s.get("CLAUDE_BIN"),
        "demo_mode": demo_mode(),
        "demo_flag": s.get("DEMO_MODE", "1") == "1",
        "daily_limit_usd": float(s.get("DAILY_LIMIT_USD") or 0),
        "usd_rub": float(s.get("USD_RUB") or 84.41),
        "providers": {r: provider(r) for r in ROLES},
        "roles": {r: label for r, (label, _) in ROLES.items()},
        "concepts_n": int_setting("CONCEPTS_N", 3),
        "auto_retry": int_setting("AUTO_RETRY", 1),
        "vertical_mode": s.get("VERTICAL_MODE", "nb2"),
        "montage_fit": s.get("MONTAGE_FIT", "crop"),
        "library_dir": s.get("LIBRARY_DIR", ""),
        "site_shots": s.get("SITE_SHOTS", "1") == "1",
        "site_build_turns": int_setting("SITE_BUILD_TURNS", 150),
        "site_build_minutes": int_setting("SITE_BUILD_MINUTES", 45),
        "site_build_resumes": int_setting("SITE_BUILD_RESUMES", 3),
        "site_build_model": s.get("SITE_BUILD_MODEL", "sonnet"),
        "host": s.get("HOST"), "port": s.get("PORT"), "auth_user": s.get("AUTH_USER"),
        "allowed_hosts": s.get("ALLOWED_HOSTS", ""), "env_only": sorted(ENV_ONLY),
    }


# ---------------------------------------------------------------------------
# Video models. Prices: fal.ai model pages, 29.09.2026, звук выключен.
# path: A макро/вращение · B кольцо на руке (видео в видео) · C ИИ-модель · D атмосфера
# ---------------------------------------------------------------------------
NB2_EDIT = "fal-ai/nano-banana-2/edit"
NB2_USD = {"1K": 0.08, "2K": 0.12, "4K": 0.16}

MODELS = {
    "kling_i2v": {
        "title": "Kling 3.0 Pro · картинка → видео",
        "endpoint": "fal-ai/kling-video/v3/pro/image-to-video",
        "usd_per_sec": 0.112,
        "needs": "photo",
        "durations": [5, 10],
        "paths": ["A", "C"],
    },
    "kling_edit": {
        "title": "Kling O3 Pro · видео в видео",
        "endpoint": "fal-ai/kling-video/o3/pro/video-to-video/edit",
        "usd_per_sec": 0.168,
        "needs": "video",
        "durations": [5],
        "paths": ["B"],
    },
    "keyframe_kling": {
        "title": "Ключевой кадр Nano Banana 2 → Kling 3.0",
        "endpoint": "fal-ai/kling-video/v3/pro/image-to-video",
        "usd_per_sec": 0.112,
        "extra_usd": NB2_USD["2K"],
        "needs": "photos",
        "durations": [5, 10],
        "paths": ["C"],
    },
    "seedance_i2v": {
        "title": "Seedance 2.0 · первый кадр → видео (720p)",
        "endpoint": "bytedance/seedance-2.0/image-to-video",
        "usd_per_sec": 0.3034,
        "needs": "photo",
        "durations": [4, 5, 6, 8],
        "paths": ["A", "C"],
    },
    "seedance_ref": {
        "title": "Seedance 2.0 · по референсам (720p)",
        "endpoint": "bytedance/seedance-2.0/reference-to-video",
        "usd_per_sec": 0.3034,
        "needs": "photos",
        "durations": [4, 5, 6, 8],
        "paths": ["C"],
    },
    "veo_i2v": {
        "title": "Veo 3.1 · картинка → видео (720p)",
        "endpoint": "fal-ai/veo3.1/image-to-video",
        "usd_per_sec": 0.20,
        "needs": "photo",
        "durations": [4, 6, 8],
        "paths": ["A", "D"],
    },
}

DEFAULT_NEGATIVE = (
    "changing ring design, changing stone shape, changing stone color, extra stones, missing stones, "
    "oversized ring, deformed ring, melting metal, ring floating, ring merging with finger, extra fingers, "
    "six fingers, fused fingers, distorted hand, plastic skin, blurry, flicker, jitter, text, watermark, logo"
)


def clip_cost(model_key: str, duration: float) -> float:
    m = MODELS.get(model_key)
    if not m:
        return 0.0
    return round(m["usd_per_sec"] * float(duration) + m.get("extra_usd", 0), 4)
