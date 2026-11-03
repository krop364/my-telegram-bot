"""Public Biblio-Globus package offers; conservative validation, no invented prices."""
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urljoin

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)
BASE = 'https://www.bgoperator.ru'
ROOT = Path(__file__).resolve().parent
# Known verified route identifiers are a fallback when catalogs are absent.
COUNTRY_FALLBACK = {'египет': '100410000047', 'турция': '100411293179', 'таиланд': '100410000051'}
CITY_FALLBACK = {'казань': '100510345650', 'москва': '100510000863', 'екатеринбург': '100510000892'}


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().casefold().replace('ё', 'е'))


def catalog(filename):
    try:
        obj = json.loads((ROOT / filename).read_text(encoding='utf-8-sig'))
        return obj if isinstance(obj, list) else []
    except (OSError, ValueError):
        return []


def resolve_route(city, country):
    countries = catalog('bg_countries.json')
    departure_cities = catalog('bg_departures.json')
    cn = next((str(x['id']) for x in countries if norm(x.get('title_ru')) == norm(country)), None)
    ct = next((str(x['id']) for x in departure_cities if norm(x.get('title_ru')) == norm(city) and str(x.get('id', '')).startswith('1005')), None)
    cn = cn or COUNTRY_FALLBACK.get(norm(country))
    ct = CITY_FALLBACK.get(norm(city)) or ct
    if not cn or not ct:
        return None
    # If catalog has a list of departure cities for this country, enforce it.
    cdata = next((x for x in countries if str(x.get('id')) == cn), None)
    if cdata and cdata.get('town_from'):
        allowed = set(str(cdata['town_from']).split('#'))
        if ct not in allowed:
            return None
    return cn, ct


def parse_offers(page):
    soup = BeautifulSoup(page, 'html.parser')
    offers = []
    hotel = resort = table_date = hotel_id = ''
    for tr in soup.select('tr'):
        if 'b-pr_t_hl' in tr.get('class', []):
            link = tr.select_one('.c_hl .name a')
            name = tr.select_one('.c_hl .name')
            place = tr.select_one('.c_hl .name span')
            day = tr.select_one('.c_de b')
            hotel = link.get_text(' ', strip=True) if link else ''
            hotel_id = name.get('data-hid', '') if name else ''
            resort = place.get_text(' ', strip=True) if place else ''
            table_date = day.get_text(' ', strip=True) if day else ''
            continue
        night_el = tr.select_one('td.c_dn')
        price_el = tr.select_one('td.c_pe b.r')
        room_el = tr.select_one('td.c_ns')
        link = tr.select_one('td.c_pe a[href]')
        if not (hotel and night_el and price_el and room_el and link):
            continue
        flights = tr.select('td.c_cn li.i_ft')
        stays = tr.select('td.c_cn li.i_an')
        if len(flights) < 2 or not stays:
            continue
        try:
            nights = int(night_el.get_text(' ', strip=True))
            price = int(re.sub(r'\D', '', price_el.get_text(' ', strip=True)))
            day = __import__('datetime').datetime.strptime(table_date, '%d.%m.%Y').date()
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        url = urljoin(BASE, link['href'])
        if urlparse(url).hostname not in ('www.bgoperator.ru', 'bgoperator.ru'):
            continue
        qs = parse_qs(urlparse(url).query)
        airline_el = tr.select_one('td.c_ar')
        offers.append({
            'hotel': hotel, 'hotel_id': hotel_id, 'resort': resort,
            'date': day, 'nights': nights, 'price_rub': price,
            'room': room_el.get_text(' ', strip=True),
            'airline': airline_el.get_text(' ', strip=True) if airline_el else '',
            'source': url, 'link_date': (qs.get('dt') or [''])[0],
            'link_nights': (qs.get('kol') or [''])[0],
            'link_p': (qs.get('p') or [''])[0],
        })
    return offers


def search_bg_tours(departure_city, country, departure_date, nights, adults,
                    children=0, limit=5, departure_date_end=None,
                    nights_max=None, budget_max=None, child_ages=None):
    """Return confirmed matching public offers. Unknown passenger codes are not guessed."""
    try:
        start = date.fromisoformat(departure_date)
        end = date.fromisoformat(departure_date_end or departure_date)
        nmin = int(nights)
        nmax = int(nights_max or nights)
        adults = int(adults)
        children = int(children)
        limit = max(1, min(int(limit), 10))
        ages = [int(x) for x in (child_ages or [])]
        budget = int(budget_max) if budget_max is not None else None
    except (ValueError, TypeError):
        return []
    if (start < date.today() or end < start or (end-start).days > 14 or
            not 1 <= nmin <= nmax <= 30 or not 1 <= adults <= 6 or
            children != len(ages) or children > 3):
        return []
    route = resolve_route(departure_city, country)
    if not route:
        LOG.info('BG: unknown route %s -> %s', departure_city, country)
        return []
    country_id, city_id = route
    # Verified format for two adults; other compositions require validated encoding.
    if adults != 2:
        LOG.info('BG: passenger count not verified (%s adults)', adults)
        return []
    if children:
        # Observed BG code for a child age 8 on 20 November 2026 only.
        if not (start == end == date(2026, 11, 20) and ages == [8]):
            LOG.info('BG: child passenger encoding not verified for this date/age')
            return []
    # Date-dependent passenger code: confirm it in returned booking URL before use.
    def passenger_code(day):
        prefix = f'{day.day:03d}'
        adult = prefix + '1019900'
        if children:
            return '.'.join([adult, adult, prefix + '1020180'])
        return '.'.join([adult, adult])

    # A single wide-range request is much cheaper than querying each day.
    params = [
        ('action', 'price'), ('tid', '211'), ('flt', country_id),
        ('flt2', city_id), ('bfr', '1'),
        ('data', start.strftime('%d.%m.%Y')),
        ('d2', end.strftime('%d.%m.%Y')),
        ('ho', '0'), ('ins', '15-40000-USD'),
        ('p', passenger_code(start)),
    ]
    for n in range(nmin, nmax + 1):
        params.append(('f7', str(n)))
    try:
        resp = requests.get(BASE + '/site', params=params,
                            headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'},
                            timeout=35)
        resp.raise_for_status()
        offers = parse_offers(resp.text)
    except (requests.RequestException, ValueError) as exc:
        LOG.warning('BG request failed: %s', exc)
        return []
    results = {}
    for offer in offers:
        day = offer['date']
        if not (start <= day <= end and nmin <= offer['nights'] <= nmax):
            continue
        if offer['link_date'] != day.strftime('%d.%m.%Y'):
            continue
        if offer['link_nights'] != str(offer['nights']):
            continue
        if offer['link_p'] != passenger_code(day):
            continue
        if budget is not None and offer['price_rub'] > budget:
            continue
        key = offer['hotel_id'] or offer['hotel']
        item = {
            'operator': 'Библио-Глобус', 'hotel': offer['hotel'],
            'hotel_id': offer['hotel_id'], 'resort': offer['resort'],
            'date': day.isoformat(), 'nights': offer['nights'],
            'adults': adults, 'children': children, 'child_ages': ages,
            'room': offer['room'], 'meal': offer['room'],
            'airline': offer['airline'], 'price_rub': offer['price_rub'],
            'rating': None, 'reviews_count': None,
            'flight_type': 'Не подтверждён', 'source': offer['source'],
        }
        if key not in results or item['price_rub'] < results[key]['price_rub']:
            results[key] = item
    LOG.info('BG %s -> %s: %s parsed, %s valid', departure_city, country, len(offers), len(results))
    return sorted(results.values(), key=lambda x: x['price_rub'])[:limit]
