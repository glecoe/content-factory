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

## 4. Доступ из браузера (только через HTTPS)

Студия слушает только `127.0.0.1`, а наружу её открывает nginx с HTTPS. В `.env` на сервере (руками — через
интерфейс эти настройки не меняются):

```
HOST=127.0.0.1
AUTH_USER=admin
AUTH_PASSWORD=длинный-случайный-пароль-от-12-символов
ALLOWED_HOSTS=studio.example.com
```

`ALLOWED_HOSTS` — домен, по которому открываешь студию: запросы с другими именами хоста отклоняются
(защита от DNS rebinding). После 8 неверных паролей подряд адрес блокируется на 15 минут.

nginx (`/etc/nginx/sites-available/studio`), сертификат — `sudo certbot --nginx -d studio.example.com`:

```
limit_req_zone $binary_remote_addr zone=studio:10m rate=10r/s;

server {
    listen 443 ssl http2;
    server_name studio.example.com;
    # ssl_certificate … — допишет certbot
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 500m;

    location / {
        limit_req zone=studio burst=40 nodelay;
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 600s;
    }
}
server { listen 80; server_name studio.example.com; return 301 https://$host$request_uri; }
```

Без пароля, с паролем короче 12 символов или с `HOST=0.0.0.0` без `PUBLIC_HTTP=1` студия наружу не откроется —
слушает только `127.0.0.1`. `PUBLIC_HTTP=1` (открыть наружу по голому HTTP) не рекомендуется: пароль пойдёт по сети
открытым текстом.

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
