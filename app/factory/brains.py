"""«Мозги» завода: Claude через подписку (Claude Code CLI, вход OAuth) и Gemini API, с автоматическим запасным вариантом.

Claude вызывается командой `claude -p` — это разрешённый способ использовать подписку в своих скриптах
(официальная документация Claude Code: headless / Agent SDK). Свой API-ключ Anthropic не нужен.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .config import settings, provider, DATA, ROLES
from . import store


class BrainError(RuntimeError):
    pass


SYSTEM = ("Ты — агент студии: контент-завод рекламных роликов и лаборатория сайтов. Работаешь в конвейере без человека рядом: "
          "не задавай вопросов, не проси подтверждений, сразу выполняй задание. Отвечай по-русски, "
          "промпты для видеомоделей пиши по-английски. Если задан формат ответа — строго соблюдай его.")

# ----------------------------------------------------------------------------- Claude (CLI)
_BIN_CANDIDATES = ["~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude",
                   "/usr/local/bin/claude", "/usr/bin/claude"]


def claude_bin() -> str | None:
    s = settings().get("CLAUDE_BIN", "").strip()
    if s and Path(os.path.expanduser(s)).exists():
        return os.path.expanduser(s)
    found = shutil.which("claude")
    if found:
        return found
    for c in _BIN_CANDIDATES:
        p = Path(os.path.expanduser(c))
        if p.exists():
            return str(p)
    return None


def _claude_env():
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)       # иначе CLI возьмёт ключ API вместо подписки
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    tok = settings().get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    env["PATH"] = env.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin:" + os.path.expanduser("~/.local/bin")
    env.setdefault("DISABLE_AUTOUPDATER", "1")
    return env


_status_cache = {"t": 0, "v": None}


def claude_status(force=False) -> dict:
    """Установлен ли Claude Code и выполнен ли вход. Кэш на минуту."""
    if not force and _status_cache["v"] and time.time() - _status_cache["t"] < 60:
        return _status_cache["v"]
    b = claude_bin()
    st = {"installed": bool(b), "bin": b, "logged_in": False, "method": None, "version": None, "error": None}
    if b:
        try:
            v = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=20, env=_claude_env(), stdin=subprocess.DEVNULL)
            st["version"] = (v.stdout or v.stderr).strip()[:60]
            r = subprocess.run([b, "auth", "status"], capture_output=True, text=True, timeout=30, env=_claude_env(), stdin=subprocess.DEVNULL)
            try:
                j = json.loads(r.stdout or "{}")
                st["method"] = j.get("authMethod")
                if "loggedIn" in j:
                    st["logged_in"] = bool(j["loggedIn"])
                else:
                    st["logged_in"] = r.returncode == 0 and j.get("authMethod") not in (None, "none")
                em = j.get("email") or (j.get("account") or {}).get("email") or ""
                if "@" in em:     # наружу — только замаскированный адрес
                    u, _, dom = em.partition("@")
                    em = (u[:1] + "***@" + dom) if u else ""
                st["email"] = em or None
            except json.JSONDecodeError:
                # старые версии без `auth status`: считаем, что вход есть, ошибку покажет сам запрос
                st["logged_in"] = True
                st["method"] = "не проверить"
            if settings().get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
                st["logged_in"] = True
                st["method"] = st["method"] or "token"
        except Exception as e:  # noqa
            st["error"] = str(e)
    _status_cache.update(t=time.time(), v=st)
    return st


def claude_available() -> bool:
    st = claude_status()
    return st["installed"] and st["logged_in"]


def ask_claude(prompt: str, images=None, schema: dict | None = None, web=False, timeout=900, max_turns=None):
    b = claude_bin()
    if not b:
        raise BrainError("Claude Code не установлен. Установи: curl -fsSL https://claude.ai/install.sh | bash, затем войди командой claude.")
    work = DATA / "claude_work" / uuid.uuid4().hex[:10]
    work.mkdir(parents=True, exist_ok=True)
    tools = []
    files_note = ""
    if images:
        names = []
        for i, p in enumerate(images):
            dst = work / f"image_{i+1}{Path(p).suffix.lower() or '.jpg'}"
            shutil.copyfile(p, dst)
            names.append(dst.name)
        tools.append("Read")
        files_note = ("\n\nФАЙЛЫ ДЛЯ ПРОСМОТРА (открой каждый инструментом Read, это фото изделия/кадры): "
                      + ", ".join(f"./{n}" for n in names))
    if web:
        tools += ["WebSearch", "WebFetch"]
    turns = max_turns or (40 if web else (6 + 2 * len(images or [])))
    cmd = [b, "-p", prompt + files_note,
           "--output-format", "json", "--no-session-persistence",
           "--system-prompt", SYSTEM,
           "--tools", ",".join(tools),
           "--permission-mode", "dontAsk",
           "--strict-mcp-config",
           "--max-turns", str(turns)]
    model = (settings().get("CLAUDE_MODEL") or "").strip()
    if model:
        cmd += ["--model", model, "--fallback-model", "haiku" if model == "sonnet" else "sonnet"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout, env=_claude_env(),
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise BrainError(f"Claude не ответил за {timeout // 60} мин.") from e
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = (r.stdout or "").strip()
    try:
        j = json.loads(out.splitlines()[-1] if out and not out.startswith("{") else out)
    except (json.JSONDecodeError, IndexError):
        err = (r.stderr or out or "").strip()[-800:]
        raise BrainError(f"Claude вернул непонятный ответ (код {r.returncode}): {err}")
    if j.get("is_error") or j.get("subtype") not in (None, "success"):
        msg = j.get("result") or j.get("subtype") or r.stderr
        hint = ""
        low = str(msg).lower()
        if "region" in low or "country" in low or "403" in low or "not available" in low:
            hint = " Похоже, Anthropic не пускает из этой страны: включи VPN для всей системы и перезапусти start.command."
        elif "login" in low or "auth" in low or "401" in low:
            hint = " Похоже, не выполнен вход: открой Терминал и запусти claude (или вставь токен setup-token в Настройках)."
        elif "limit" in low or "usage" in low:
            hint = " Похоже, исчерпан лимит подписки — дождись сброса или переключи роль на Gemini."
        raise BrainError(f"Claude: {str(msg)[:600]}{hint}")
    meta = {"provider": "claude", "cost_equiv_usd": float(j.get("total_cost_usd") or 0),
            "seconds": round(time.time() - t0, 1), "turns": j.get("num_turns")}
    if schema:
        data = j.get("structured_output")
        if data is None:
            from .llm import parse_json
            data = parse_json(j.get("result") or "")
        return data, meta
    return (j.get("result") or "").strip(), meta


class ClaudeCodeStopped(BrainError):
    """Сессия Claude Code остановлена по лимиту (время, простой, шаги) — работа в папке сохранена, её можно продолжить."""
    def __init__(self, msg, reason="", files=None, steps=0, seconds=0):
        super().__init__(msg)
        self.reason, self.files, self.steps, self.seconds = reason, sorted(files or []), steps, seconds


def run_claude_code(job, prompt: str, cwd: Path, tools=("Read", "Write", "Edit", "Glob", "Grep"),
                    max_turns=120, timeout=3600, model=None, idle=900, allowed=None) -> dict:
    """Claude Code как разработчик: работает с файлами в папке cwd, журнал действий идёт в задачу.
    Использует подписку (OAuth), как и остальные роли.
    Сторож останавливает сессию по общему времени (timeout) или если Claude молчит дольше idle секунд."""
    import threading
    b = claude_bin()
    if not b:
        raise BrainError("Claude Code не установлен. Установи: curl -fsSL https://claude.ai/install.sh | bash, затем войди командой claude.")
    cmd = [b, "-p", prompt, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
           "--append-system-prompt", SYSTEM, "--tools", ",".join(tools), "--allowedTools", ",".join(allowed or tools),
           "--permission-mode", "acceptEdits", "--strict-mcp-config", "--max-turns", str(max_turns)]
    model = model or (settings().get("CLAUDE_MODEL") or "").strip()
    if model:
        cmd += ["--model", model, "--fallback-model", "haiku" if model == "sonnet" else "sonnet"]
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=_claude_env(), stdin=subprocess.DEVNULL, bufsize=1)
    state = {"last": time.time(), "stop": None}

    def watchdog():
        while proc.poll() is None:
            now = time.time()
            if now - t0 > timeout:
                state["stop"] = "timeout"
            elif now - state["last"] > idle:
                state["stop"] = "idle"
            if state["stop"]:
                proc.kill()
                return
            time.sleep(5)
    threading.Thread(target=watchdog, daemon=True).start()

    result, files, last_text, steps = None, set(), "", 0
    try:
        for line in proc.stdout:
            state["last"] = time.time()
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for c in (ev.get("message") or {}).get("content", []):
                    if c.get("type") == "tool_use":
                        steps += 1
                        inp = c.get("input") or {}
                        fp = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
                        if c.get("name") in ("Write", "Edit", "MultiEdit") and fp:
                            files.add(fp)
                        name = {"Write": "пишет", "Edit": "правит", "MultiEdit": "правит", "Read": "читает",
                                "Glob": "ищет", "Grep": "ищет", "WebFetch": "читает документацию"}.get(c.get("name"), c.get("name"))
                        if c.get("name") == "WebFetch":
                            fp = inp.get("url") or fp
                        rel = str(fp).replace(str(cwd), "").lstrip("/")
                        job.say(f"  Claude {name} {rel}"[:160])
                    elif c.get("type") == "text" and c.get("text", "").strip():
                        last_text = c["text"].strip()
            elif ev.get("type") == "result":
                result = ev
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    secs = round(time.time() - t0)
    rel_files = [str(f).replace(str(cwd), "").lstrip("/") for f in files]
    if state["stop"]:
        why = {"timeout": f"время сессии вышло ({timeout // 60} мин)",
               "idle": f"Claude молчал больше {idle // 60} мин"}[state["stop"]]
        raise ClaudeCodeStopped(f"Claude Code остановлен: {why}. Сделанное сохранено.", state["stop"], rel_files, steps, secs)
    if not result:
        err = (proc.stderr.read() if proc.stderr else "")[-800:]
        raise BrainError(f"Claude Code завершился без результата (код {proc.returncode}): {err}")
    if result.get("subtype") == "error_max_turns":
        raise ClaudeCodeStopped("Claude Code остановлен: закончились шаги сессии. Сделанное сохранено.", "max_turns",
                                rel_files, steps, secs)
    if result.get("is_error") or result.get("subtype") not in (None, "success"):
        msg = str(result.get("result") or result.get("subtype"))
        raise BrainError(f"Claude Code: {msg[:600]}")
    store.log_cost("llm", 0.0, "", f"site build via claude, {result.get('num_turns')} шагов, "
                                   f"≈${float(result.get('total_cost_usd') or 0):.2f} по прайсу API (по подписке)")
    return {"summary": (result.get("result") or last_text or "").strip(), "files": rel_files,
            "turns": result.get("num_turns"), "seconds": secs}


# ----------------------------------------------------------------------------- маршрутизатор
def _gemini(prompt, images, schema, web, temperature):
    from . import llm
    if web:
        text, tokens = llm.gemini_search(prompt + ("\n\nОтвет — строго JSON по описанной структуре." if schema else ""))
        data = llm.parse_json(text) if schema else text
        return data, {"provider": "gemini", "tokens": tokens}
    parts = [prompt + ("\n\nОтвет — строго JSON по этой схеме:\n" + json.dumps(schema, ensure_ascii=False) if schema else "")]
    parts += [llm._img_part(p) for p in (images or [])]
    data, tokens = llm.ask_gemini(parts, want_json=bool(schema), temperature=temperature)
    return data, {"provider": "gemini", "tokens": tokens}


def available(name) -> bool:
    if name == "claude":
        return claude_available()
    from . import llm
    return llm.gemini_available()


def ask(role: str, prompt: str, images=None, schema: dict | None = None, web=False, temperature=0.7,
        product: str = "", job=None, timeout=900):
    """Спросить «мозг» роли. Сначала выбранный провайдер, при ошибке — другой."""
    first = provider(role)
    order = [first, "gemini" if first == "claude" else "claude"]
    errors = []
    for name in order:
        if not available(name):
            if name == "claude":
                cs = claude_status(force=True)
                errors.append("claude: " + ("не установлен (curl -fsSL https://claude.ai/install.sh | bash)" if not cs["installed"]
                                            else "не выполнен вход — в Терминале набери claude и войди, потом «Настройки → Обновить статус»"))
            else:
                errors.append("gemini: нет ключа")
            continue
        try:
            if job:
                job.say(f"  {ROLES.get(role, (role,))[0]}: думает {'Claude (подписка)' if name == 'claude' else 'Gemini'}…")
            if name == "claude":
                data, meta = ask_claude(prompt, images, schema, web, timeout=timeout)
            else:
                data, meta = _gemini(prompt, images, schema, web, temperature)
            detail = f"{role} via {name}"
            if meta.get("cost_equiv_usd"):
                detail += f", по подписке (≈${meta['cost_equiv_usd']:.2f} по прайсу API)"
            if meta.get("tokens"):
                detail += f", tokens {meta['tokens']}"
            store.log_cost("llm", 0.0, product, detail)
            return data, meta
        except Exception as e:  # пробуем запасной вариант
            errors.append(f"{name}: {e}")
            if job:
                job.say(f"  {name} не справился: {str(e)[:200]}")
    raise BrainError("Ни один «мозг» не ответил. " + " | ".join(errors))


def status() -> dict:
    from . import llm
    return {"claude": claude_status(), "gemini": {"key": llm.gemini_available()}}
