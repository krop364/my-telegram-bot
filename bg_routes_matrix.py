
"""BG: end-to-end discovery xml=11 -> package prices xml=51.
Standalone diagnostic: python bg_routes_matrix.py. Requires requests.
No imports from bot.py or bg_search.py. Does not modify any files.
"""
from collections import Counter
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit
import traceback
import requests

BASE = 'https://www.bgoperator.ru/'
API = urljoin(BASE, 'site')
CASES = [
    ('Москва → Турция', '100411293179', '100510000863', '20.11.2026', 7),
    ('Екатеринбург → Таиланд', '100410000051', '100510000892', '15.11.2026', 11),
    ('Екатеринбург → Таиланд', '100410000051', '100510000892', '15.11.2026', 13),
    ('Казань → Египет', '100410000047', '100510345650', '15.11.2026', 6),
    ('Казань → Египет', '100410000047', '100510345650', '15.11.2026', 9),
]

# Ограничение количества запросов на одно направление.
MAX_PROGRAMS_PER_CASE = 8
TIMEOUT = 40

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Referer': BASE,
})


def get_json(parameters):
    r = session.get(API, params=parameters, timeout=TIMEOUT)
    print('  HTTP', r.status_code, '| bytes', len(r.content), '|', r.url[:250])
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        print('  ОШИБКА: ответ не JSON:', r.text[:250])
        return {}


def persons_code(date):
    # Подтверждено только для этих двух дат и двух взрослых.
    return {
        '15.11.2026': '0151019900.0151019900',
        '20.11.2026': '0201019900.0201019900',
    }[date]


def allowed_nights(raw):
    return {int(x) for x in str(raw or '').split('/') if x.isdigit()}


def discover(from_id, to_id, date, nights):
    data = get_json([
        ('action', 'files'),
        ('flt', from_id),
        ('flt2', to_id),
        ('xml', '11'),
    ])

    rows = data.get('entries', [])
    if not isinstance(rows, list):
        print('  ОШИБКА: entries не список:', str(rows)[:150])
        return []

    print(
        '  Строк расписания:', len(rows),
        '| уникальных ID:',
        len({
            str(x.get('id_price'))
            for x in rows
            if isinstance(x, dict)
        })
    )

    exact = [
        x for x in rows
        if isinstance(x, dict)
        and x.get('date') == date
        and nights in allowed_nights(x.get('duration'))
    ]

    print('  Совпали дата и ночи:', len(exact))

    if not exact:
        dates = sorted({
            str(x.get('date', ''))
            for x in rows
            if isinstance(x, dict) and x.get('date')
        })
        print('  Даты в расписании (первые 12):', dates[:12])
        return []

    # Одну программу запрашиваем только один раз.
    unique = {}
    for x in exact:
        program = str(x.get('id_price', ''))
        if program.isdigit():
            unique.setdefault(program, x)

    print('  Подходящие программы:', len(unique))

    for program, row in unique.items():
        print(
            '   ', program,
            '|', row.get('route'),
            '| дата', row.get('date'),
            '| ночи', row.get('duration')
        )

    return list(unique.items())


