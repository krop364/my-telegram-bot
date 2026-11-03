"""Самостоятельная проверка программ Библио-Глобуса в GitHub Actions.
Не импортирует bg_search.py и не меняет бот.
Зависимости: requests, beautifulsoup4.
"""
import re
import traceback
from collections import Counter
from datetime import datetime, date
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = 'https://www.bgoperator.ru/'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36', 'Accept-Language': 'ru-RU,ru;q=0.9'})

CASES = [
    {'name': 'Москва → Турция', 'flt': '100411293179', 'flt2': '100510000863',
     'start': '20.11.2026', 'end': '20.11.2026', 'nights': [7],
     'templates': [('Турция: подтверждённая программа для 2 взрослых', '121110211811', {})]},
    {'name': 'Екатеринбург → Таиланд', 'flt': '100410000051', 'flt2': '100510000892',
     'start': '15.11.2026', 'end': '22.11.2026', 'nights': [11, 12, 13],
     'templates': [
         ('Паттайя / Аэрофлот', '121163457355', {'ins': '0-50000-USD', 'f50': '104611014871', 'f51': '104625988050'}),
         ('Пхукет / Аэрофлот', '121166921602', {'ins': '0-50000-USD'}),
     ]},
    {'name': 'Казань → Египет', 'flt': '100410000047', 'flt2': '100510345650',
     'start': '15.11.2026', 'end': '22.11.2026', 'nights': [6, 7, 8, 9], 'templates': []},
]


def fetch(url, params):
    response = SESSION.get(url, params=params, timeout=40)
    response.raise_for_status()
    response.encoding = response.apparent_encoding if response.encoding == 'ISO-8859-1' else response.encoding
    return response.text, response.url


def params_for(case, template=None, extras=None):
    # Код p подтверждён только для двух взрослых и даты 15/20 ноября 2026.
    day = int(case['start'][:2])
    person = f'{day:03d}1019900'
    params = [('action', 'price'), ('tid', '211'), ('flt', case['flt']),
              ('flt2', case['flt2']), ('bfr', '1'), ('data', case['start']),
              ('d2', case['end']), ('ho', '0'), ('ins', '0-50000-USD'),
              ('p', f'{person}.{person}')]
    if template:
        params.append(('id_price', template))
    for n in case['nights']:
        params.append(('f7', str(n)))
    if extras:
        for key, value in extras.items():
            params = [(k, v) for k, v in params if k != key]
            params.append((key, value))
    return params


def discover(html):
    # Диагностика: наличие id_price в HTML не доказывает, что программа доступна.
    decoded = html.replace('&amp;', '&')
    ids = set(re.findall(r'(?i)\bid_price\s*[=:]\s*["\']?(\d{8,18})', decoded))
    ids.update(re.findall(r'(?i)\bid_price(?:%3[dD]|=)(\d{8,18})', decoded))
    ids.update(re.findall(r'(?i)\btempl(?:=|%3[dD])(\d{8,18})', decoded))
    return sorted(ids)


def parse_offers(html):
    soup = BeautifulSoup(html, 'html.parser')
    hotel = ''
    offers = []
    for tr in soup.select('tr'):
        classes = tr.get('class') or []
        if 'b-pr_t_hl' in classes:
            link = tr.select_one('a')
            hotel = (link or tr).get_text(' ', strip=True)[:130]
            continue
        night_cell = tr.select_one('td.c_dn')
        price_cell = tr.select_one('td.c_pe')
        if not night_cell or not price_cell:
            continue
        night_match = re.search(r'\b(\d{1,2})\b', night_cell.get_text(' ', strip=True))
        price_node = price_cell.select_one('b.r')
        if not night_match or not price_node:
            continue
        price_digits = re.sub(r'\D', '', price_node.get_text(' ', strip=True))
        link = price_cell.select_one('a[href*="zaya"]') or tr.select_one('a[href*="zaya"]')
        if not price_digits or not link:
            continue
        url = urljoin(BASE, link.get('href', ''))
        query = parse_qs(urlparse(url).query)
        flight_count = len(tr.select('td.c_cn li.i_ft'))
        accommodation_count = len(tr.select('td.c_cn li.i_an'))
        # В некоторых таблицах услуги выводятся в соседних строках;
        # без явных маркеров пакет не считаем подтверждённым.
        offers.append({'hotel': hotel, 'nights': int(night_match.group(1)),
                       'price': int(price_digits), 'url': url,
                       'date': (query.get('dt') or [''])[0],
                       'link_nights': (query.get('kol') or [''])[0],
                       'p': (query.get('p') or [''])[0],
                       'flights': flight_count, 'hotels': accommodation_count})
    return offers


