"""Biblio-Globus JSON tour search, compatible with the existing bot.py interface.

Prices and booking URLs come from BG; checkout availability is not guaranteed.
"""
import calendar
import html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urljoin, urlsplit

import requests

LOG = logging.getLogger(__name__)
BASE = 'https://www.bgoperator.ru'
API = BASE + '/site'
ROOT = Path(__file__).resolve().parent
TIMEOUT = 35
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'Referer': BASE + '/',
}
COUNTRY_FALLBACK = {
    'египет': '100410000047', 'турция': '100411293179',
    'таиланд': '100410000051',
}
CITY_FALLBACK = {
    'казань': '100510345650', 'москва': '100510000863',
    'екатеринбург': '100510000892', 'санкт-петербург': '100510001075',
}
MEAL_RE = re.compile(
    r'(?<![A-Za-z])(?:ULTRA\s+ALL\s+INCLUSIVE|ULTRA\s+ALL|UAI|AI|FB\+|HB\+|BB|FB|HB|AO|RO)(?![A-Za-z])',
    re.I,
)


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().casefold().replace('ё', 'е'))


def catalog(filename):
    try:
        data = json.loads((ROOT / filename).read_text(encoding='utf-8-sig'))
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    except (OSError, ValueError) as exc:
        LOG.warning('BG catalog %s unavailable: %s', filename, exc)
        return []


def resolve_route(city, country):
    countries = catalog('bg_countries.json')
    departures = catalog('bg_departures.json')
    c = next((x for x in countries if norm(x.get('title_ru')) == norm(country)
              or norm(x.get('title_en')) == norm(country)), None)
    country_id = str(c['id']) if c and c.get('id') else COUNTRY_FALLBACK.get(norm(country))
    if not country_id:
        return None
    allowed = set(str(c.get('town_from') or '').split('#')) if c else set()
    matches = [x for x in departures
               if (norm(x.get('title_ru')) == norm(city) or norm(x.get('title_en')) == norm(city))
               and str(x.get('id', '')).startswith('1005')]
    matches.sort(key=lambda x: (str(x.get('id')) not in allowed, str(x.get('id'))))
    city_id = str(matches[0]['id']) if matches else CITY_FALLBACK.get(norm(city))
    if not city_id:
        return None
    # Do not reject a city merely because town_from is incomplete or stale;
    # the schedule endpoint is the authority on actual routes.
    return country_id, city_id


