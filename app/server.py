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
import sys
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory import config, store, pipeline, jobs, media, montage, brains, research, gen  # noqa: E402
from factory.config import DATA, APP, MODELS  # noqa: E402

STATIC = APP / "static"


class Handler(BaseHTTPRequestHandler):
    server_version = "ContentFactory/0.1"

    def log_message(self, fmt, *args):  # тише в терминале
        if "/api/jobs/" not in (args[0] if args else ""):
            sys.stderr.write("  " + fmt % args + "\n")

    # ---------- доступ ----------
    def _authorized(self) -> bool:
        pw = config.settings().get("AUTH_PASSWORD", "")
        if not pw:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, given = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                return (hmac.compare_digest(given, pw) and
                        hmac.compare_digest(user, config.settings().get("AUTH_USER", "admin")))
            except Exception:
                return False
        return False

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="content-factory", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        self._json({"error": str(msg)}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        b = self._body()
        return json.loads(b.decode("utf-8")) if b else {}

    def _file(self, path: Path):
        if not path.exists() or not path.is_file():
            return self._err("not found", 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-cache")
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

    # ---------- routing ----------
    def do_GET(self):
        if not self._authorized():
            return self._deny()
        u = urlparse(self.path)
        path = unquote(u.path)
        try:
            if path in ("/", "/index.html"):
                return self._file(STATIC / "index.html")
            if path.startswith("/static/"):
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC.resolve() not in f.parents:
                    return self._err("forbidden", 403)
                return self._file(f)
            if path.startswith("/files/"):
                f = (DATA / path[len("/files/"):]).resolve()
                if DATA.resolve() not in f.parents:
                    return self._err("forbidden", 403)
                return self._file(f)
            if path == "/api/state":
                return self._json({
                    "settings": config.public_settings(), "tools": media.check_tools(),
                    "models": MODELS, "hero_styles": {k: v[0] for k, v in gen.HERO_STYLES.items()}, "products": store.list_products(), "costs": store.costs_summary(),
                    "taste": store.taste_text(), "music": montage.music_tracks(),
                    "ratings": len(store.ratings()), "jobs": jobs.active(), "brains": brains.status(),
                    "research": {"active": research.active_id(), "briefs": len(research.list_briefs())}})
            if path == "/api/research":
                bid = research.active_id()
                return self._json({"config": research.load_config(), "briefs": research.list_briefs(), "active": bid,
                                   "brief": research.load_brief(bid) if bid else None,
                                   "breakdowns": research.all_breakdowns(), "refs": research.list_refs()})
            m = re.fullmatch(r"/api/research/brief/([\w\-]+)", path)
            if m:
                return self._json(research.load_brief(m.group(1)))
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
        except Exception as e:
            return self._err(e, 500)

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        u = urlparse(self.path)
        path, qs = unquote(u.path), parse_qs(u.query)
        try:
            if path == "/api/settings":
                b = self._jbody()
                upd = {}
                for k, v in b.items():
                    if k not in config.DEFAULTS or v is None:
                        continue
                    if k in config.SECRET_KEYS:
                        if v == "":
                            continue            # пусто = оставить как есть
                        if v == "-":
                            v = ""              # «-» = стереть
                    upd[k] = v
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
            if path == "/api/research/config":
                return self._json(research.save_config(self._jbody()))
            if path == "/api/research/run":
                return self._json(jobs.start("Ресёрч трендов", research.run).to_dict())
            if path == "/api/research/activate":
                research.set_active(self._jbody().get("id", ""))
                return self._json({"ok": True})
            if path == "/api/research/upload":
                name = qs.get("name", ["ref.mp4"])[0]
                return self._json({"file": research.add_ref(name, self._body())})
            if path == "/api/research/analyze":
                b = self._jbody()
                return self._json(jobs.start("Разбор ролика", research.analyze_one, b.get("ref", ""),
                                             b.get("kind", "url")).to_dict())
            if path == "/api/research/deleteref":
                research.delete_ref(self._jbody().get("name", ""))
                return self._json({"ok": True})
            if path == "/api/products":
                return self._json(store.create_product(self._jbody()))
            m = re.fullmatch(r"/api/products/([\w\-]+)/(\w+)", path)
            if not m:
                if path == "/api/taste":
                    store.save_taste(self._jbody().get("text", ""))
                    return self._json({"ok": True})
                if path == "/api/taste/update":
                    return self._json(jobs.start("Профиль вкуса", pipeline.run_taste).to_dict())
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
        except Exception as e:
            return self._err(e, 400)


def main():
    config.load_settings()
    tools = media.check_tools()
    if not tools["ffmpeg"]:
        print("\n  ⚠  FFmpeg не найден. Установи: brew install ffmpeg\n")
    s = config.settings()
    host = s.get("HOST") or "127.0.0.1"
    port = int(os.environ.get("CF_PORT") or s.get("PORT") or 8765)
    if host not in ("127.0.0.1", "localhost") and not s.get("AUTH_PASSWORD"):
        print("\n  ⚠  HOST открыт наружу, а пароль (AUTH_PASSWORD) не задан — слушаю только 127.0.0.1.\n")
        host = "127.0.0.1"
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