def inspect(case, label, html):
    offers = parse_offers(html)
    start = datetime.strptime(case['start'], '%d.%m.%Y').date()
    end = datetime.strptime(case['end'], '%d.%m.%Y').date()
    dates = Counter(o['date'] for o in offers)
    nights = Counter(o['nights'] for o in offers)
    reasons = Counter()
    valid = []
    for offer in offers:
        try:
            d = datetime.strptime(offer['date'], '%d.%m.%Y').date()
        except ValueError:
            reasons['нет даты в ссылке'] += 1
            continue
        expected = f'{d.day:03d}1019900'
        checks = {
            'дата вне диапазона': not start <= d <= end,
            'неподходящие ночи': offer['nights'] not in case['nights'],
            'ночи в ссылке не совпадают': offer['link_nights'] != str(offer['nights']),
            'состав туристов не совпадает': offer['p'] != f'{expected}.{expected}',
            'нет подтверждения 2 перелётов': offer['flights'] < 2,
            'нет подтверждения проживания': offer['hotels'] < 1,
        }
        for reason, failed in checks.items():
            if failed:
                reasons[reason] += 1
        if not any(checks.values()):
            valid.append(offer)
    print(f'  [{label}] HTML={len(html)} | предложений={len(offers)} | строго подходящих={len(valid)}', flush=True)
    print(f'    даты ссылок: {dict(dates.most_common(6))}; ночи: {dict(nights.most_common(8))}', flush=True)
    print(f'    причины отклонения: {dict(reasons)}', flush=True)
    for o in sorted(valid, key=lambda item: item['price'])[:3]:
        print(f"    {o['hotel']} | {o['price']:,} ₽ | {o['date']} | {o['nights']} ночей", flush=True)
        print('    ' + o['url'], flush=True)
    return valid


def run_case(case):
    print('\n' + '=' * 68, flush=True)
    print(f"{case['name']} | {case['start']}–{case['end']} | ночи {case['nights']}", flush=True)
    known = {item[1] for item in case['templates']}
    common_html, common_url = fetch(BASE, params_for(case))
    print(f'Общая страница: HTTP 200 | HTML={len(common_html)} | {common_url[:160]}', flush=True)
    discovered = discover(common_html)
    print(f'Найдено упоминаний разных ID программ: {len(discovered)}', flush=True)
    print(f'Первые ID: {discovered[:25]}', flush=True)
    inspect(case, 'общая страница', common_html)
    for label, template, extras in case['templates']:
        html, url = fetch(urljoin(BASE, 'price.shtml'), params_for(case, template, extras))
        print(f'  Запрос программы {template}: HTTP 200 | URL={url[:160]}', flush=True)
        inspect(case, label, html)
    additional = [p for p in discovered if p not in known][:4]
    print(f'Дополнительные программы для проверки: {additional}', flush=True)
    for template in additional:
        try:
            html, _ = fetch(urljoin(BASE, 'price.shtml'), params_for(case, template))
            inspect(case, f'автоматически найденная {template}', html)
        except Exception as exc:
            print(f'  Программа {template}: {type(exc).__name__}: {exc}', flush=True)
    if not discovered:
        print('В общей HTML-странице ID программ не обнаружены: для универсального поиска нужен другой источник программ.', flush=True)


if __name__ == '__main__':
    print('=== BG: САМОСТОЯТЕЛЬНАЯ ПРОВЕРКА ПРОГРАММ, БЕЗ bg_search.py ===', flush=True)
    for case in CASES:
        try:
            run_case(case)
        except Exception as exc:
            print(f"ОШИБКА {case['name']}: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
    print('\n=== ГОТОВО ===', flush=True)
