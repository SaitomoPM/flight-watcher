# Flight Watcher — Ankara/İstanbul → Schengen ucuz uçak bildirimcisi

Günde 2 kez ESB, IST ve SAW çıkışlı Schengen bölgesi uçuşlarını tarar,
eşik altı fiyat bulursa Telegram'a mesaj atar. Ücretsiz
(Travelpayouts/Aviasales Data API + GitHub Actions free tier + Telegram Bot API).

> **Not:** İlk versiyonda Amadeus Self-Service API kullanılmıştı, ancak Amadeus
> geliştirici portalını Temmuz 2026'da kapattı (yeni kayıtlar durduruldu,
> mevcut erişim 17 Temmuz'da tamamen kesiliyor). Bu yüzden Travelpayouts
> (Aviasales) Data API'ye geçildi — kayıt anında oluyor, onay beklemiyor.

## Kurulum (yaklaşık 15 dakika)

### 1. Telegram bot oluştur
1. Telegram'da **@BotFather**'ı bul, `/newbot` yaz, bot ismi/kullanıcı adı ver.
2. Bot sana bir **token** verecek (`123456789:ABC-DEF...` formatında). Kaydet.
3. **Önemli:** Şimdi kendi botunu Telegram'da ara (BotFather'ın verdiği @kullaniciadi
   ile) ve bota `/start` yaz. Bot sana mesaj gönderemez, önce sen ona yazmalısın.
4. Chat ID'ni öğrenmek için tarayıcıda (token'ı yerine koyarak):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Dönen JSON'da `"chat":{"id": 123456789...}` kısmındaki sayı senin chat ID'n.
   Hâlâ boş dönerse: bota mesaj attığından ve token'ı boşluksuz kopyaladığından emin ol.

**Otomatik abone sistemi**: Artık chat ID'leri elle bulup secret'a eklemene
gerek yok. Botunu paylaştığın herkes `/start` yazdığında script otomatik
olarak onu abone listesine ekliyor (`data/subscribers.json`), `/stop` yazan
da otomatik çıkıyor. Sadece `TELEGRAM_CHAT_ID` secret'ına **senin** ID'ni
(admin olarak her zaman abone) koyman yeterli, gerisi otomatik.

### 2. Travelpayouts hesabı aç (Amadeus yerine)
1. https://www.travelpayouts.com adresinde ücretsiz kaydol (email + şifre, anında aktif).
2. Giriş yaptıktan sonra bir **affiliate programına bağlan** — "Aviasales" programını seç
   (arama kutusuna "Aviasales" yaz, "Connect"/"Bağlan" butonuna bas). Onay gerektirmez.
3. Profilinde **API token** bölümüne git (genelde "Tools" → "API" altında), token'ı kopyala.

### 3. (Opsiyonel ama önerilir) Skyscanner doğrulaması için RapidAPI hesabı
Bu adım opsiyonel — atlarsan sistem sadece Travelpayouts ile çalışmaya devam eder.
1. https://rapidapi.com adresinde ücretsiz kaydol.
2. "Sky Scrapper" API'sini ara, **BASIC (ücretsiz) plana** abone ol.
   Ücretsiz tier ayda **sadece 100 istek** veriyor — bu yüzden script bunu
   sadece en iyi 2 adayı doğrulamak için, günde 1 kez kullanıyor.
3. Sana bir `X-RapidAPI-Key` verecek, kaydet.

### 4. Bu klasörü kendi GitHub repona yükle
```bash
cd flight-watcher
git init
git add .
git commit -m "flight watcher ilk kurulum"
git remote add origin https://github.com/<kullanici-adin>/flight-watcher.git
git push -u origin main
```

