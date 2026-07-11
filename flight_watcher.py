"""
Ankara/Istanbul -> Schengen ucuz uçak bileti tarayıcı
------------------------------------------------------
İki kaynaklı sistem:
1. Travelpayouts (Aviasales) Data API - geniş tarama (ESB/IST/SAW x Schengen
   şehirleri x yaz ayları), birden fazla 'market' ile çeşitlendirilmiş.
2. Sky Scrapper (RapidAPI üzerinden Skyscanner verisi) - Travelpayouts'un
   bulduğu en iyi birkaç adayı DOĞRULAMAK için kullanılır (ücretsiz tier
   ayda sadece 100 istek verdiği için tüm taramayı buradan yapmıyoruz).

Not: Amadeus self-service API portalı Temmuz 2026'da kapatıldığı için
(yeni kayıtlar durduruldu, mevcut erişim 17 Temmuz'da kesiliyor) bu script
Amadeus kullanmıyor.

Ortam değişkenleri (GitHub Secrets ya da yerel .env):
  TRAVELPAYOUTS_TOKEN
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  RAPIDAPI_KEY          (opsiyonel - yoksa Skyscanner doğrulaması atlanır)
"""

import os
import sys
import json
import time
from datetime import date, timedelta, datetime

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

# Bu fiyatın (EUR) altındaki GİDİŞ-DÖNÜŞ bulgular bildirim tetikler
PRICE_THRESHOLD = 150

# Round-trip için kalış süresi (hafta) - month-matrix API bunu istiyor,
# yoksa sessizce tek yön fiyat döndürüyor
TRIP_DURATION_WEEKS = 1  # ~1 haftalık tatil; 2 hafta istersen 2 yap

# Aynı rotayı farklı 'market'lerden sorgulamak Aviasales cache'inin farklı
# dilimlerine erişmemizi sağlıyor - aynı API'den daha geniş örneklem.
MARKETS = ["tr", "de"]

TRAVELPAYOUTS_BASE = "https://api.travelpayouts.com"

# Skyscanner doğrulaması için kaç aday kontrol edilsin (RapidAPI ücretsiz
# tier ayda 100 istek verdiği için düşük tutuyoruz)
SKYSCANNER_VERIFY_TOP_N = 2
SKYSCANNER_HOST = "sky-scrapper.p.rapidapi.com"
SKYID_CACHE_PATH = os.path.join(os.path.dirname(__file__), "skyid_cache.json")


# ---------------------------------------------------------------------------
# Travelpayouts (Aviasales) yardımcı fonksiyonları
# ---------------------------------------------------------------------------

