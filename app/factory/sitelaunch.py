"""Лаборатория сайтов · «боевой» сайт: оплата и чеки (54-ФЗ), формы, аналитика, юридические страницы
и инструкция по запуску для владельца (LAUNCH.md).

Что умеет ИИ, а что делает человек:
- ИИ (Claude Code) пишет код интеграции: создание платежа на сервере, данные чека, вебхуки с проверкой подписи,
  тестовый режим, страницы успеха/ошибки, отправку заявок, шаблоны юр. документов.
- Человек: договор с платёжным сервисом, проверка сайта сервисом, включение чеков (облачная касса или чеки сервиса),
  ключи в .env на сервере, адрес вебхука в личном кабинете, тестовые и первый боевой платёж.
Сведения о сервисах собраны 10.10.2026; точные поля API сборщик сверяет с официальной документацией.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

PROVIDERS = {
    "yookassa": {
        "name": "ЮKassa",
        "who": "ИП и ООО. Самозанятым — отдельное подключение; автоматические чеки самозанятых ЮKassa с 29.12.2025 "
               "не формирует (доход в «Мой налог» — вручную).",
        "receipts": "Вариант 1 — «Чеки от ЮKassa»: чеки пробивает партнёр ЮKassa на своей кассе, своя касса не нужна, "
                    "включается в личном кабинете. Вариант 2 — своя облачная касса партнёра (АТОЛ Онлайн, Orange Data и др.), "
                    "подключается в личном кабинете ЮKassa. В обоих случаях данные чека уходят в запросе платежа (объект receipt).",
        "api": "REST API v3 (https://api.yookassa.ru/v3): POST /payments, Basic-авторизация shopId:секретный ключ, заголовок "
               "Idempotence-Key (уникальный на попытку); amount {value, currency: RUB}, capture: true, confirmation "
               "{type: redirect, return_url}, metadata {orderId}, receipt {customer {email|phone}, items [description, quantity, "
               "amount, vat_code, payment_subject, payment_mode]}. Ответ — confirmation.confirmation_url, туда редирект. "
               "Уведомления (HTTP-уведомления о событиях payment.succeeded / payment.canceled / refund.succeeded) — на "
               "HTTPS-адрес; подлинность проверять повторным запросом GET /payments/{id} с ключами магазина. "
               "Есть тестовый магазин со своими shopId/ключом и тестовыми картами.",
        "docs": ["https://yookassa.ru/developers/"],
        "domains": ["yookassa.ru"],
        "env": ["YOOKASSA_SHOP_ID", "YOOKASSA_SECRET_KEY"],
    },
    "tbank": {
        "name": "Т-Банк · интернет-эквайринг (Т-Касса)",
        "who": "ИП и ООО (обычно с расчётным счётом в Т-Банке).",
        "receipts": "Нужна облачная онлайн-касса: подключается в личном кабинете Т-Бизнеса (касса банка-партнёра или своя "
                    "облачная), данные чека передаются в запросе Init в объекте Receipt.",
        "api": "API v2 (https://securepay.tinkoff.ru/v2/): Init — TerminalKey, Amount в копейках, OrderId, Description, "
               "SuccessURL, FailURL, NotificationURL, Receipt {Email|Phone, Taxation, Items [Name, Price, Quantity, Amount, Tax, "
               "PaymentMethod, PaymentObject]}; подпись Token = SHA-256 от склеенных значений корневых скалярных параметров "
               "вместе с Password, отсортированных по имени ключа. Ответ — PaymentURL, туда редирект. Уведомления на "
               "NotificationURL: проверить Token тем же способом, ответить телом OK. Есть тестовый (DEMO) терминал.",
        "docs": ["https://developer.tbank.ru/eacq/"],
        "domains": ["developer.tbank.ru", "tbank.ru", "tinkoff.ru"],
        "env": ["TBANK_TERMINAL_KEY", "TBANK_PASSWORD"],
    },
    "cloudpayments": {
        "name": "CloudPayments",
        "who": "ИП и ООО.",
        "receipts": "CloudKassir — облачная касса CloudPayments (аренда, по их сайту от ~3 000 ₽/мес + стартовый платёж; "
                    "фискальный накопитель входит, регистрацию кассы в ФНС делаешь сам через личный кабинет налоговой с КЭП) "
                    "или другая облачная касса. Чек передаётся в параметрах платежа (receipt / CustomerReceipt).",
        "api": "Платёжный виджет (скрипт https://widget.cloudpayments.ru/bundles/cloudpayments.js, публичный publicId, "
               "amount, currency RUB, invoiceId, accountId, данные чека) — карта вводится на стороне CloudPayments. "
               "Серверные уведомления Check / Pay / Fail на HTTPS-адрес с подписью HMAC-SHA256 тела запроса "
               "(заголовок Content-HMAC, ключ — API Secret); ответ {\"code\":0}. Тестовые карты — в документации.",
        "docs": ["https://developers.cloudpayments.ru/"],
        "domains": ["developers.cloudpayments.ru", "cloudpayments.ru"],
        "env": ["NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID", "CLOUDPAYMENTS_API_SECRET"],
    },
    "robokassa": {
        "name": "Robokassa",
        "who": "ИП, ООО и самозанятые.",
        "receipts": "«Робочеки» — чеки Robokassa без своей кассы и фискального накопителя (ИП и ООО); «Робочеки СМЗ» — "
                    "чеки самозанятых в «Мой налог»; или своя облачная касса. Включаются в личном кабинете, состав чека "
                    "передаётся параметром Receipt.",
        "api": "Переход на платёжную страницу https://auth.robokassa.ru/Merchant/Index.aspx с параметрами MerchantLogin, "
               "OutSum, InvId, Description, Receipt (URL-кодированный JSON: items [name, quantity, sum, tax, payment_method, "
               "payment_object]), SignatureValue — хеш (алгоритм, выбранный в личном кабинете) строки "
               "MerchantLogin:OutSum:InvId:Receipt:Пароль#1; IsTest=1 — тестовый режим. Result URL (сервер): проверить "
               "SignatureValue = хеш OutSum:InvId:Пароль#2 и ответить OK{InvId}. Success/Fail URL — только страницы для покупателя.",
        "docs": ["https://docs.robokassa.ru/"],
        "domains": ["docs.robokassa.ru", "robokassa.com", "robokassa.ru"],
        "env": ["ROBOKASSA_LOGIN", "ROBOKASSA_PASSWORD1", "ROBOKASSA_PASSWORD2", "ROBOKASSA_TEST"],
    },
}

LEGAL = {"ip": "ИП", "ooo": "ООО", "npd": "самозанятый (НПД)"}
SELLS = {"goods": "товары с доставкой", "services": "услуги", "digital": "цифровые товары / доступы",
         "booking": "запись / бронирование с предоплатой"}
CHECKOUT = {"cart": "корзина на несколько товаров", "buy": "кнопка «Купить» на конкретный товар/услугу",
            "deposit": "предоплата / депозит за запись"}
RECEIPTS = {"provider": "чеки платёжного сервиса (без своей кассы)", "own": "своя облачная касса",
            "npd": "чеки самозанятого («Мой налог»)", "unknown": "ещё не решили"}
VAT = {"none": "без НДС", "22": "НДС 22%", "10": "НДС 10%", "5": "НДС 5% (УСН)", "7": "НДС 7% (УСН)", "0": "НДС 0%"}
TAX = {"usn_income": "УСН «доходы»", "usn_ie": "УСН «доходы минус расходы»", "osn": "ОСН", "patent": "ПСН (патент)",
       "npd": "НПД (самозанятый)", "unknown": "не знаю"}
FORMS = {"telegram": "заявки в Telegram", "email": "заявки на почту", "both": "Telegram и почта", "none": "без форм"}
HOSTING = {"ru": "сервер в России (VPS / облако)", "vercel": "Vercel или другой зарубежный хостинг", "unknown": "ещё не выбрали"}

DEFAULT = {"on": False, "legal": "ip", "sells": "services", "checkout": "buy", "payments": "yookassa", "payments_other": "",
           "receipts": "provider", "vat": "none", "tax": "usn_income", "forms": "telegram", "metrika": True,
           "hosting": "ru", "domain": "", "legal_docs": True,
           "company": {"legal_name": "", "inn": "", "ogrn": "", "address": "", "email": "", "phone": ""}}
ENUMS = {"legal": LEGAL, "sells": SELLS, "checkout": CHECKOUT, "receipts": RECEIPTS, "vat": VAT, "tax": TAX,
         "forms": FORMS, "hosting": HOSTING, "payments": {**{k: v["name"] for k, v in PROVIDERS.items()},
                                                          "other": "другой сервис", "none": "без онлайн-оплаты"}}


def get(p) -> dict:
    L = {**DEFAULT, **(p.get("launch") or {})}
    L["company"] = {**DEFAULT["company"], **(L.get("company") or {})}
    return L


def clean(data: dict) -> dict:
    """Проверенные настройки запуска из брифа."""
    if not isinstance(data, dict):
        return dict(DEFAULT)
    out = {"on": bool(data.get("on")), "metrika": bool(data.get("metrika", True)),
           "legal_docs": bool(data.get("legal_docs", True))}
    for k, allowed in ENUMS.items():
        v = str(data.get(k, DEFAULT[k]))
        out[k] = v if v in allowed else DEFAULT[k]
    out["payments_other"] = str(data.get("payments_other", ""))[:200]
    out["domain"] = re.sub(r"[^\w.\-]", "", str(data.get("domain", "")).lower().replace("https://", "").replace("http://", ""))[:120]
    comp = data.get("company") if isinstance(data.get("company"), dict) else {}
    out["company"] = {k: str(comp.get(k, ""))[:300] for k in DEFAULT["company"]}
    if out["legal"] == "npd":
        out["receipts"] = "npd" if out["receipts"] in ("provider", "own") else out["receipts"]
        out["vat"], out["tax"] = "none", "npd"
    return out


def needs_server(p) -> bool:
    L = get(p)
    return L["on"] and (L["payments"] != "none" or L["forms"] != "none")


def text(p) -> str:
    """Короткое описание запуска для промптов."""
    L = get(p)
    if not L["on"]:
        return ""
    pay = L["payments"]
    prov = PROVIDERS.get(pay)
    c = L["company"]
    lines = [
        "БОЕВОЙ САЙТ (готов к запуску, не макет):",
        f"- Продавец: {LEGAL[L['legal']]}; налог: {TAX[L['tax']]}; в чеке: {VAT[L['vat']]}.",
        f"- Продаём: {SELLS[L['sells']]}; оформление: {CHECKOUT[L['checkout']]}.",
        f"- Онлайн-оплата: {prov['name'] if prov else (L['payments_other'] or 'другой сервис') if pay == 'other' else 'нет'}"
        + (f"; чеки 54-ФЗ: {RECEIPTS[L['receipts']]}." if pay != "none" else "."),
        f"- Заявки с форм: {FORMS[L['forms']]}. Яндекс Метрика: {'да' if L['metrika'] else 'нет'}.",
        f"- Хостинг: {HOSTING[L['hosting']]}{'; домен ' + L['domain'] if L['domain'] else ''}.",
        f"- Юридические страницы: {'сделать (оферта, политика ПДн, согласие на обработку ПДн, cookies, оплата/доставка/возврат)' if L['legal_docs'] else 'не нужны'}.",
        "- Реквизиты для футера и документов: " + "; ".join(f"{k}: {v}" for k, v in (
            ("наименование", c["legal_name"]), ("ИНН", c["inn"]), ("ОГРН/ОГРНИП", c["ogrn"]), ("адрес", c["address"]),
            ("email", c["email"]), ("телефон", c["phone"])) if v) + (" (чего нет — плейсхолдер [ЗАПОЛНИТЬ])" if not all(c.values()) else ""),
    ]
    return "\n".join(lines)


def doc_domains(p) -> list[str]:
    """Домены официальной документации, которые сборщику можно читать (WebFetch)."""
    L = get(p)
    d = list((PROVIDERS.get(L["payments"]) or {}).get("domains", []))
    if L["on"]:
        d += ["nextjs.org", "core.telegram.org", "yandex.ru"]
    return d


def build_tools(p) -> tuple[tuple, tuple]:
    """Инструменты Claude Code для сборки: при боевом сайте — ещё чтение официальной документации."""
    base = ("Read", "Write", "Edit", "Glob", "Grep")
    doms = doc_domains(p)
    if not doms:
        return base, base
    return base + ("WebFetch",), base + tuple(f"WebFetch(domain:{d})" for d in doms)


# --------------------------------------------------------------------------- пакет запуска
LAUNCH_SCHEMA = {"type": "object", "properties": {
    "integrations": {"type": "string"}, "launch": {"type": "string"}, "legal": {"type": "string"},
    "checklist": {"type": "array", "items": {"type": "string"}}},
    "required": ["integrations", "launch", "checklist"]}

COMMON_FACTS = """ПРОВЕРЕННЫЕ ФАКТЫ (на 10.10.2026; в инструкции пометь, что условия и тарифы нужно сверить у сервиса):
- 54-ФЗ: при онлайн-оплате на сайте ИП и ООО обязаны выдавать электронный чек (облачная касса или чеки платёжного сервиса).
  Самозанятые — чек в «Мой налог» (вручную или через сервис, который это умеет, например «Робочеки СМЗ»).
