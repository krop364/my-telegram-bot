
import re
import requests
from bs4 import BeautifulSoup
from collections import Counter
from urllib.parse import urljoin

URL = "https://www.bgoperator.ru/site"

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

REQUESTED_NIGHTS = 8


def get_text(element):
    if element is None:
        return ""
    return element.get_text(" ", strip=True)


def parse_offers(page):
    soup = BeautifulSoup(page, "html.parser")

    current_hotel = None
    current_resort = None
    current_date = None
    offers = []

    for tr in soup.select("tr"):
        classes = tr.get("class", [])

        if "b-pr_t_hl" in classes:
            hotel_link = tr.select_one(".c_hl .name a")
            hotel_name = tr.select_one(".c_hl .name")
            resort = tr.select_one(".c_hl .name span")
            date_cell = tr.select_one(".c_de b")

            current_hotel = get_text(hotel_link)
            current_resort = get_text(resort)
            current_date = get_text(date_cell)

            if hotel_name:
                hotel_id = hotel_name.get("data-hid", "")
            else:
                hotel_id = ""

            continue

        if not current_hotel:
            continue

        nights_cell = tr.select_one("td.c_dn")
        price_cell = tr.select_one("td.c_pe")
        room_cell = tr.select_one("td.c_ns")

        if not (nights_cell and price_cell and room_cell):
            continue

        nights_text = get_text(nights_cell)
        price_element = price_cell.select_one("b.r")
        price_text = get_text(price_element)

        try:
            nights = int(nights_text)
            price_rub = int(
                re.sub(r"\D", "", price_text)
            )
        except ValueError:
            continue

        if price_rub <= 0:
            continue

        airline = get_text(tr.select_one("td.c_ar"))
        room = get_text(room_cell)

        booking_link = price_cell.select_one("a[href]")
        booking_url = (
            urljoin(URL, booking_link["href"])
            if booking_link
            else None
        )

        services = tr.select("td.c_cn li")

        flight_services = [
            li for li in services
            if "i_ft" in li.get("class", [])
        ]

        accommodation_services = [
            li for li in services
            if "i_an" in li.get("class", [])
        ]

        # Требуем два сегмента перелёта
        # и хотя бы одну услугу проживания.
        has_flights = len(flight_services) >= 2
        has_hotel = len(accommodation_services) >= 1

        if not (has_flights and has_hotel):
            continue

        offers.append({
            "hotel": current_hotel,
            "hotel_id": hotel_id,
            "resort": current_resort,
            "date": current_date,
            "nights": nights,
            "airline": airline,
            "room": room,
            "price_rub": price_rub,
            "booking_url": booking_url,
        })

    return offers


def main():
    print("=== BG: ГОТОВЫЕ ПРЕДЛОЖЕНИЯ ===")

    response = requests.get(
        URL,
        params=PARAMS,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru-RU,ru;q=0.9",
        },
        timeout=60,
    )

    print("HTTP:", response.status_code)
    response.raise_for_status()

    offers = parse_offers(response.text)

    print("Полных предложений:", len(offers))
    print(
        "Ночей:",
        dict(Counter(
            offer["nights"] for offer in offers
        )),
    )

    exact = [
        offer for offer in offers
        if offer["nights"] == REQUESTED_NIGHTS
    ]

    print(
        f"Ровно {REQUESTED_NIGHTS} ночей:",
        len(exact),
    )

    if exact:
        selected = exact
    else:
        print(
            "\nНа запрошенное число ночей "
            "точных совпадений нет."
        )
        print(
            "Ниже альтернативы, "
            "не выдаваемые за точные совпадения."
        )
        selected = offers

    selected.sort(
        key=lambda offer: offer["price_rub"]
    )

    print("\n=== 10 САМЫХ ДЕШЁВЫХ ===")

    for index, offer in enumerate(selected[:10], 1):
        print(f"\n{index}. {offer['hotel']}")
        print("Курорт:", offer["resort"])
        print("Дата:", offer["date"])
        print("Ночей:", offer["nights"])
        print(
            "Цена:",
            f"{offer['price_rub']:,}".replace(",", " "),
            "₽",
        )
        print("Авиакомпания:", offer["airline"])
        print("Номер / питание:", offer["room"])
        print("Ссылка:", offer["booking_url"])

    print("\n=== ГОТОВО ===")


if __name__ == "__main__":
    main()
