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

from factory import config, store, pipeline, jobs, media, montage, brains, research, gen, library, sitelab, niches  # noqa: E402
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

    def _file(self, path: Path, sandbox=False, download_name=None):
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
        if sandbox:   # сгенерированные сайты: отдельный «источник», к админке доступа нет
            self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups allow-modals")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
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
        path, qs = unquote(u.path), parse_qs(u.query)
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
                sb = path.startswith("/files/sites/") and f.suffix.lower() in (".html", ".htm", ".svg", ".js")
                return self._file(f, sandbox=sb)
            if path == "/api/sites":
                lab = sitelab.resolve_lab(qs.get("lab", [""])[0])
                return self._json({"lab": sitelab.load_lab(lab), "labs": sitelab.list_labs(),
                                   "projects": sitelab.list_projects(lab), "taste": sitelab.taste_text(lab),
                                   "ratings": len(sitelab.ratings(lab)), "stacks": list(sitelab.STACKS)})
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
                return self._file(library.thumb(parse_qs(u.query).get("f", [""])[0]))
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
        return J("Пакет промтов", S.run_prompts)
    if action == "promptsave":
        b = self._jbody()
        S.write_prompt_file(sid, b.get("file", ""), b.get("text", ""))
        return self._json({"ok": True})
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
