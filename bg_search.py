"""BG tour search (experimental): Kazan -> Egypt, 2 adults, tested child ages 3/6.

Hotel IDs/names are discovered from the public price page. If discovery fails,
retain the two verified hotels. Ratings are never fabricated.
"""
import json
import re
import html
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
import requests

BASE = 'https://www.bgoperator.ru'
KNOWN_HOTELS = {
    '102610165892': 'MAZAR RESORT 3*',
    '102674017122': 'MEGAN HALOMY HOTEL 3*',
}
AGE_CODES = {3: '0071020230', 6: '0071020200'}
ADULT_CODE = '0071019900'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/json,*/*'}
# Limit work so one chat message cannot launch hundreds of HTTP requests.
MAX_HOTELS = 90
CHUNK_SIZE = 30


def _discover_hotels(day, nights, passenger_code):
    """Find BG's [hotel_id, {'n':'Hotel name'}] structures in public HTML.

    The page format can change; no claim of completeness is made.
    """
    params = [
        ('action', 'price'), ('tid', '211'), ('flt', '100410000047'),
        ('flt2', '100510345650'), ('id_price', '121116223474'),
        ('data', day), ('d2', day), ('f7', str(nights)), ('p', passenger_code),
    ]
    response = requests.get(BASE + '/price.shtml', params=params,
                            headers=HEADERS, timeout=20)
    response.raise_for_status()
    page = html.unescape(response.text)
    hotels = {}
    # Actual site sample: [102610165892, {"c":"3*", "n":"MAZAR RESORT 3*"}]
    # Capture a bounded object body, then extract its n field (order-independent).
    for match in re.finditer(r'\[\s*["\']?(\d{10,15})["\']?\s*,\s*\{([^{}]{0,1500})\}', page):
        hotel_id, body = match.groups()
        name_match = re.search(r'["\']n["\']\s*:\s*["\']((?:\\.|[^"\']){2,160})["\']', body)
        if not name_match:
            continue
        name = name_match.group(1).replace('\\"', '"').replace("\\'", "'").strip()
        if name and not name.isdigit():
            hotels[hotel_id] = name
    print('BG discovered hotel names:', len(hotels), flush=True)
    return hotels


def _get_entries(day, nights, passenger_code, hotel_ids, price_id):
    params = [
        ('xml', '31'), ('action', 'price'), ('tid', '211'),
        ('flt', '100410000047'), ('flt2', '100510345650'),
        ('id_price', str(price_id)), ('data', day), ('d2', day),
        ('f7', str(nights)),
        *[('F4', hotel_id) for hotel_id in hotel_ids],
        ('p', passenger_code),
    ]
    response = requests.get(BASE + '/site', params=params,
                            headers=HEADERS, timeout=25)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
        raise ValueError('BG: unexpected price response')
    return data['entries']


def search_bg_tours(departure_city, country, departure_date, nights, adults,
                    children=0, limit=5, departure_date_end=None,
                    nights_max=None, budget_max=None, child_ages=None):
    if departure_city.strip().casefold() != 'казань' or country.strip().casefold() != 'египет':
        return []
    try:
        start = date.fromisoformat(departure_date)
        end = date.fromisoformat(departure_date_end or departure_date)
        nights = int(nights)
        max_nights = int(nights_max if nights_max is not None else nights)
        adults, children, limit = int(adults), int(children), int(limit)
        ages = [int(a) for a in (child_ages or [])]
        budget = float(budget_max) if budget_max is not None else None
    except (ValueError, TypeError):
        return []
    if (start < date.today() or end < start or (end - start).days > 14
            or not 1 <= nights <= max_nights <= 30 or adults != 2
            or children != len(ages) or children > 2
            or any(a not in AGE_CODES for a in ages) or not 1 <= limit <= 20):
        return []

    passenger_code = '.'.join([ADULT_CODE] * adults + [AGE_CODES[a] for a in ages])
    try:
        ratings = json.loads(Path(__file__).with_name('bg_ratings.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        ratings = {}
    if not isinstance(ratings, dict):
        ratings = {}

    best = {}
    for offset in range((end - start).days + 1):
        day_obj = date.fromordinal(start.toordinal() + offset)
        day = day_obj.strftime('%d.%m.%Y')
        for night_count in range(nights, max_nights + 1):
            hotels = dict(KNOWN_HOTELS)
            try:
                discovered = _discover_hotels(day, night_count, passenger_code)
                # Prioritize known hotel IDs and then other IDs found on the page.
                for hid, name in discovered.items():
                    if len(hotels) >= MAX_HOTELS:
                        break
                    hotels[hid] = name
            except (requests.RequestException, ValueError) as exc:
                print('BG hotel discovery error:', type(exc).__name__, str(exc)[:160], flush=True)

            allowed = {}
            for hid, name in hotels.items():
                rating = ratings.get(hid)
                if rating is not None:
                    try:
                        if float(rating['rating']) <= 3.5 or int(rating['reviews']) <= 100:
                            continue
                    except (TypeError, KeyError, ValueError):
                        continue
                allowed[hid] = (name, rating)

            ids = list(allowed)
            entries = []
            for i in range(0, len(ids), CHUNK_SIZE):
                group = ids[i:i + CHUNK_SIZE]
                try:
                    # -1 is seen in BG's multi-hotel requests; compatibility is
                    # checked by the response, not assumed.
                    batch = _get_entries(day, night_count, passenger_code, group, -1)
                    entries.extend(batch)
                except (requests.RequestException, ValueError) as exc:
                    print('BG batch request error:', type(exc).__name__, str(exc)[:160], flush=True)

            # If the broader request returns nothing, keep the proven package query.
            if not entries:
                try:
                    entries = _get_entries(day, night_count, passenger_code,
                                           list(KNOWN_HOTELS), '121116223474')
                    print('BG used verified fallback', flush=True)
                except (requests.RequestException, ValueError) as exc:
                    print('BG fallback error:', type(exc).__name__, str(exc)[:160], flush=True)
                    continue

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                hid = str(entry.get('id_hotel', ''))
                if hid not in allowed:
                    continue
                if entry.get('dt') != day or str(entry.get('duration')) != str(night_count):
                    continue
                name, rating = allowed[hid]
                for offer in entry.get('prices', []):
                    try:
                        amount = int(float(offer['RUR']))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if amount <= 0 or (budget is not None and amount > budget):
                        continue
                    room = str(entry.get('room', ''))
                    # Link to BG price page with this hotel and actual package id.
                    actual_package = str(entry.get('id_price') or '121116223474')
                    source = BASE + '/price.shtml?' + urlencode([
                        ('action', 'price'), ('tid', '211'),
                        ('flt', '100410000047'), ('flt2', '100510345650'),
                        ('id_price', actual_package), ('data', day), ('d2', day),
                        ('f7', str(night_count)), ('F4', hid), ('p', passenger_code),
                    ])
                    item = {
                        'operator': 'Библио-Глобус', 'hotel': name, 'hotel_id': hid,
                        'date': day_obj.isoformat(), 'nights': night_count,
                        'adults': adults, 'children': children, 'child_ages': ages[:],
                        'room': room,
                        'meal': 'AI' if room.upper().endswith(' AI') else 'Не уточнено',
                        'price_rub': amount, 'age_category': offer.get('ag'),
                        'rating': float(rating['rating']) if rating else None,
                        'reviews_count': int(rating['reviews']) if rating else None,
                        'flight_type': 'Не подтверждён', 'source': source,
                    }
                    key = hid  # best offer per hotel
                    if key not in best or amount < best[key]['price_rub']:
                        best[key] = item
    print('BG unique hotels with prices:', len(best), flush=True)
    return sorted(best.values(), key=lambda item: item['price_rub'])[:limit]
