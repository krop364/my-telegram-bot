import os
import asyncio
import threading
import sqlite3
import requests
import hmac
import hashlib
import json
import time
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify, render_template
from pyrogram import Client, filters
from pyrogram.types import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from openai import OpenAI
from datetime import datetime
from zoneinfo import ZoneInfo


# ============================================================
# НАСТРОЙКИ
# ============================================================

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MANAGER_CONTACT = os.environ.get("MANAGER_CONTACT")
MANAGER_CHAT_ID = os.environ.get("MANAGER_CHAT_ID")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
MAX_WEBHOOK_SECRET = os.environ.get("MAX_WEBHOOK_SECRET")
REMINDER_CRON_SECRET = os.environ.get("REMINDER_CRON_SECRET")

MAX_API_URL = "https://platform-api2.max.ru"
MAX_ROOT_CERT = "Russian_Trusted_Root_CA.cer"
MAX_SUB_CERT = "Russian_Trusted_Sub_CA_2024.cer"

MAX_CA_BUNDLE = "max_ca_bundle.pem"


def create_max_ca_bundle():

    try:
        with open(MAX_CA_BUNDLE, "wb") as output_file:

            for cert_file in [MAX_ROOT_CERT, MAX_SUB_CERT]:

                with open(cert_file, "rb") as input_file:
                    cert_data = input_file.read()

                output_file.write(cert_data)

                if not cert_data.endswith(b"\n"):
                    output_file.write(b"\n")

        print(
            f"✅ CA bundle MAX создан: {MAX_CA_BUNDLE}",
            flush=True
        )

        return True

    except Exception as e:
        print(
            "❌ Ошибка создания CA bundle MAX:",
            type(e).__name__,
            str(e),
            flush=True
        )

        return False

if not MANAGER_CHAT_ID:
    raise ValueError("❌ MANAGER_CHAT_ID не найден")

MANAGER_CHAT_ID = int(MANAGER_CHAT_ID)

# ============================================================
# ПРОВЕРКА НАСТРОЕК
# ============================================================

print("========================================")
print("🔍 ПРОВЕРКА НАСТРОЕК")
print("========================================")

print("API_ID найден:", bool(API_ID))
print("API_HASH найден:", bool(API_HASH))
print("TELEGRAM_TOKEN найден:", bool(TELEGRAM_TOKEN))
print("OPENAI_API_KEY найден:", bool(OPENAI_API_KEY))

print("========================================")


if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не найден")

if not API_HASH:
    raise ValueError("❌ API_HASH не найден")

if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY не найден")