def bg_request(session, params):
    error = None
    for attempt in range(3):
        try:
            response = session.get(API, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('BG returned non-object JSON')
            if data.get('ERROR'):
                raise ValueError(f"BG ERROR: {data['ERROR']}")
            return data
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError(str(error))


def nights_in(value):
    return {int(x) for x in re.findall(r'\d+', str(value or ''))}


def find_programs(entries, start, end, nmin, nmax):
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            day = datetime.strptime(str(entry.get('date', '')), '%d.%m.%Y').date()
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        program = str(entry.get('id_price') or '')
        if not program.isdigit():
            continue
        for nights in nights_in(entry.get('duration')):
            if nmin <= nights <= nmax:
                result[(program, day, nights)] = {
                    'program': program, 'date': day, 'nights': nights,
                    'resort': clean_text(entry.get('cn')),
                    'route': clean_text(entry.get('route')),
                }
    return sorted(result.values(), key=lambda x: (x['date'], x['nights'], x['program']))


def clean_text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()


def age_on(born, day):
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def birthday_for_age(day, age):
    """Synthetic DOB whose age on departure day is exactly age.

    Previous calendar month preserves the tested November encoding.
    January must use the previous *year* for December DOBs.
    """
    month = day.month - 1 or 12
    year = day.year - age - (1 if day.month == 1 else 0)
    dom = min(day.day, calendar.monthrange(year, month)[1])
    born = date(year, month, dom)
    if age_on(born, day) != age:
        raise ValueError('Invalid synthetic child birthday')
    return born


def passenger_code(day, adults, ages):
    if adults < 1 or any(age < 0 or age > 17 for age in ages):
        raise ValueError('Invalid passenger composition')
    month = day.month - 1 or 12
    adult_year = min(1990, day.year - 25) - (1 if day.month == 1 else 0)
    adult_dob = date(adult_year, month, min(day.day, calendar.monthrange(adult_year, month)[1]))
    def encode(born):
        return '0' + born.strftime('%d%m%Y') + '0'
    return '.'.join([encode(adult_dob)] * adults + [encode(birthday_for_age(day, age)) for age in ages])


def price_number(value):
    if isinstance(value, bool):
        return None
    raw = str(value or '').strip()
    if not re.fullmatch(r'\d[\d\s\u00a0\u202f]*', raw):
        return None
    number = int(re.sub(r'\s+', '', raw))
    return number if number > 0 else None


def extract_price(price):
    return price_number(price.get('RUR')) or price_number(price.get('amount'))


def extract_meal(entry, price):
    for field in (entry.get('room'), price.get('room'), entry.get('meal'), price.get('meal')):
        match = MEAL_RE.search(clean_text(field))
        if match:
            code = match.group().upper()
            return 'UAI' if code.startswith('ULTRA') else code
    return ''


def booking_url(section, entry, price, program, persons):
    href0 = str(section.get('href0') or '')
    href1 = str(entry.get('href1') or '')
    href2 = str(price.get('href2') or '')
    if not href0 or not href1:
        return None
    url = urljoin(BASE, href0) + href1 + '&p=' + persons + href2
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.bgoperator.ru', 'bgoperator.ru') or parsed.path != '/zaya':
        return None
    query = parse_qs(parsed.query)
    if query.get('templ', [''])[0] != program or query.get('p', [''])[0] != persons:
        return None
    return url


def price_params(country_id, city_id, info, persons):
    params = [('xml', '51'), ('action', 'price'), ('id_price', info['program']), ('flt2', city_id)]
    params.extend(('f8', meal) for meal in ('BB', 'HB', 'FB', 'AI', 'AO'))
    params.extend([
        ('entr', '-100'), ('data', info['date'].strftime('%d.%m.%Y')),
        ('f7', str(info['nights'])), ('flt', country_id), ('p', persons),
    ])
    return params


def next_page_params(next_page, current_params):
    if not next_page:
        return None
    if isinstance(next_page, dict):
        next_page = next_page.get('url') or next_page.get('href') or next_page.get('next_page')
    if not isinstance(next_page, str):
        return None
    value = html.unescape(next_page.strip())
    match = re.search(r'''href\s*=\s*['"]([^'"]+)['"]''', value, re.I)
    if match:
        value = match.group(1)
    parsed = urlsplit(urljoin(API, value))
    if parsed.hostname not in ('www.bgoperator.ru', 'bgoperator.ru', 'export.bgoperator.ru'):
        return None
    query = parse_qs(parsed.query)
    mp = query.get('mp', [None])[0]
    if not mp:
        return None
    original = dict(current_params)
    for key in ('id_price', 'p', 'data', 'f7'):
        received = query.get(key, [None])[0]
        if received is not None and received != original.get(key):
            raise ValueError(f'BG pagination changed {key}')
    return [(key, value) for key, value in current_params if key != 'mp'] + [('mp', mp)]


def hotel_map(data):
    filters = data.get('FILTER') or {}
    rows = filters.get('HOTELS') or [] if isinstance(filters, dict) else []
    if not isinstance(rows, list):
        return {}
    return {str(row.get('ID')): clean_text(row.get('TITLE'))
            for row in rows if isinstance(row, dict) and row.get('ID')}


def parse_price_page(data, info, adults, ages, persons):
    section = data.get('PRICE_SECTION') or {}
    if not isinstance(section, dict):
        raise ValueError('Invalid PRICE_SECTION')
    entries = section.get('entries') or []
    if not isinstance(entries, list):
        raise ValueError('Invalid PRICE_SECTION.entries')
    hotels = hotel_map(data)
    day_text = info['date'].strftime('%d.%m.%Y')
    offers = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get('tour_date')) != day_text or str(entry.get('duration')) != str(info['nights']):
            continue
        hotel_id = str(entry.get('id_hotel') or '')
        room = clean_text(entry.get('room'))
        for price in entry.get('prices') or []:
            if not isinstance(price, dict):
                continue
            amount = extract_price(price)
            if amount is None:
                continue
            url = booking_url(section, entry, price, info['program'], persons)
            if not url:
                continue
            offers[url] = {
                'operator': 'Библио-Глобус',
                'hotel': hotels.get(hotel_id) or clean_text(entry.get('hotel')) or clean_text(entry.get('hotel_name')),
                'hotel_id': hotel_id,
                'resort': info['resort'],
                'date': info['date'].isoformat(),
                'nights': info['nights'],
                'adults': adults, 'children': len(ages), 'child_ages': list(ages),
                'room': room or clean_text(price.get('room')),
                'meal': extract_meal(entry, price),
                'airline': '',
                'price_rub': amount,
                'rating': None, 'reviews_count': None,
                'flight_type': 'Не подтверждён',
                'source': url,
            }
    return list(offers.values()), section.get('next_page') or data.get('next_page')


