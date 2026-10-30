"""Read-only BG route discovery. Run: python bg_route_probe_v2.py 2026-11-20 8"""
import html
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
import requests

BASE = 'https://www.bgoperator.ru'

class RouteParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.routes = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        raw = attrs.get('urr', '')
        if 'id_price=' not in raw:
            return
        query = parse_qs(html.unescape(raw).lstrip('&'), keep_blank_values=True)
        route_id = (query.get('id_price') or [''])[0]
        if not re.fullmatch(r'\d{6,15}', route_id):
            return
        self.routes.append({
            'id_price': route_id,
            'date': (query.get('data') or [''])[0],
            'end_date': (query.get('d2') or [''])[0],
            'component_nights': (query.get('dl') or [''])[0],
            'type': (query.get('q') or [''])[0],
            'title': re.sub(r'\s+', ' ', attrs.get('title', ''))[:115],
        })

def inspect(day_iso, nights):
    day = date.fromisoformat(day_iso).strftime('%d.%m.%Y')
    nights = int(nights)
    if not 1 <= nights <= 30:
        raise ValueError('nights must be between 1 and 30')
    params = [('action', 'price'), ('tid', '211'), ('flt', '100410000047'),
              ('flt2', '100510345650'), ('bfr', '1'), ('data', day),
              ('d2', day), ('f7', str(nights)), ('ho', '0'), ('ins', '15-40000-USD')]
    response = requests.get(BASE + '/price.shtml', params=params,
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    response.raise_for_status()
    parser = RouteParser()
    parser.feed(response.text)
    routes = parser.routes
    ids = sorted({r['id_price'] for r in routes})
    print('Requested:', day, 'nights:', nights)
    print('HTTP:', response.status_code, 'HTML bytes:', len(response.content))
    print('Components with route ID:', len(routes), 'unique route IDs:', len(ids))
    print('Route IDs:', ', '.join(ids[:100]) or '(none)')
    print('Component types:', dict(Counter(r['type'] for r in routes)))
    print('Components on requested date:', sum(r['date'] == day for r in routes))
    by_id = defaultdict(list)
    for route in routes:
        by_id[route['id_price']].append(route)
    for route_id, components in sorted(by_id.items(), key=lambda kv: -len(kv[1]))[:30]:
        matching = [r for r in components if r['date'] == day]
        print('\nID:', route_id, '| components:', len(components), '| on requested date:', len(matching))
        for r in (matching or components)[:5]:
            print(' ', r['date'], 'to', r['end_date'], 'dl=', r['component_nights'],
                  'q=', r['type'], '|', r['title'])
    print('\nNOTE: dl is a component duration, not necessarily total tour nights.')
    print('NOTE: IDs in page HTML are candidates; package price and total nights must be verified separately.')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python bg_route_probe_v2.py YYYY-MM-DD NIGHTS')
    inspect(sys.argv[1], sys.argv[2])