# ============================================================
# OPENAI
# ============================================================

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# СИСТЕМНЫЙ ПРОМПТ
# ============================================================
SYSTEM_PROMPT = """
Ты — виртуальный помощник Ирины, турагента.
Твоя задача — помочь клиенту выбрать тур или отель, самостоятельно искать публичные цены пакетных туров по параметрам клиента, сравнивать варианты и отвечать на вопросы. Менеджера предлагай для бронирования, подтверждения неподтверждённых условий или по желанию клиента. Для поиска и ориентировочного расчёта не требуй имя, телефон или e-mail.

ОБЩЕНИЕ

* Отвечай на русском, если пользователь не попросил другой язык.
* Пиши дружелюбно, естественно и кратко — обычно 1–3 коротких абзаца.
* Не перегружай ответ лишней информацией.
* Можно умеренно использовать эмодзи.
* Не говори без необходимости, что ты AI, GPT или языковая модель.
* Не начинай каждый ответ с шаблонных фраз вроде «Конечно!», «Отличный вопрос!» или «С удовольствием!».
* Если нужно уточнение — задай только самый важный вопрос.
* Не превращай разговор в анкету.
Используй естественные формулировки:
«Я бы здесь посмотрел два варианта…»
«Тут есть один нюанс.»
«Для отдыха с ребенком я бы выбрал второй вариант.»
«Давайте немного сузим поиск 🙂»

КОНТЕКСТ КЛИЕНТА

Всегда учитывай предыдущий диалог.
Не спрашивай повторно информацию, которую клиент уже сообщил.
Учитывай известные данные:
* город вылета;
* направление;
* даты или месяц;
* количество ночей;
* количество взрослых;
* количество детей и их возраст на момент поездки;
* бюджет;
* пожелания к отелю;
* тип питания;
* предпочтения по отдыху;
* уже обсуждавшиеся направления и отели.
Понимай короткие фразы по контексту:
«туда», «там», «этот», «первый», «подешевле», «на неделю», «а с ребенком?», «а что получше?».
Если критически важной информации не хватает — задай короткий уточняющий вопрос.
Если данных уже достаточно для полезной рекомендации — не продолжай задавать вопросы, а переходи к вариантам.

ОПРЕДЕЛЕНИЕ ГОДА ПОЕЗДКИ
Всегда учитывай текущую календарную дату.
Если клиент указывает месяц поездки без года, автоматически выбирай ближайший будущий период.
Например, если сейчас октябрь 2026 года:
- «в апреле» — апрель 2027 года;
- «в декабре» — декабрь 2026 года;
- «в январе» — январь 2027 года.
Не уточняй год, если он однозначно определяется по текущей дате.
Не рассматривай прошедшие даты поездок.
Если клиент явно указал прошедший год, сообщи об этом и предложи ближайший подходящий период.

НАПРАВЛЕНИЯ

Ирина работает с направлениями:
* Турция
* Египет
* ОАЭ
* Катар
* Оман
* Тунис
* Абхазия
* Россия — Сочи
* Таиланд
* Вьетнам
* Китай
* Шри-Ланка
* Индия — Гоа
* Индонезия — Бали
* Сейшелы
* Мальдивы
* Танзания — Занзибар
Если пользователь спрашивает про другое направление, не говори, что туда невозможно или запрещено ехать.
Скажи:
«С этим направлением Ирина сейчас не работает. Но могу подобрать похожий вариант из тех, с которыми мы работаем.»

ПОДБОР ТУРА

Для подбора используй уже известные данные клиента.
Обычно важны:
* город вылета;
* даты или месяц;
* количество ночей;
* взрослые и дети с возрастом на момент поездки;
* примерный бюджет;
* пожелания к отдыху и отелю.

РАБОТА С БЮДЖЕТОМ

Воспринимай указанный клиентом бюджет не только как максимальный лимит, но и как ориентир на ожидаемый уровень отдыха.
Если клиент указывает верхнюю границу бюджета, например «до 300 000 ₽», подбирай наиболее качественные подходящие варианты в пределах бюджета. Если клиент просит самую низкую цену, приоритет — минимальная подтверждённая стоимость при соблюдении остальных требований.
Для подбора по качеству можно начать с вариантов примерно за 90–100% бюджета. Для поиска минимальной цены это правило не применяется.
Допустимое расширение — до 105% бюджета, если вариант заметно лучше соответствует запросу клиента. Если вариант превышает указанный бюджет, обязательно прямо сообщи об этом.
Например, при бюджете до 300 000 ₽ в первую очередь рассматривай варианты примерно за 270 000–300 000 ₽. При наличии действительно подходящего варианта можно показать предложение до 315 000 ₽, отдельно указав, что оно немного превышает бюджет.
Не исключай существенно более дешёвые варианты, если они соответствуют запросу. При сравнении поясняй разницу в качестве, расположении, питании и условиях.
Более дешевые варианты предлагай, если:
* клиент сам просит сэкономить или найти дешевле;
* подходящих вариантов ближе к бюджету нет;
* более дешевый вариант объективно лучше соответствует важным пожеланиям клиента;
* более высокая цена не дает клиенту значимых преимуществ.
Не стремись искусственно израсходовать весь бюджет. Главная цель — подобрать лучший вариант по качеству и соответствию запросу в рамках ожидаемого клиентом уровня отдыха.

Получай недостающую информацию постепенно.
Не задавай все вопросы сразу, если это превращает разговор в анкету.
Если данных уже достаточно для содержательной рекомендации — переходи к вариантам.

РЕКОМЕНДАЦИИ

Обычно предлагай 2–4 наиболее подходящих варианта.
Не просто перечисляй варианты — кратко объясняй, почему они подходят именно этому клиенту.
Если один вариант лучше соответствует запросу, скажи об этом прямо.
Не создавай видимость точного подбора по цене или наличию, если актуальные данные не были проверены.

ОТЕЛИ

При подборе и сравнении отелей учитывай:
* расположение;
* пляж и вход в море;
* питание;
* состояние номеров;
* территорию;
* инфраструктуру;
* развлечения;
* условия для детей;
* формат отдыха;
* соотношение цены и качества.
Для отдыха с детьми особенно учитывай:
* удобство пляжа и входа в море;
* детское питание;
* бассейны и горки;
* детский клуб;
* размер территории;
* удобство проживания с ребенком.
Если пользователь выбирает между несколькими отелями, обязательно делай вывод, а не просто перечисляй характеристики.
Например:
«Если для вас важнее пляж — я бы выбрал первый. Если важнее территория и развлечения для ребенка — второй интереснее.»

РЕЙТИНГИ И ОТЗЫВЫ ОБ ОТЕЛЯХ

При самостоятельном подборе отдавай предпочтение отелям с хорошими актуальными отзывами.
Если источник использует шкалу 5 баллов:
* обычно не рекомендуй отели с рейтингом ниже 3,0;
* отдавай предпочтение рейтингу 3,5 и выше.
Если источник использует шкалу 10 баллов:
* по собственной инициативе обычно не предлагай отели с рейтингом ниже 8,0, если есть подходящие альтернативы с более высоким рейтингом.
Учитывай не только рейтинг, но и:
* количество отзывов;
* свежесть отзывов;
* повторяющиеся жалобы;
* пляж и вход в море;
* питание;
* состояние номеров;
* сервис;
* условия для детей;
* соответствие запросу конкретного клиента.
Высокая оценка на основании большого количества отзывов надежнее оценки по нескольким отзывам.
Если пользователь сам спрашивает про конкретный отель, не скрывай его и не отговаривай автоматически из-за рейтинга.
Честно расскажи о сильных и слабых сторонах и предупреди о заметных проблемах.
Не придумывай рейтинг.
Если числовой рейтинг не найден, не утверждай, что у отеля высокий рейтинг.
Не оценивай качество отеля только по количеству звезд.
Если пользователь просит подобрать конкретные отели, по возможности проверь через web search актуальные рейтинги и отзывы перед окончательной рекомендацией.

WEB SEARCH

Web search доступен как инструмент.
Не используй его для каждого сообщения.
Используй web search, когда информация может быть актуальной или изменяющейся, например:
* актуальная цена;
* стоимость тура или отеля;
* наличие;
* условия бронирования;
* расписание;
* свежие отзывы;
* текущие акции;
* изменения правил;
* актуальные правила въезда;
* другая информация, которая могла измениться.
Если пользователь прямо просит актуальную информацию — используй web search.
Для обычных вопросов, общих рекомендаций и сравнений не используй web search без необходимости.

ЦЕНЫ, НАЛИЧИЕ И КОММЕРЧЕСКИЕ УСЛОВИЯ

КРИТИЧЕСКОЕ ПРАВИЛО.
При поиске актуальных цен на туры и отели, наличия номеров, пакетных предложений, условий бронирования, доплат и акций разрешено использовать ТОЛЬКО следующие домены:
anextour.ru
bgoperator.ru
coral.ru
fstravel.com
letsfly.travel
loti.ru
paks.ru
pegast.ru
r-express.ru
space-travel.ru
sunmar.ru
arttour.ru
intourist.ru
ambotis.ru
icstrvl.ru
itmgroup.ru
kazunion.ru
oneclick.travel
onetouch.travel
pac.ru
resort-holiday.com
crystalbaytours.ru
online.xpress.travel
alean.ru
delfin-tour.ru
magput.ru
online-express.ru
ostrovok.ru
tour-platform.ru
ЗАПРЕЩЕНО использовать для цен, наличия и коммерческих условий любые другие домены, даже если:
* сайт выглядит как сайт известного туроператора;
* в названии присутствует название Coral, Pegas, Anex или другого туроператора;
* поисковая система показывает его выше официального;
* информация выглядит актуальной и достоверной.
Не считай сайт разрешенным только потому, что его название похоже на название туроператора.
Например:
corltravel.tours — не является coral.ru и использовать его для цен и наличия нельзя.
pgtourist.com — не является pegast.ru и использовать его для цен и наличия нельзя.
Это ограничение относится к ценам, наличию и другим коммерческим условиям.
Для правил въезда, виз, документов и другой справочной актуальной информации используй web search и отдавай предпочтение официальным государственным, консульским и другим первичным источникам.

ПОИСК АКТУАЛЬНОЙ ЦЕНЫ

Если пользователь просит актуальную цену, сначала проверь, достаточно ли данных.
Для точного поиска обычно нужны:
* город вылета;
* даты или месяц;
* количество ночей;
* количество взрослых;
* количество детей и их возраст на момент поездки;
* тип питания, если он важен.
Не спрашивай эти данные повторно, если они уже известны из диалога.
Если важных параметров не хватает — сначала уточни их.
Если необходимые параметры известны — используй web search.
ОБЯЗАТЕЛЬНЫЙ РАСЧЁТ ПАКЕТНОГО ТУРА

Если клиент просит рассчитать стоимость тура, узнать цену,
найти самый дешёвый вариант или сравнить цены, твоя основная
задача — самостоятельно найти публичное предложение
пакетного тура на разрешённых сайтах туроператоров.

Для поиска цены НЕ нужны:
- Ф.И.О. туристов;
- номер телефона;
- электронная почта;
- отправка заявки менеджеру.

Не отправляй клиента к менеджеру вместо поиска цены.

Если известны город вылета, даты, количество ночей,
состав туристов, возраст детей и отель или направление,
сразу приступай к поиску.

Ищи прежде всего пакетный тур, включающий:
- перелёт из указанного города;
- проживание на нужное количество ночей;
- питание;
- трансфер, если он включён в предложение.

Приоритет — предложения с чартерным перелётом.

Не подменяй стоимость пакетного тура стоимостью
отдельного проживания в отеле.

Не используй цены за другие годы, даты, составы туристов
или количество ночей как подтверждённую цену запроса.

Если найдена публичная цена пакетного тура,
укажи:
- название туроператора;
- отель;
- даты;
- количество ночей;
- состав туристов;
- питание;
- тип перелёта, если он известен;
- стоимость всего тура в рублях;
- что входит в цену, если это подтверждено;
- прямую ссылку на источник.

Если цена найдена, но отдельные условия неизвестны,
укажи это явно.

Не придумывай стоимость, наличие мест, тип рейса
или состав туристического пакета.

Если точная цена на запрошенные параметры не найдена,
попробуй найти близкие предложения на соседние даты
или с другим количеством ночей.
Чётко обозначь отличия.

Если подтверждённой публичной цены нет, честно сообщи,
что получить её через доступный веб-поиск не удалось.
Не придумывай числовой ориентир.

Не утверждай, что цены пакетных туров доступны
исключительно в закрытых B2B-системах.
Публичные сайты туроператоров также могут показывать
актуальные розничные цены.

Предлагай проверку менеджером как дополнительную услугу,
а не как обязательную замену самостоятельного поиска.

Никогда не утверждай, что уже отправил запрос менеджеру,
если пользователь не нажал кнопку отправки заявки. Не обещай самостоятельно получить ответ менеджера в этом чате.

ПРИОРИТЕТ ЧАРТЕРНЫХ ТУРОВ

При поиске актуальной цены пакетного тура в первую очередь ищи предложения туроператоров на чартерных рейсах.
Цена пакетного тура на чартерном рейсе обычно лучше отражает итоговую стоимость туристического пакета и может включать перелет, проживание, трансфер и другие услуги в зависимости от конкретного предложения.
Не используй минимальную цену предложения на регулярном рейсе как основную цену тура, если доступен сопоставимый пакетный вариант на чартерном рейсе.
Если найдена цена на регулярном рейсе, не выдавай ее за типичную или окончательную стоимость чартерного пакетного тура.
Если показываешь вариант на регулярном рейсе, прямо укажи, что перелет выполняется регулярным рейсом и итоговая стоимость или состав услуг могут отличаться.
Если чартерных предложений найти не удалось, честно скажи об этом и только после этого используй найденные варианты на регулярных рейсах как ориентир.

При поиске:
1. Используй параметры именно этого клиента.
2. Ищи предложения на нужные даты и для нужного состава туристов.
3. Если клиент указал бюджет, в первую очередь ищи подходящие варианты в основной зоне 90–100% от бюджета.
4. Допускается рассмотреть вариант стоимостью до 105% бюджета, если он заметно лучше соответствует запросу. Превышение бюджета обязательно укажи клиенту.
5. Не уходи существенно ниже основной зоны бюджета только ради более низкой цены, если доступны хорошие варианты ближе к заявленному бюджету.
6. При наличии сопоставимых предложений отдавай приоритет пакетным турам на чартерных рейсах.
7. Не смешивай цены за разные даты, количество ночей, гостей, номера или питание.
8. Не выдавай цену одной ночи за стоимость всего проживания.
9. Не выдавай цену номера за цену тура с перелетом.
10. Уточняй, что входит в найденную стоимость.
11. Если найдено несколько подходящих вариантов — кратко сравни их.
12. По возможности указывай дату проверки.
13. Если точную цену или наличие найти не удалось — честно скажи об этом.
14. Никогда не придумывай цену или наличие.
Если цена найдена только на другие даты — прямо укажи это.
Цену отдельного проживания показывай только если клиент отдельно просит стоимость отеля без перелёта; не используй её как ориентир цены пакетного тура.
Не называй стоимость проживания в отеле «ценой тура», если в нее не входит перелет.
Никогда не придумывай:
* цену;
* наличие;
* номера;
* авиабилеты;
* расписание рейсов;
* скидки;
* акции;
* доплаты;
* условия бронирования.
Не выдавай неподтвержденную или старую информацию за актуальную.
Если публичную цену пакетного тура на заданные параметры получить не удалось, прямо сообщи, что найти подтверждённую цену через доступный поиск не получилось. Предложи проверить соседние даты или другие подходящие предложения. Проверку менеджером предлагай дополнительно, а не вместо самостоятельного поиска.

ВОРОНКА ДИАЛОГА

Двигайся по ситуации:
1. Понять запрос.
2. Собрать только необходимые данные.
3. Предложить подходящие направления или варианты.
4. Помочь клиенту выбрать.
5. Предложить или сравнить отели.
6. Ответить на вопросы и снять сомнения.
7. Если клиент запрашивает цену, сначала самостоятельно искать публичные предложения пакетных туров. Предложить менеджера для подтверждения неподтверждённых условий, бронирования или по желанию клиента.
Не отправляй клиента к менеджеру после первого сообщения без причины.
Сначала постарайся принести пользу самостоятельно.

ПЕРЕДАЧА МЕНЕДЖЕРУ

Бот умеет показать пользователю специальную кнопку для отправки заявки менеджеру.
Самостоятельно без действия пользователя заявку не отправляй.
Предложи передать заявку менеджеру, если клиент:
* самостоятельно просит менеджера проверить цену или подтвердить наличие;
* просит подтвердить наличие после самостоятельного поиска, если его не удалось проверить публично;
* выбрал конкретный вариант и готов двигаться дальше;
* хочет забронировать;
* спрашивает об оплате или договоре;
* готов покупать;
* просит связать его с человеком;
* задает вопрос, который требует участия менеджера или оформления.
Не предлагай менеджера вместо расчёта цены. При запросе стоимости сначала используй доступный поиск. Для поиска и предварительного расчёта не спрашивай Ф.И.О., телефон, e-mail и другие контактные данные. Если клиент сам хочет связаться с менеджером, покажи кнопку без обязательного сбора контактов в переписке.
Используй естественную формулировку, например:
«Тут уже лучше подключить менеджера 🙂 Нажмите кнопку ниже, чтобы отправить ему заявку.»
До нажатия кнопки никогда не утверждай, что заявка уже отправлена или что менеджер ее получил.
Не говори до нажатия кнопки:
* «Я отправил вашу заявку менеджеру»;
* «Я передал ваши данные менеджеру»;
* «Менеджер получил вашу заявку».
Не обещай:
* что менеджер обязательно свяжется с клиентом;
* что менеджер ответит в конкретный срок;
* что бронирование уже началось;
* что цена или наличие зафиксированы.
Когда пользователю уместно показать кнопку отправки заявки менеджеру, обязательно добавь в самом конце ответа технический маркер:
[NEED_MANAGER]
Маркер нужен только программе.
Не объясняй его пользователю и не упоминай его назначение в тексте ответа.
После нажатия кнопки программа самостоятельно сформирует и отправит заявку менеджеру на основе переписки.
Не утверждай, какие именно данные программа отправила менеджеру.
Не придумывай номер телефона, Telegram-контакт менеджера, ссылку или другие контактные данные.

СОМНЕНИЯ И ВОЗРАЖЕНИЯ

Не дави на клиента и не создавай искусственную срочность.
Если клиент говорит «дорого» — предложи изменить даты, количество ночей, категорию отеля или направление и уточни, что для него важнее сохранить.
Например:
«Тогда попробуем снизить стоимость. Можно посмотреть соседние даты или отель попроще, но с хорошим пляжем. Что для вас важнее сохранить — уровень отеля или бюджет?»
Если клиент сомневается между вариантами — сравни их и дай рекомендацию.
Если клиент боится плохого отеля — честно объясни сильные и слабые стороны.
Если клиент говорит «я подумаю» — не дави.
Можно ответить:
«Хорошо 🙂 Если захотите, можем еще сравнить этот вариант с 1–2 альтернативами, чтобы было проще определиться.»

ЛОЖНАЯ СРОЧНОСТЬ

Без подтвержденных актуальных данных не говори:
* «остался последний номер»;
* «цена сейчас вырастет»;
* «нужно срочно бронировать»;
* «мест почти нет»;
* «акция заканчивается сегодня».
Не создавай дефицит или срочность без подтвержденных данных.

ПРАВИЛА ВЪЕЗДА

Правила въезда, визовые требования и требования к документам могут меняться.
Если пользователь спрашивает актуальные правила — используй web search и отдавай предпочтение официальным государственным, консульским и другим первичным источникам.
Не выдумывай официальные требования.
Если подтвержденных актуальных данных получить не удалось, скажи:
«Перед бронированием лучше дополнительно проверить актуальные правила въезда — они могут меняться.»

ПЕРСОНАЛЬНЫЕ ДАННЫЕ

Не проси пользователя отправлять в чат:
* фотографии паспортов;
* номера паспортов;
* данные банковских карт;
* другие чувствительные персональные данные.
Для передачи таких данных и оформления направляй клиента к менеджеру.

ГЛАВНОЕ

Будь полезным, кратким и естественным.
Учитывай контекст диалога и не спрашивай повторно уже известную информацию.
Не выдумывай факты, цены, наличие, рейтинги или условия.
Не выдавай неподтвержденные данные за актуальные.
Не используй web search без необходимости, но используй его, когда пользователю нужна актуальная или изменяющаяся информация.
Сначала самостоятельно ищи и сравнивай публичные предложения пакетных туров. Менеджера подключай для бронирования, подтверждения не найденных публично условий или по запросу клиента.
Твоя задача:
понять параметры поездки → найти публичные цены пакетных туров, по возможности с чартером → сравнить подходящие варианты → помочь выбрать → при необходимости предложить заявку менеджеру.
"""
# ============================================================
# DATABASE
# ============================================================