- Своя облачная касса (АТОЛ Онлайн, Orange Data, CloudKassir и др.): кассу и фискальный накопитель предоставляет сервис,
  но регистрацию кассы в ФНС делает владелец — в личном кабинете налоговой с квалифицированной электронной подписью (КЭП);
  нужен договор с оператором фискальных данных (ОФД, часто включён у сервиса). ИИ этого сделать не может.
- Чеки платёжного сервиса (без своей кассы): «Чеки от ЮKassa», «Робочеки» Robokassa — включаются в личном кабинете.
- НДС с 2026: базовая ставка 22%; УСН освобождена от НДС при доходе за прошлый год до 20 млн ₽ в 2026 году
  (15 млн в 2027, 10 млн с 2028), выше — 5% или 7% (или 22% с вычетами). Ставку в чеке указывать по факту.
- Эквайер проверяет сайт перед подключением: оферта, реквизиты (наименование/ФИО ИП, ИНН, ОГРН(ИП), адрес), контакты,
  цены в рублях, описание товаров/услуг, порядок оплаты, доставки и возврата, политика обработки персональных данных,
  согласие на обработку ПДн, HTTPS, свой домен, рабочие ссылки, нет запрещённых товаров.
- 152-ФЗ: персональные данные россиян (имя, телефон, email из форм и заказов) хранить на серверах в России; владелец сайта —
  оператор ПДн, до начала обработки подаёт уведомление в Роскомнадзор (pd.rkn.gov.ru); согласие на обработку ПДн —
  отдельным документом, не внутри оферты или политики; чекбокс согласия не должен быть отмечен заранее.
