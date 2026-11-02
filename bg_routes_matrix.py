
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent


def read_json(filename):
    path = BASE / filename
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл: {filename}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_departures():
    text = (BASE / "bg_departures.json").read_text(
        encoding="utf-8-sig"
    ).strip()

    # Этот справочник начинается с: var BG_FLTX =
    match = re.search(r"\bvar\s+BG_FLTX\s*=", text)
    if not match:
        raise ValueError("Не найдена переменная BG_FLTX")

    data = text[match.end():].strip().rstrip(";").strip()
    return json.loads(data)


def extract_departures(data):
    # В BG_FLTX города вылета находятся в flt2:
    # [ID, {"n": "Название", ...}]
    if not isinstance(data, dict):
        raise ValueError("BG_FLTX должен быть объектом")

    result = {}

    for entry in data.get("flt2", []):
        if not isinstance(entry, list) or len(entry) < 2:
            continue

        city_id, info = entry[0], entry[1]

        if isinstance(info, dict) and info.get("n"):
            result[str(info["n"]).strip().casefold()] = str(city_id)

    return result


def find_country(countries, name):
    for country in countries:
        if country.get("title_ru", "").strip().casefold() == name.casefold():
            return country
    return None


def check_route(countries, departures, city, destination):
    country = find_country(countries, destination)
    city_id = departures.get(city.casefold())

    print(f"\n=== {city} -> {destination} ===")

    if not country:
        print("FAIL: страна не найдена")
        return False

    if not city_id:
        print("FAIL: город вылета не найден")
        return False

    country_id = str(country["id"])

    allowed_cities = set(
        filter(None, country.get("town_from", "").split("#"))
    )

    print("flt  (страна):", country_id)
    print("flt2 (вылет): ", city_id)
    print("Туры в справочнике:", country.get("tours"))

    if city_id in allowed_cities:
        print("PASS: направление присутствует в справочнике BG")
        return True

    print("NO MATCH: пара отсутствует в списке town_from")
    return False


def main():
    print("=== ЛОКАЛЬНЫЕ СПРАВОЧНИКИ BG ===")

    countries = read_json("bg_countries.json")
    resorts = read_json("bg_resorts.json")
    raw_departures = read_departures()
    departures = extract_departures(raw_departures)

    print("Стран:", len(countries))
    print("Городов и курортов:", len(resorts))
    print("Городов вылета:", len(departures))

    print("\nПервые города вылета:")
    for name, city_id in list(departures.items())[:8]:
        print(f"  {name}: {city_id}")

    routes = [
        ("Казань", "Египет"),
        ("Москва", "Турция"),
        ("Екатеринбург", "Таиланд"),
    ]

    passed = sum(
        check_route(countries, departures, city, country)
        for city, country in routes
    )

    print(f"\nRESULT: {passed}/{len(routes)} routes matched")

    if passed != len(routes):
        raise SystemExit(1)

    print("SUCCESS: локальные справочники BG работают")


if __name__ == "__main__":
    main()
