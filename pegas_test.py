"""Run in existing GitHub Actions, optionally pass an exported HAR for offline parsing."""
import argparse
import json
from datetime import date
from pathlib import Path
from pegas_search import search_pegas_tours, parse_search_data, resolve_route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--har', help='Local HAR only; do not commit HAR (may contain cookies)')
    args = parser.parse_args()
    assert resolve_route('Казань', 'Египет') == (397, 133)
    if args.har:
        entries = json.loads(Path(args.har).read_text(encoding='utf-8'))['log']['entries']
        body = next(x['response']['content']['text'] for x in entries
                    if x['request']['url'] == 'https://pegast.ru/tours/search' and x['response']['content'].get('text'))
        data = json.loads(body)['data']
        offers = parse_search_data(data, 'Казань', 'Египет', 2, [5, 7],
                                   date(2027, 1, 15), date(2027, 1, 22), 6, 11)
        assert len(offers) == 147, f'Expected 147 parsed captured results, got {len(offers)}'
        assert offers[0]['hotel'] == 'El Khan Sharm Hotel'
        assert offers[0]['price_rub_exact'] == 212901.55
        assert '%253D' not in offers[0]['source']
        print('PEGAS HAR PARSER: OK; offers:', len(offers))
    else:
        offers = search_pegas_tours('Казань', 'Египет', '2027-01-15', 6, 2,
                                   children=2, child_ages=[5, 7],
                                   departure_date_end='2027-01-22', nights_max=11)
        print('=== PEGAS LIVE SEARCH ===')
        for x in offers:
            print(x['hotel'], x['date'], x['nights'], x['meal'], x['price_rub'], x['source'])
        assert offers, 'PEGAS live search returned no offers; check request status and payload'
        print('PEGAS LIVE SEARCH: OK')


if __name__ == '__main__':
    main()
