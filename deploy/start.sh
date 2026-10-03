#!/bin/bash
# Запуск на Linux-сервере (вручную или из systemd).
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export CF_NO_BROWSER=1
unset ANTHROPIC_API_KEY
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -q -r requirements.txt
exec python app/server.py
