"""
Ankara/Istanbul -> Schengen ucuz uçak bileti tarayıcı
------------------------------------------------------
Travelpayouts (Aviasales) Data API ile ESB, IST, SAW çıkışlı Schengen
bölgesi uçuşlarını tarar, eşik altı fiyat bulursa Telegram'a bildirim atar.

Not: Amadeus self-service API portalı Temmuz 2026'da kapatıldığı için
(yeni kayıtlar durduruldu, mevcut erişim 17 Temmuz'da kesiliyor) bu script
Travelpayouts/Aviasales Data API kullanır - anında, onaysız kayıt oluyor.

Ortam değişkenleri (GitHub Secrets ya da yerel .env):
  TRAVELPAYOUTS_TOKEN
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import sys
import json
import time
from datetime import date, timedelta

import requests

# ---------------------------------------------------------------------------
# Ayarlar - buradan kolayca değiştirebilirsin
# ---------------------------------------------------------------------------

ORIGINS = ["ESB", "IST", "SAW"]  # Ankara Esenboğa, İstanbul Havalimanı, Sabiha Gökçen

# Schengen bölgesindeki popüler / ucuza uçulabilen şehirler (IATA kodları)
# Listeyi dilediğin gibi genişlet/daralt
SCHENGEN_DESTINATIONS = [
    "BCN",  # Barcelona
    "MAD",  # Madrid
    "MXP",  # Milano Malpensa
    "BGY",  # Milano Bergamo (low-cost hub)
    "FCO",  # Roma
    "VIE",  # Viyana
    "WAW",  # Varşova
    "KRK",  # Krakow
    "PRG",  # Prag
    "BUD",  # Budapeşte
    "ATH",  # Atina (Schengen değil ama genelde birlikte aranır - istersen çıkar)
    "AMS",  # Amsterdam
    "CDG",  # Paris
    "BER",  # Berlin
    "ZRH",  # Zürih
    "LIS",  # Lizbon
    "OTP",  # Bükreş
    "SOF",  # Sofya
]

# Tüm yaz esnek tarama aralığı (bugünden itibaren)
SEARCH_START = date.today() + timedelta(days=14)   # en az 2 hafta sonrası
SEARCH_END = date(2026, 9, 15)                       # yaz sonu

# Bu fiyatın (EUR) altındaki tek yön bulgular bildirim tetikler
# (gidiş-dönüş için pratikte bu değerin ~2 katını düşün)
PRICE_THRESHOLD = 60

TRAVELPAYOUTS_BASE = "https://api.travelpayouts.com"


# ---------------------------------------------------------------------------
# Travelpayouts (Aviasales) yardımcı fonksiyonları
# ---------------------------------------------------------------------------

def cheapest_month_prices(token: str, origin: str, destination: str, month: str) -> list[dict]:
    """
    v2/prices/month-matrix: verilen ay için her günün en ucuz fiyatını döndürür.
    month formatı: 'YYYY-MM-01'
    """
    resp = requests.get(
        f"{TRAVELPAYOUTS_BASE}/v2/prices/month-matrix",
        params={
            "currency": "eur",
            "origin": origin,
            "destination": destination,
            "show_to_affiliates": "false",
            "month": month,
            "token": token,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("data", []) or []


# ---------------------------------------------------------------------------
# Telegram bildirimi
# ---------------------------------------------------------------------------

def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=20,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------

def months_between(start: date, end: date) -> list[str]:
    """SEARCH_START ile SEARCH_END arasındaki ayları 'YYYY-MM-01' formatında listeler."""
    months = []
    cur = start.replace(day=1)
    while cur <= end:
        months.append(cur.isoformat())
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return months


def main() -> None:
    token = os.environ["TRAVELPAYOUTS_TOKEN"]
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    months = months_between(SEARCH_START, SEARCH_END)
    findings = []  # dict listesi: origin, destination, price, depart_date, return_date

    for origin in ORIGINS:
        for dest in SCHENGEN_DESTINATIONS:
            for month in months:
                offers = cheapest_month_prices(token, origin, dest, month)
                time.sleep(0.3)  # rate limit'e nazik davran

                for offer in offers:
                    price = float(offer.get("value", offer.get("price", 0)))
                    if 0 < price <= PRICE_THRESHOLD:
                        findings.append({
                            "origin": origin,
                            "destination": dest,
                            "price": price,
                            "depart_date": offer.get("depart_date"),
                            "return_date": offer.get("return_date"),
                        })

    if not findings:
        print("Eşik altı fiyat bulunamadı.")
        return

    findings.sort(key=lambda f: f["price"])

    lines = ["✈️ *Ucuz Schengen uçuşu bulundu!*\n"]
    for f in findings[:10]:  # en ucuz 10 sonucu bildir
        lines.append(
            f"*{f['origin']} → {f['destination']}*: {f['price']} EUR "
            f"({f['depart_date']} - {f.get('return_date', '?')})"
        )

    message = "\n".join(lines)
    send_telegram(bot_token, chat_id, message)
    print(f"{len(findings)} bulgu bulundu, Telegram'a gönderildi.")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"Eksik ortam değişkeni: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"API hatası: {e.response.text if e.response else e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Ağ hatası: {e}", file=sys.stderr)
        sys.exit(1)
