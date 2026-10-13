"""Общие проверки безопасности: имена сборок, публичные адреса (SSRF), безопасные тексты ошибок."""
from __future__ import annotations

import ipaddress
import re
import socket
import sys
import traceback
from urllib.parse import urlparse

from .config import ROOT

BUILD_RE = re.compile(r"v\d{1,4}")


def check_build_name(bdir: str) -> str:
    """Имя папки сборки — только v1, v2, … (никаких ../ и абсолютных путей)."""
    if not BUILD_RE.fullmatch(str(bdir or "")):
        raise ValueError("Некорректное имя сборки")
    return bdir


# ------------------------------------------------------------------ SSRF
def _ip_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
                or a.is_unspecified or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")))


def public_url(url: str) -> bool:
    """True, если адрес — http(s) и ВСЕ IP его хоста публичные (не localhost, не локальная сеть, не метаданные облака)."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return False
    host = u.hostname.strip("[]").lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        return False
    try:
        port = u.port or (443 if u.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (OSError, ValueError, UnicodeError):
        return False
    ips = {i[4][0] for i in infos}
    return bool(ips) and all(_ip_public(ip) for ip in ips)


# ------------------------------------------------------------------ ошибки наружу
_PATH_RE = re.compile(r"(?:/Users|/home|/root|/private|/var|/tmp|/opt|/srv|[A-Za-z]:\\)[^\s'\"<>,;)]*")


def clean_text(text: str) -> str:
    """Убирает из текста абсолютные пути (папку проекта и прочие)."""
    t = str(text or "").replace(str(ROOT) + "/", "").replace(str(ROOT), "")
    return _PATH_RE.sub("…", t)


def public_error(e: BaseException) -> str:
    """Короткий текст ошибки для интерфейса; подробности — в терминал."""
    sys.stderr.write("  ! " + "".join(traceback.format_exception(type(e), e, e.__traceback__, limit=6)))
    if isinstance(e, FileNotFoundError):
        return "Не найдено"
    if isinstance(e, PermissionError):
        return "Нет доступа к файлу"
    if isinstance(e, (json_errors())):
        return "Некорректный JSON"
    msg = clean_text(str(e)) or type(e).__name__
    return msg[:600]


def json_errors():
    import json
    return (json.JSONDecodeError,)
