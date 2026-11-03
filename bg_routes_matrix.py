
"""Самостоятельная проверка JSON API Библио-Глобуса и обнаружения программ.

Запуск в GitHub Actions: python bg_routes_matrix.py
Зависимости: requests (установлен в проекте). Не импортирует bg_search.py/bot.py.
Только чтение публичных страниц BG. Render не нужен.
"""
import json
import re
import traceback
from collections import Counter
from html import unescape
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

SITE = 'https://www.bgoperator.ru/site'
HOME = 'https://www.bgoperator.ru/'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Referer': HOME,
}

# Рабочие программы подтверждены ранее HTML-проверкой, а не новым JSON API.
# На Таиланде проверяем также Пхукет, который раньше отдавал неверную дату.
CASES = [
    {'title': 'Екатеринбург → Таиланд / Паттайя', 'from': '100410000051', 'to': '100510000892',
     'program': '121163457355', 'date': '15.11.2026', 'nights': 11, 'persons': '0151019900.0151019900'},
    {'title': 'Екатеринбург → Таиланд / Паттайя, 13 ночей', 'from': '100410000051', 'to': '100510000892',
     'program': '121163457355', 'date': '15.11.2026', 'nights': 13, 'persons': '0151019900.0151019900'},
    {'title': 'Екатеринбург → Таиланд / Пхукет', 'from': '100410000051', 'to': '100510000892',
     'program': '121166921602', 'date': '15.11.2026', 'nights': 13, 'persons': '0151019900.0151019900'},
    {'title': 'Казань → Египет', 'from': '100410000047', 'to': '100510345650',
     'program': '121110211282', 'date': '15.11.2026', 'nights': 6, 'persons': '0151019900.0151019900'},
    {'title': 'Казань → Египет, 9 ночей', 'from': '100410000047', 'to': '100510345650',
     'program': '121110211282', 'date': '15.11.2026', 'nights': 9, 'persons': '0151019900.0151019900'},
]

session = requests.Session()
session.headers.update(HEADERS)


def params(case, program=None):
    return [
        ('xml', '51'), ('action', 'price'), ('id_price', program or case['program']),
        ('flt2', case['to']), ('f8', 'BB'), ('f8', 'HB'), ('f8', 'FB'),
        ('f8', 'AI'), ('f8', 'AO'), ('entr', '-100'),
        ('data', case['date']), ('f7', str(case['nights'])),
        ('flt', case['from']), ('p', case['persons']),
    ]


def fetch_json(case, program=None):
    response = session.get(SITE, params=params(case, program), timeout=55)
    print('HTTP:', response.status_code, '| bytes:', len(response.content))
    print('URL:', response.url[:350])
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        print('НЕ JSON:', response.text[:350])
        return None


