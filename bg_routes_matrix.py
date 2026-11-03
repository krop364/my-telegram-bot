"""BG: validate tour dates, passenger composition and booking links.
Run: python bg_routes_matrix.py
Requires: requests, beautifulsoup4, bg_countries.json, bg_departures.json.
"""
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
URL = 'https://www.bgoperator.ru/price.shtml'


def read_json(name):
    with (BASE / name).open('r', encoding='utf-8-sig') as f:
        return json.load(f)


def resolve_route(city, destination):
    countries = read_json('bg_countries.json')
    departures = read_json('bg_departures.json')
    country = next((x for x in countries if str(x.get('title_ru', '')).strip().casefold() == destination.casefold()), None)
    if country is None:
        raise ValueError(f'Страна не найдена: {destination}')
    allowed = str(country.get('town_from', '')).split('#')
    city_item = next((x for x in departures if str(x.get('title_ru', '')).strip().casefold() == city.casefold() and str(x.get('id')) in allowed), None)
    if city_item is None:
        raise ValueError(f'Город вылета не найден: {city} → {destination}')
    return str(country['id']), str(city_item['id'])


def txt(el):
    return el.get_text(' ', strip=True) if el else ''


def date_value(s):
    try:
        return datetime.strptime(s, '%d.%m.%Y').date()
    except (ValueError, TypeError):
        return None


def parse_offers(html):
    soup = BeautifulSoup(html, 'html.parser')
    offers = []
    hotel = resort = table_date = ''
    for tr in soup.select('tr'):
        if 'b-pr_t_hl' in tr.get('class', []):
            hotel = txt(tr.select_one('.c_hl .name a'))
            resort = txt(tr.select_one('.c_hl .name span'))
            table_date = txt(tr.select_one('.c_de b'))
            continue
        nights_el = tr.select_one('td.c_dn')
        price_el = tr.select_one('td.c_pe b.r')
        room_el = tr.select_one('td.c_ns')
        if not (hotel and nights_el and price_el and room_el):
            continue
        try:
            nights = int(txt(nights_el))
            price = int(re.sub(r'\D', '', txt(price_el)))
        except ValueError:
            continue
        if price <= 0:
            continue
        services = tr.select('td.c_cn li')
        if sum('i_ft' in el.get('class', []) for el in services) < 2:
            continue
        if not any('i_an' in el.get('class', []) for el in services):
            continue
        link = tr.select_one('td.c_pe a[href]')
        if not link:
            continue
        booking_url = urljoin(URL, link['href'])
        query = parse_qs(urlparse(booking_url).query)
        offers.append({
            'hotel': hotel,
            'resort': resort,
            'date': table_date,
            'booking_date': query.get('dt', [''])[0],
            'nights': nights,
            'booking_nights': query.get('kol', [''])[0],
            'passengers': query.get('p', [''])[0],
            'price_rub': price,
            'airline': txt(tr.select_one('td.c_ar')),
            'room': txt(room_el),
            'url': booking_url,
        })
    return offers


def search(case):
    country_id, city_id = resolve_route(case['city'], case['destination'])
    params = [
        ('action', 'price'), ('tid', '211'), ('idt', ''),
        ('flt2', city_id), ('bfr', '1'),
        ('id_price', case['id_price']),
        ('data', case['date']), ('d2', case['end_date']),
    ]
    params += [('f7', str(n)) for n in case['nights']]
    params += [('f3', ''), ('f8', ''), ('ho', '0'), ('ins', case['ins'])]
    params += case.get('extra', [])
    params += [('flt', country_id), ('p', case['p'])]
    response = requests.get(
        URL, params=params,
        headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'},
        timeout=90,
    )
    response.raise_for_status()
    return response, parse_offers(response.text)


CASES = [
    {
        'label': 'Екатеринбург → Паттайя',
        'city': 'Екатеринбург', 'destination': 'Таиланд',
        'date': '15.11.2026', 'end_date': '22.11.2026',
        'nights': [11, 13], 'id_price': '121163457355',
        'ins': '0-50000-USD',
        'extra': [('f50', '104611014871'), ('f51', '104625988050')],
        'p': '0151019900.0151019900',
    },
    {
        'label': 'Екатеринбург → Пхукет',
        'city': 'Екатеринбург', 'destination': 'Таиланд',
        'date': '15.11.2026', 'end_date': '22.11.2026',
        'nights': [11, 13], 'id_price': '121166921602',
        'ins': '0-50000-USD', 'extra': [],
        'p': '0151019900.0151019900',
    },
    {
        'label': 'Москва → Турция / 2 взрослых + ребёнок 8 лет',
        'city': 'Москва', 'destination': 'Турция',
        'date': '20.11.2026', 'end_date': '20.11.2026',
        'nights': [7], 'id_price': '121110183689',
        'ins': '', 'extra': [],
        'p': '0201019900.0201019900.0201020180',
    },
]


def main():
    print('=== BG: ПРОВЕРКА ДАТ И СОСТАВА ТУРИСТОВ ===', flush=True)
    for case in CASES:
        print('\n' + '=' * 60, flush=True)
        print(case['label'], '| id_price:', case['id_price'], flush=True)
        try:
            response, offers = search(case)
            start, end = date_value(case['date']), date_value(case['end_date'])
            if not start or not end or start > end:
                raise ValueError('Неверный диапазон дат')
            counters = Counter()
            valid = []
            for offer in offers:
                table_dt = date_value(offer['date'])
                link_dt = date_value(offer['booking_date'])
                date_ok = bool(table_dt and start <= table_dt <= end)
                link_date_ok = bool(link_dt and start <= link_dt <= end)
                dates_equal = bool(table_dt and link_dt and table_dt == link_dt)
                nights_ok = offer['nights'] in case['nights']
                link_nights_ok = offer['booking_nights'] == str(offer['nights'])
                passengers_ok = offer['passengers'] == case['p']
                for key, ok in [
                    ('Дата таблицы в диапазоне', date_ok),
                    ('Дата ссылки в диапазоне', link_date_ok),
                    ('Даты таблицы и ссылки совпадают', dates_equal),
                    ('Ночи совпадают с запросом', nights_ok),
                    ('Ночи в ссылке совпадают с таблицей', link_nights_ok),
                    ('Состав туристов совпадает', passengers_ok),
                ]:
                    if not ok:
                        counters[key] += 1
                if all((date_ok, link_date_ok, dates_equal, nights_ok, link_nights_ok, passengers_ok)):
                    valid.append(offer)
            valid.sort(key=lambda o: o['price_rub'])
            print('HTTP:', response.status_code)
            print('Получено предложений:', len(offers))
            print('Даты в таблице:', dict(Counter(o['date'] for o in offers).most_common(5)))
            print('Даты в ссылках:', dict(Counter(o['booking_date'] for o in offers).most_common(5)))
            print('Ночи:', dict(Counter(o['nights'] for o in offers)))
            print('Причины отклонения (могут пересекаться):', dict(counters))
            print('СТРОГО ПОДХОДЯЩИХ:', len(valid))
            for i, offer in enumerate(valid[:3], 1):
                print(f"{i}. {offer['hotel']} | {offer['date']} | {offer['nights']} ночей | {offer['price_rub']:,} ₽")
                print('Ссылка:', offer['url'])
            if not valid:
                print('Нет подтверждённых совпадений: в боте такие туры НЕ показывать.')
        except Exception as exc:
            print('ERROR:', type(exc).__name__, str(exc)[:400])
    print('\n=== ГОТОВО ===')


if __name__ == '__main__':
    main()
