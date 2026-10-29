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
