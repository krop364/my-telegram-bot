
"""Universal BG catalog probe. Only reads local catalogs; no bot imports or edits.
Run: python bg_routes_matrix.py
Optional: python bg_routes_matrix.py --all
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

BASE = 'https://www.bgoperator.ru/'
API = urljoin(BASE, 'site')
ROOT = Path(__file__).resolve().parent

# Only these two-adult codes were verified in prior BG responses.
VERIFIED = {
    '15.11.2026': '0151019900.0151019900',
    '20.11.2026': '0201019900.0201019900',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Referer': BASE,
}



def load_catalog(filename, prefix):
    path = ROOT / filename

    if not path.is_file():
        raise FileNotFoundError(
            f'{filename} отсутствует рядом с bg_routes_matrix.py'
        )

    raw = json.loads(path.read_text(encoding='utf-8-sig'))

    print(f'\n=== ДИАГНОСТИКА КАТАЛОГА: {filename} ===')
    print('Тип данных:', type(raw).__name__)

    if isinstance(raw, dict):
        print('Ключи верхнего уровня:', list(raw.keys())[:20])

        for key in ('entries', 'items', 'data', 'countries', 'departures'):
            value = raw.get(key)
            if isinstance(value, list):
                raw = value
                print('Список найден в поле:', key)
                break

    if not isinstance(raw, list):
        print('Пример содержимого:', repr(raw)[:1000])
        raise ValueError(
            f'{filename}: не удалось найти список записей'
        )

    print('Всего записей:', len(raw))
    print('Первые три записи:')

    for row in raw[:3]:
        print(repr(row)[:1000])

    found = {}

    for row in raw:
        if not isinstance(row, dict):
            continue

        ident = str(
            row.get('id')
            or row.get('ID')
            or row.get('value')
            or ''
        )

        title = str(
            row.get('title_ru')
            or row.get('title')
            or row.get('name')
            or row.get('label')
            or ''
        ).strip()

        if ident.startswith(prefix) and ident.isdigit() and title:
            found[ident] = (ident, title, row)

    print(
        f'Записей с ID, начинающимся на {prefix}:',
        len(found)
    )

    if not found:
        print(
            'ВНИМАНИЕ: структура каталога отличается '
            'от ожидаемой.'
        )
        print(
            'Пришли эти диагностические строки — '
            'по ним определим правильные поля.'
        )
        raise ValueError(
            f'{filename}: формат записей требует уточнения'
        )

    return sorted(
        found.values(),
        key=lambda x: x[1].casefold(),
    )


def allowed_departures(country, departures):
    raw = country[2].get('town_from')

    if not raw:
        return departures

    ids = set(re.findall(r'1004\d+', str(raw)))

    return (
        [d for d in departures if d[0] in ids]
        if ids
        else departures
    )


def get_json(session, params):
    response = session.get(
        API,
        params=params,
        timeout=35,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError('Ответ BG не является JSON-объектом')

    return data


def nights_set(value):
    return {
        int(x)
        for x in re.findall(r'\d+', str(value or ''))
    }


def inspect_price(
    session,
    city_id,
    country_id,
    program,
    day,
    nights,
    persons,
):
    params = [
        ('xml', '51'),
        ('action', 'price'),
        ('id_price', program),
        ('flt2', country_id),
    ]

    params += [
        ('f8', meal)
        for meal in ('BB', 'HB', 'FB', 'AI', 'AO')
    ]

    params += [
        ('entr', '-100'),
        ('data', day),
        ('f7', str(nights)),
        ('flt', city_id),
        ('p', persons),
    ]

    data = get_json(session, params)

    if data.get('ERROR'):
        print('    BG ERROR:', str(data['ERROR'])[:130])
        return 0

    section = data.get('PRICE_SECTION') or {}
    entries = section.get('entries') or []

    hotels = {
        str(h.get('ID')): str(h.get('TITLE') or '')
        for h in (data.get('FILTER') or {}).get('HOTELS', [])
        if isinstance(h, dict)
    }

    valid = []
    rejected = Counter()

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        # Validate the full package, not a booking segment.
        if (
            str(entry.get('tour_date')) != day
            or str(entry.get('duration')) != str(nights)
        ):
            rejected['дата/ночи предложения'] += 1
            continue

        for price in entry.get('prices') or []:
            if not isinstance(price, dict):
                continue

            try:
                rub = int(
                    re.sub(
                        r'\s+',
                        '',
                        str(price.get('RUR') or ''),
                    )
                )
            except ValueError:
                rejected['цена'] += 1
                continue

            if rub <= 0:
                rejected['цена'] += 1
                continue

            href0 = str(section.get('href0') or '')
            href1 = str(entry.get('href1') or '')
            href2 = str(price.get('href2') or '')

            if '/zaya' not in href0 or 'templ=' not in href1:
                rejected['части ссылки'] += 1
                continue

            link = (
                urljoin(BASE, href0)
                + href1
                + '&p='
                + persons
                + href2
            )

            parsed = urlsplit(link)
            q = parse_qs(parsed.query)

            if (
                parsed.hostname not in (
                    'bgoperator.ru',
                    'www.bgoperator.ru',
                )
                or parsed.path != '/zaya'
                or q.get('p', [''])[0] != persons
                or q.get('templ', [''])[0] != program
            ):
                rejected['ссылка/программа/туристы'] += 1
                continue

            # For combined tours, dt/kol can describe
            # one booking segment rather than the full tour.
            # Preserve the BG booking link unchanged.
            valid.append((
                rub,
                hotels.get(str(entry.get('id_hotel')), ''),
                link,
            ))

    unique = {
        link: (rub, hotel, link)
        for rub, hotel, link in valid
    }

    print(
        f'    xml=51: {len(entries)} строк; '
        f'{len(unique)} ссылок; '
        f'отклонено {dict(rejected)}'
    )

    for rub, hotel, link in sorted(unique.values())[:1]:
        q = parse_qs(urlsplit(link).query)

        print(
            f'    Пример: '
            f'{hotel or "[отель без названия]"} '
            f'| {rub:,} ₽'
        )

        print(
            '    Ссылка: dt=',
            q.get('dt', [''])[0],
            'kol=',
            q.get('kol', [''])[0],
            '| полный тур:',
            day,
            nights,
            'ночей',
        )

    return len(unique)


def main():
    parser = argparse.ArgumentParser(
        description='BG: universal catalog and API test'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='проверить расписание всех стран',
    )

    parser.add_argument(
        '--countries',
        type=int,
        default=12,
        help='число стран в выборке',
    )

    parser.add_argument(
        '--max-schedule',
        type=int,
        default=30,
        help='лимит запросов xml=11',
    )

    parser.add_argument(
        '--max-prices',
        type=int,
        default=12,
        help='лимит запросов xml=51',
    )

    args = parser.parse_args()

    countries = load_catalog(
        'bg_countries.json',
        '1004',
    )

    departures = load_catalog(
        'bg_departures.json',
        '1005',
    )

    print(
        f'Каталоги: стран {len(countries)}, '
        f'городов вылета {len(departures)}'
    )
    print('\n=== ПРОВЕРКА ИДЕНТИФИКАТОРОВ ===')
    
    print('Первые 5 стран:')
    for ident, title, _ in countries[:5]:
        print(ident, '|', title)
    
    print('Первые 5 городов вылета:')
    for ident, title, _ in departures[:5]:
        print(ident, '|', title)
    
    return
    # Select countries across the entire sorted catalog.
    # No hardcoded list of Turkey/Egypt/Thailand.
    if args.all:
        selected = countries
    else:
        count = max(
            1,
            min(args.countries, len(countries)),
        )

        selected = [
            countries[i * len(countries) // count]
            for i in range(count)
        ]

    print(
        'Стран для теста:',
        len(selected),
        '| лимиты:',
        args.max_schedule,
        'xml=11,',
        args.max_prices,
        'xml=51',
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    schedule_calls = 0
    price_calls = 0
    successful = 0
    stats = Counter()

    for country_id, country_name, country_row in selected:
        if schedule_calls >= args.max_schedule:
            print('Достигнут лимит xml=11')
            break

        cities = allowed_departures(
            (country_id, country_name, country_row),
            departures,
        )

        if not cities:
            print(
                f'\n{country_name}: '
                'нет разрешённых городов вылета в каталоге'
            )
            stats['нет городов'] += 1
            continue

        print(
            f'\n=== {country_name} ({country_id}) ==='
        )

        for city_id, city_name, _ in cities[:3]:
            if schedule_calls >= args.max_schedule:
                break

            schedule_calls += 1

            try:
                data = get_json(
                    session,
                    [
                        ('action', 'files'),
                        ('flt', city_id),
                        ('flt2', country_id),
                        ('xml', '11'),
                    ],
                )

            except (requests.RequestException, ValueError) as exc:
                print(
                    f'  {city_name}: ошибка xml=11: '
                    f'{str(exc)[:140]}'
                )
                stats['ошибка расписания'] += 1
                continue

            rows = data.get('entries') or []

            if not isinstance(rows, list):
                print(
                    f'  {city_name}: entries не список'
                )
                continue

            print(
                f'  {city_name}: '
                f'xml=11 строк {len(rows)}'
            )

            if not rows:
                stats['пустое расписание'] += 1
                continue

            stats['есть расписание'] += 1

            # Price requests only use previously verified
            # passenger codes. Discovery itself is universal.
            matching = {}

            for row in rows:
                if not isinstance(row, dict):
                    continue

                day = str(row.get('date') or '')
                program = str(row.get('id_price') or '')

                if (
                    day not in VERIFIED
                    or not program.isdigit()
                ):
                    continue

                for n in sorted(
                    nights_set(row.get('duration'))
                ):
                    if 1 <= n <= 21:
                        matching.setdefault(
                            (program, day, n),
                            row,
                        )
                        break

            if not matching:
                print(
                    '    Нет совпадений на проверенные даты '
                    '15/20.11.2026; это не значит, '
                    'что туров нет'
                )
                stats['нет проверенных дат'] += 1
                continue

            print(
                '    Программ/дат для цен:',
                len(matching),
            )

            if price_calls >= args.max_prices:
                print(
                    '    Лимит xml=51 достигнут; '
                    'расписания продолжаем проверять'
                )
                continue

            for (program, day, n), row in list(
                matching.items()
            )[:2]:

                if price_calls >= args.max_prices:
                    break

                price_calls += 1

                route_name = re.sub(
                    r'<[^>]+>',
                    '',
                    str(row.get('route') or ''),
                )[:90]

                print(
                    '    Программа:',
                    program,
                    '|',
                    route_name,
                    '|',
                    day,
                    '|',
                    n,
                    'ночей',
                )

                try:
                    total = inspect_price(
                        session,
                        city_id,
                        country_id,
                        program,
                        day,
                        n,
                        VERIFIED[day],
                    )

                    if total:
                        successful += 1
                        stats['есть цены'] += 1

                except (
                    requests.RequestException,
                    ValueError,
                    TypeError,
                ) as exc:
                    print(
                        '    Ошибка xml=51:',
                        str(exc)[:140],
                    )
                    stats['ошибка цен'] += 1

            # One nonempty departure schedule is enough
            # for this country's discovery test.
            break

    print('\n=== ИТОГО ===')

    print(
        'xml=11 запросов:',
        schedule_calls,
        '| xml=51 запросов:',
        price_calls,
        '| запросов с проверенными ссылками:',
        successful,
    )

    print(
        'Статистика:',
        dict(stats),
    )

    print(
        'Внимание: это выборочная проверка. '
        'Отсутствие цен на двух тестовых датах '
        'не означает отсутствие туров.'
    )


if __name__ == '__main__':
    main()