def search_bg_tours(departure_city, country, departure_date, nights, adults,
                    children=0, limit=5, departure_date_end=None,
                    nights_max=None, budget_max=None, child_ages=None):
    """Return cheapest matching BG offers using schedule, all programs and pagination.

    ``limit`` affects only returned results, not search completeness.
    If any BG page fails, log the error and return [] rather than claiming a
    partial set is a complete cheapest-price ranking.
    """
    try:
        start = date.fromisoformat(str(departure_date))
        end = date.fromisoformat(str(departure_date_end or departure_date))
        nmin = int(nights)
        nmax = int(nights_max) if nights_max is not None else nmin
        adults = int(adults)
        ages = [int(x) for x in (child_ages or [])]
        children = int(children)
        limit = int(limit) if limit is not None else None
        budget = int(budget_max) if budget_max is not None else None
    except (TypeError, ValueError) as exc:
        LOG.warning('BG invalid parameters: %s', exc)
        return []
    if (start < date.today() or end < start or nmin < 1 or nmax < nmin
            or adults < 1 or children < 0 or children != len(ages)
            or any(age < 0 or age > 17 for age in ages)
            or (limit is not None and limit < 1)
            or (budget is not None and budget < 0)):
        LOG.info('BG invalid search bounds or passenger composition')
        return []
    route = resolve_route(departure_city, country)
    if not route:
        LOG.info('BG route not found: %s -> %s', departure_city, country)
        return []
    country_id, city_id = route
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        schedule = bg_request(session, [
            ('action', 'files'), ('flt', country_id), ('flt2', city_id), ('xml', '11'),
        ]).get('entries') or []
        if not isinstance(schedule, list):
            raise ValueError('Invalid BG schedule')
        programs = find_programs(schedule, start, end, nmin, nmax)
        results = {}
        request_count = 0
        for info in programs:
            persons = passenger_code(info['date'], adults, ages)
            params = price_params(country_id, city_id, info, persons)
            seen_pages = set()
            while params is not None:
                page_key = tuple(params)
                if page_key in seen_pages:
                    raise ValueError(f"Repeated BG page for program {info['program']}")
                seen_pages.add(page_key)
                data = bg_request(session, params)
                request_count += 1
                offers, next_page = parse_price_page(data, info, adults, ages, persons)
                for offer in offers:
                    if budget is None or offer['price_rub'] <= budget:
                        results.setdefault(offer['source'], offer)
                if not next_page:
                    break
                params = next_page_params(next_page, params)
                if params is None:
                    raise ValueError(f"Unrecognized BG pagination for program {info['program']}")
        ranked = sorted(results.values(), key=lambda x: x['price_rub'])
        LOG.info('BG %s -> %s: programs=%s price_requests=%s offers=%s',
                 departure_city, country, len(programs), request_count, len(ranked))
        return ranked[:limit] if limit is not None else ranked
    except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
        LOG.warning('BG search incomplete: %s', exc)
        return []
    finally:
        session.close()
