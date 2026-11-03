import json
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from collections import Counter
from urllib.parse import urljoin

URL = "https://www.bgoperator.ru/site"
import requests
from bs4 import BeautifulSoup

PARAMS = {
    "action": "price",
    "tid": "211",
    "flt": "100410000047",
    "flt2": "100510345650",
    "bfr": "1",
    "data": "15.11.2026",
    "d2": "15.11.2026",
    "f7": "8",
    "ho": "0",
    "ins": "15-40000-USD",
}
BASE = Path(__file__).resolve().parent
BG_URL = "https://www.bgoperator.ru/site"

REQUESTED_NIGHTS = 8

def read_json(filename):
    return json.loads(
        (BASE / filename).read_text(encoding="utf-8-sig")
    )

def get_text(element):
    if element is None:
        return ""
    return element.get_text(" ", strip=True)

def load_departures():
    # Здесь города берём из обычного JSON.
    # BG_FLTX для этого этапа не требуется.
    cities = read_json("bg_departures.json")

def parse_offers(page):
    soup = BeautifulSoup(page, "html.parser")
    result = {}

    current_hotel = None
    current_resort = None
    current_date = None
    offers = []
    for city in cities:
        name = city.get("title_ru", "").strip()
        city_id = city.get("id")

    for tr in soup.select("tr"):
        classes = tr.get("class", [])
        if name and city_id:
            result[name.casefold()] = str(city_id)

        if "b-pr_t_hl" in classes:
            hotel_link = tr.select_one(".c_hl .name a")
            hotel_name = tr.select_one(".c_hl .name")
            resort = tr.select_one(".c_hl .name span")
            date_cell = tr.select_one(".c_de b")
    return result

            current_hotel = get_text(hotel_link)
            current_resort = get_text(resort)
            current_date = get_text(date_cell)

            if hotel_name:
                hotel_id = hotel_name.get("data-hid", "")
            else:
                hotel_id = ""
COUNTRIES = read_json("bg_countries.json")
DEPARTURES = load_departures()

            continue

        if not current_hotel:
            continue
