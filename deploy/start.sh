#!/bin/bash
# Запуск на Linux-сервере (вручную или из systemd).
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export CF_NO_BROWSER=1
unset ANTHROPIC_API_KEY
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -q -r requirements.txt
if [ ! -f .venv/.pw_chromium ]; then
  python -m playwright install --with-deps chromium && touch .venv/.pw_chromium || echo "Playwright browser not installed"
fi
exec python app/server.py