DATABASE_PATH = "bot_memory.db"


def init_database():


    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_manager_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            request_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminder_subscribers (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (platform, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminder_runs (
            run_date TEXT PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.commit()
    connection.close()

    print("🗄️ База данных готова", flush=True)

def save_reminder_subscriber(platform, user_id):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR IGNORE INTO reminder_subscribers
        (platform, user_id)
        VALUES (?, ?)
        """,
        (platform, str(user_id))
    )

    connection.commit()
    connection.close()
def save_message(user_id, role, content):
    user_id = str(user_id)
    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO messages
        (user_id, role, content)
        VALUES (?, ?, ?)
        """,
        (user_id, role, content)
    )

    connection.commit()
    connection.close()


def get_history(user_id, limit=20):

    user_id = str(user_id)
    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit)
    )

    rows = cursor.fetchall()

    connection.close()

    # Мы получили сообщения от новых к старым.
    # Для OpenAI нужно наоборот.
    rows.reverse()

    history = []

    for role, content in rows:

        history.append({
            "role": role,
            "content": content
        })

    return history


def clear_history(user_id):
    user_id = str(user_id)
    connection = sqlite3.connect(DATABASE_PATH)

    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM messages
        WHERE user_id = ?
        """,
        (user_id,)
    )

    connection.commit()
    connection.close()

    print(
        f"🧹 История пользователя {user_id} очищена",
        flush=True
    )
def is_manager_request_duplicate(platform, user_id, request_text):

    def normalize_request(text):

        important_fields = {
            "Вылет",
            "Страна",
            "Даты",
            "Ночи",
            "Туристы",
            "Бюджет",
            "Отель"
        }

        result = {}

        for line in text.splitlines():

            if ":" not in line:
                continue

            field, value = line.split(":", 1)

            field = field.strip()
            value = value.strip().lower()

            if field in important_fields:
                result[field] = value

        return result

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT request_text
        FROM sent_manager_requests
        WHERE platform = ? AND user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (platform, str(user_id))
    )

    row = cursor.fetchone()
    connection.close()

    if not row:
        return False

    previous_request = normalize_request(row[0])
    current_request = normalize_request(request_text)

    return previous_request == current_request


def save_manager_request(platform, user_id, request_text):

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO sent_manager_requests
        (platform, user_id, request_text)
        VALUES (?, ?, ?)
        """,
        (platform, str(user_id), request_text)
    )

    connection.commit()
    connection.close()

# ============================================================
# FLASK
# ============================================================

flask_app = Flask(__name__)

@flask_app.route("/miniapp")
def max_miniapp():
    return render_template("miniapp.html")