def package_prices(from_id, to_id, date, nights, program):
    p = [
        ('xml', '51'),
        ('action', 'price'),
        ('id_price', program),
        ('flt2', to_id),
    ]

    p.extend([
        ('f8', v)
        for v in ('BB', 'HB', 'FB', 'AI', 'AO')
    ])

    p.extend([
        ('entr', '-100'),
        ('data', date),
        ('f7', str(nights)),
        ('flt', from_id),
        ('p', persons_code(date)),
    ])

    data = get_json(p)

    if data.get('ERROR'):
        print('  ОШИБКА BG:', data['ERROR'])
        return []

    section = data.get('PRICE_SECTION') or {}
    entries = section.get('entries') or []

    hotels = {
        str(h.get('ID')): h.get('TITLE', '')
        for h in (data.get('FILTER') or {}).get('HOTELS', [])
        if isinstance(h, dict)
    }

    print(
        '  Предложений API:', len(entries),
        '| отелей в FILTER:', len(hotels),
        '| next_page:', bool(section.get('next_page'))
    )

    valid = []
    rejects = Counter()

    for e in entries:
        if not isinstance(e, dict):
            rejects['не объект'] += 1
            continue

        if (
            str(e.get('tour_date')) != date
            or str(e.get('duration')) != str(nights)
        ):
            rejects['дата/ночи'] += 1
            continue

        for price in e.get('prices') or []:
            if not isinstance(price, dict):
                continue

            try:
                rub = int(
                    str(price.get('RUR', '')).replace(' ', '')
                )
            except (ValueError, TypeError):
                rejects['цена'] += 1
                continue

            if rub <= 0:
                rejects['цена'] += 1
                continue

            href0 = str(section.get('href0') or '')
            href1 = str(e.get('href1') or '')
            href2 = str(price.get('href2') or '')

            if '/zaya' not in href0 or 'templ=' not in href1:
                rejects['ссылка'] += 1
                continue

            link = (
                urljoin(BASE, href0)
                + href1
                + '&p='
                + persons_code(date)
                + href2
            )

            q = parse_qs(urlsplit(link).query)

            actual = {
                'dt': q.get('dt', [''])[0],
                'kol': q.get('kol', [''])[0],
                'p': q.get('p', [''])[0],
                'templ': q.get('templ', [''])[0],
            }
            
            expected = {
                'dt': date,
                'kol': str(nights),
                'p': persons_code(date),
                'templ': program,
            }
            
            differences = {
                key: (expected[key], actual[key])
                for key in expected
                if actual[key] != expected[key]
            }
            
            if differences:
                rejects['параметры бронирования'] += 1
            
                if rejects['параметры бронирования'] == 1:
                    print('  ДИАГНОСТИКА ССЫЛКИ:', differences)
                    print('  ПРИМЕР:', link[:350])
            
                continue

            valid.append((
                rub,
                str(hotels.get(str(e.get('id_hotel')), '')),
                str(e.get('aircompany') or ''),
                link
            ))

    unique = list({
        v[3]: v
        for v in valid
    }.values())

    print(
        '  Подходящих вариантов:', len(valid),
        '| уникальных ссылок:', len(unique),
        '| отклонено:', dict(rejects)
    )

    for rub, hotel, airline, link in sorted(unique)[:2]:
        print(
            '   ',
            hotel or '[без названия]',
            '|',
            f'{rub:,} ₽',
            '|',
            airline
        )
        print('    Бронирование:', link[:280])

    return unique


def main():
    print('=== BG: АВТОМАТИЧЕСКИЙ ПОИСК xml=11 → xml=51 ===')
    print('Самостоятельный тест без bg_search.py, bot.py и Render.')

    for title, from_id, to_id, date, nights in CASES:
        print('\n' + '=' * 78)
        print(
            title,
            '|', date,
            '|', nights, 'ночей',
            '| 2 взрослых'
        )

        try:
            programs = discover(
                from_id, to_id, date, nights
            )

            if not programs:
                print(
                    'ИТОГО: нет подходящих программ '
                    'в расписании xml=11'
                )
                continue

            all_offers = []

            for program, row in programs[:MAX_PROGRAMS_PER_CASE]:
                print(
                    '\nПРОГРАММА',
                    program,
                    '|',
                    row.get('route', '')
                )

                all_offers.extend(
                    package_prices(
                        from_id,
                        to_id,
                        date,
                        nights,
                        program
                    )
                )

            unique = {
                offer[3]: offer
                for offer in all_offers
            }

            print(
                '\nИТОГО:',
                len(unique),
                'уникальных туров по',
                min(len(programs), MAX_PROGRAMS_PER_CASE),
                'программам'
            )

            if len(programs) > MAX_PROGRAMS_PER_CASE:
                print(
                    'ВНИМАНИЕ: лимит запросов; '
                    'осталось программ:',
                    len(programs) - MAX_PROGRAMS_PER_CASE
                )

        except Exception as exc:
            print(
                'ОШИБКА:',
                type(exc).__name__,
                str(exc)
            )
            traceback.print_exc()

    print('\n=== КОНЕЦ ===')


if __name__ == '__main__':
    main()
