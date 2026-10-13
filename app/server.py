"""Контент-завод · прототип. Запуск: python3 app/server.py → http://localhost:8765

На сервере: задай AUTH_PASSWORD и HOST=0.0.0.0 в .env (или CF_HOST/CF_PORT/CF_AUTH_PASSWORD в окружении),
лучше за nginx с HTTPS. Без пароля сервер слушает только 127.0.0.1."""
from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory import config, store, pipeline, jobs, media, montage, brains, research, gen, library, sitelab, niches  # noqa: E402
from factory import sitelaunch, sitevideo  # noqa: E402
from factory.config import DATA, APP, MODELS  # noqa: E402
from factory.safety import public_error  # noqa: E402

STATIC = APP / "static"
MAX_UPLOAD = 500 * 1024 * 1024        # потолок загрузки файла
MAX_JSON = 40 * 1024 * 1024           # потолок JSON-запроса (PNG финальной плашки в base64 — несколько МБ)
INLINE_TYPES = ("image/", "video/", "audio/")
TOKEN_FILE = DATA / ".studio_token"

APP_CSP = ("default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
           "media-src 'self' blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src 'self' https://fonts.gstatic.com; frame-src 'self'; frame-ancestors 'none'; "
           "object-src 'none'; base-uri 'none'; form-action 'self'")
# Сгенерированные сайты и любые чужие файлы: отдельный «нулевой» источник, без доступа к API студии
SANDBOX_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals; frame-ancestors 'self'"
FILE_CSP = "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'"


def _load_token() -> str:
    """Токен студии: встраивается в страницу и проверяется в каждом POST. Хранится в data/ (права 600)."""
    try:
        t = TOKEN_FILE.read_text().strip()
        if re.fullmatch(r"[\w\-]{32,}", t):
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(t)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return t


TOKEN = _load_token()

# Неудачные попытки входа (серверный режим): ip -> [кол-во, время первой, заблокирован до]
_fails: dict[str, list] = {}
_fails_lock = threading.Lock()
FAIL_LIMIT, FAIL_WINDOW, BLOCK_SECONDS = 8, 15 * 60, 15 * 60