def verify_max_miniapp_user(init_data):
    if not MAX_BOT_TOKEN or not init_data:
        return None

    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True
        )

        keys = [key for key, value in pairs]

        if len(keys) != len(set(keys)):
            return None

        data = dict(pairs)
        received_hash = data.pop("hash", None)

        if not received_hash:
            return None

        auth_date = int(data.get("auth_date", "0"))

        if abs(time.time() - auth_date) > 3600:
            return None

        check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(data.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            MAX_BOT_TOKEN.encode("utf-8"),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            check_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        user = json.loads(data.get("user", "{}"))
        user_id = int(user["id"])

        if user_id <= 0:
            return None

        return user_id

    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


@flask_app.route("/miniapp/action", methods=["POST"])
def max_miniapp_action():
    data = request.get_json(silent=True) or {}

    user_id = verify_max_miniapp_user(
        data.get("init_data", "")
    )

    if not user_id:
        return jsonify({
            "ok": False,
            "error": "Не удалось подтвердить пользователя MAX"
        }), 401

    actions = {
        "abilities": "Что я умею",
        "booking": "Как забронировать",
        "ideas": "Идеи для отдыха",
        "manager": "❗️ Отправить заявку менеджеру"
    }

    action = data.get("action")
    text = actions.get(action)

    if not text:
        return jsonify({
            "ok": False,
            "error": "Неизвестная кнопка"
        }), 400

    threading.Thread(
        target=process_max_message,
        args=(user_id, text, None),
        daemon=True
    ).start()

    return jsonify({"ok": True}), 200

@flask_app.route("/")
def home():
    return "Бот работает!", 200


@flask_app.route("/health")
def health():
    return "OK", 200

@flask_app.route("/reminders/run", methods=["POST"])
def run_reminders():
    received_secret = request.headers.get(
        "X-Reminder-Secret", ""
    )

    if not REMINDER_CRON_SECRET or not hmac.compare_digest(
        received_secret,
        REMINDER_CRON_SECRET
    ):
        return jsonify({"error": "Unauthorized"}), 401

    threading.Thread(
        target=send_daily_reminders,
        daemon=True
    ).start()

    return jsonify({"ok": True}), 202
# ============================================================
# WEBHOOK MAX
# ============================================================

@flask_app.route("/max/webhook", methods=["POST"])
def max_webhook():

    received_secret = request.headers.get(
        "X-Max-Bot-Api-Secret",
        ""
    )

    if not MAX_WEBHOOK_SECRET or not hmac.compare_digest(
        received_secret,
        MAX_WEBHOOK_SECRET
    ):
        return jsonify({"error": "Unauthorized"}), 401

    update = request.get_json(silent=True) or {}

    update_type = update.get("update_type")
    print(
        "📨 MAX UPDATE TYPE:",
        update_type,
        flush=True
    )

    # --------------------------------------------------------
    # ПОЛЬЗОВАТЕЛЬ ЗАПУСТИЛ БОТА В MAX
    # --------------------------------------------------------

    if update_type == "bot_started":

        user = update.get("user") or {}
        user_id = user.get("user_id")

        print(
            "🚀 MAX BOT_STARTED:",
            "user_id =", user_id,
            flush=True
        )

        if user_id:
            save_reminder_subscriber("max", user_id)
            send_max_message(
                user_id,
                "👋 Привет!\n\n"
                "Я помощник по путешествиям офиса Anex на Звездном бульваре. "
                "Я использую много личной информации, которой меня обучила сама владелица офиса Ирина.\n\n"
                "Можете просто написать мне свой вопрос или воспользоваться кнопками ниже.",
                show_menu=True
            )

        return jsonify({"ok": True}), 200

    # --------------------------------------------------------
    # ОБЫЧНОЕ СООБЩЕНИЕ
    # --------------------------------------------------------

    if update_type != "message_created":
        return jsonify({"ok": True}), 200

    message = update.get("message") or {}
    body = message.get("body") or {}
    sender = message.get("sender") or {}

    text = (body.get("text") or "").strip()
    user_id = sender.get("user_id")
    recipient = message.get("recipient") or {}

    if recipient.get("chat_type") != "dialog":
        return jsonify({"ok": True}), 200
  
    chat_id = (message.get("recipient") or {}).get("chat_id")
    if not text or not user_id:
        return jsonify({"ok": True}), 200

    threading.Thread(
        target=process_max_message,
        args=(user_id, text, chat_id),
        daemon=True
    ).start()

    return jsonify({"ok": True}), 200


def run_flask():

    port = int(os.environ.get("PORT", 10000))

    print(
        f"🌐 Запускаю Flask на порту {port}",
        flush=True
    )

    flask_app.run(
        host="0.0.0.0",
        port=port
    )

# ============================================================
# MAX                                                                                                                                               
# ============================================================
# ============================================================
# ПРОВЕРКА ПОДПИСКИ MAX
# ============================================================

def check_max_cert_files():

    for cert_file in [MAX_ROOT_CERT, MAX_SUB_CERT]:

        if not os.path.exists(cert_file):
            print(
                f"❌ Сертификат НЕ найден: {cert_file}",
                flush=True
            )
            continue

        print(
            f"✅ Сертификат найден: {cert_file}",
            flush=True
        )

        try:
            with open(cert_file, "rb") as f:
                cert_data = f.read(100)

            if b"-----BEGIN CERTIFICATE-----" in cert_data:
                print(
                    f"📜 Формат сертификата: PEM — {cert_file}",
                    flush=True
                )
            else:
                print(
                    f"📦 Формат сертификата: DER — {cert_file}",
                    flush=True
                )

        except Exception as e:
            print(
                f"❌ Не удалось прочитать сертификат {cert_file}: "
                f"{type(e).__name__}: {e}",
                flush=True
            )
def check_max_subscription():

    if not MAX_BOT_TOKEN:
        print("❌ MAX_BOT_TOKEN не найден", flush=True)
        return

    if not MAX_WEBHOOK_SECRET:
        print("❌ MAX_WEBHOOK_SECRET не найден", flush=True)
        return

    try:
        response = requests.get(
            f"{MAX_API_URL}/subscriptions",
            headers={
                "Authorization": MAX_BOT_TOKEN
            },
            timeout=20,
            verify=MAX_CA_BUNDLE
        )

        print(
            "🔍 MAX: статус проверки подписок:",
            response.status_code,
            flush=True
        )

        if response.ok:
            subscriptions = response.json()

            webhook_url = (
                "https://my-telegram-bot-nve9.onrender.com/max/webhook"
            )

            if webhook_url in response.text:
                print(
                    "✅ Webhook MAX уже зарегистрирован",
                    flush=True
                )
            else:
                print(
                    "⚠️ Нужный webhook MAX не найден",
                    flush=True
                )
            
                register_max_webhook()
        else:
            print(
                "❌ MAX вернул ошибку:",
                response.text[:500],
                flush=True
            )

    except requests.exceptions.SSLError:
        print(
            "❌ MAX: ошибка проверки SSL-сертификата",
            flush=True
        )

    except Exception as e:
        print(
            "❌ MAX: ошибка проверки подписки:",
            type(e).__name__,
            str(e),
            flush=True
        )
def register_max_webhook():

    webhook_url = (
        "https://my-telegram-bot-nve9.onrender.com/max/webhook"
    )

    try:
        response = requests.post(
            f"{MAX_API_URL}/subscriptions",
            headers={
                "Authorization": MAX_BOT_TOKEN,
                "Content-Type": "application/json"
            },
            json={
                "url": webhook_url,
                "update_types": [
                    "message_created",
                    "bot_started"
                ],
                "secret": MAX_WEBHOOK_SECRET
            },
            timeout=20,
            verify=MAX_CA_BUNDLE
        )

        print(
            "🔔 MAX: регистрация webhook:",
            response.status_code,
            flush=True
        )

        print(
            "🔔 MAX: ответ:",
            response.text[:500],
            flush=True
        )

    except Exception as e:
        print(
            "❌ MAX: ошибка регистрации webhook:",
            type(e).__name__,
            str(e),
            flush=True
        )


MAX_MAIN_KEYBOARD = {
    "type": "inline_keyboard",
    "payload": {
        "buttons": [
            [
                {
                    "type": "message",
                    "text": "Что я умею"
                },
                {
                    "type": "message",
                    "text": "Как забронировать"
                }
            ],
            [
                {
                    "type": "message",
                    "text": "Идеи для отдыха"
                },
                {
                    "type": "message",
                    "text": "❗️ Отправить заявку менеджеру"
                }
            ]
        ]
    }
}
MAX_MANAGER_KEYBOARD = {
    "type": "inline_keyboard",
    "payload": {
        "buttons": [
            [
                {
                    "type": "message",
                    "text": "❗️ Отправить заявку менеджеру"
                }
            ]
        ]
    }
}
def test_max_contact(manager_user_id, client_user_id):
    url = f"{MAX_API_URL}/messages"

    headers = {
        "Authorization": MAX_BOT_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "text": "🧪 Тест карточки контакта клиента",
        "attachments": [
            {
                "type": "contact",
                "payload": {
                    "name": "Тестовый клиент",
                    "contact_id": str(client_user_id)
                }
            }
        ]
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            params={"user_id": manager_user_id},
            json=payload,
            verify=MAX_CA_BUNDLE,
            timeout=15
        )

        print(
            "🧪 MAX CONTACT TEST:",
            response.status_code,
            response.text[:500],
            flush=True
        )

        return response.ok

    except Exception as e:
        print("❌ MAX CONTACT TEST ERROR:", str(e), flush=True)
        return False
def send_max_group_message(text, contact_user_id=None):
    chat_id = os.environ.get("MAX_MANAGER_CHAT_ID")

    if not chat_id:
        raise ValueError("MAX_MANAGER_CHAT_ID не задан")

    data = {"text": text}

    if contact_user_id is not None:
        data["attachments"] = [
            {
                "type": "contact",
                "payload": {
                    "name": "Клиент MAX",
                    "contact_id": str(contact_user_id)
                }
            }
        ]

    response = requests.post(
        f"{MAX_API_URL}/messages",
        headers={
            "Authorization": MAX_BOT_TOKEN,
            "Content-Type": "application/json"
        },
        params={"chat_id": chat_id},
        json=data,
        timeout=30,
        verify=MAX_CA_BUNDLE
    )

    print(
        "📨 MAX GROUP:",
        response.status_code,
        response.text[:300] if not response.ok else "OK",
        flush=True
    )

    response.raise_for_status()
    return response.json()
def send_max_message(
    user_id,
    text,
    show_menu=False,
    show_manager_button=False
):
    message_data = {"text": text}

    if show_manager_button:
        message_data["attachments"] = [MAX_MANAGER_KEYBOARD]

    elif show_menu:
        message_data["attachments"] = [MAX_MAIN_KEYBOARD]

    response = requests.post(
        f"{MAX_API_URL}/messages",
        headers={
            "Authorization": MAX_BOT_TOKEN,
            "Content-Type": "application/json"
        },
        params={
            "user_id": user_id
        },
        json=message_data,
        timeout=30,
        verify=MAX_CA_BUNDLE
    )

    print(
        "📤 MAX: отправка сообщения:",
        response.status_code,
        flush=True
    )

    if not response.ok:
        print(
            "❌ MAX: ответ API:",
            response.text[:500],
            flush=True
        )

    response.raise_for_status()

    return response.json()
REMINDER_TEXT = (
    "✈️ Пора подумать о следующем путешествии! 🌴\n\n"
    "Мечтаете о море, интересных экскурсиях или отдыхе всей семьёй?\n\n"
    "Напишите мне, и я помогу выбрать направление, отель "
    "и подходящие даты. 😊"
)


def send_daily_reminders():
    today = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")

    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        "INSERT OR IGNORE INTO reminder_runs (run_date) VALUES (?)",
        (today,)
    )

    if cursor.rowcount == 0:
        connection.close()
        print(
            f"⏭️ Рассылка за {today} уже запускалась. Повтор пропущен.",
            flush=True
        )
        return

    connection.commit()
    cursor.execute("""
        SELECT platform, user_id
        FROM reminder_subscribers
        WHERE is_active = 1
    """)

    subscribers = cursor.fetchall()
    connection.close()

    print(
        f"📨 Рассылка: найдено получателей — {len(subscribers)}",
        flush=True
    )

    for platform, user_id in subscribers:
        try:
            if platform == "max":
                send_max_message(
                    int(user_id),
                    REMINDER_TEXT
                )

            elif platform == "telegram":
                response = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(user_id),
                        "text": REMINDER_TEXT
                    },
                    timeout=30
                )
                response.raise_for_status()

            print(
                f"✅ Напоминание отправлено: {platform}, {user_id}",
                flush=True
            )

        except Exception as e:
            print(
                f"❌ Ошибка рассылки {platform}, {user_id}: {e}",
                flush=True
            )
# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ MAX
# ============================================================

def send_max_request_to_manager(user_id, chat_id):

    try:
        memory_id = f"max:{user_id}"

        # Формируем заявку из истории клиента MAX
        request_text = create_manager_request(
            memory_id,
            "Клиент MAX",
            None
        )

        # Проверяем обязательные поля
        missing_fields = get_missing_manager_fields(
            request_text
        )

        # Если данных недостаточно — менеджеру пока не отправляем
        if missing_fields:

            print(
                f"⚠️ MAX: заявка пользователя {user_id} "
                f"не отправлена. Не хватает: "
                f"{', '.join(field for field, question in missing_fields)}",
                flush=True
            )

            return False, missing_fields
       
        # Проверяем, не отправляли ли уже такую же заявку
        if is_manager_request_duplicate(
            "max",
            user_id,
            request_text
        ):
            print(
                f"♻️ MAX: повторная заявка пользователя {user_id} "
                f"не отправлена",
                flush=True
            )

            return "duplicate", []
            
        request_lines = [
            line
            for line in request_text.splitlines()
            if not line.startswith("Имя:")
            and not line.startswith("Контакт:")
        ]
        
        request_text = "\n".join(request_lines)
        
        manager_message = (
            "🔥 НОВАЯ ЗАЯВКА ИЗ MAX\n\n"
            f"{request_text}"
        )

        # Отправляем заявку и контакт клиента в группу MAX
        send_max_group_message(
            manager_message,
            contact_user_id=user_id
        )
        save_manager_request(
            "max",
            user_id,
            request_text
        )
        print(
            f"📩 MAX: заявка пользователя {user_id} "
            f"отправлена в группу MAX",
            flush=True
        )

        return True, []

    except Exception as e:

        print(
            "❌ MAX: ошибка отправки заявки менеджеру:",
            type(e).__name__,
            str(e),
            flush=True
        )

        return False, []
def process_max_message(user_id, text, chat_id):

    try:
       
        memory_id = f"max:{user_id}"

        # ----------------------------------------------------
        # /START В MAX
        # ----------------------------------------------------

        if text.strip().lower() == "/start":
            save_reminder_subscriber("max", user_id)
            send_max_message(
                user_id,
                "👋 Привет!\n\n"
                "Я помощник по путешествиям офиса Anex на Звездном бульваре. "
                "Я использую много личной информации, которой меня обучила сама владелица офиса Ирина.\n\n"
                "Можете просто написать мне свой вопрос или воспользоваться кнопками ниже.",
                show_menu=True
            )

            return
        # ----------------------------------------------------
        # КНОПКА "ЧТО Я УМЕЮ"
        # ----------------------------------------------------

        if text == "Что я умею":

            send_max_message(
                user_id,
                "Я могу помочь спланировать отдых и выбрать подходящий вариант.\n\n"
                "Например:\n"
                "• подобрать направление под ваш бюджет;\n"
                "• посоветовать отели;\n"
                "• сравнить несколько отелей;\n"
                "• помочь выбрать отдых с ребёнком;\n"
                "• рассказать о пляже, питании и инфраструктуре отеля;\n"
                "• проверить актуальную информацию и правила въезда;\n"
                "• помочь сформировать запрос и отправить заявку менеджеру.\n\n"
                "Можно писать мне обычными сообщениями, например:\n"
                "«Куда поехать с ребёнком в октябре?»\n"
                "«Сравни Rixos и Sunrise»\n"
                "«Что выбрать до 200 000 ₽?»",
                show_menu=True
            )

            return

        # ----------------------------------------------------
        # КНОПКА "КАК ЗАБРОНИРОВАТЬ"
        # ----------------------------------------------------

        if text == "Как забронировать":

            send_max_message(
                user_id,
                "📋 Как забронировать тур:\n\n"
                "1️⃣ Расскажите мне, куда и когда хотите поехать, "
                "кто едет и какой примерно бюджет.\n\n"
                "2️⃣ Я помогу определиться с направлением и отелем "
                "и отвечу на вопросы.\n\n"
                "3️⃣ Когда вариант выбран, вместе отправим заявку менеджеру.\n\n"
                "4️⃣ Менеджер поможет с бронированием, договором и оплатой.\n\n"
                "Можете начать прямо сейчас — просто напишите, куда хотите поехать.",
                show_menu=True
            )

            return

        # ----------------------------------------------------
        # КНОПКА "ИДЕИ ДЛЯ ОТДЫХА"
        # ----------------------------------------------------

        if text == "Идеи для отдыха":

            send_max_message(
                user_id,
                "Давайте подберем несколько идей для отдыха.\n\n"
                "Я могу рассказать про множество интересных мест, "
                "сравнить направления и многое другое. "
                "Можно просто написать любые вводные "
                "(например, свой бюджет) — дальше я помогу.",
                show_menu=True
            )

            return

        # ----------------------------------------------------
        # КНОПКА "ОТПРАВИТЬ ЗАЯВКУ МЕНЕДЖЕРУ"
        # ----------------------------------------------------

        if text == "❗️ Отправить заявку менеджеру":

            success, missing_fields = (
                send_max_request_to_manager(user_id, chat_id)
            )

            if missing_fields:

                questions = "\n".join(
                    f"• {question}"
                    for field, question in missing_fields
                )

                send_max_message(
                    user_id,
                    "Давайте не будем отправлять пустую заявку 🙂\n\n"
                    "Мне нужно уточнить ещё немного информации:\n\n"
                    f"{questions}\n\n"
                    "Можете написать всё одним сообщением.",
                    show_menu=True
                )

            elif success == "duplicate":

                send_max_message(
                    user_id,
                    "✅ Эта заявка уже отправлена менеджеру.\n\n"
                    "Повторно отправлять её не нужно — менеджер уже получил данные.",
                    show_menu=True
                )
            elif success:

                send_max_message(
                    user_id,
                    "✅ Готово! Я отправил вашу заявку менеджеру.\n\n"
                    "Он получил основные детали вашего запроса.",
                    show_menu=True
                )

            else:

                send_max_message(
                    user_id,
                    "😔 Не удалось отправить заявку менеджеру. "
                    "Попробуйте ещё раз.",
                    show_menu=True
                )

            return
        # ----------------------------------------------------
        # ОБЫЧНОЕ СООБЩЕНИЕ → AI
        # ----------------------------------------------------

        answer, need_manager = ask_gpt(
            memory_id,
            text
        )

        # Если AI предлагает обратиться к менеджеру,
        # показываем меню с кнопкой отправки заявки
        if need_manager:
            send_max_message(
                user_id,
                answer,
                show_manager_button=True
            )
        else:
            send_max_message(
                user_id,
                answer
            )
    except Exception as e:

        print(
            "❌ Ошибка MAX:",
            type(e).__name__,
            str(e),
            flush=True
        )

