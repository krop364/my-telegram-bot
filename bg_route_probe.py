"""Read-only investigation of BG route IDs. Does NOT modify the running bot.
Run: python bg_route_probe.py 2026-11-20 8
"""
import json
import re
import sys
from datetime import date
from urllib.parse import parse_qs, urlsplit
import requests

BASE = 'https://www.bgoperator.ru'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'text/html,application/json,*/*'}

def inspect(day_iso, nights):
    day = date.fromisoformat(day_iso).strftime('%d.%m.%Y')
    nights = int(nights)
    if not 1 <= nights <= 30:
        raise ValueError('nights must be between 1 and 30')
    # Date-specific passenger codes are not inferred: this probe does not price tours.
    params = [('action','price'), ('tid','211'), ('flt','100410000047'),
              ('flt2','100510345650'), ('bfr','1'), ('data',day),
              ('d2',day), ('f7',str(nights)), ('ho','0'), ('ins','15-40000-USD')]
    session = requests.Session()
    session.headers.update(HEADERS)
    for label, url, arguments in [
        ('constructor', BASE + '/price.shtml', params),
        ('price-page', BASE + '/price.shtml', [('action','price'), ('tid','211'),
                ('flt','100410000047'), ('flt2','100510345650')]),
    ]:
        print('\n===', label, '===', flush=True)
        try:
            response = session.get(url, params=arguments, timeout=25)
            print('HTTP:', response.status_code, 'bytes:', len(response.content),
                  'final path:', urlsplit(response.url).path, flush=True)
            response.raise_for_status()
            body = response.text
            # Search for IDs in text and URL-encoded query strings.
            found = {}
            patterns = [r'id_price\s*[=:]\s*["\']?(-?\d{6,15})',
                        r'id_price(?:%3[dD]|=)(-?\d{6,15})',
                        r'["\']id_price["\']\s*:\s*["\']?(-?\d{6,15})']
            for pattern in patterns:
                for match in re.finditer(pattern, body, re.I):
                    ident = match.group(1)
                    if ident == '-1':
                        continue
                    snippet = re.sub(r'\s+', ' ', body[max(0,match.start()-100):match.end()+130])
                    found.setdefault(ident, snippet[:250])
            print('Candidate route IDs:', len(found), flush=True)
            for ident, snippet in list(found.items())[:30]:
                print('  id_price:', ident, '| context:', snippet, flush=True)
            for token in ['121110246682', '121110211282', '121116223474']:
                print('Known ID', token, 'present:', token in body, flush=True)
            print('JS script paths (first 12):', flush=True)
            scripts = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)', body, re.I)
            for path in scripts[:12]:
                print('  ', path[:200], flush=True)
            print('Relevant keyword counts:', json.dumps({
                key: len(re.findall(re.escape(key), body, re.I))
                for key in ['id_price','flt2','f7','tour_date','departure','route','xml=']
            }, ensure_ascii=False), flush=True)
        except requests.RequestException as exc:
            print('REQUEST FAILED:', type(exc).__name__, str(exc)[:220], flush=True)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python bg_route_probe.py YYYY-MM-DD NIGHTS')
    inspect(sys.argv[1], sys.argv[2])
