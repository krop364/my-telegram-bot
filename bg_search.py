"""Осторожный поиск BG: пока только Казань -> Египет, проверенные коды туристов.
Тестовый режим: отели без рейтинга показываются с явной пометкой.
"""
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
import requests

BASE = 'https://www.bgoperator.ru'
HOTELS = {
    '102610165892': 'MAZAR RESORT 3*',
    '102674017122': 'MEGAN HALOMY HOTEL 3*',
}
# Проверено экспериментом: возраст 3 -> 0071020230, возраст 6 -> 0071020200.
AGE_CODES = {3: '0071020230', 6: '0071020200'}
ADULT_CODE = '0071019900'


def search_bg_tours(departure_city, country, departure_date, nights, adults,
                    children=0, limit=5, departure_date_end=None,
                    nights_max=None, budget_max=None, child_ages=None):
    if departure_city.strip().casefold() != 'казань' or country.strip().casefold() != 'египет':
        return []
    ages = child_ages or []
    try:
        nights = int(nights)
        adults = int(adults)
        children = int(children)
        start = date.fromisoformat(departure_date)
        end = date.fromisoformat(departure_date_end or departure_date)
        max_nights = int(nights_max if nights_max is not None else nights)
        limit = int(limit)
        budget = float(budget_max) if budget_max is not None else None
        ages = [int(a) for a in ages]
    except (ValueError, TypeError):
        return []
    if (start < date.today() or end < start or (end - start).days > 14
            or not 1 <= nights <= max_nights <= 30 or adults != 2
            or children != len(ages) or children > 2
            or any(age not in AGE_CODES for age in ages)
            or not 1 <= limit <= 20):
        return []

    # Рейтинги задаются только после независимой проверки по конкретному отелю.
    # Формат bg_ratings.json: {"1026...": {"rating": 4.2, "reviews": 250, "source": "..."}}
    ratings_path = Path(__file__).with_name('bg_ratings.json')
    try:
        ratings = json.loads(ratings_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        ratings = {}
    allowed = {}
    for hotel_id, name in HOTELS.items():
        record = ratings.get(hotel_id, {})
        try:
            if float(record.get('rating', 0)) > 3.5 and int(record.get('reviews', 0)) > 100:
                allowed[hotel_id] = (name, record)
        except (TypeError, ValueError):
            pass
    # Тестовый режим: допускаем отели без рейтинга, но не выдумываем оценку.
    # Отели с известным рейтингом ниже порога исключаем.
    for hotel_id, name in HOTELS.items():
        if hotel_id not in allowed and hotel_id not in ratings:
            allowed[hotel_id] = (name, None)
    if not allowed:
        return []

    p = '.'.join([ADULT_CODE] * adults + [AGE_CODES[a] for a in ages])
    best = {}
    for day_offset in range((end - start).days + 1):
        day = date.fromordinal(start.toordinal() + day_offset)
        for night_count in range(nights, max_nights + 1):
            params = [
                ('xml', '31'), ('action', 'price'), ('tid', '211'),
                ('flt', '100410000047'), ('flt2', '100510345650'),
                ('id_price', '121116223474'),
                ('data', day.strftime('%d.%m.%Y')),
                ('d2', day.strftime('%d.%m.%Y')),
                ('f7', str(night_count)),
                *[('F4', hotel_id) for hotel_id in allowed],
                ('p', p),
            ]
            try:
                response = requests.get(BASE + '/site', params=params,
                                        headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                                        timeout=25)
                response.raise_for_status()
                entries = response.json().get('entries', [])
            except (requests.RequestException, ValueError, AttributeError) as exc:
                print('BG request error:', type(exc).__name__, str(exc)[:200], flush=True)
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                hid = str(entry.get('id_hotel', ''))
                if hid not in allowed:
                    continue
                if entry.get('dt') != day.strftime('%d.%m.%Y') or str(entry.get('duration')) != str(night_count):
                    continue
                name, rating = allowed[hid]
                for price_info in entry.get('prices', []):
                    try:
                        price = int(float(price_info['RUR']))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if price <= 0 or (budget is not None and price > budget):
                        continue
                    # ag — возрастные категории предложения, а не подтверждение точных возрастов.
                    # Сохраняем для проверки, не утверждаем, что цена окончательная.
                    item = {
                        'operator': 'Библио-Глобус', 'hotel': name, 'hotel_id': hid,
                        'date': day.isoformat(), 'nights': night_count,
                        'adults': adults, 'children': children, 'child_ages': ages[:],
                        'room': str(entry.get('room', '')),
                        'meal': 'AI' if str(entry.get('room', '')).upper().endswith(' AI') else 'Не уточнено',
                        'price_rub': price, 'age_category': price_info.get('ag'),
                        'rating': float(rating['rating']) if rating else None,
                        'reviews_count': int(rating['reviews']) if rating else None,
                        'flight_type': 'Не подтверждён',
                        'source': BASE + '/price.shtml?' + urlencode([
                            ('action', 'price'), ('tid', '211'), ('flt', '100410000047'),
                            ('flt2', '100510345650'), ('id_price', '121116223474'),
                            ('data', day.strftime('%d.%m.%Y')), ('d2', day.strftime('%d.%m.%Y')),
                            ('f7', str(night_count)), ('F4', hid), ('p', p),
                        ]),
                    }
                    if hid not in best or price < best[hid]['price_rub']:
                        best[hid] = item
    return sorted(best.values(), key=lambda x: x['price_rub'])[:limit]