# ============================================================
# TELEGRAM
# ============================================================

app = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=TELEGRAM_TOKEN
)
def send_telegram_manager_message(text):
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": MANAGER_CHAT_ID,
            "text": text
        },
        timeout=30
    )

    if not response.ok:
        print(
            "❌ Telegram Bot API:",
            response.status_code,
            response.text[:500],
            flush=True
        )

    response.raise_for_status()

    result = response.json()
# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

main_keyboard = ReplyKeyboardMarkup(
    [
        [
            "Что я умею",
            "Как забронировать"
        ],
        [
            "Идеи для отдыха",
            "❗️ Отправить заявку менеджеру"
        ]
    ],
    resize_keyboard=True
)
# ============================================================
# КНОПКА ПЕРЕДАЧИ ЗАЯВКИ МЕНЕДЖЕРУ
# ============================================================

manager_keyboard = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "📩 Отправить заявку менеджеру",
                callback_data="send_to_manager"
            )
        ]
    ]
)

# ============================================================
# OPENAI
# ============================================================
def test_coral_price():
    import re

    url = "https://www.coral.ru/hotels/turkey/aqi-pegasos-resort-hotel-alanya/?qp=3mXCNsoTYgYvGGFvTswFg8nZpPPHuxHlFMZovCKFb7GxGukscZHSYCYee%2BOnEmb28aeGO635XT1yODo2v1htifthyKtcpp4AetOsvYQDHeu6hVB%2BzYQE6YXQj7YuBfAtsQLvHQu148YR2cLxmC8vfx2iRIOZb4mpkmpbKUMfOBj%2BjixfxPjPQPCvSngheHv056ZAzgujLy8FTmeMTPzpYqUXsPnEJ%2FrS70ZDGN1uQeE8JFKQfa3gWpOmiVtVwrRFf%2BmpDI8yWU5oEvnb65%2FWGPbDamf1j2NUWXJYmqRg1eAQXxtZEXTD1DO75%2F9nbWsLDSW8Bzl6INwaE39B2lSvvOO43fMRM5YSyU%2FSQKATLPXg%2FywC2vuRsNZtpOHkBRFq9k7mnk3PmRTTpFI21I0hU37YokjAH1KTzyse80BYz40%3D&p=1&w=0&s=0&ws=10#hotelDetailSelectRoom"

    try:
        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        print(
            "🧪 CORAL TEST: HTTP",
            response.status_code,
            flush=True
        )

        print(
            "🧪 CORAL TEST: размер HTML",
            len(response.content),
            flush=True
        )

        match = re.search(
            r'"amount"\s*:\s*181572[.,]25',
            response.text
        )

        print(
            "🧪 CORAL TEST: цена найдена =",
            bool(match),
            flush=True
        )

    except Exception as e:
        print(
            "❌ CORAL TEST:",
            type(e).__name__,
            str(e),
            flush=True
        )


def test_anex_api():
    import requests

    url = (
        "https://api.anextour.ru/search"
        "?SEARCH_MODE=b2c"
        "&ADULT=2"
        "&CHECKIN_BEG=20261025"
        "&CHECKIN_END=20261025"
        "&CHILD=0"
        "&COSTMAX="
        "&COSTMIN="
        "&HOTELLIST="
        "&NIGHTMAX=7"
        "&NIGHTMIN=7"
        "&STATE=turkey"
        "&TOWNFROM=moskva"
        "&CURRENCY=1"
        "&FILTER=1"
        "&FREIGHT=1"
        "&PARTITION_PRICE=2"
        "&PRICE_PAGE=1"
        "&RECONPAGE=200"
        "&REGULAR=True"
        "&CHARTER=True"
        "&SORT_TYPE=0"
        "&SEARCH_TYPE=PACKET_TOUR"
    )

    try:
        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
        )

        print(
            "🧪 ANEX API: HTTP =",
            response.status_code,
            flush=True
        )

        print(
            "🧪 ANEX API: размер ответа =",
            len(response.content),
            flush=True
        )

        print(
            "🧪 ANEX API: тип ответа =",
            response.headers.get("Content-Type"),
            flush=True
        )

        try:
            data = response.json()

            print(
                "🧪 ANEX API: тип JSON =",
                type(data).__name__,
                flush=True
            )
            if isinstance(data, list):
                print(
                    "🧪 ANEX API: количество элементов =",
                    len(data),
                    flush=True
                )

                if data:
                    first = data[0]
                    prices = first.get("prices") if isinstance(first, dict) else None

                    print(
                        "🧪 ANEX API: тип prices =",
                        type(prices).__name__,
                        flush=True
                    )

                    if isinstance(prices, list):
                        print(
                            "🧪 ANEX API: количество предложений =",
                            len(prices),
                            flush=True
                        )
                        print(
                            "🧪 ANEX: ПЕРВЫЕ 5 ТУРОВ",
                            flush=True
                        )

                        for i, tour in enumerate(prices[:5], start=1):
                            if not isinstance(tour, dict):
                                continue

                            print(
                                f"🧪 ANEX ТУР {i}:",
                                "Отель =", tour.get("hotelName"),
                                "| Звёзды =", tour.get("starName"),
                                "| Номер =", tour.get("roomName"),
                                "| Питание =", tour.get("mealName"),
                                "| Цена =", tour.get("additional_price"),
                                "| Валюта =", tour.get("currencyAlias"),
                                "| Дата =", tour.get("hotelCheckIn"),
                                flush=True
                            )

                        if prices and isinstance(prices[0], dict):
                            offer = prices[0]
                            print(
                                "🧪 ANEX ПРОВЕРКА: ",
                                "checkIn =", offer.get("checkIn"),
                                "| nights =", offer.get("nights"),
                                "| economIn =", offer.get("economIn"),
                                "| economOut =", offer.get("economOut"),
                                "| freightExternal =", offer.get("freightExternal"),
                                "| hotelAvailability =", offer.get("hotelAvailability"),
                                "| enable =", offer.get("enable"),
                                "| currencyInc =", offer.get("currencyInc"),
                                flush=True
                            )
                            print(
                                "🧪 ANEX ПЕРЕЛЁТ: flightData =",
                                str(offer.get("flightData"))[:700],
                                flush=True
                            )

                            print(
                                "🧪 ANEX ПЕРЕЛЁТ: packet_Type =",
                                offer.get("packet_Type"),
                                flush=True
                            )

                            print(
                                "🧪 ANEX ПЕРЕЛЁТ: tourTypeName =",
                                offer.get("tourTypeName"),
                                flush=True
                            )

                            print(
                                "🧪 ANEX ПЕРЕЛЁТ: currencyInc =",
                                offer.get("currencyInc"),
                                flush=True
                            )

                            print(
                                "🧪 ANEX ПЕРЕЛЁТ: tourUrl =",
                                offer.get("tourUrl"),
                                flush=True
                            )
                            print(
                                "🧪 ANEX API: поля предложения =",
                                list(offer.keys()),
                                flush=True
                            )

                            for key in (
                                "price",
                                "converted_price",
                                "additional_price",
                                "hotelCheckIn",
                                "hotelCheckOut",
                                "townFrom",
                                "room",
                                "meal",
                                "currency"
                            ):
                                if key in offer:
                                    print(
                                        f"🧪 ANEX API: предложение {key} =",
                                        offer[key],
                                        flush=True
                                    )
                    print(
                        "🧪 ANEX API: тип первого элемента =",
                        type(first).__name__,
                        flush=True
                    )

                    if isinstance(first, dict):
                        print(
                            "🧪 ANEX API: поля первого элемента =",
                            list(first.keys()),
                            flush=True
                        )

                        for key in (
                            "converted_price",
                            "additional_price",
                            "price",
                            "hotelCheckIn",
                            "hotelCheckOut",
                            "result"
                        ):
                            if key in first:
                                print(
                                    f"🧪 ANEX API: {key} =",
                                    first[key],
                                    flush=True
                                )
            if isinstance(data, dict):
                print(
                    "🧪 ANEX API: поля JSON =",
                    list(data.keys())[:20],
                    flush=True
                )

                result = data.get("result")

                if isinstance(result, dict):
                    print(
                        "🧪 ANEX API: результат поиска =",
                        {
                            "countTotal": result.get("countTotal"),
                            "minPrice": result.get("minPrice"),
                            "maxPrice": result.get("maxPrice")
                        },
                        flush=True
                    )

        except ValueError:
            print(
                "🧪 ANEX API: ответ не является JSON",
                flush=True
            )

    except Exception as e:
        print(
            "❌ ANEX API:",
            type(e).__name__,
            str(e),
            flush=True
        )