- Яндекс Метрика ставит cookies — нужен баннер cookies и политика cookies.
- Telegram-бот для заявок: токен у @BotFather, chat_id — из getUpdates; токен хранить только на сервере."""


def provider_block(p) -> str:
    L = get(p)
    prov = PROVIDERS.get(L["payments"])
    if not prov:
        return (f"Платёжный сервис: {L['payments_other'] or 'не выбран'} — найди его официальную документацию и сделай так же "
                "безопасно: платёж создаётся только на сервере, подтверждение — по подписанному уведомлению.") if L["payments"] == "other" else "Онлайн-оплаты нет."
    return (f"ПЛАТЁЖНЫЙ СЕРВИС: {prov['name']}\nКто может подключить: {prov['who']}\nЧеки 54-ФЗ: {prov['receipts']}\n"
            f"Техника: {prov['api']}\nДокументация: {', '.join(prov['docs'])}\nПеременные окружения: {', '.join(prov['env'])}")


def run_launch_pack(job, sid):
    """INTEGRATIONS.md (тех. задание сборщику), LAUNCH.md (инструкция владельцу), LEGAL.md (юр. тексты-шаблоны)."""
    from . import brains, sitelab
    p = sitelab.load(sid)
    L = get(p)
    if not L["on"]:
        return None
    d = sitelab.pdir(sid) / "prompts"
    if not (d / "MASTER.md").exists():
        raise ValueError("Сначала напиши пакет промптов.")
    master = (d / "MASTER.md").read_text(encoding="utf-8")[:6000]
    prompt = f"""Ты — тимлид веб-студии, который сдаёт клиенту БОЕВОЙ сайт: с настоящей оплатой, чеками, заявками и документами.
