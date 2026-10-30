"""Read-only BG route matrix. Run: python bg_routes_matrix.py"""
from collections import Counter
from datetime import datetime, timedelta
import requests
from bg_search_auto_experimental import BASE, HEADERS, _BGRouteParser

CASES = [('15.11.2026', [2, 6, 8]), ('20.11.2026', [8, 9, 10, 11]), ('25.11.2026', [8, 9])]
session = requests.Session()
session.headers.update(HEADERS)
for day, nights_options in CASES:
    for nights in nights_options:
        params = [('action','price'),('tid','211'),('flt','100410000047'),
                  ('flt2','100510345650'),('bfr','1'),('data',day),('d2',day),
                  ('f7',str(nights)),('ho','0'),('ins','15-40000-USD')]
        try:
            r = session.get(BASE + '/price.shtml', params=params, timeout=25)
            r.raise_for_status()
            parser = _BGRouteParser()
            parser.feed(r.text)
            by_route = {}
            for route_id, component_day, component_nights in parser.components:
                rec = by_route.setdefault(route_id, {'dates': Counter(), 'lengths': Counter()})
                rec['dates'][component_day] += 1
                rec['lengths'][component_nights] += 1
            print(f'\nDATE={day} REQUESTED_NIGHTS={nights} ROUTES={len(by_route)} COMPONENTS={len(parser.components)}', flush=True)
            for route_id, info in sorted(by_route.items(), key=lambda x: -sum(x[1]['dates'].values()))[:12]:
                print(' ID=',route_id,'DATES=',info['dates'].most_common(5),
                      'COMPONENT_NIGHTS=',info['lengths'].most_common(8), flush=True)
            if not by_route:
                print(' NO ROUTES; PAGE_LENGTH=', len(r.text), 'SERVER_HINT=',r.text[:150].replace('\n',' '),flush=True)
        except Exception as exc:
            print(f'ERROR date={day} nights={nights}: {type(exc).__name__}: {str(exc)[:180]}', flush=True)
