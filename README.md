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

### 2. Travelpayouts hesabı aç (Amadeus yerine)
1. https://www.travelpayouts.com adresinde ücretsiz kaydol (email + şifre, anında aktif).
2. Giriş yaptıktan sonra bir **affiliate programına bağlan** — "Aviasales" programını seç
   (arama kutusuna "Aviasales" yaz, "Connect"/"Bağlan" butonuna bas). Onay gerektirmez.
3. Profilinde **API token** bölümüne git (genelde "Tools" → "API" altında), token'ı kopyala.

### 3. Bu klasörü kendi GitHub repona yükle
```bash
cd flight-watcher
git init
git add .
git commit -m "flight watcher ilk kurulum"
git remote add origin https://github.com/<kullanici-adin>/flight-watcher.git
git push -u origin main
```

### 4. GitHub Secrets'ı ekle
Repo sayfasında: **Settings → Secrets and variables → Actions → New repository secret**
Şu 3 secret'ı tek tek ekle:
- `TRAVELPAYOUTS_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Test et
**Actions** sekmesine git → **Flight Watcher** workflow'unu seç →
**Run workflow** butonuyla manuel tetikle. Loglardan sonucu görebilirsin.
Eşik altı bir şey bulunursa Telegram'a mesaj gelecek.

## Ayarları değiştirmek

`flight_watcher.py` dosyasının başındaki değişkenleri düzenle:
- `SCHENGEN_DESTINATIONS`: taranacak şehir listesi (ekle/çıkar)
- `PRICE_THRESHOLD`: bildirim tetikleyen fiyat eşiği (şu an tek yön 60 EUR)
- `SEARCH_START` / `SEARCH_END`: tarama yapılacak tarih aralığı
- Cron zamanlaması: `.github/workflows/flight-watch.yml` içindeki `cron` satırı

## Notlar
- Travelpayouts verisi kullanıcı arama geçmişi cache'inden geliyor (7 gün saklanıyor);
  gerçek zamanlı canlı fiyat değil, trend/tahmin niteliğinde. Ciddi bir fırsat
  gördüğünde mutlaka Google Flights/Skyscanner'dan güncel fiyatı teyit et.
- Bu sistem **arama ve bildirim** yapar, **rezervasyon/ödeme yapmaz** — bilinçli
  olarak böyle tasarlandı: kimlik/ödeme bilgini hiçbir yere göndermiyor.
- Rate limit (429) hatası alırsan `flight_watcher.py` içindeki `time.sleep(0.3)`
  değerini artır (örn. 1.0).
- İlk birkaç gün eşiği yüksek tutup (örn. 100 EUR) gerçek piyasa fiyatlarını
  gözlemlemeni, sonra eşiği daraltmanı öneririm.
