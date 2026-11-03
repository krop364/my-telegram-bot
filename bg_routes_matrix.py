"""Check actual BG search module and programme discovery without deploying Render.
GitHub Actions: pip install requests beautifulsoup4 && python bg_routes_matrix.py
Place next to bg_search.py (and BG JSON catalogues if available).
"""
import re
import traceback
from collections import Counter
from datetime import date
from urllib.parse import parse_qs, urlparse

import requests
import bg_search

CASES = [
    ('Москва', 'Турция', '2026-11-20', '2026-11-20', 7, 7),
    ('Екатеринбург', 'Таиланд', '2026-11-15', '2026-11-22', 11, 13),
    ('Казань', 'Египет', '2026-11-15', '2026-11-22', 6, 9),
]


def check(city, country, start, end, nmin, nmax):
    print('\n' + '=' * 65, flush=True)
    print(f'{city} → {country} | {start} — {end} | {nmin}–{nmax} ночей | 2 взрослых', flush=True)
    route = bg_search.resolve_route(city, country)
    print('Маршрут:', route, flush=True)
    if not route:
        print('ОШИБКА: маршрут не найден; проверьте справочники и ID', flush=True)
        return
    cn, ct = route
    start_day = date.fromisoformat(start)
    end_day = date.fromisoformat(end)
    adult = f'{start_day.day:03d}1019900'
    passengers = f'{adult}.{adult}'
    params = [
        ('action', 'price'), ('tid', '211'), ('flt', cn), ('flt2', ct),
        ('bfr', '1'), ('data', start_day.strftime('%d.%m.%Y')),
        ('d2', end_day.strftime('%d.%m.%Y')), ('ho', '0'),
        ('ins', '15-40000-USD'), ('p', passengers),
    ] + [('f7', str(n)) for n in range(nmin, nmax + 1)]

    pages = bg_search.get_programme_pages(params, start_day, end_day)
    print('Страниц:', len(pages), flush=True)
    print('Программы:', [p for p, _ in pages], flush=True)
    common = pages[0][1]
    discovered = bg_search.discover_programmes(common, start_day, end_day)
    print('ID программ в общей странице:', discovered[:20], flush=True)
    print('Упоминаний id_price в общей странице:', len(re.findall(r'id_price(?:=|%3D)\d+', common, re.I)), flush=True)

    for label, html in pages:
        offers = bg_search.parse_offers(html)
        dates = Counter(o['date'].strftime('%d.%m.%Y') for o in offers)
        nights = Counter(o['nights'] for o in offers)
        valid = [o for o in offers if start_day <= o['date'] <= end_day
                 and nmin <= o['nights'] <= nmax
                 and o['link_date'] == o['date'].strftime('%d.%m.%Y')
                 and o['link_nights'] == str(o['nights'])
                 and o['link_p'] == f"{o['date'].day:03d}1019900.{o['date'].day:03d}1019900"]
        print(f'  [{label}] HTML={len(html)} | предложений={len(offers)} | строго подходящих={len(valid)}', flush=True)
        print(f'    даты={dict(dates.most_common(5))} ночи={dict(nights.most_common(8))}', flush=True)
        for offer in sorted(valid, key=lambda x: x['price_rub'])[:2]:
            print(f"    {offer['hotel']} | {offer['price_rub']} ₽ | {offer['date']} | {offer['nights']} ночей", flush=True)
            print(f"    {offer['source']}", flush=True)

    results = bg_search.search_bg_tours(city, country, start, nmin, 2,
        departure_date_end=end, nights_max=nmax, limit=5)
    print('РЕЗУЛЬТАТ РЕАЛЬНОЙ ФУНКЦИИ БОТА:', len(results), flush=True)
    for o in results:
        print(f"  {o['hotel']} | {o['price_rub']} ₽ | {o['date']} | {o['nights']} ночей", flush=True)


if __name__ == '__main__':
    print('=== BG: ПРОВЕРКА РАСШИРЕННОГО ПОИСКА ДЛЯ БОТА ===', flush=True)
    for case in CASES:
        try:
            check(*case)
        except (requests.RequestException, Exception) as exc:
            print('ОШИБКА:', type(exc).__name__, str(exc), flush=True)
            traceback.print_exc()
    print('\n=== КОНЕЦ ===', flush=True)