Напиши три документа для пакета сборки.

{sitelab.brief_text(p)}
{text(p)}
{provider_block(p)}

{COMMON_FACTS}

Фрагмент главного промпта сайта (стек и структура):
{master}

1) integrations — INTEGRATIONS.md, техзадание для Claude Code (он собирает сайт). Markdown:
   · архитектура: Next.js App Router с серверной частью (Route Handlers в app/api/…), всё секретное — только на сервере;
   · оплата{'' if L['payments'] != 'none' else ' (НЕ НУЖНА — раздел пропусти)'}: модель заказа (номер, состав, сумма, статус, контакты), хранение заказов
     (SQLite через better-sqlite3 или JSON-файл в data/ на сервере — выбери и обоснуй), создание платежа на сервере,
     данные чека (позиции, количество, цена, ставка НДС, признак предмета и способа расчёта — для «{SELLS[L['sells']]}»
     подбери правильные значения), идемпотентность, редирект на оплату, страницы «Оплата прошла» / «Не прошла»,
     обработчик уведомлений с проверкой подлинности, смена статуса заказа только по уведомлению, повторные уведомления,
     уведомление владельцу в Telegram/почту об оплате, возвраты (хотя бы описать, где делать в личном кабинете),
     тестовый режим через переменную окружения;
   · формы заявок: серверная отправка ({FORMS[L['forms']]}), защита от спама (honeypot + ограничение частоты),
     обязательный чекбокс согласия на обработку ПДн со ссылкой на документ;
   · аналитика: {'Яндекс Метрика (ID из переменной окружения) + цели на отправку формы и оплату + баннер cookies' if L['metrika'] else 'не нужна'};
   · .env.example со всеми переменными и комментариями, README-раздел «Запуск»; безопасность: HTTPS, заголовки,
     проверка входных данных, суммы считать на сервере по своему прайсу (не доверять сумме из браузера);
   · что сверить в официальной документации перед написанием кода (названия полей, коды НДС на 2026 год).
