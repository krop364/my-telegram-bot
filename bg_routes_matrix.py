"""BG diagnostics: Thailand routes and family occupancy.
Run: python bg_routes_matrix.py
Requires: requests, beautifulsoup4; bg_countries.json, bg_departures.json.
"""
import json
import re
from collections import Counter
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
    city_item = next((x for x in departures if str(x.get('title_ru', '')).strip().casefold() == city.casefold() and str(x.get('id')) in str(country.get('town_from', '')).split('#')), None)
    if city_item is None:
        raise ValueError(f'Город вылета не найден для направления: {city} → {destination}')
    return str(country['id']), str(city_item['id'])


def txt(el):
    return el.get_text(' ', strip=True) if el else ''


def parse_offers(html):
    soup = BeautifulSoup(html, 'html.parser')
    offers = []
    hotel = resort = departure_date = ''
    for tr in soup.select('tr'):
        if 'b-pr_t_hl' in tr.get('class', []):
            hotel = txt(tr.select_one('.c_hl .name a'))
            resort = txt(tr.select_one('.c_hl .name span'))
            departure_date = txt(tr.select_one('.c_de b'))
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
        flights = [el for el in services if 'i_ft' in el.get('class', [])]
        accommodation = [el for el in services if 'i_an' in el.get('class', [])]
        if len(flights) < 2 or not accommodation:
            continue
        link = tr.select_one('td.c_pe a[href]')
        booking_url = urljoin(URL, link['href']) if link else None
        airline = txt(tr.select_one('td.c_ar'))
        offers.append({
            'hotel': hotel, 'resort': resort, 'date': departure_date,
            'nights': nights, 'price_rub': price, 'airline': airline,
            'room': txt(room_el), 'url': booking_url,
        })
    return offers


def search_bg_tours(case):
    country_id, city_id = resolve_route(case['city'], case['destination'])
    params = [
        ('action', 'price'), ('tid', '211'), ('idt', ''),
        ('flt2', city_id), ('bfr', '1'),
        ('id_price', case['id_price']),
        ('data', case['date']), ('d2', case['end_date']),
    ]
    for n in case['nights']:
        params.append(('f7', str(n)))
    params.extend([
        ('f3', ''), ('f8', ''), ('ho', '0'),
        ('ins', case['ins']),
    ])
    for k, v in case.get('extra', []):
        params.append((k, v))
    params.extend([('flt', country_id), ('p', case['p'])])
    response = requests.get(
        URL, params=params,
        headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'},
        timeout=90,
    )
    response.raise_for_status()
    offers = parse_offers(response.text)
    offers.sort(key=lambda o: o['price_rub'])
    return response, offers, country_id, city_id


CASES = [
    {
        'label': 'Екатеринбург → Паттайя / Аэрофлот',
        'city': 'Екатеринбург', 'destination': 'Таиланд',
        'date': '15.11.2026', 'end_date': '22.11.2026',
        'nights': [11, 13], 'id_price': '121163457355',
        'ins': '0-50000-USD',
        'extra': [('f50', '104611014871'), ('f51', '104625988050')],
        'p': '0151019900.0151019900',
    },
    {
        'label': 'Екатеринбург → Пхукет / Аэрофлот',
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
    print('=== BG: ТАИЛАНД И СОСТАВ ТУРИСТОВ ===', flush=True)
    for case in CASES:
        print('\n' + '=' * 55, flush=True)
        print(case['label'], '| id_price:', case['id_price'], flush=True)
        try:
            response, offers, country_id, city_id = search_bg_tours(case)
            print('flt:', country_id, '| flt2:', city_id)
            print('HTTP:', response.status_code, '| HTML байт:', len(response.content))
            print('Всего полных предложений:', len(offers))
            print('Ночи:', dict(Counter(x['nights'] for x in offers)))
            print('Даты:', dict(Counter(x['date'] for x in offers).most_common(8)))
            print('Уникальных отелей:', len({x['hotel'] for x in offers}))
            for idx, offer in enumerate(offers[:3], 1):
                print(f"\n{idx}. {offer['hotel']} | {offer['date']} | {offer['nights']} ночей")
                print('Цена:', f"{offer['price_rub']:,}".replace(',', ' '), '₽')
                print('Авиакомпания:', offer['airline'])
                print('Номер / питание:', offer['room'])
                print('Ссылка:', offer['url'])
                if offer['url']:
                    link_p = parse_qs(urlparse(offer['url']).query).get('p', [''])[0]
                    print('p в ссылке:', link_p)
                    print('Состав совпадает с запросом:', link_p == case['p'])
            if not offers:
                print('Нет извлечённых предложений; это не доказывает отсутствие туров.')
                print('Заголовок HTML:', txt(BeautifulSoup(response.text[:100000], 'html.parser').title)[:180])
        except Exception as exc:
            print('ERROR:', type(exc).__name__, str(exc)[:500])
    print('\n=== ТЕСТ ЗАВЕРШЁН ===')


if __name__ == '__main__':
    main()