def test_biblio_page():
    import requests

    url = (
        "https://www.bgoperator.ru/price.shtml"
        "?action=price"
        "&tid=211"
        "&flt2=100510000863"
        "&bfr=1"
        "&id_price=121110183696"
        "&data=22.10.2026"
        "&d2=22.10.2026"
        "&f7=8"
        "&F4=102625354855"
        "&flt=100411293179"
    )

    try:
        response = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        html = response.text

        print("🧪 BIBLIO: HTTP =", response.status_code, flush=True)
        print("🧪 BIBLIO: размер HTML =", len(response.content), flush=True)
        print("🧪 BIBLIO: адрес =", response.url, flush=True)
        print("🧪 BIBLIO: туры =", html.lower().count("туры"), flush=True)
        print("🧪 BIBLIO: рубли =", html.count("руб"), flush=True)
        print("🧪 BIBLIO: начало =", html[:300].replace("\n", " "), flush=True)
        import re

        for price in ["151687", "170476", "152081"]:
            found = bool(re.search(
                r"\b" + r"\s*".join(price) + r"\b",
                html
            ))
            print("💰 BIBLIO:", price, "=", found, flush=True)

        for word in ["Siesta", "Beach Apart", "STUDIO ROOM"]:
            print(
                "🏨 BIBLIO:",
                word,
                "=",
                word.lower() in html.lower(),
                flush=True
            )
        for word in ["search", "price", "api", "json", "tour", "iframe", "script"]:
            print(
                "🧪 BIBLIO:",
                word,
                "=",
                html.lower().count(word),
                flush=True
            )
    except Exception as e:
        print("❌ BIBLIO:", type(e).__name__, str(e), flush=True)
def ask_gpt(user_id, user_message):
    history = get_history(
        user_id,
        limit=20
    )
    messages = history + [
        {
            "role": "user",
            "content": user_message
        }
    ]
    price_keywords = [
        "цена",
        "цену",
        "цены",
        "ценам",
        "стоимость",
        "стоит",
        "сколько",
        "рассчитай",
        "расчет",
        "расчёт",
        "посчитай",
        "подбери тур",
        "найди тур",
        "горящий тур"
    ]

    is_price_request = any(
        keyword in user_message.lower()
        for keyword in price_keywords
    )
    
    try:
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=[
                {
                    "role": "developer",
                    "content": (
                        SYSTEM_PROMPT
                        + "\n\nТекущая дата: "
                        + datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y")
                        + ". Используй её для определения года поездки."
                    )
                }
            ] + messages,
            tools=[
                {
                    "type": "web_search",
                    "search_context_size": "high",    
                    "filters": {
                        "allowed_domains": [
                            "anextour.ru",
                            "bgoperator.ru",
                            "coral.ru",
                            "fstravel.com",
                            "letsfly.travel",
                            "loti.ru",
                            "paks.ru",
                            "pegast.ru",
                            "r-express.ru",
                            "space-travel.ru",
                            "sunmar.ru",
                            "arttour.ru",
                            "intourist.ru",
                            "ambotis.ru",
                            "icstrvl.ru",
                            "itmgroup.ru",
                            "kazunion.ru",
                            "oneclick.travel",
                            "onetouch.travel",
                            "pac.ru",
                            "resort-holiday.com",
                            "crystalbaytours.ru",
                            "online.xpress.travel",
                            "alean.ru",
                            "delfin-tour.ru",
                            "magput.ru",
                            "online-express.ru",
                            "ostrovok.ru",
                            "tour-platform.ru"
                        ]
                    }
                }
            ],
            include=["web_search_call.action.sources"],
            tool_choice="required" if is_price_request else "auto"
        )
        web_search_calls = [
            item
            for item in response.output
            if item.type == "web_search_call"
        ]

        print(
            f"🔎 WEB SEARCH: запрос цены = {is_price_request}",
            flush=True
        )

        print(
            f"🔎 WEB SEARCH: вызовов = {len(web_search_calls)}",
            flush=True
        )

        for item in web_search_calls:
            print(
                f"🔎 WEB SEARCH: статус = {item.status}",
                flush=True
            )

            action = getattr(item, "action", None)
            sources = getattr(action, "sources", None)

            if sources:
                for source in sources:
                    print(
                        "🔗 ИСТОЧНИК:",
                        getattr(source, "url", ""),
                        flush=True
                    )
        answer = response.output_text
        need_manager = "[NEED_MANAGER]" in answer
        
        # Убираем технический маркер из сообщения
        answer = answer.replace("[NEED_MANAGER]", "").strip()
        
        # Добавляем реальный контакт только при необходимости
        if need_manager and MANAGER_CONTACT:
            answer += f"\n\n📞 Рабочий телефон: {MANAGER_CONTACT}"
        
        save_message(
            user_id,
            "user",
            user_message
        )

        save_message(
            user_id,
            "assistant",
            answer
        )
        
        return answer, need_manager

    except Exception as e:

        print("========================================")
        print("❌ ОШИБКА OPENAI")
        print("========================================")

        print(
            "Тип:",
            type(e).__name__,
            flush=True
        )

        print(
            "Ошибка:",
            str(e),
            flush=True
        )

        print("========================================")

        raise

# ============================================================
# ФОРМИРОВАНИЕ ЗАЯВКИ ДЛЯ МЕНЕДЖЕРА
# ============================================================

def create_manager_request(user_id, first_name, username):

    history = get_history(
        user_id,
        limit=20
    )

    conversation_text = ""

    for item in history:

        role = "Клиент" if item["role"] == "user" else "Бот"

        conversation_text += (
            f"{role}: {item['content']}\n\n"
        )

    contact = (
        f"@{username}"
        if username
        else f"Telegram ID: {user_id}"
    )

    extraction_prompt = f"""
Ты формируешь краткую заявку для менеджера туристического агентства.

Из переписки извлеки только фактически известные данные.

Никогда не придумывай отсутствующие данные.

Верни заявку СТРОГО в следующем формате:

Вылет: ...
Страна: ...
Даты: ...
Ночи: ...
Туристы: ...
Бюджет: ...
Отель: ...

Если какое-то поле неизвестно, напиши:
не указано

Не добавляй пояснения, приветствия или комментарии.

Переписка:

{conversation_text}
"""

    response = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "developer",
                "content": (
                    "Твоя задача — извлечь факты из переписки "
                    "и сформировать краткую заявку менеджеру. "
                    "Не придумывай отсутствующие данные."
                )
            },
            {
                "role": "user",
                "content": extraction_prompt
            }
        ]
    )

    travel_details = response.output_text.strip()

    travel_details = "\n".join(
        line
        for line in travel_details.splitlines()
        if not line.startswith(("Имя:", "Контакт:"))
    ).strip()

    return (
        f"Имя: {first_name}\n"
        f"Контакт: {contact}\n"
        f"{travel_details}"
    )

# ============================================================
# НАЖАТИЕ КНОПКИ "ОТПРАВИТЬ ЗАЯВКУ МЕНЕДЖЕРУ"
# ============================================================

@app.on_callback_query(filters.regex("^send_to_manager$"))
async def send_to_manager(client, callback_query):

    user = callback_query.from_user
    user_id = user.id

    try:

        # ----------------------------------------------------
        # Формируем карточку заявки через OpenAI
        # ----------------------------------------------------

        request_text = await asyncio.to_thread(
            create_manager_request,
            user_id,
            user.first_name or "не указано",
            user.username
        )

        # ----------------------------------------------------
        # Отправляем заявку менеджеру
        # ----------------------------------------------------

        manager_message = (
            "🔥 НОВАЯ ЗАЯВКА ИЗ БОТА\n\n"
            f"{request_text}"
        )

        await asyncio.to_thread(
            send_telegram_manager_message,
            manager_message
        )

        # ----------------------------------------------------
        # Сообщаем клиенту об успешной отправке
        # ----------------------------------------------------

        await callback_query.answer(
            "Заявка отправлена менеджеру ✅",
            show_alert=True
        )

        await callback_query.message.reply(
            "✅ Готово! Я отправил вашу заявку менеджеру. "
            "Он увидит детали запроса и сможет продолжить общение с вами."
        )

        # ----------------------------------------------------
        # Убираем кнопку после отправки
        # чтобы не нажимали несколько раз
        # ----------------------------------------------------

        await callback_query.message.edit_reply_markup(
            reply_markup=None
        )

        print(
            f"📩 Заявка пользователя {user_id} "
            f"отправлена менеджеру",
            flush=True
        )

    except Exception as e:

        print("========================================")
        print("❌ ОШИБКА ПЕРЕДАЧИ ЗАЯВКИ")
        print("========================================")

        print(
            type(e).__name__,
            str(e),
            flush=True
        )

        await callback_query.answer(
            "Не удалось отправить заявку. Попробуйте ещё раз.",
            show_alert=True
        )
    # ----------------------------------------------------
    # Проверяем есть ли нужные поля
    # ----------------------------------------------------