class BodyTooLarge(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = "Studio"
    sys_version = ""

    def version_string(self):
        return "Studio"

    def log_message(self, fmt, *args):  # тише в терминале
        if "/api/jobs/" not in (args[0] if args else ""):
            sys.stderr.write("  " + fmt % args + "\n")

    # ---------- заголовки безопасности на каждом ответе ----------
    def send_header(self, keyword, value):
        if not hasattr(self, "_sent"):
            self._sent = set()
        self._sent.add(keyword.lower())
        super().send_header(keyword, value)

    def end_headers(self):
        sent = getattr(self, "_sent", set())
        if "x-content-type-options" not in sent:
            super().send_header("X-Content-Type-Options", "nosniff")
        if "referrer-policy" not in sent:
            super().send_header("Referrer-Policy", "no-referrer")
        if "content-security-policy" not in sent:
            super().send_header("Content-Security-Policy", APP_CSP)
            super().send_header("X-Frame-Options", "DENY")
        elif "x-frame-options" not in sent:
            super().send_header("X-Frame-Options", "SAMEORIGIN")
        super().send_header("Cross-Origin-Opener-Policy", "same-origin")
        self._sent = set()
        super().end_headers()

    # ---------- доступ ----------
    def _client_ip(self) -> str:
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1") and self.headers.get("X-Real-IP"):   # за nginx на этой же машине
            ip = self.headers.get("X-Real-IP", ip).strip()
        return ip

    def _authorized(self) -> bool:
        pw = config.settings().get("AUTH_PASSWORD", "")
        if not pw:
            return True
        ip = self._client_ip()
        now = time.time()
        with _fails_lock:
            rec = _fails.get(ip)
            if rec and rec[2] > now:
                self._blocked = True
                return False
        h = self.headers.get("Authorization", "")
        if not h:
            return False                        # первый запрос браузера — просто спросить пароль
        ok = False
        if h.startswith("Basic "):
            try:
                user, _, given = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                ok = (hmac.compare_digest(given.encode(), pw.encode()) and
                      hmac.compare_digest(user.encode(), config.settings().get("AUTH_USER", "admin").encode()))
            except Exception:
                ok = False
        with _fails_lock:
            if ok:
                _fails.pop(ip, None)
                return True
            rec = _fails.get(ip)
            if not rec or now - rec[1] > FAIL_WINDOW:
                rec = [0, now, 0]
            rec[0] += 1
            if rec[0] >= FAIL_LIMIT:
                rec[2] = now + BLOCK_SECONDS
                sys.stderr.write(f"  ! {ip}: {rec[0]} неудачных входов — блокирую на {BLOCK_SECONDS // 60} мин\n")
            _fails[ip] = rec
            if len(_fails) > 10000:
                _fails.clear()
        time.sleep(1.0)                         # замедляем перебор
        return False

    def _deny(self):
        if getattr(self, "_blocked", False):
            return self._err("Слишком много неудачных попыток входа. Подожди 15 минут.", 429)
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="studio", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _allowed_hosts(self) -> set:
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if port == 80:
            hosts |= {"127.0.0.1", "localhost", "[::1]"}
        s = config.settings()
        h = (s.get("HOST") or "").strip()
        if h and h not in ("0.0.0.0", "::"):
            hosts.add(f"{h}:{port}")
        for x in (s.get("ALLOWED_HOSTS") or "").split(","):
            x = x.strip().lower()
            if x:
                hosts.add(x)
                if ":" not in x.replace("[", "").replace("]", "") or x.startswith("["):
                    hosts.add(f"{x}:{port}")
        return hosts

    def _host_ok(self) -> bool:
        """Защита от DNS rebinding: отвечаем только на свои имена хоста."""
        return (self.headers.get("Host") or "").strip().lower() in self._allowed_hosts()

    def _csrf_ok(self) -> bool:
        """Защита от CSRF: чужой Origin — отказ; обязательны свой заголовок и токен (браузер не пошлёт их с чужого сайта)."""
        allowed = self._allowed_hosts()
        o = self.headers.get("Origin")
        if o and (o == "null" or (urlparse(o).netloc or "").lower() not in allowed):
            return False
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
            return False
        if self.headers.get("X-Requested-With") != "studio":
            return False
        return hmac.compare_digest((self.headers.get("X-Studio-Token") or "").encode(), TOKEN.encode())

    # ---------- helpers ----------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, code=400):
        if isinstance(msg, BaseException):
            msg = public_error(msg)
        self._json({"error": str(msg)}, code)

    def _length(self) -> int:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise BodyTooLarge("bad length") from None
        if n < 0:
            raise BodyTooLarge("bad length")
        return n

    def _body(self, limit=MAX_UPLOAD) -> bytes:
        if getattr(self, "_body_read", False):
            return b""
        n = self._length()
        if n > limit:
            raise BodyTooLarge()
        self._body_read = True
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        if getattr(self, "_jcache", None) is not None:
            return self._jcache
        n = self._length()
        if n and (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise ValueError("Нужен Content-Type: application/json")
        b = self._body(MAX_JSON)
        d = json.loads(b.decode("utf-8")) if b else {}
        if not isinstance(d, dict):
            raise ValueError("Ожидался JSON-объект")
        self._jcache = d
        return d

    def _file(self, path: Path, sandbox=False, download_name=None, untrusted=False):
        """sandbox — страница сгенерированного сайта (скрипты в изолированном источнике);
        untrusted — файл из data/: показываем только картинки/видео/аудио, остальное — скачиванием и в песочнице."""
        if not path.exists() or not path.is_file():
            return self._err("not found", 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)) and size:
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
        if sandbox:
            self.send_header("Content-Security-Policy", SANDBOX_CSP)
        elif untrusted:
            self.send_header("Content-Security-Policy", FILE_CSP)
            media_ok = ctype.startswith(INLINE_TYPES) and not ctype.startswith("image/svg")
            if not media_ok and not download_name:
                download_name = path.name
        if download_name:
            safe = re.sub(r'[^\w.\-]+', "_", download_name)[:120] or "file"
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _index(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__STUDIO_TOKEN__", TOKEN)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _gate(self) -> bool:
        """Общие проверки перед любым запросом. False — ответ уже отправлен."""
        self._jcache, self._body_read, self._blocked = None, False, False   # соединение keep-alive переиспользует объект
        if not self._host_ok():
            self.close_connection = True
            self._err("Неизвестный адрес хоста. На сервере добавь домен в ALLOWED_HOSTS в .env.", 403)
            return False
        if not self._authorized():
            self.close_connection = True
            self._deny()
            return False
        return True

    def do_OPTIONS(self):            # CORS-preflight не разрешаем никому
        self.close_connection = True
        self._err("forbidden", 403)

    def do_PUT(self):
        self.do_OPTIONS()

    do_DELETE = do_PATCH = do_PUT

    # ---------- routing ----------
    def do_GET(self):
        if not self._gate():
            return
        u = urlparse(self.path)
        path, qs = unquote(u.path), parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                return self._index()
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC.resolve() not in f.parents:
                    return self._err("forbidden", 403)
                return self._file(f)
            if path.startswith("/files/"):
                f = (DATA / path[len("/files/"):]).resolve()
                if DATA.resolve() not in f.parents or any(x.startswith(".") for x in f.relative_to(DATA.resolve()).parts):
                    return self._err("forbidden", 403)
                if path.startswith("/files/sites/"):    # сгенерированный сайт: всё — в песочнице
                    return self._file(f, sandbox=True)
                return self._file(f, untrusted=True)
            if path == "/api/sites":
                lab = sitelab.resolve_lab(qs.get("lab", [""])[0])
                return self._json({"lab": sitelab.load_lab(lab), "labs": sitelab.list_labs(),
                                   "projects": sitelab.list_projects(lab), "taste": sitelab.taste_text(lab),
                                   "ratings": len(sitelab.ratings(lab)), "stacks": sitelab.STACK_NAMES,
                                   "launch": {"enums": sitelaunch.ENUMS, "default": sitelaunch.DEFAULT},
                                   "video": {"usd": sitevideo.USD, "modes": sitevideo.MODES, "aspects": sitevideo.V_ASPECTS}})
            if path == "/api/labs":
                return self._json({"labs": sitelab.list_labs()})
            if path == "/api/niches":
                return self._json({"niches": niches.list_niches(), "fields": niches.FIELDS})
            m = re.fullmatch(r"/api/niches/([\w\-]+)", path)
            if m:
                return self._json(niches.load(m.group(1)))
            m = re.fullmatch(r"/api/sites/([\w\-]+)", path)
            if m:
                return self._json(sitelab.load(m.group(1)))
            m = re.fullmatch(r"/api/sites/([\w\-]+)/prompt", path)
            if m:
                return self._json({"text": sitelab.read_prompt_file(m.group(1), qs.get("file", ["MASTER.md"])[0])})
            m = re.fullmatch(r"/api/sites/([\w\-]+)/download", path)
            if m:
                z = sitelab.make_zip(m.group(1), qs.get("what", ["prompts"])[0])
                return self._file(z, download_name=z.name)
            if path == "/api/state":
                nid = niches.resolve(qs.get("niche", [""])[0])
                return self._json({
                    "settings": config.public_settings(), "tools": media.check_tools(),
                    "models": MODELS, "hero_styles": {k: v[0] for k, v in gen.HERO_STYLES.items()},
                    "niche": niches.load(nid), "niches": niches.list_niches(), "labs": sitelab.list_labs(),
                    "products": store.list_products(nid), "costs": store.costs_summary(),
                    "taste": store.taste_text(nid), "music": montage.music_tracks(),
                    "ratings": len(store.ratings(nid)), "jobs": jobs.active(), "brains": brains.status(),
                    "research": {"active": research.active_id(nid), "briefs": len(research.list_briefs(nid))}})
            if path == "/api/library":
                return self._json(library.list_items())
            if path == "/library/thumb":
                return self._file(library.thumb(parse_qs(u.query).get("f", [""])[0]), untrusted=True)
            if path == "/api/research":
                nid = niches.resolve(qs.get("niche", [""])[0])
                bid = research.active_id(nid)
                return self._json({"niche": nid, "config": research.load_config(nid), "briefs": research.list_briefs(nid),
                                   "active": bid, "brief": research.load_brief(nid, bid) if bid else None,
                                   "breakdowns": research.all_breakdowns(nid), "refs": research.list_refs(nid)})
            m = re.fullmatch(r"/api/research/brief/([\w\-]+)", path)
            if m:
                return self._json(research.load_brief(qs.get("niche", [""])[0] or None, m.group(1)))
            m = re.fullmatch(r"/api/products/([\w\-]+)", path)
            if m:
                return self._json(store.load_product(m.group(1)))
            m = re.fullmatch(r"/api/products/([\w\-]+)/brief", path)
            if m:
                return self._json({"brief": pipeline.brief(m.group(1))})
            m = re.fullmatch(r"/api/jobs/(\w+)", path)
            if m:
                j = jobs.get(m.group(1))
                return self._json(j) if j else self._err("нет такой задачи", 404)
            return self._err("not found", 404)
        except (FileNotFoundError, ValueError) as e:
            return self._err(e, 404 if isinstance(e, FileNotFoundError) else 400)
        except Exception as e:
            return self._err(e, 500)

    def do_POST(self):
        if not self._gate():
            return
        if not self._csrf_ok():
            self.close_connection = True
            return self._err("Запрос отклонён (защита от подделки запросов). Обнови страницу студии.", 403)
        try:
            if self._length() > MAX_UPLOAD:
                self.close_connection = True
                return self._err("Файл слишком большой (максимум 500 МБ).", 413)
        except BodyTooLarge:
            self.close_connection = True
            return self._err("bad request", 400)
        u = urlparse(self.path)
        path, qs = unquote(u.path), parse_qs(u.query)
        try:
            if path == "/api/settings":
                b = self._jbody()
                upd = {}
                for k, v in b.items():
                    if v is None or k not in config.DEFAULTS:
                        continue
                    if k in config.SECRET_KEYS:
                        if v == "":
                            continue            # пусто = оставить как есть
                        if v == "-":
                            upd[k] = ""         # «-» = стереть
                            continue
                    v = config.validate_setting(k, v)
                    if v is not None:
                        upd[k] = v
                for k in upd:
                    if k in config.ENV_ONLY:
                        raise ValueError(f"Настройку {k} можно менять только в файле .env")
                config.save_settings(upd)
                brains.claude_status(force=True)
                return self._json(config.public_settings())
            if path == "/api/claude/status":
                return self._json(brains.claude_status(force=True))
            if path == "/api/claude/test":
                def test(job):
                    st = brains.claude_status(force=True)
                    job.say(f"Claude Code: {'найден ' + str(st.get('version')) if st['installed'] else 'не установлен'}; "
                            f"вход: {st.get('method') or 'нет'}")
                    txt, meta = brains.ask_claude("Ответь ровно одной фразой по-русски: «Сценарист на связи».", timeout=180)
                    job.say(f"Ответ: {txt} · {meta['seconds']} с")
                    return {"answer": txt}
                return self._json(jobs.start("Проверка Claude", test).to_dict())
            nid = niches.resolve(qs.get("niche", [""])[0])
            if path == "/api/research/config":
                return self._json(research.save_config(nid, self._jbody()))
            if path == "/api/research/run":
                return self._json(jobs.start(f"Ресёрч · {niches.load(nid)['name']}", research.run, nid).to_dict())
            if path == "/api/research/activate":
                research.set_active(nid, self._jbody().get("id", ""))
                return self._json({"ok": True})
            if path == "/api/research/upload":
                name = qs.get("name", ["ref.mp4"])[0]
                return self._json({"file": research.add_ref(nid, name, self._body())})
            if path == "/api/research/analyze":
                b = self._jbody()
                return self._json(jobs.start("Разбор ролика", research.analyze_one, nid, b.get("ref", ""),
                                             b.get("kind", "url")).to_dict())
            if path == "/api/research/deleteref":
                research.delete_ref(nid, self._jbody().get("name", ""))
                return self._json({"ok": True})
            if path == "/api/products":
                b = self._jbody()
                return self._json(store.create_product({**b, "niche": b.get("niche") or nid}))
            # ниши завода
            if path == "/api/niches":
                return self._json(niches.create(self._jbody()))
            m = re.fullmatch(r"/api/niches/([\w\-]+)/(\w+)", path)
            if m:
                n_id, act = m.group(1), m.group(2)
                if act == "update":
                    return self._json(niches.update(n_id, self._jbody()))
                if act == "fill":
                    return self._json(jobs.start("Контекст ниши", niches.run_fill, n_id).to_dict())
                if act == "archive":
                    niches.archive(n_id)
                    return self._json({"ok": True})
                return self._err("unknown action", 404)
            # направления лаборатории
            lab = qs.get("lab", [""])[0] or None
            if path == "/api/labs":
                return self._json(sitelab.create_lab(self._jbody()))
            m = re.fullmatch(r"/api/labs/([\w\-]+)/(\w+)", path)
            if m:
                if m.group(2) == "update":
                    return self._json(sitelab.update_lab(m.group(1), self._jbody()))
                if m.group(2) == "archive":
                    sitelab.archive_lab(m.group(1))
                    return self._json({"ok": True})
                return self._err("unknown action", 404)
            if path == "/api/sites":
                b = self._jbody()
                return self._json(sitelab.create({**b, "lab": b.get("lab") or lab}))
            if path == "/api/sites/taste":
                sitelab.save_taste(self._jbody().get("text", ""), lab)
                return self._json({"ok": True})
            if path == "/api/sites/taste/update":
                return self._json(jobs.start("Вкус направления", sitelab.run_taste, lab).to_dict())
            m = re.fullmatch(r"/api/sites/([\w\-]+)/(\w+)", path)
            if m:
                return self._site_action(m.group(1), m.group(2), qs)
            m = re.fullmatch(r"/api/products/([\w\-]+)/(\w+)", path)
            if not m:
                if path == "/api/taste":
                    store.save_taste(self._jbody().get("text", ""), nid)
                    return self._json({"ok": True})
                if path == "/api/taste/update":
                    return self._json(jobs.start(f"Вкус · {niches.load(nid)['name']}", pipeline.run_taste, nid).to_dict())
                return self._err("not found", 404)
            pid, action = m.group(1), m.group(2)
            if action == "update":
                b = self._jbody()
                keys = ("name", "description_ru", "visual_en", "price", "promo", "link", "brand")
                return self._json(store.update_product(pid, lambda p: p.update({k: b[k] for k in keys if k in b})))
            if action == "upload":
                name = qs.get("name", ["file"])[0]
                label = qs.get("label", [""])[0]
                return self._json(pipeline.add_file(pid, name, self._body(), label))
            if action == "fromlibrary":
                return self._json(pipeline.add_from_library(pid, self._jbody().get("file", "")))
            if action == "remove":
                b = self._jbody()
                return self._json(pipeline.remove_file(pid, b.get("kind"), b.get("file")))
            if action == "passport":
                return self._json(jobs.start("Паспорт изделия", pipeline.run_passport, pid).to_dict())
            if action == "scenario":
                b = self._jbody()
                return self._json(jobs.start("Сценарист", pipeline.run_scenario, pid, b.get("n")).to_dict())
            if action == "autopilot":
                b = self._jbody()
                return self._json(jobs.start("Автопилот", pipeline.run_autopilot, pid, int(b.get("variants", 2)),
                                             b.get("n")).to_dict())
            if action == "hero":
                return self._json(jobs.start("Фото для финала", pipeline.run_hero, pid,
                                             self._jbody().get("styles", [])).to_dict())
            if action == "heroupload":
                return self._json(pipeline.add_hero_upload(pid, qs.get("name", ["hero.jpg"])[0], self._body()))
            if action == "endcardcfg":
                return self._json(pipeline.save_endcard_cfg(pid, self._jbody()))
            if action == "tagline":
                return self._json(jobs.start("Слоганы", pipeline.run_tagline, pid).to_dict())
            if action == "publish":
                return self._json(jobs.start("Тексты публикации", pipeline.run_publish, pid,
                                             self._jbody().get("video")).to_dict())
            if action == "template":
                return self._json(pipeline.add_template_concept(pid))
            if action == "manual":
                return self._json(pipeline.save_manual_scenario(pid, self._jbody().get("text", "")))
            if action == "concepts":
                return self._json(pipeline.save_concepts(pid, self._jbody().get("concepts", [])))
            if action == "clearconcepts":
                return self._json(store.update_product(pid, lambda p: p.__setitem__("concepts", [])))
            if action == "estimate":
                return self._json(pipeline.estimate(pid, self._jbody().get("concepts", [])))
            if action == "generate":
                b = self._jbody()
                return self._json(jobs.start("Генерация кадров", pipeline.run_generate, pid,
                                             b.get("concepts", []), b.get("qa", True)).to_dict())
            if action == "qa":
                return self._json(jobs.start("Проверка кадра", pipeline.run_qa, pid, self._jbody().get("clip")).to_dict())
            if action == "reject":
                b = self._jbody()
                return self._json(pipeline.reject_clip(pid, b.get("clip"), bool(b.get("rejected", True))))
            if action == "endcard":
                data = self._jbody().get("png", "")
                png = base64.b64decode(data.split(",", 1)[-1])
                return self._json({"file": pipeline.save_endcard(pid, png)})
            if action == "montage":
                b = self._jbody()
                return self._json(jobs.start("Монтаж", pipeline.run_montage, pid, b.get("concept"),
                                             int(b.get("variants", 2)), bool(b.get("ai", True))).to_dict())
            if action == "rate":
                b = self._jbody()
                pipeline.rate(pid, b.get("video"), b.get("like"), b.get("tags", []), b.get("comment", ""))
                return self._json({"ok": True})
            return self._err("unknown action", 404)
        except BodyTooLarge:
            self.close_connection = True
            return self._err("Запрос слишком большой.", 413)
        except Exception as e:
            return self._err(e, 400)


def _site_action(self, sid, action, qs):
    S = sitelab
    J = lambda title, fn, *a: self._json(jobs.start(title, fn, sid, *a).to_dict())  # noqa: E731
    if action == "brief":
        return self._json(S.update_brief(sid, self._jbody()))
    if action == "logo":
        return self._json(S.add_logo(sid, qs.get("name", ["logo.png"])[0], self._body()))
    if action == "logoremove":
        return self._json(S.remove_logo(sid))
    if action == "brand":
        return J("Бренд-кит", S.run_brand)
    if action == "brandsave":
        return self._json(S.save_brand(sid, self._jbody()))
    if action == "research":
        return J("Ресёрч сайтов", S.run_research)
    if action == "auto":
        return J("Бренд → ресёрч → концепции", S.run_to_concepts)
    if action == "concepts":
        return J("Концепции сайта", S.run_concepts, int(self._jbody().get("n", 3)))
    if action == "preview":
        return J("Превью концепции", S.make_previews, int(self._jbody().get("idx", 0)))
    if action == "choose":
        b = self._jbody()
        return self._json(S.choose(sid, int(b.get("idx", 0)), b.get("feedback", "")))
    if action == "photoplan":
        return J("План фото", S.run_photo_plan)
    if action == "photogen":
        return J("Генерация фото", S.run_generate_photos, self._jbody().get("slots") or None)
    if action == "photoupload":
        return self._json(S.add_photo_upload(sid, qs.get("name", ["photo.jpg"])[0], self._body(), qs.get("slot", [""])[0]))
    if action == "photoassign":
        return J("Разложить мои фото", S.run_assign, bool(self._jbody().get("auto_enhance", False)))
    if action == "photoenhance":
        b = self._jbody()
        return J("Улучшение фото", S.run_enhance, b.get("slot", ""), b.get("file", ""), b.get("mode", "retouch"), b.get("extra", ""))
    if action == "photochoose":
        b = self._jbody()
        return self._json(S.choose_photo(sid, b.get("slot", ""), b.get("file")))
    if action == "photoslot":
        b = self._jbody()
        return self._json(S.save_slot(sid, b.get("slot", ""), b))
    if action == "photouse":
        b = self._jbody()
        return self._json(S.assign_upload(sid, b.get("file", ""), b.get("slot", "")))
    if action == "prompts":
        return J("Пакет промптов", S.run_prompts)
    if action == "promptsave":
        b = self._jbody()
        S.write_prompt_file(sid, b.get("file", ""), b.get("text", ""))
        S.refresh_pack(sid)
        return self._json({"ok": True})
    if action == "promptedit":
        return J("Правка промптов", S.run_prompt_edit, str(self._jbody().get("wish", ""))[:4000])
    if action == "promptundo":
        return self._json(S.undo_prompt_edit(sid, str(self._jbody().get("snapshot", ""))))
    if action == "launchpack":
        return J("Пакет запуска", sitelaunch.run_launch_pack)
    # видео
    V = sitevideo
    if action == "videoupload":
        return self._json(V.add_upload(sid, qs.get("name", ["video.mp4"])[0], self._body(), qs.get("slot", [""])[0]))
    if action == "videoslotadd":
        return self._json(V.add_slot(sid, self._jbody()))
    if action == "videoslot":
        b = self._jbody()
        return self._json(V.save_slot(sid, str(b.get("slot", "")), b))
    if action == "videoslotdel":
        return self._json(V.remove_slot(sid, str(self._jbody().get("slot", ""))))
    if action == "videochoose":
        b = self._jbody()
        return self._json(V.choose(sid, str(b.get("slot", "")), b.get("file")))
    if action == "videouse":
        b = self._jbody()
        return self._json(V.assign_upload(sid, str(b.get("file", "")), str(b.get("slot", ""))))
    if action == "videogen":
        b = self._jbody()
        return J("Видео из фото", V.run_generate, str(b.get("slot", "")), str(b.get("photo", "")),
                 int(b.get("duration") or 0), str(b.get("extra", ""))[:500])
    if action == "videoenhance":
        b = self._jbody()
        return J("Улучшение видео", V.run_enhance, str(b.get("slot", "")), str(b.get("file", "")),
                 str(b.get("mode", "grade")), str(b.get("extra", ""))[:500], int(b.get("seconds") or 0))
    if action == "build":
        return J("Сборка сайта", S.run_build, self._jbody().get("extra", ""))
    if action == "resume":
        b = self._jbody()
        return J("Продолжение сборки", S.run_resume, b.get("dir", ""), b.get("extra", ""))
    if action == "review":
        return J("Проверка сайта", S.run_review, self._jbody().get("dir", ""))
    if action == "fix":
        b = self._jbody()
        return J("Правки сайта", S.run_fix, b.get("dir", ""), b.get("extra", ""), bool(b.get("use_review", True)))
    if action == "rate":
        b = self._jbody()
        S.rate(sid, b.get("what", "concept"), b.get("ref"), bool(b.get("like")), b.get("comment", ""))
        return self._json(S.load(sid))
    return self._err("unknown action", 404)


Handler._site_action = _site_action


def main():
    config.load_settings()
    tools = media.check_tools()
    if not tools["ffmpeg"]:
        print("\n  ⚠  FFmpeg не найден. Установи: brew install ffmpeg\n")
    s = config.settings()
    host = s.get("HOST") or "127.0.0.1"
    port = int(os.environ.get("CF_PORT") or s.get("PORT") or 8765)
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and not s.get("AUTH_PASSWORD"):
        print("\n  ⚠  HOST открыт наружу, а пароль (AUTH_PASSWORD) не задан — слушаю только 127.0.0.1.\n")
        host, local = "127.0.0.1", True
    if not local and len(s.get("AUTH_PASSWORD", "")) < 12:
        print("\n  ⚠  Пароль короче 12 символов — наружу не открываю, слушаю только 127.0.0.1.\n")
        host, local = "127.0.0.1", True
    if not local and s.get("PUBLIC_HTTP") != "1":
        print("\n  ⚠  HOST открыт наружу без HTTPS: пароль пойдёт по сети открытым текстом. Поставь nginx с HTTPS\n"
              "     (см. SERVER.md) и оставь HOST=127.0.0.1. Если всё же нужно — PUBLIC_HTTP=1 в .env.\n"
              "     Сейчас слушаю только 127.0.0.1.\n")
        host, local = "127.0.0.1", True
    st = brains.claude_status(force=True)
    print("  Claude Code: " + ("вход выполнен (" + str(st.get("method")) + ")" if st["logged_in"] else
          "найден, но вход не выполнен — запусти claude в Терминале" if st["installed"] else
          "не установлен — сценарист будет работать на Gemini"))
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://localhost:{port}"
    print(f"\n  Контент-завод запущен: {url}" + (f" (слушаю {host})" if host != "127.0.0.1" else "") +
          "\n  Остановить: Ctrl+C в этом окне\n")
    if os.environ.get("CF_NO_BROWSER") != "1" and host in ("127.0.0.1", "localhost"):
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Остановлено.")


if __name__ == "__main__":
    main()
