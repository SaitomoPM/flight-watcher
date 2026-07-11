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

# ÖNEMLİ TASARIM DEĞİŞİKLİĞİ: Elle seçilmiş 18 şehirlik liste yerine Schengen
# ÜLKE kodları kullanıyoruz. Travelpayouts API'sinde destination parametresine
# ülke kodu verirsen, o ülkedeki TÜM şehirler arasından en ucuzunu buluyor.
# Bu, Debrecen gibi elle seçilen listede olmayan ikincil/ucuz şehirleri de
# otomatik olarak kapsıyor - manuel aramanın önüne geçmenin tek yolu bu.
SCHENGEN_COUNTRIES = [
    "AT", "BE", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IS", "IT", "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL",
    "PT", "SK", "SI", "ES", "SE", "CH", "HR",
]

# Tüm yaz esnek tarama aralığı (bugünden itibaren)
SEARCH_START = date.today() + timedelta(days=14)   # en az 2 hafta sonrası
SEARCH_END = date(2026, 9, 15)                       # yaz sonu

# Bu fiyatın (EUR) altındaki GİDİŞ-DÖNÜŞ bulgular bildirim tetikler.
# Gerçek piyasa tabanı ~50-60 EUR civarında görünüyor (tek yön 24 EUR gibi
# fırsatlar var); bunun biraz üzerinde tutup gerçek dağılımı gözlemleyelim.
PRICE_THRESHOLD = 90

# Kombinasyon (gidiş + dönüş ayrı ayrı) için kabul edilebilir konaklama süresi
MIN_STAY_DAYS = 1
MAX_STAY_DAYS = 14

# Aynı rotayı farklı 'market'lerden sorgulamak Aviasales cache'inin farklı
# dilimlerine erişmemizi sağlıyor - aynı API'den daha geniş örneklem.
MARKETS = ["tr", "de"]

TRAVELPAYOUTS_BASE = "https://api.travelpayouts.com"

# Skyscanner doğrulaması için kaç aday kontrol edilsin (RapidAPI ücretsiz
# tier ayda 100 istek verdiği için düşük tutuyoruz)
SKYSCANNER_VERIFY_TOP_N = 2
SKYSCANNER_HOST = "sky-scrapper.p.rapidapi.com"
SKYID_CACHE_PATH = os.path.join(os.path.dirname(__file__), "skyid_cache.json")
PRICE_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "price_history.csv")

# Faz 2'de (dönüş taraması) kaç farklı şehir denensin - artırmak daha fazla
# istek demek ama daha geniş kapsam sağlar. best_outbound_per_dest'te kaç
# farklı şehir bulunduysa o kadarı zaten üst sınır (27 ülke olsa da farklı
# günlerde farklı şehirler çıkabildiği için sayı 27'den fazla olabilir).
TOP_CANDIDATES_FOR_INBOUND_SCAN = 30


# ---------------------------------------------------------------------------
# Travelpayouts (Aviasales) yardımcı fonksiyonları
# ---------------------------------------------------------------------------

def cheapest_one_way_prices(token: str, origin: str, destination: str, month: str, market: str) -> list[dict]:
    """
    v2/prices/month-matrix - TEK YÖN modda (one_way parametresi verilmeden,
    API'nin varsayılan davranışı bu). destination'a ülke kodu verilirse o
    ülkedeki tüm şehirler arasından her günün en ucuzunu bulur.
    Neden tek yön: low-cost havayolları (Wizz Air, Ryanair, easyJet vb.) her
    yönü ayrı fiyatlandırıyor - en ucuz gidiş + en ucuz dönüşü ayrı ayrı
    bulup toplamak, "paket" round-trip aramaktan genelde daha ucuza çıkıyor.
    month formatı: 'YYYY-MM-01'.
    """
    params = {
        "currency": "eur",
        "origin": origin,
        "destination": destination,
        "show_to_affiliates": "false",
        "month": month,
        "market": market,
        "token": token,
    }
    resp = requests.get(f"{TRAVELPAYOUTS_BASE}/v2/prices/month-matrix", params=params, timeout=30)
    if resp.status_code != 200:
        return []
    return resp.json().get("data", []) or []

