# Migri randevu takipçisi (Helsinki / Turku)

Her 5 dakikada bir Migri'nin randevu sistemini kontrol eder. Helsinki veya Turku'da
vatandaşlık kimlik doğrulama randevusu açılırsa **telefonuna anında bildirim** gelir.
Bilgisayarının açık olması gerekmez; GitHub'ın ücretsiz sunucularında çalışır.

---

## 1. Telefona bildirim uygulamasını kur (2 dk)

1. Telefona **ntfy** uygulamasını indir (App Store / Google Play, ücretsiz).
2. Uygulamada **+** → "Subscribe to topic".
3. Kimsenin tahmin edemeyeceği bir konu adı yaz, örn: `migri-kaya-8f3k29xq`
   (bu ad şifre gibidir, kimseyle paylaşma).
4. Bu adı bir yere not et → aşağıda **NTFY_TOPIC** olarak kullanacağız.

## 2. GitHub'a yükle (5 dk)

1. github.com'da ücretsiz hesap aç (yoksa).
2. Sağ üstte **+ → New repository**. İsim: `migri-watch`, **Public** seç
   (public depolarda GitHub Actions sınırsız ücretsizdir; konu adın gizli kalır,
   çünkü onu "secret" olarak gireceğiz).
3. "uploading an existing file" linkine tıkla, bu klasördeki **tüm dosyaları**
   (`.github` klasörü dahil) sürükle bırak → **Commit changes**.
   > `.github` klasörü bilgisayarında gizli görünebilir. Görmüyorsan:
   > depoda **Add file → Create new file** de, ad olarak
   > `.github/workflows/migri.yml` yaz ve `migri.yml` dosyasının içeriğini yapıştır.

## 3. Gizli konu adını gir

Depoda **Settings → Secrets and variables → Actions → New repository secret**

- Name: `NTFY_TOPIC`
- Secret: 1. adımdaki konu adın

İsteğe bağlı (**Variables** sekmesi):

| Ad | Örnek | Ne işe yarar |
|---|---|---|
| `BEFORE_DATE` | `2027-01-08` | Bu tarihten önceki randevular bildirilir. **Zaten ayarlı: 7 Ocak 2027 dahil.** Değiştirmek istersen gir |
| `CITIES` | `Helsinki,Turku` | Takip edilecek şehirler |
| `WEEKS_AHEAD` | `12` | Kaç hafta ileriye bakılsın |
| `SERVICE_ID` | (aşağıya bak) | Otomatik bulma çalışmazsa |

## 4. Çalıştır ve kontrol et

**Actions** sekmesi → "Migri randevu takibi" → **Run workflow**.
Bir dakika sonra çalışmaya tıkla, "Randevuları kontrol et" adımının çıktısını oku:

- `aday servis: ... Citizenship ...` ve `N ofis tarandı` görüyorsan **her şey tamam**.
  Artık her 5 dakikada kendiliğinden çalışır.
- `Vatandaşlık servisi otomatik bulunamadı` görürsen → 5. adım.

## 5. (Gerekirse) SERVICE_ID nasıl bulunur

1. Bilgisayarda Chrome ile migri.fi → **Book an appointment** sayfasını aç.
2. **F12** → **Network** sekmesi.
3. Sayfada vatandaşlık (Citizenship) seçeneğini seç.
4. Network listesinde `localities` adlı isteğe tıkla → **Payload**.
   `"values": ["xxxxxxxx-xxxx-..."]` içindeki uzun kod **SERVICE_ID**'dir.
5. GitHub'da **Variables** kısmına `SERVICE_ID` olarak ekle, tekrar **Run workflow**.

## Alternatif: kendi bilgisayarında çalıştırmak

```bash
pip install requests
export NTFY_TOPIC=migri-kaya-8f3k29xq        # Windows: set NTFY_TOPIC=...
python migri_watch.py --test-notify           # telefona deneme bildirimi
python migri_watch.py --discover              # servis ve ofisleri listeler
python migri_watch.py --loop 180              # her 3 dakikada kontrol
```

## Notlar

- Aynı randevu için tekrar tekrar bildirim gelmez; sadece **yeni** açılanlar bildirilir.
- Bildirime tıklayınca Migri randevu sayfası açılır. Randevular hızlı gittiği için
  bildirim gelir gelmez rezervasyon yap.
- Randevunu aldıktan sonra **Actions → workflow → ⋯ → Disable workflow** ile durdur.
- Migri sitesini değiştirirse betik çalışmayı bırakabilir; Actions'taki kırmızı ✗
  işaretleri bunu gösterir.
