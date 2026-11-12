"""PEGAS public package search via observed JSON endpoints (not an official API)."""
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests

LOG = logging.getLogger(__name__)
BASE = 'https://pegast.ru'
ROOT = Path(__file__).resolve().parent


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().casefold().replace('ё', 'е'))


def _catalog(filename):
    for path in (ROOT / 'data' / filename, ROOT / filename):
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8-sig'))
    return []


def resolve_route(departure_city, country):
    """IDs and supported routes are extracted from a captured PEGAS directions response."""
    cities = _catalog('pegas_departures.json')
    countries = _catalog('pegas_countries.json')
    city = next((x for x in cities if norm(x['name']) == norm(departure_city)
                 or norm(x.get('name_en')) == norm(departure_city)), None)
    target = next((x for x in countries if norm(x['name']) == norm(country)
                   or norm(x.get('name_en')) == norm(country)), None)
    if not city or not target:
        return None
    if target['id'] not in city.get('destination_country_ids', []):
        return None
    return int(city['id']), int(target['id'])


def _post(session, endpoint, payload, timeout=45):
    response = session.post(BASE + endpoint, json=payload, timeout=timeout,
                            headers={'Accept': 'application/json',
                                     'X-Requested-With': 'XMLHttpRequest',
                                     'Origin': BASE, 'Referer': BASE + '/'})
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get('ok') is not True or not isinstance(body.get('data'), dict):
        raise ValueError('PEGAS returned invalid/error JSON: ' + str(body.get('errorDescription') if isinstance(body, dict) else type(body)))
    return body['data']


def _payload(city_id, country_id, adults, ages, dates, durations):
    return {
        'departure': {'locationId': city_id, 'airportId': None},
        'destination': {'hotel': {'countryIds': [country_id], 'regionIds': [],
                                  'locationIds': [], 'locationAreaIds': [],
                                  'hotelsOutsideAreasLocationIds': [], 'hotelIds': []}},
        'accommodation': {'adults': adults, 'childrenAges': ages},
        'departureDates': dates, 'durations': durations,
        'departureDayVariance': 0, 'resource': 0,
        'hotelAccommodationFilters': None,
    }


def parse_search_data(data, departure_city, country, adults, ages, start, end, nmin, nmax, budget=None):
    """Pure parser; accepts a captured JSON data object for offline regression tests."""
    refs = data.get('referenceDescription') or {}
    def by_id(key):
        return {str(x['id']): x for x in (refs.get(key) or []) if isinstance(x, dict) and 'id' in x}
    hotels = by_id('hotels')
    boards = by_id('hotelBoardTypes')
    rooms = by_id('roomCategories')
    locations = by_id('locations')
    airlines = by_id('airlines')
    results = {}
    encrypted = data.get('encryptedSearchParameters')
    search_link = BASE + '/packages?search=' + encrypted if isinstance(encrypted, str) and re.fullmatch(r'[A-Za-z0-9_+/%=-]+', encrypted) else BASE + '/packages'
    for item in data.get('resultItems') or []:
        if not isinstance(item, dict):
            continue
        main = item.get('mainHotel') or {}
        try:
            day = date.fromisoformat(str(item.get('date', ''))[:10])
            nights = int(item['nights'])
            raw = item['holidayPrice']['paymentCurrency']['raw']
            price = float(raw)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not (start <= day <= end and nmin <= nights <= nmax and 0 < price < 1e9):
            continue
        if budget is not None and price > budget:
            continue
        # Never substitute package currency (often USD) for payment RUB.
        payment = item['holidayPrice']['paymentCurrency']
        currency = ((payment.get('parts') or {}).get('currency') or {}).get('symbol')
        if currency not in ('₽', 'руб.', 'руб', 'RUB'):
            continue
        hotel_id = str(main.get('hotelId', ''))
        hotel_info = hotels.get(hotel_id, {})
        hotel_name = hotel_info.get('name') or hotel_info.get('nameEn') or (item.get('filtersInfo') or {}).get('mainHotelName')
        if not hotel_name:
            continue
        board_info = boards.get(str(main.get('boardTypeId')), {})
        room_info = rooms.get(str(main.get('roomCategoryId')), {})
        loc_info = locations.get(str((main.get('location') or {}).get('locationId')), {})
        flight_names = []
        for flight in item.get('flights') or []:
            for segment in flight.get('segments') or []:
                airline = airlines.get(str(segment.get('airlineId')), {}).get('name')
                if airline and airline not in flight_names:
                    flight_names.append(airline)
        ratings = (main.get('ratings') or {}).get('topHotels') or {}
        hotel_link = main.get('hotelDescriptionUrl')
        if hotel_link and not hotel_link.startswith('/'):
            hotel_link = None
        # Hotel description is not a booking link. Link to captured search instead.
        result = {
            'operator': 'PEGAS Touristik', 'hotel': hotel_name, 'hotel_id': hotel_id,
            'resort': loc_info.get('name', ''), 'country': country,
            'departure_city': departure_city, 'date': day.isoformat(),
            'nights': nights, 'adults': adults, 'children': len(ages), 'child_ages': list(ages),
            'room': room_info.get('name', ''),
            'meal': board_info.get('code') or board_info.get('name', ''),
            'airline': ', '.join(flight_names), 'price_rub': round(price),
            'rating': ratings.get('rating'), 'reviews_count': ratings.get('numberOfReview'),
            'flight_type': 'Не подтверждён',
            'source': search_link, 'hotel_url': urljoin(BASE, hotel_link) if hotel_link else '',
            'package_offer_id': item.get('id'), 'price_rub_exact': price,
        }
        # Deduplicate exact hotel/date/nights/meal/room, keep cheapest valid option.
        key = (hotel_id, day, nights, str(main.get('boardTypeId')), str(main.get('roomCategoryId')))
        if key not in results or price < results[key]['price_rub_exact']:
            results[key] = result
    return sorted(results.values(), key=lambda x: x['price_rub_exact'])


def search_pegas_tours(departure_city, country, departure_date, nights, adults,
                       children=0, limit=5, departure_date_end=None,
                       nights_max=None, budget_max=None, child_ages=None,
                       session=None):
    """Search PEGAS JSON. Dates and durations are exact; do not guess availability."""
    try:
        start = date.fromisoformat(str(departure_date))
        end = date.fromisoformat(str(departure_date_end or departure_date))
        nmin, nmax = int(nights), int(nights_max if nights_max is not None else nights)
        adults, children, limit = int(adults), int(children), int(limit)
        ages = [int(x) for x in (child_ages or [])]
        budget = float(budget_max) if budget_max is not None else None
    except (TypeError, ValueError):
        return []
    if (start < date.today() or end < start or (end-start).days > 14 or
            not 1 <= nmin <= nmax <= 30 or not 1 <= adults <= 6 or
            not 0 <= children <= 3 or children != len(ages) or
            any(a < 0 or a > 17 for a in ages) or limit < 1):
        return []
    route = resolve_route(departure_city, country)
    if not route:
        LOG.info('PEGAS unsupported/unknown route: %s -> %s', departure_city, country)
        return []
    dates = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    durations = list(range(nmin, nmax+1))
    payload = _payload(*route, adults, ages, dates, durations)
    s = session or requests.Session()
    try:
        data = _post(s, '/tours/search', payload, timeout=65)
        return parse_search_data(data, departure_city, country, adults, ages, start, end, nmin, nmax, budget)[:limit]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        LOG.warning('PEGAS search failed: %s', exc)
        return []
    finally:
        if session is None:
            s.close()