def examine(case, data, label):
    if not isinstance(data, dict):
        print(label, '| ответ не объект JSON')
        return

    section = data.get('PRICE_SECTION')
    if not isinstance(section, dict):
        print(label, '| PRICE_SECTION отсутствует; ключи:', list(data))
        print('Фрагмент:', json.dumps(data, ensure_ascii=False)[:450])
        return

    entries = section.get('entries') or []
    if not isinstance(entries, list):
        print(label, '| entries не список:', str(entries)[:200])
        return

    hotel_rows = (data.get('FILTER') or {}).get('HOTELS') or []
    hotels = {
        str(h.get('ID')): str(h.get('TITLE') or '').strip()
        for h in hotel_rows if isinstance(h, dict)
    }

    print(label, '| предложений:', len(entries), '| отелей в фильтре:', len(hotels))
    print('Даты:', dict(Counter(str(e.get('tour_date')) for e in entries if isinstance(e, dict))))
    print('Ночи:', dict(Counter(str(e.get('duration')) for e in entries if isinstance(e, dict))))
    print('Авиакомпании:', Counter(
        str(e.get('aircompany')) for e in entries if isinstance(e, dict)
    ).most_common(4))
    print('ID программ:', dict(Counter(
        str(e.get('id_price')) for e in entries if isinstance(e, dict)
    )))

    next_page = section.get('next_page') or ''
    print('next_page:', str(next_page)[:300] or '(нет)')

    rejected = Counter()
    valid = []

    for e in entries:
        if not isinstance(e, dict):
            rejected['не объект'] += 1
            continue

        if str(e.get('tour_date')) != case['date'] or str(e.get('duration')) != str(case['nights']):
            rejected['неверная дата/ночи'] += 1
            continue

        for price in e.get('prices') or []:
            if not isinstance(price, dict):
                continue

            try:
                rub = int(str(price.get('RUR', '')).replace(' ', ''))
            except (TypeError, ValueError):
                rejected['неверная цена'] += 1
                continue

            if rub <= 0:
                rejected['неверная цена'] += 1
                continue

            href0 = str(section.get('href0') or '')
            href1 = str(e.get('href1') or '')
            href2 = str(price.get('href2') or '')

            if '/zaya' not in href0 or 'templ=' not in href1:
                rejected['нет ссылки бронирования'] += 1
                continue

            url = urljoin(HOME, href0) + href1 + '&p=' + case['persons'] + href2
            q = parse_qs(urlsplit(url).query)

            if q.get('dt', [''])[0] != case['date'] or q.get('kol', [''])[0] != str(case['nights']):
                rejected['ссылка с неверной датой/ночами'] += 1
                continue

            if q.get('p', [''])[0] != case['persons']:
                rejected['состав туристов не совпал'] += 1
                continue

            valid.append((
                rub,
                hotels.get(str(e.get('id_hotel')), ''),
                str(e.get('aircompany') or ''),
                q.get('templ', [''])[0],
                url
            ))

    print('Подходящих ценовых вариантов:', len(valid), '| отклонено:', dict(rejected))
    print('Фактические templ:', dict(Counter(v[3] for v in valid)))
    print('Уникальных ссылок:', len({v[4] for v in valid}))

    for rub, hotel, airline, templ, url in sorted(valid)[:3]:
        print('  ', hotel or '[нет названия]', '|', f'{rub:,} ₽', '|', airline, '| templ=', templ)
        print('    ', url[:320])


def discover(case):
    """Проверяем наличие id_price в HTML общей страницы, без предположения о полноте списка."""
    p = [
        ('action', 'price'), ('tid', '211'), ('flt', case['from']),
        ('flt2', case['to']), ('bfr', '1'), ('data', case['date']),
        ('d2', case['date']), ('f7', str(case['nights'])),
        ('ho', '0'), ('p', case['persons']),
    ]

    r = session.get(HOME, params=p, timeout=45)
    r.raise_for_status()

    html = unescape(r.text)
    found = sorted(set(re.findall(
        r'(?:id_price|idprice)\s*[=:]\s*["\']?(\d{9,15})', html, re.I
    )))
    found += [
        v for v in re.findall(r'[?&]id_price=(\d{9,15})', html, re.I)
        if v not in found
    ]

    print('Общая страница:', r.status_code, '| HTML bytes:', len(r.content))
    print('Обнаруженные ID (не гарантирован полный список):', found[:25], '| всего:', len(found))
    return found


def main():
    print('=== BG: JSON API xml=51 — ТАИЛАНД И ЕГИПЕТ ===')
    print('Независимая диагностика; bg_search.py, bot.py, Render не используются.')

    discovery_cache = {}

    for case in CASES:
        print('\n' + '=' * 78)
        print(case['title'], '|', case['date'], '|', case['nights'], 'ночей', '| 2 взрослых')

        try:
            key = (case['from'], case['to'], case['date'])

            if key not in discovery_cache:
                discovery_cache[key] = discover(case)

            found = discovery_cache[key]
            data = fetch_json(case)

            examine(case, data, 'ИЗВЕСТНАЯ ПРОГРАММА ' + case['program'])

            # Один дополнительный ID с общей страницы:
            # проверяем, даёт ли он новые туры.
            extra = next((x for x in found if x != case['program']), None)

            if extra:
                print('\nПРОВЕРКА АВТОМАТИЧЕСКИ НАЙДЕННОЙ ПРОГРАММЫ:', extra)
                extra_data = fetch_json(case, extra)
                examine(case, extra_data, 'АВТОМАТИЧЕСКИ НАЙДЕННАЯ ' + extra)
            else:
                print('Дополнительная программа для проверки не обнаружена.')

        except Exception as exc:
            print('ОШИБКА:', type(exc).__name__, str(exc))
            traceback.print_exc()

    print('\n=== КОНЕЦ ===')


if __name__ == '__main__':
    main()
