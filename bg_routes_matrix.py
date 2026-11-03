"""Проверка реального JSON API BG (xml=51), без bg_search.py и Render.
Запуск: python bg_routes_matrix.py
Зависимость: requests. Только диагностика, ничего не записывает.
"""
import json
import re
import traceback
from collections import Counter
from urllib.parse import parse_qs, urlsplit

import requests

BASE = 'https://www.bgoperator.ru/site'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Referer': 'https://www.bgoperator.ru/',
}
# Первые две программы и параметры взяты из реальных запросов браузера (HAR).
# Третий тест проверяет перенос тех же параметров на другую дату.
CASES = [
    ('HAR: Москва → Турция, 15.11, 8 ночей, программа 1', '121110228298', '15.11.2026', 8, '0101019900.0101019900'),
    ('HAR: Москва → Турция, 15.11, 8 ночей, программа 2', '121110211811', '15.11.2026', 8, '0101019900.0101019900'),
    ('Проверка новой даты: Москва → Турция, 20.11, 7 ночей', '121110211811', '20.11.2026', 7, '0201019900.0201019900'),
]


def request_params(programme, date, nights, persons):
    # Повторяем параметры из HAR, включая повторяющиеся f8.
    return [
        ('xml', '51'), ('action', 'price'), ('id_price', programme),
        ('flt2', '100510000863'),
        ('f8', 'BB'), ('f8', 'HB'), ('f8', 'FB'), ('f8', 'AI'), ('f8', 'AO'),
        ('entr', '-100'), ('data', date), ('f7', str(nights)),
        ('flt', '100411293179'), ('p', persons),
    ]


def show_result(name, programme, date, nights, persons):
    print('\n' + '=' * 76)
    print(name)
    params = request_params(programme, date, nights, persons)
    response = requests.get(BASE, params=params, headers=HEADERS, timeout=55)
    print('HTTP:', response.status_code, '| bytes:', len(response.content))
    print('URL:', response.url)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        print('ОШИБКА: не JSON. Начало ответа:', response.text[:450])
        return
    if not isinstance(data, dict):
        print('Неожиданный тип JSON:', type(data).__name__, str(data)[:400])
        return
    print('Ключи JSON:', list(data))
    section = data.get('PRICE_SECTION')
    if not isinstance(section, dict):
        print('PRICE_SECTION отсутствует; начало:', json.dumps(data, ensure_ascii=False)[:650])
        return
    entries = section.get('entries', [])
    if not isinstance(entries, list):
        print('entries не список:', str(entries)[:300])
        return
    hotels = ((data.get('FILTER') or {}).get('HOTELS') or [])
    hotel_names = {str(h.get('ID')): (h.get('TITLE') or '').strip() for h in hotels if isinstance(h, dict)}
    print('Всего предложений:', len(entries), '| отелей в FILTER:', len(hotels))
    print('Даты:', dict(Counter(str(e.get('tour_date', '')) for e in entries if isinstance(e, dict))))
    print('Ночи:', dict(Counter(str(e.get('duration', '')) for e in entries if isinstance(e, dict))))
    print('Авиакомпании:', Counter(str(e.get('aircompany', '')) for e in entries if isinstance(e, dict)).most_common(5))
    print('ID программ в результатах:', dict(Counter(str(e.get('id_price', '')) for e in entries if isinstance(e, dict))))
    print('next_page:', str(section.get('next_page', ''))[:400] or '(нет)')
    valid = []
    rejected = Counter()
    for e in entries:
        if not isinstance(e, dict):
            rejected['не объект'] += 1
            continue
        if e.get('tour_date') != date or str(e.get('duration')) != str(nights):
            rejected['другая дата/длительность'] += 1
            continue
        prices = e.get('prices') or []
        if not isinstance(prices, list) or not prices:
            rejected['нет цен'] += 1
            continue
        for price in prices:
            if not isinstance(price, dict):
                continue
            rub = price.get('RUR')
            if not str(rub or '').isdigit() or int(rub) <= 0:
                rejected['нет цены в рублях'] += 1
                continue
            # Формат ссылки BG: href0 + href1 + &p=... + href2.
            href0 = section.get('href0') or ''
            href1 = e.get('href1') or ''
            href2 = price.get('href2') or ''
            if not href0.startswith('https://www.bgoperator.ru/zaya') or '&templ=' not in href1:
                rejected['нет ссылки бронирования'] += 1
                continue
            url = href0 + href1 + '&p=' + persons + href2
            actual_template = parse_qs(urlsplit(url).query).get('templ', [''])[0]
            valid.append((int(rub), hotel_names.get(str(e.get('id_hotel')), ''), e.get('aircompany', ''), actual_template, url, price.get('ag', '')))
    print('Подходящих ценовых вариантов:', len(valid), '| исключено:', dict(rejected))
    print('Фактические templ:', dict(Counter(v[3] for v in valid)))
    for rub, hotel, airline, templ, url, ages in sorted(valid)[:4]:
        print(f'  {hotel or "[название не найдено]"} | {rub:,} ₽ | {airline} | возраст: {ages} | templ={templ}')
        print('  Бронирование:', url[:500])
    if valid and not any('13+' in str(v[5]) for v in valid):
        print('ВНИМАНИЕ: возрастные группы в ответе требуют отдельной проверки.')


def main():
    print('=== BG: ПРОВЕРКА JSON API xml=51 ПО РЕАЛЬНОМУ HAR ===')
    print('Проверяем только Москву → Турцию, без bg_search.py и bot.py.')
    for case in CASES:
        try:
            show_result(*case)
        except Exception as exc:
            print('ОШИБКА:', type(exc).__name__, str(exc))
            traceback.print_exc()
    print('\n=== КОНЕЦ ===')


if __name__ == '__main__':
    main()