def resolve_route(city, destination):
    country = next(
        (
            item for item in COUNTRIES
            if item.get("title_ru", "").strip().casefold()
            == destination.strip().casefold()
        ),
        None,
    )

    if not country:
        raise ValueError(
            f"Страна не найдена: {destination}"
        )

        nights_cell = tr.select_one("td.c_dn")
        price_cell = tr.select_one("td.c_pe")
        room_cell = tr.select_one("td.c_ns")
    city_id = DEPARTURES.get(city.strip().casefold())

        if not (nights_cell and price_cell and room_cell):
            continue
    if not city_id:
        raise ValueError(
            f"Город вылета не найден: {city}"
        )

        nights_text = get_text(nights_cell)
        price_element = price_cell.select_one("b.r")
        price_text = get_text(price_element)
    allowed = set(filter(
        None,
        country.get("town_from", "").split("#"),
    ))

        try:
            nights = int(nights_text)
            price_rub = int(
                re.sub(r"\D", "", price_text)
    if city_id not in allowed:
        raise ValueError(
            f"Направление {city} → {destination} "
            "не найдено в справочнике"
        )

    return str(country["id"]), city_id


def parse_offers(page):
    soup = BeautifulSoup(page, "html.parser")

    offers = []
    hotel = ""
    resort = ""
    departure_date = ""

    for tr in soup.select("tr"):
        if "b-pr_t_hl" in tr.get("class", []):
            hotel = tr.select_one(".c_hl .name a")
            resort_el = tr.select_one(".c_hl .name span")
            date_el = tr.select_one(".c_de b")

            hotel = (
                hotel.get_text(" ", strip=True)
                if hotel else ""
            )
            resort = (
                resort_el.get_text(" ", strip=True)
                if resort_el else ""
            )
            departure_date = (
                date_el.get_text(" ", strip=True)
                if date_el else ""
            )
        except ValueError:
            continue

        if price_rub <= 0:
            continue
        nights_el = tr.select_one("td.c_dn")
        price_el = tr.select_one("td.c_pe b.r")
        room_el = tr.select_one("td.c_ns")

        airline = get_text(tr.select_one("td.c_ar"))
        room = get_text(room_cell)
        if not (
            hotel and nights_el
            and price_el and room_el
        ):
            continue

        booking_link = price_cell.select_one("a[href]")
        booking_url = (
            urljoin(URL, booking_link["href"])
            if booking_link
            else None
        )
        try:
            nights = int(
                nights_el.get_text(" ", strip=True)
            )
            price = int(re.sub(
                r"\D", "",
                price_el.get_text(" ", strip=True),
            ))
        except ValueError:
            continue

        services = tr.select("td.c_cn li")

        flight_services = [
            li for li in services
            if "i_ft" in li.get("class", [])
        flights = [
            el for el in services
            if "i_ft" in el.get("class", [])
        ]

        accommodation_services = [
            li for li in services
            if "i_an" in li.get("class", [])
        accommodation = [
            el for el in services
            if "i_an" in el.get("class", [])
        ]

        # Требуем два сегмента перелёта
        # и хотя бы одну услугу проживания.
        has_flights = len(flight_services) >= 2
        has_hotel = len(accommodation_services) >= 1

        if not (has_flights and has_hotel):
        if len(flights) < 2 or not accommodation:
            continue

        link = tr.select_one("td.c_pe a[href]")

        offers.append({
            "hotel": current_hotel,
            "hotel_id": hotel_id,
            "resort": current_resort,
            "date": current_date,
            "hotel": hotel,
            "resort": resort,
            "date": departure_date,
            "nights": nights,
            "airline": airline,
            "room": room,
            "price_rub": price_rub,
            "booking_url": booking_url,
            "price_rub": price,
            "airline": (
                tr.select_one("td.c_ar")
                .get_text(" ", strip=True)
                if tr.select_one("td.c_ar") else ""
            ),
            "room": room_el.get_text(" ", strip=True),
            "url": urljoin(
                BG_URL,
                link["href"],
            ) if link else None,
        })

    return offers


def main():
    print("=== BG: ГОТОВЫЕ ПРЕДЛОЖЕНИЯ ===")

def search_bg_tours(
    city,
    destination,
    date,
    nights,
    adults=2,
    children_ages=None,
    end_date=None,
    id_price=None,
    passenger_code=None,
):
    country_id, city_id = resolve_route(
        city, destination
    )

    if children_ages is None:
        children_ages = []

    if not passenger_code:
        if adults != 2 or children_ages:
            raise ValueError(
                "Для этого состава туристов "
                "пока нужен код p с сайта BG"
            )
        day = date[:2]
        passenger_code = (
            f"0{day}1019900.0{day}1019900"
        )

    if isinstance(nights, int):
        nights = [nights]

    # Список пар сохраняет повторяющиеся f7.
    params = [
        ("action", "price"),
        ("tid", "211"),
        ("idt", ""),
        ("flt2", city_id),
        ("bfr", "1"),
        ("id_price", id_price or ""),
        ("data", date),
        ("d2", end_date or date),
    ]

    for value in nights:
        params.append(("f7", str(value)))

    params.extend([
        ("f3", ""),
        ("f8", ""),
        ("ho", "0"),
        ("ins", ""),
        ("flt", country_id),
        ("p", passenger_code),
    ])

    response = requests.get(
        "https://www.bgoperator.ru/price.shtml",
        params=params,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        timeout=90,
    )
    response.raise_for_status()

    offers = parse_offers(response.text)

    # Диапазон дат: не отбрасываем другие
    # даты внутри выбранного периода.
    offers.sort(key=lambda x: x["price_rub"])

    return {
        "country_id": country_id,
        "city_id": city_id,
        "http": response.status_code,
        "html_size": len(response.content),
        "total": len(offers),
        "nights_found": dict(Counter(
            offer["nights"] for offer in offers
        )),
        "offers": offers,
    }


def main():
    cases = [
        {
            "city": "Екатеринбург",
            "destination": "Таиланд",
            "date": "15.11.2026",
            "end_date": "22.11.2026",
            "nights": [11, 13],
            "id_price": "121163457355",
        },
        {
            "city": "Екатеринбург",
            "destination": "Таиланд",
            "date": "15.11.2026",
            "end_date": "22.11.2026",
            "nights": [11, 13],
            "id_price": "121166921602",
        },
        {
            "city": "Москва",
            "destination": "Турция",
            "date": "20.11.2026",
            "nights": [7],
            "adults": 2,
            "children_ages": [8],
            "id_price": "121110183689",
            "passenger_code": (
                "0201019900.0201019900.0201020180"
            ),
        },
    ]

    print("=== BG: МАРШРУТЫ И СОСТАВ ТУРИСТОВ ===")

    for case in cases:
        print("\n" + "=" * 50)
        print(
            case["city"], "→",
            case["destination"],
            "| шаблон:", case["id_price"]
        )

        try:
            result = search_bg_tours(**case)

            print("HTTP:", result["http"])
            print("HTML байт:", result["html_size"])
            print("Всего предложений:", result["total"])
            print("Ночей:", result["nights_found"])

            for offer in result["offers"][:3]:
                print(
                    "\nОтель:", offer["hotel"],
                    "\nДата:", offer["date"],
                    "\nНочей:", offer["nights"],
                    "\nЦена:", offer["price_rub"], "₽",
                    "\nСсылка:", offer["url"],
                )

            if not result["offers"]:
                print(
                    "Предложений не извлечено. "
                    "Нужно проверить ответ BG."
                )

        except Exception as exc:
            print(
                "ERROR:",
                type(exc).__name__,
                str(exc)[:400],
            )

    print("\n=== ГОТОВО ===")


if __name__ == "__main__":
    main()
