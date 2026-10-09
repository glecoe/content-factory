#!/bin/bash
# Контент-завод · запуск на Mac. Двойной клик по файлу или: bash start.command
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
unset ANTHROPIC_API_KEY   # Claude работает по подписке, а не по API-ключу
echo ""
echo "  Контент-завод · запуск"
echo ""

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "  ⚠  Не найден FFmpeg. Установи командой:  brew install ffmpeg"
  echo ""
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "  ⚠  Claude Code не установлен — сценарист/ресёрчер будут работать на Gemini."
  echo "     Установка:  curl -fsSL https://claude.ai/install.sh | bash   затем  claude  (войти)"
  echo ""
fi

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo "  Нужен Python 3.10 или новее. Установи командой:  brew install python@3.12"
  read -r -p "  Нажми Enter, чтобы закрыть окно…"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "  Первый запуск: готовлю окружение (1–2 минуты)…"
  "$PY" -m venv .venv || { echo "  Не получилось создать окружение"; read -r; exit 1; }
fi
source .venv/bin/activate
python -m pip install -q --upgrade pip >/dev/null 2>&1
python -m pip install -q -r requirements.txt || echo "  ⚠  Не все пакеты установились — проверь интернет. Демо-режим всё равно заработает."

# браузер для скриншотов лаборатории сайтов (один раз, ~150 МБ)
if [ ! -f .venv/.pw_chromium ] && python -c "import playwright" 2>/dev/null; then
  echo "  Ставлю браузер для скриншотов сайтов (один раз, 1–3 минуты)…"
  python -m playwright install chromium && touch .venv/.pw_chromium || echo "  ⚠  Браузер не поставился — лаборатория будет работать без скриншотов."
fi

python app/server.py