# Bölgede sık uçan havayollarının IATA kodu -> isim eşlemesi (mesajda okunaklı
# göstermek için). Listede olmayan bir kod gelirse ham kodu gösteriyoruz.
AIRLINE_NAMES = {
    "TK": "Turkish Airlines", "PC": "Pegasus", "XQ": "SunExpress",
    "AJ": "AJet", "W6": "Wizz Air", "W9": "Wizz Air Malta",
    "FR": "Ryanair", "U2": "easyJet", "VY": "Vueling", "EW": "Eurowings",
    "LO": "LOT Polish Airlines", "RO": "Tarom", "A3": "Aegean Airlines",
    "JU": "Air Serbia", "OU": "Croatia Airlines", "OS": "Austrian Airlines",
    "LH": "Lufthansa", "LX": "Swiss", "KL": "KLM", "AF": "Air France",
    "IB": "Iberia", "AZ": "ITA Airways", "BA": "British Airways",
}


def get_airline_for_route(token: str, origin: str, destination: str, depart_month: str) -> str | None:
    """
    v1/prices/cheap: month-matrix'in vermediği havayolu bilgisini almak için
    sadece SON adaylar için çağrılır (tüm taramada değil).
    depart_month formatı: 'YYYY-MM'
    """
    resp = requests.get(
        f"{TRAVELPAYOUTS_BASE}/v1/prices/cheap",
        params={
            "origin": origin,
            "destination": destination,
            "depart_date": depart_month,
            "currency": "eur",
            "token": token,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        return None
    dest_data = resp.json().get("data", {}).get(destination, {})
    if not dest_data:
        return None
    first_entry = next(iter(dest_data.values()), {})
    code = first_entry.get("airline")
    if not code:
        return None
    return AIRLINE_NAMES.get(code, code)


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
# Fiyat geçmişi (kendi verimizi biriktirmek için) - CSV'ye ekleniyor,
# workflow bunu her koşu sonunda repoya commit'liyor.
# ---------------------------------------------------------------------------

def log_price_history(combos: list[dict]) -> None:
    """Bulunan TÜM kombinasyonları (eşikten bağımsız) CSV'ye ekler."""
    import csv

    os.makedirs(os.path.dirname(PRICE_HISTORY_PATH), exist_ok=True)
    file_exists = os.path.exists(PRICE_HISTORY_PATH)

    with open(PRICE_HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "run_timestamp", "origin", "destination", "depart_date", "return_date",
                "outbound_price", "inbound_price", "total_price", "market",
            ])
        run_ts = datetime.utcnow().isoformat(timespec="seconds")
        for c in combos:
            writer.writerow([
                run_ts, c["origin"], c["destination"], c["depart_date"], c["return_date"],
                f"{c['outbound_price']:.2f}", f"{c['inbound_price']:.2f}", f"{c['price']:.2f}",
                c["market"],
            ])
    print(f"Fiyat geçmişine {len(combos)} kayıt eklendi -> {PRICE_HISTORY_PATH}")


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


def combine_outbound_inbound(
    token: str, origin: str, destination: str, depart_date: str, months: list[str], markets: list[str]
) -> tuple[float, str] | None:
    """
    Belirli bir varış şehri için, depart_date'ten sonra MIN/MAX_STAY_DAYS
    penceresine düşen en ucuz DÖNÜŞ biletini arar (tek yön, ters yönde).
    Bulursa (dönüş_fiyatı, dönüş_tarihi) döndürür.
    """
    depart = date.fromisoformat(depart_date)
    window_start = depart + timedelta(days=MIN_STAY_DAYS)
    window_end = depart + timedelta(days=MAX_STAY_DAYS)

    candidate_months = sorted({
        m for m in months
        if date.fromisoformat(m) <= window_end and date.fromisoformat(m).replace(day=28) >= window_start
    })

    best = None  # (price, date)
    for month in candidate_months:
        for market in markets:
            offers = cheapest_one_way_prices(token, destination, origin, month, market)
            time.sleep(0.3)
            for offer in offers:
                d = offer.get("depart_date")
                if not d:
                    continue
                try:
                    offer_date = date.fromisoformat(d)
                except ValueError:
                    continue
                if not (window_start <= offer_date <= window_end):
                    continue
                price = float(offer.get("value", offer.get("price", 0)))
                if price <= 0:
                    continue
                if best is None or price < best[0]:
                    best = (price, d)

    return best


def main() -> None:
    token = os.environ["TRAVELPAYOUTS_TOKEN"]
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")  # opsiyonel

    months = months_between(SEARCH_START, SEARCH_END)

    # FAZ 1 - GİDİŞ TARAMASI: her ülke için, her günün en ucuz tek yön
    # biletini buluyoruz (gerçek varış şehri API tarafından çözümleniyor)
    outbound_offers = []
    for origin in ORIGINS:
        for country in SCHENGEN_COUNTRIES:
            for month in months:
                for market in MARKETS:
                    offers = cheapest_one_way_prices(token, origin, country, month, market)
                    time.sleep(0.3)
                    for offer in offers:
                        price = float(offer.get("value", offer.get("price", 0)))
                        dest = offer.get("destination")
                        depart_date = offer.get("depart_date")
                        if dest and depart_date and price > 0:
                            outbound_offers.append({
                                "origin": origin, "destination": dest,
                                "depart_date": depart_date, "price": price, "market": market,
                            })

    if not outbound_offers:
        print("Gidiş bileti bulunamadı.")
        return

    # Her varış şehri için en ucuz GİDİŞ'i tut (tek bir şehir domine etmesin)
    best_outbound_per_dest: dict[str, dict] = {}
    for o in outbound_offers:
        key = o["destination"]
        if key not in best_outbound_per_dest or o["price"] < best_outbound_per_dest[key]["price"]:
            best_outbound_per_dest[key] = o

    # En ucuz gidişi olan ilk N şehri, dönüş taraması için aday seçiyoruz
    candidates = sorted(best_outbound_per_dest.values(), key=lambda o: o["price"])[:TOP_CANDIDATES_FOR_INBOUND_SCAN]

    # FAZ 2 - DÖNÜŞ TARAMASI: her adayın varış şehrinden gerçek dönüşü bul,
    # gidiş + dönüşü toplayarak GERÇEK toplam maliyeti hesapla.
    # NOT: eşikten BAĞIMSIZ tüm kombinasyonları topluyoruz (all_combos) -
    # geçmiş veri biriktirmek için, eşik altı olanları bildirim için ayırıyoruz.
    all_combos = []
    for cand in candidates:
        result = combine_outbound_inbound(
            token, cand["origin"], cand["destination"], cand["depart_date"], months, MARKETS
        )
        if result is None:
            continue
        inbound_price, inbound_date = result
        total_price = cand["price"] + inbound_price
        all_combos.append({
            "origin": cand["origin"],
            "destination": cand["destination"],
            "depart_date": cand["depart_date"],
            "return_date": inbound_date,
            "outbound_price": cand["price"],
            "inbound_price": inbound_price,
            "price": total_price,
            "market": cand["market"],
        })

    # Geçmiş veri olarak HER ŞEYİ kaydet (eşik altı olsun olmasın) - trend
    # görmek için lazım. Eşik uygulanmamış ham veri.
    log_price_history(all_combos)

    combined_findings = [c for c in all_combos if c["price"] <= PRICE_THRESHOLD]

    if not combined_findings:
        print(f"Eşik altı fiyat bulunamadı. En ucuz {len(candidates)} adaydan hiçbiri "
              f"{PRICE_THRESHOLD} EUR toplamın altında değildi.")
        # Yine de en ucuz 3 adayı logla ki neye yaklaştığımızı görelim
        for c in sorted(all_combos, key=lambda f: f["price"])[:3]:
            print(f"  (bilgi) {c['origin']} → {c['destination']}: toplam {c['price']:.0f} EUR "
                  f"(gidiş {c['outbound_price']:.0f} + dönüş {c['inbound_price']:.0f})")
        return

    top_candidates = sorted(combined_findings, key=lambda f: f["price"])[:10]

    # Havayolu bilgisi sadece son adaylar için çekiliyor (tüm taramada değil)
    for f in top_candidates:
        depart_month = f["depart_date"][:7] if f.get("depart_date") else None  # 'YYYY-MM'
        if depart_month:
            try:
                f["airline"] = get_airline_for_route(token, f["origin"], f["destination"], depart_month)
            except requests.RequestException:
                f["airline"] = None
            time.sleep(0.3)

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

    lines = ["✈️ *Ucuz Schengen uçuşu bulundu! (gidiş+dönüş ayrı ayrı en ucuz)*\n"]
    for f in top_candidates:
        airline_str = f" - {f['airline']}" if f.get("airline") else ""
        line = (
            f"*{f['origin']} → {f['destination']}*: TOPLAM {f['price']:.0f} EUR "
            f"(gidiş {f['outbound_price']:.0f} + dönüş {f['inbound_price']:.0f}) "
            f"({f['depart_date']} → {f['return_date']}) [{f.get('market', '?')}]{airline_str}"
        )
        if f.get("skyscanner_price") is not None:
            line += f"\n   ↳ Skyscanner doğrulaması: {f['skyscanner_price']:.0f} EUR"
        lines.append(line)

    message = "\n".join(lines)
    send_telegram(bot_token, chat_id, message)
    print(f"{len(combined_findings)} kombinasyon bulundu, Telegram'a gönderildi.")


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