2) launch — LAUNCH.md, пошаговая инструкция для ВЛАДЕЛЬЦА (не программиста), что сделать руками, чтобы сайт принимал деньги:
   по шагам с чек-боксами: юр. статус и расчётный счёт → заявка в {PROVIDERS.get(L['payments'], {}).get('name', 'платёжный сервис') if L['payments'] != 'none' else '(оплаты нет — пропусти)'} и проверка сайта
   → чеки 54-ФЗ (что выбрать при варианте «{RECEIPTS[L['receipts']]}», что именно делает человек, сколько примерно стоит)
   → ключи в .env на сервере → адрес уведомлений в личном кабинете → тестовые платежи → хостинг в России, домен, HTTPS
   → уведомление в Роскомнадзор и документы по ПДн → Telegram-бот/почта для заявок → Метрика → перевод в боевой режим,
   первый настоящий платёж и возврат → что проверять раз в месяц. Отдельно: «Что может сделать ИИ, а что только вы» —
   короткая таблица. Пиши просто, без воды, со ссылками на официальные страницы. В начале — дисклеймер, что это не
   юридическая консультация, а условия сервисов меняются.
3) legal — LEGAL.md: тексты-шаблоны юридических страниц ({'оферта, политика обработки ПДн, согласие на обработку ПДн (отдельный документ), политика cookies, оплата и доставка, возврат' if L['legal_docs'] else 'не нужны — верни пустую строку'}),
   с подстановкой реквизитов из брифа и плейсхолдерами [ЗАПОЛНИТЬ: …] там, где данных нет; пометка «проверить у юриста».
4) checklist — 10–16 пунктов приёмки боевой части (оплата в тестовом режиме, уведомление меняет статус, подпись проверяется,
   чек уходит, форма доходит в Telegram, согласие обязательно, нет секретов в клиентском коде, …).
По-русски. Ответ — JSON."""
    job.say("Пишу пакет запуска: интеграции, инструкция для владельца, юр. тексты…")
    data, _ = brains.ask("site_prompt", prompt, schema=LAUNCH_SCHEMA, temperature=0.4, job=job, timeout=1500)
    (d / "INTEGRATIONS.md").write_text(data["integrations"].strip() + "\n", encoding="utf-8")
    (d / "LAUNCH.md").write_text(data["launch"].strip() + "\n", encoding="utf-8")
    files = ["INTEGRATIONS.md", "LAUNCH.md"]
    if (data.get("legal") or "").strip():
        (d / "LEGAL.md").write_text(data["legal"].strip() + "\n", encoding="utf-8")
        files.append("LEGAL.md")
    ck = d / "CHECKLIST.md"
    extra = "\n## Боевая часть\n\n" + "\n".join(f"- [ ] {x}" for x in data.get("checklist", [])) + "\n"
    base = ck.read_text(encoding="utf-8").split("\n## Боевая часть")[0] if ck.exists() else "# Приёмка\n"
    ck.write_text(base.rstrip() + "\n" + extra, encoding="utf-8")
    job.say("Пакет запуска готов: " + ", ".join(files))
    return files