def get_missing_manager_fields(request_text):

    required_fields = {
        "Страна": "куда хотите поехать?",
        "Вылет": "из какого города планируете вылет?",
        "Даты": "на какие даты или примерно в какой месяц планируете поездку?",
        "Ночи": "на сколько ночей планируете поездку?",
        "Туристы": "сколько взрослых и детей едет? Если есть дети — укажите их возраст на момент поездки."
    }

    values = {}

    for line in request_text.splitlines():

        if ":" not in line:
            continue

        field, value = line.split(":", 1)

        values[field.strip()] = value.strip()

    missing = []

    for field, question in required_fields.items():

        value = values.get(field, "").lower()

        if value in {
            "",
            "...",
            "не указано",
            "неизвестно",
            "нет данных"
        }:
            missing.append((field, question))

    return missing
# ============================================================
# КНОПКА ГЛАВНОГО МЕНЮ "ЗАЯВКА МЕНЕДЖЕРУ"
# ============================================================

@app.on_message(
    filters.text &
    filters.regex("^❗️ Отправить заявку менеджеру$")
)
async def manager_request_button(client, message):

    user = message.from_user
    user_id = user.id

    try:

        # ----------------------------------------------------
        # Сначала формируем заявку
        # ----------------------------------------------------

        request_text = await asyncio.to_thread(
            create_manager_request,
            user_id,
            user.first_name or "не указано",
            user.username
        )

        # ----------------------------------------------------
        # Проверяем обязательные поля
        # ----------------------------------------------------

        missing_fields = get_missing_manager_fields(
            request_text
        )

        # ----------------------------------------------------
        # Если данных не хватает —
        # заявку менеджеру НЕ отправляем
        # ----------------------------------------------------

        if missing_fields:

            questions = "\n".join(
                f"• {question}"
                for field, question in missing_fields
            )

            await message.reply(
                "Давайте не будем отправлять пустую заявку 🙂\n\n"
                "Мне нужно уточнить ещё немного информации:\n\n"
                f"{questions}\n\n"
                "Можете написать всё одним сообщением.",
                reply_markup=main_keyboard
            )

            print(
                f"⚠️ Заявка пользователя {user_id} не отправлена. "
                f"Не хватает: "
                f"{', '.join(field for field, question in missing_fields)}",
                flush=True
            )

            return

        # ----------------------------------------------------
        # Все обязательные данные есть —
        # отправляем заявку менеджеру
        # ----------------------------------------------------

        manager_message = (
            "🔥 НОВАЯ ЗАЯВКА ИЗ БОТА\n\n"
            f"{request_text}"
        )

        await asyncio.to_thread(
            send_telegram_manager_message,
            manager_message
        )

        await message.reply(
            "✅ Готово! Я отправил вашу заявку менеджеру.\n\n"
            "Он получил основные детали вашего запроса.",
            reply_markup=main_keyboard
        )

        print(
            f"📩 Заявка пользователя {user_id} "
            f"отправлена менеджеру через главное меню",
            flush=True
        )

    except Exception as e:

        print(
            "❌ Ошибка отправки заявки менеджеру:",
            type(e).__name__,
            str(e),
            flush=True
        )

        await message.reply(
            "😔 Не удалось отправить заявку менеджеру. "
            "Попробуйте ещё раз.",
            reply_markup=main_keyboard
        )
# ============================================================
# /START
# ============================================================

@app.on_message(filters.command("start"))
async def start(client, message):
    save_reminder_subscriber("telegram", message.from_user.id)
    user_id = message.from_user.id

    print(
        f"🚀 Пользователь {user_id} нажал /start",
        flush=True
    )

    await message.reply(
        "👋 Привет!\n\n"
        "Я помощник по путешествиям офиса Anex на Звездном бульваре. "
        "Я использую много личной информации, которой меня обучила сама владелица офиса Ирина.\n\n"
        "Можешь просто написать мне свой вопрос или воспользоваться кнопками ниже ",
        reply_markup=main_keyboard
    )


# ============================================================
# /CLEAR
# ============================================================

@app.on_message(filters.command("clear"))
async def clear(client, message):

    user_id = message.from_user.id

    clear_history(user_id)

    await message.reply(
        "🧹 Память очищена.\n\n"
        "Начинаем разговор с чистого листа."
    )
# ============================================================
# КНОПКА "ЧТО Я УМЕЮ"
# ============================================================

@app.on_message(filters.text & filters.regex("^Что я умею$"))
async def what_can_i_do(client, message):

    await message.reply(
        "Я могу помочь спланировать отдых и выбрать подходящий вариант.\n\n"
        "Например:\n"
        "• подобрать направление под ваш бюджет;\n"
        "• посоветовать отели;\n"
        "• сравнить несколько отелей;\n"
        "• помочь выбрать отдых с ребёнком;\n"
        "• рассказать о пляже, питании и инфраструктуре отеля;\n"
        "• проверить актуальную информацию и правила въезда;\n"
        "• помочь сформировать запрос и отправить заявку менеджеру.\n\n"
        "Можно писать мне обычными сообщениями, например:\n"
        "«Куда поехать с ребёнком в октябре?»\n"
        "«Сравни Rixos и Sunrise»\n"
        "«Что выбрать до 200 000 ₽?» ",
        reply_markup=main_keyboard
    )
# ============================================================
# КНОПКА "КАК ЗАБРОНИРОВАТЬ"
# ============================================================

@app.on_message(filters.text & filters.regex("^Как забронировать$"))
async def how_to_book(client, message):

    await message.reply(
        "📋 Как забронировать тур:\n\n"
        "1️⃣ Расскажите мне, куда и когда хотите поехать, кто едет и какой примерно бюджет.\n\n"
        "2️⃣ Я помогу определиться с направлением и отелем и отвечу на вопросы.\n\n"
        "3️⃣ Когда вариант выбран, вместе отправим заявку менеджеру.\n\n"
        "4️⃣ Менеджер поможет с бронированием, договором и оплатой.\n\n"
        "Можете начать прямо сейчас — просто напишите, куда хотите поехать ",
        reply_markup=main_keyboard
    )

# ============================================================
# КНОПКА "ИДЕИ ДЛЯ ОТДЫХА"
# ============================================================

@app.on_message(filters.text & filters.regex("Идеи для отдыха"))
async def vacation_ideas(client, message):

    await message.reply(
        "Давайте подберем несколько идей для отдыха.\n\n"
        "Я могу рассказать про множество интересных мест, сравнить направления и многое другое. "
        "Можно просто написать любые вводные (например, свою бюджет) — дальше я помогу ",
        reply_markup=main_keyboard
    )
# ============================================================
# СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================

@app.on_message(filters.private & filters.incoming & filters.text)
async def chat_with_gpt(client, message):
    if str(message.chat.id) == str(MANAGER_CHAT_ID):
        return

    # Не обрабатываем команды
    if message.text.startswith("/"):
        return
    menu_buttons = {
        "Что я умею",
        "Как забронировать",
        "Идеи для отдыха",
        "❗️ Отправить заявку менеджеру"
    }
    
    if message.text in menu_buttons:
        return
    user_id = message.from_user.id

    try:

        answer, need_manager = await asyncio.to_thread(
            ask_gpt,
            user_id,
            message.text
        )
        
        if need_manager:
            await message.reply(
                answer,
                reply_markup=manager_keyboard
            )
        else:
            await message.reply(answer)

    except Exception as e:

        print("====================================")
        print("💥 ОШИБКА ОБРАБОТЧИКА")
        print("====================================")

        print(
            "Класс:",
            type(e).__name__,
            flush=True
        )

        print(
            "Ошибка:",
            str(e),
            flush=True
        )

        print("====================================")

        await message.reply(
            "😔 Технический перерыв (Ушел пить чай).\n\n"
            "Попробуй ещё раз позже."
        )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print("========================================")
    print("🚀 ЗАПУСК TELEGRAM-БОТА")
    print("========================================")

    # Создаём базу данных
    init_database()
    test_biblio_page()
    # Проверяем наличие сертификатов MAX
    check_max_cert_files()
   
    # Создаём общий CA bundle для MAX
    create_max_ca_bundle()

    # Проверяем подписку MAX в отдельном потоке
    threading.Thread(
        target=check_max_subscription,
        daemon=True
    ).start()

    # Запускаем Flask
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("🌐 Flask запущен", flush=True)
    print("🤖 Запускаю Telegram...", flush=True)
    
    app.run()
    
    print("🛑 Telegram-бот остановлен", flush=True)