### 5. GitHub Secrets'ı ekle
Repo sayfasında: **Settings → Secrets and variables → Actions → New repository secret**
Şu secret'ları tek tek ekle:
- `TRAVELPAYOUTS_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `RAPIDAPI_KEY` (opsiyonel — Skyscanner doğrulaması istiyorsan)

### 6. Test et
**Actions** sekmesine git → **Flight Watcher** workflow'unu seç →
**Run workflow** butonuyla manuel tetikle. Loglardan sonucu görebilirsin.
Eşik altı bir şey bulunursa Telegram'a mesaj gelecek.

## Ayarları değiştirmek

`flight_watcher.py` dosyasının başındaki değişkenleri düzenle:
- `SCHENGEN_COUNTRIES`: taranacak ülke kodu listesi (ekle/çıkar) — artık şehir
  değil ülke bazlı tarıyoruz, API her ülkedeki en ucuz şehri kendisi buluyor
- `PRICE_THRESHOLD`: bildirim tetikleyen fiyat eşiği (şu an gidiş-dönüş 90 EUR)
- `SEARCH_START` / `SEARCH_END`: tarama yapılacak tarih aralığı
- Cron zamanlaması: `.github/workflows/flight-watch.yml` içindeki `cron` satırı

## Notlar
- **Otomatik abone sistemi**: Bota `/start` yazan herkes otomatik bildirim
  almaya başlıyor, `/stop` yazan çıkıyor. Liste `data/subscribers.json`'da
  tutuluyor ve her koşuda repoya commit'leniyor (fiyat geçmişi gibi).
  `TELEGRAM_CHAT_ID` secret'ındaki ID(ler) her zaman admin olarak dahil edilir.
- **Mimari değişikliği (en önemlisi)**: Sistem artık round-trip "paket" fiyatı
  aramıyor. Bunun yerine flightlist.io gibi araçların kullandığı stratejiyi
  uyguluyor: **en ucuz GİDİŞ + en ucuz DÖNÜŞÜ ayrı ayrı bulup topluyor.**
  Low-cost havayolları (Wizz Air, Ryanair, easyJet) her yönü ayrı fiyatlandırdığı
  için bu, "paket" round-trip aramaktan genelde çok daha ucuza çıkıyor.
  İki fazlı çalışıyor: Faz 1 en ucuz gidişleri bulur (27 ülke x 3 çıkış),
  Faz 2 en ucuz `TOP_CANDIDATES_FOR_INBOUND_SCAN` (varsayılan 30) adayın
  gerçek dönüş biletini arar ve toplar.
- **Kapsam düzeltmesi**: `destination` parametresine şehir değil ÜLKE kodu
  veriyoruz - API o ülkedeki tüm şehirler arasından en ucuzunu buluyor, elle
  seçilmiş bir listeye bağımlı kalmıyoruz (Debrecen gibi ikincil şehirler dahil).
- **Havayolu bilgisi**: Son 10 aday için ayrıca `v1/prices/cheap` endpoint'i
  çağrılıp hangi havayoluna ait olduğu ekleniyor. Bazen boş gelebilir.
- Skyscanner airport ID eşleştirmeleri (`skyid_cache.json`) GitHub Actions
  cache'inde saklanıyor, her koşuda yeniden çözümlenmiyor (kota tasarrufu için).
- Toplam istek sayısı ~600/koşu (Faz 1 + Faz 2 + havayolu + Skyscanner),
  ~6-9 dakika sürüyor. Süre uzun gelirse `MARKETS` listesini `["tr"]`'ye
  indirebilir ya da `TOP_CANDIDATES_FOR_INBOUND_SCAN` sayısını düşürebilirsin.
- Travelpayouts verisi kullanıcı arama geçmişi cache'inden geliyor (7 gün saklanıyor);
  gerçek zamanlı canlı fiyat değil. Ciddi bir fırsat gördüğünde mutlaka
  Google Flights/Skyscanner'dan güncel fiyatı teyit et.
- Bu sistem **arama ve bildirim** yapar, **rezervasyon/ödeme yapmaz** — bilinçli
  olarak böyle tasarlandı: kimlik/ödeme bilgini hiçbir yere göndermiyor.
- Rate limit (429) hatası alırsan `flight_watcher.py` içindeki `time.sleep(0.3)`
  değerini artır (örn. 1.0).
- İlk birkaç gün eşiği (`PRICE_THRESHOLD`) yüksek tutup gerçek piyasa
  fiyatlarını gözlemlemeni, sonra daraltmanı öneririm.
