"""Read-only BG investigation: routes, tourist codes, and returned dates.
Run: python bg_next_probe.py
No bot code is changed.
"""
import re
from collections import Counter
from urllib.parse import parse_qs
import requests
from bg_search_auto_experimental import BASE, HEADERS, _BGRouteParser, _get_entries, _discover_hotels

CASES = [('15.11.2026', 8), ('20.11.2026', 8), ('25.11.2026', 9)]
for day, nights in CASES:
    print('\n===', day, nights, 'nights ===', flush=True)
    params = [('action','price'),('tid','211'),('flt','100410000047'),('flt2','100510345650'),('bfr','1'),('data',day),('d2',day),('f7',str(nights)),('ho','0'),('ins','15-40000-USD')]
    try:
        r = requests.get(BASE+'/price.shtml', params=params, headers=HEADERS, timeout=25)
        r.raise_for_status()
        parser = _BGRouteParser(); parser.feed(r.text)
        print('COMPONENTS:', len(parser.components), 'ROUTES:', Counter(x[0] for x in parser.components).most_common(10))
        print('ROUTE DATES:', Counter(x[1] for x in parser.components).most_common(6))
        print('COMPONENT DURATIONS:', Counter(x[2] for x in parser.components).most_common(12))
        routes = [rid for rid, _ in Counter(x[0] for x in parser.components).most_common(3)]
        for rid in routes:
            prefix = f'{int(day[:2]):03d}'  # diagnostic only; NOT a verified tourist code
            p = '.'.join([prefix+'1019900']*2 + [prefix+'1020230', prefix+'1020200'])
            hotels = _discover_hotels(day, nights, p, rid)
            if not hotels:
                print('NO HOTEL IDS', rid); continue
            entries = _get_entries(day, nights, p, list(hotels)[:20], rid)
            print('ROUTE:', rid, 'ENTRIES:', len(entries))
            print('TOUR DATES:', Counter(str(e.get('tour_date')) for e in entries if isinstance(e,dict)).most_common(8))
            print('DT:', Counter(str(e.get('dt')) for e in entries if isinstance(e,dict)).most_common(8))
            print('DURATIONS:', Counter(str(e.get('duration')) for e in entries if isinstance(e,dict)).most_common(12))
            for e in entries[:2]:
                print('SAMPLE:', {k:e.get(k) for k in ('tour_date','dt','duration','id_price','tourComposition','prices')})
    except Exception as exc:
        print('ERROR:', type(exc).__name__, str(exc)[:250], flush=True)
