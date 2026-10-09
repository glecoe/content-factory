# Перенос на сервер

Прототип — обычная папка. На сервере он работает так же, как на Mac, только Claude входит по токену.

## 1. Что поставить (Ubuntu/Debian)

```
sudo apt update && sudo apt install -y python3 python3-venv ffmpeg
# браузер для скриншотов лаборатории сайтов ставит deploy/start.sh (playwright install --with-deps chromium)
curl -fsSL https://claude.ai/install.sh | bash        # Claude Code
```

## 2. Вход в Claude без браузера

На **своём компьютере** (где уже выполнен вход в Claude) запусти:

```
claude setup-token
```

Он выдаст токен на год. Вставь его на сервере в «Настройки → Claude по подписке → Токен для сервера»
(или в `.env` строкой `CLAUDE_CODE_OAUTH_TOKEN=...`). Проверка — кнопка «Проверить Claude».

Важно: в окружении сервера не должно быть `ANTHROPIC_API_KEY`, иначе Claude Code возьмёт API-ключ вместо подписки
(скрипты запуска его сбрасывают).

## 3. Перенос папки

Скопируй папку `content-factory` целиком, кроме `.venv` (он пересоздастся):

```
rsync -av --exclude .venv ~/Documents/content-factory/ user@server:/home/factory/content-factory/
```

`data/` — это все изделия, ролики, оценки и профиль вкуса; `.env` — ключи (права 600); `library/` — библиотека
съёмки «По изделиям». Если ставишь сервер через `git clone`, сначала `sudo apt install -y git-lfs && git lfs install`,
иначе в `library/` окажутся текстовые заглушки вместо фото и видео.

## 4. Доступ из браузера

В `.env` на сервере:

```
HOST=0.0.0.0
AUTH_USER=admin
AUTH_PASSWORD=длинный-пароль
```

Без пароля сервер наружу не откроется. Для постоянной работы лучше поставить перед ним nginx с HTTPS
(Let's Encrypt) и оставить `HOST=127.0.0.1`.

## 5. Автозапуск

```
chmod +x deploy/start.sh
sudo cp deploy/content-factory.service /etc/systemd/system/   # поправь User и пути
sudo systemctl daemon-reload && sudo systemctl enable --now content-factory
journalctl -u content-factory -f                              # журнал
```

## Ограничения подписки

Claude по подписке тратит лимиты твоего тарифа (Pro/Max). Один прогон ресёрча с поиском в интернете — заметная
часть 5-часового окна на Pro; на десятки изделий в день нужен Max или переключение части ролей на Gemini
(«Настройки → Кто какую работу делает»). Если Claude упёрся в лимит, задача сама уходит на Gemini.
