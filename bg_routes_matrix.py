
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read_json(filename):
    text = (BASE / filename).read_text(encoding="utf-8-sig")
    return json.loads(text)


def read_bg_fltx():
    text = (BASE / "bg_resorts.json").read_text(
        encoding="utf-8-sig"
    ).strip()

    match = re.search(r"\bvar\s+BG_FLTX\s*=", text)

    if not match:
        raise ValueError(
            "В bg_resorts.json не найдена переменная BG_FLTX"
        )

    text = text[match.end():].strip().rstrip(";").strip()
    return json.loads(text)


def extract_departures(data):
    result = {}

    for item in data.get("flt2", []):
        if not isinstance(item, list) or len(item) < 2:
            continue

        city_id, info = item[0], item[1]

        if isinstance(info, dict):
            name = str(info.get("n", "")).strip()
            if name:
                result[name.casefold()] = str(city_id)

    return result


def check_route(countries, departures, city, destination):
    print(f"\n=== {city} -> {destination} ===")

    country = next(
        (
            item for item in countries
            if item.get("title_ru", "").strip().casefold()
            == destination.casefold()
        ),
        None,
    )

    city_id = departures.get(city.casefold())

    if not country:
        print("FAIL: страна не найдена")
        return False

    if not city_id:
        print("FAIL: город вылета не найден")
        return False

    country_id = str(country["id"])

    allowed = set(
        filter(None, country.get("town_from", "").split("#"))
    )

    print("flt:", country_id)
    print("flt2:", city_id)
    print("Туры:", country.get("tours"))

    if city_id in allowed:
        print("PASS: направление найдено в справочнике")
        return True

    print("NO MATCH: город отсутствует в town_from")
    return False


def main():
    print("=== ЛОКАЛЬНЫЕ СПРАВОЧНИКИ BG ===")

    countries = read_json("bg_countries.json")
    cities = read_json("bg_departures.json")
    fltx = read_bg_fltx()
    departures = extract_departures(fltx)

    print("Стран:", len(countries))
    print("Городов и курортов:", len(cities))
    print("Городов вылета:", len(departures))

    routes = [
        ("Казань", "Египет"),
        ("Москва", "Турция"),
        ("Екатеринбург", "Таиланд"),
    ]

    passed = sum(
        check_route(countries, departures, city, destination)
        for city, destination in routes
    )

    print(f"\nRESULT: {passed}/{len(routes)}")

    if passed != len(routes):
        raise SystemExit(1)

    print("SUCCESS: справочники BG работают")


if __name__ == "__main__":
    main()