def cheapest_month_prices(token: str, origin: str, destination: str, month: str, market: str) -> list[dict]:
    """
    v2/prices/month-matrix: verilen ay için her günün en ucuz GİDİŞ-DÖNÜŞ
    fiyatını döndürür. one_way=false + trip_duration olmadan API sessizce
    tek yön fiyat döndürüyor, bu yüzden ikisi de zorunlu.
    month formatı: 'YYYY-MM-01'. market: cache'in hangi ülke sitesinden
    geldiğini belirler (tr, de, us vb.) - çeşitlilik için değiştiriyoruz.
    """
    resp = requests.get(
        f"{TRAVELPAYOUTS_BASE}/v2/prices/month-matrix",
        params={
            "currency": "eur",
            "origin": origin,
            "destination": destination,
            "show_to_affiliates": "false",
            "month": month,
            "one_way": "false",
            "trip_duration": TRIP_DURATION_WEEKS,
            "market": market,
            "token": token,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("data", []) or []


# ---------------------------------------------------------------------------
# Skyscanner (RapidAPI Sky Scrapper) - ikinci kaynak, sadece doğrulama için
# ---------------------------------------------------------------------------

def _load_skyid_cache() -> dict:
    if os.path.exists(SKYID_CACHE_PATH):
        with open(SKYID_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_skyid_cache(cache: dict) -> None:
    with open(SKYID_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def resolve_sky_id(rapidapi_key: str, iata: str, cache: dict) -> dict | None:
    """IATA kodunu Skyscanner'ın kendi skyId/entityId'sine çevirir, cache'ler."""
    if iata in cache:
        return cache[iata]

    resp = requests.get(
        f"https://{SKYSCANNER_HOST}/api/v1/flights/searchAirport",
        params={"query": iata, "locale": "en-US"},
        headers={"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": SKYSCANNER_HOST},
        timeout=20,
    )
    if resp.status_code != 200:
        return None

    results = resp.json().get("data", [])
    if not results:
        return None

    first = results[0]
    resolved = {
        "skyId": first.get("skyId") or first.get("navigation", {}).get("relevantFlightParams", {}).get("skyId"),
        "entityId": first.get("entityId") or first.get("navigation", {}).get("entityId"),
    }
    if not resolved["skyId"] or not resolved["entityId"]:
        return None

    cache[iata] = resolved
    _save_skyid_cache(cache)
    return resolved


def verify_with_skyscanner(
    rapidapi_key: str, origin: str, destination: str, depart_date: str, return_date: str, cache: dict
) -> float | None:
    """Belirli bir aday uçuşu Skyscanner'da tekrar arayıp fiyatı doğrular."""
    origin_ids = resolve_sky_id(rapidapi_key, origin, cache)
    dest_ids = resolve_sky_id(rapidapi_key, destination, cache)
    if not origin_ids or not dest_ids:
        return None

    params = {
        "originSkyId": origin_ids["skyId"],
        "destinationSkyId": dest_ids["skyId"],
        "originEntityId": origin_ids["entityId"],
        "destinationEntityId": dest_ids["entityId"],
        "date": depart_date,
        "adults": 1,
        "currency": "EUR",
        "market": "en-US",
        "countryCode": "TR",
    }
    if return_date:
        params["returnDate"] = return_date

    resp = requests.get(
        f"https://{SKYSCANNER_HOST}/api/v1/flights/searchFlights",
        params=params,
        headers={"X-RapidAPI-Key": rapidapi_key, "X-RapidAPI-Host": SKYSCANNER_HOST},
        timeout=30,
    )
    if resp.status_code != 200:
        return None

    itineraries = resp.json().get("data", {}).get("itineraries", [])
    if not itineraries:
        return None

    prices = [it["price"]["raw"] for it in itineraries if it.get("price", {}).get("raw")]
    return min(prices) if prices else None


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
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")  # opsiyonel

    months = months_between(SEARCH_START, SEARCH_END)
    findings = []  # dict listesi: origin, destination, price, depart_date, return_date

    for origin in ORIGINS:
        for dest in SCHENGEN_DESTINATIONS:
            for month in months:
                for market in MARKETS:
                    offers = cheapest_month_prices(token, origin, dest, month, market)
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
                                "market": market,
                            })

    if not findings:
        print("Eşik altı fiyat bulunamadı.")
        return

    # Her destinasyon için sadece en ucuz bulguyu tut - tek bir şehir
    # (örn. hep en ucuz olan) tüm bildirim listesini domine etmesin
    best_per_destination: dict[str, dict] = {}
    for f in findings:
        key = f["destination"]
        if key not in best_per_destination or f["price"] < best_per_destination[key]["price"]:
            best_per_destination[key] = f

    diversified = sorted(best_per_destination.values(), key=lambda f: f["price"])
    top_candidates = diversified[:10]

    # İkinci kaynak: en iyi birkaç adayı Skyscanner ile doğrula (varsa key).
    # RapidAPI ücretsiz tier ayda sadece 100 istek verdiği için, günde 2 kez
    # çalışan cron'un sadece SABAH koşusunda doğrulama yapıyoruz (akşam koşusu
    # sadece Travelpayouts ile tarar). datetime UTC saatine göre kontrol ediyoruz.
    current_hour_utc = datetime.utcnow().hour
    should_verify_with_skyscanner = rapidapi_key and current_hour_utc < 12

    if should_verify_with_skyscanner:
        cache = _load_skyid_cache()
        for f in top_candidates[:SKYSCANNER_VERIFY_TOP_N]:
            try:
                verified_price = verify_with_skyscanner(
                    rapidapi_key, f["origin"], f["destination"],
                    f["depart_date"], f.get("return_date") or "", cache,
                )
                f["skyscanner_price"] = verified_price
            except requests.RequestException:
                f["skyscanner_price"] = None
            time.sleep(1.0)  # Skyscanner kotası kısıtlı, nazik davran

    lines = ["✈️ *Ucuz Schengen uçuşu bulundu! (gidiş-dönüş)*\n"]
    for f in top_candidates:
        line = (
            f"*{f['origin']} → {f['destination']}*: {f['price']} EUR "
            f"({f['depart_date']} - {f.get('return_date', '?')}) "
            f"[{f.get('market', '?')}]"
        )
        if f.get("skyscanner_price") is not None:
            line += f"\n   ↳ Skyscanner doğrulaması: {f['skyscanner_price']:.0f} EUR"
        lines.append(line)

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
