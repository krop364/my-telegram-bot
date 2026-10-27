import requests

url = "https://www.bgoperator.ru/site"

params = [
    ("xml", "31"),
    ("action", "price"),
    ("tid", "211"),
    ("flt", "100410000047"),
    ("flt2", "100510345650"),
    ("id_price", "121116223474"),
    ("data", "07.11.2026"),
    ("d2", "07.11.2026"),
    ("f7", "9"),
    ("F4", "102610165892"),
    ("F4", "102674017122"),
    ("p", "0071019900.0071019900.0071020230.0071020200"),
]

hotels = {
    "102610165892": "MAZAR RESORT 3*",
    "102674017122": "MEGAN HALOMY HOTEL 3*",
}

try:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    entries = data.get("entries", [])

    print("Получено предложений:", len(entries))

    for tour in entries[:10]:
        hotel_id = str(tour.get("id_hotel", ""))
        hotel_name = hotels.get(hotel_id, f"Отель ID {hotel_id}")

        for price in tour.get("prices", []):
            print(
                hotel_name,
                "|", tour.get("room"),
                "|", tour.get("duration"), "ночей",
                "|", price.get("RUR"), "₽",
                "| возрастная группа:", price.get("ag"),
            )

except Exception as e:
    print("Ошибка:", type(e).__name__, str(e))
