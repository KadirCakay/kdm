# KDM — Kişisel İndirme Yöneticisi

IDM (Internet Download Manager) benzeri, **Windows / macOS / Linux**'ta çalışan kişisel indirme yöneticisi.

- **Herhangi bir sitedeki** videoyu, diziyi, canlı yayın kaydını veya dosyayı indirir (sadece YouTube değil).
- İndirme düğmesi olmayan **eğitim platformlarında** da çalışır: tarayıcı eklentisi, oynatılan videoyu
  yakalar ve oturum bilgilerinizi indirme yöneticisine aktarır.
- **BigBlueButton** ders kayıtlarını (slaytlar + ekran paylaşımı + ses) tek bir MP4'e dönüştürür.
- Dizilerde IDM'deki gibi **altyazı seçeneği** sunar; **çift sesli (DUAL)** yayınlarda dil seçtirir.

Her şey kendi bilgisayarınızda çalışır. Hiçbir sunucuya, hesaba veya aboneliğe bağlı değildir.

---

## İçindekiler

1. [Nasıl çalışır?](#nasıl-çalışır)
2. [Kurulum — Windows](#kurulum--windows)
3. [Kurulum — macOS](#kurulum--macos)
4. [Kurulum — Linux](#kurulum--linux)
5. [Tarayıcı eklentisini yükleme](#tarayıcı-eklentisini-yükleme)
6. [Kullanım](#kullanım)
7. [Ayarlar](#ayarlar)
8. [Güncelleme ve uzun süreli kullanım](#güncelleme-ve-uzun-süreli-kullanım)
9. [Sorun giderme](#sorun-giderme)
10. [Sınırlamalar](#sınırlamalar)
11. [Mimari](#mimari)

---

## Nasıl çalışır?

KDM iki parçadan oluşur:

| Parça | Ne yapar |
|---|---|
| **KDM uygulaması** (Python) | İndirmeleri yapan program. Arka planda çalışır, arayüzü tarayıcıda açılır: <http://127.0.0.1:9614> |
| **KDM Yakalayıcı** (tarayıcı eklentisi) | Sayfadaki videoları, akışları ve altyazıları yakalar, tek tıkla uygulamaya gönderir. |

Kullanırken **uygulamanın açık olması gerekir**. Uygulama penceresi (siyah terminal penceresi) açık kaldığı sürece
indirmeler devam eder; kapatırsanız indirmeler duraklar ve bir sonraki açılışta ▶ ile kaldığı yerden sürer.

---

## Kurulum — Windows

### 1. Gerekli programlar

**Python 3.10 veya daha yenisi**
1. <https://www.python.org/downloads/> adresinden en son sürümü indirin.
2. Kurulumun **ilk ekranında** alttaki **“Add python.exe to PATH”** kutusunu işaretleyin. Bu adım önemlidir.
3. “Install Now” ile kurun.

**ffmpeg** (ses ve görüntüyü birleştirmek, altyazı ve BBB işlemleri için gerekir)
- Başlat menüsünde “PowerShell”i açıp şunu yazın:
  ```powershell
  winget install ffmpeg
  ```
- Kurulumdan sonra açık terminal pencerelerini kapatıp yeniden açın.

**Git** (GitHub'dan indirmek ve kolay güncellemek için)
```powershell
winget install Git.Git
```

Kurulumu kontrol etmek için **yeni** bir PowerShell penceresinde şunları çalıştırın:
```powershell
python --version     # Python 3.10 veya üstü
ffmpeg -version      # sürüm bilgisi görünmeli
git --version
```

### 2. KDM'yi indirme

```powershell
cd $HOME\Documents
git clone https://github.com/KadirCakay/kdm.git
cd kdm
```

> Git kullanmak istemezseniz GitHub sayfasında **Code → Download ZIP** ile indirip bir klasöre çıkarabilirsiniz.
> Bu durumda güncellemeleri de elle indirmeniz gerekir.

### 3. Çalıştırma

`kdm` klasöründeki **`start.bat`** dosyasına çift tıklayın.

- **İlk açılışta** gerekli Python paketleri `.venv` klasörüne kurulur (1–2 dakika).
- Ardından arayüz tarayıcıda açılır: <http://127.0.0.1:9614>
- Açılan siyah pencere uygulamanın kendisidir. **Kapatmayın**, simge durumuna küçültün.

**Masaüstü kısayolu (isteğe bağlı):** `start.bat` → sağ tık → *Diğer seçenekleri göster* → *Gönder* →
*Masaüstü (kısayol oluştur)*.

**Windows açılışında otomatik başlatma (isteğe bağlı):** `Win + R` → `shell:startup` yazın → açılan klasöre
`start.bat` için bir kısayol koyun.

Şimdi [tarayıcı eklentisini yükleyin](#tarayıcı-eklentisini-yükleme).

---

## Kurulum — macOS

Intel ve Apple Silicon (M1/M2/M3/M4) Mac'lerde çalışır.

### 1. Gerekli programlar

macOS'un kendi Python'u (3.9) **yeterli değildir**, bu yüzden Homebrew ile güncel Python kurulur.

1. **Homebrew** kurulu değilse *Terminal* uygulamasını açın ve <https://brew.sh> sayfasındaki komutu yapıştırın:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Kurulumun sonunda ekrana yazılan **“Next steps”** komutlarını (PATH ayarı) da çalıştırın.
2. Python, ffmpeg ve git'i kurun:
   ```bash
   brew install python ffmpeg git
   ```
3. Kontrol edin:
   ```bash
   python3 --version    # 3.10 veya üstü olmalı
   ffmpeg -version
   ```

### 2. KDM'yi indirme

```bash
cd ~/Documents
git clone https://github.com/KadirCakay/kdm.git
cd kdm
```

### 3. Çalıştırma

İki yolunuz var:

- **Terminal'den:**
  ```bash
  ./start.sh
  ```
- **Finder'dan çift tıklayarak:** `kdm` klasöründeki **`start.command`** dosyasına çift tıklayın.
  - İlk seferde macOS *“tanımlanamayan geliştirici”* uyarısı verebilir. Bu durumda dosyaya **sağ tık → Aç → Aç**
    deyin. Bir kez onayladıktan sonra çift tıklama normal çalışır.
  - Yeni macOS sürümlerinde uyarıda “Aç” seçeneği yoksa: *Sistem Ayarları → Gizlilik ve Güvenlik* sayfasının
    altındaki **“Yine de Aç”** düğmesini kullanın.
  - “İzin reddedildi” (permission denied) hatası alırsanız, Terminal'de bir kez şunu çalıştırın:
    `chmod +x start.sh start.command update.sh`

İlk açılışta paketler kurulur, ardından arayüz tarayıcıda açılır. Açılan Terminal penceresini kapatmayın.

**Dock'a eklemek (isteğe bağlı):** `start.command` dosyasını Dock'un sağ tarafına (çöp kutusunun yanına) sürükleyin.

**Oturum açılışında otomatik başlatma (isteğe bağlı):** *Sistem Ayarları → Genel → Giriş Öğeleri* →
“Oturum Açıldığında Aç” listesine `start.command` dosyasını ekleyin.

> **Safari desteklenmez.** Safari eklentileri ayrı bir paketleme gerektirir. Mac'te eklenti için
> **Chrome, Brave, Edge veya Firefox** kullanın. KDM'nin arayüzü ise Safari'de de açılır.

Şimdi [tarayıcı eklentisini yükleyin](#tarayıcı-eklentisini-yükleme).

---

## Kurulum — Linux

```bash
# Debian / Ubuntu / Mint
sudo apt install python3 python3-venv ffmpeg git
# Fedora
sudo dnf install python3 ffmpeg git        # ffmpeg için RPM Fusion deposu gerekebilir
# Arch
sudo pacman -S python ffmpeg git

cd ~
git clone https://github.com/KadirCakay/kdm.git
cd kdm
./start.sh
```

Python 3.10 veya üstü gerekir (`python3 --version`).

---

## Tarayıcı eklentisini yükleme

Eklenti, projedeki **`extension`** klasörüdür. Mağazada yayınlanmadığı için “paketlenmemiş” olarak yüklenir.
Bu tek seferlik bir işlemdir.

### Chrome / Edge / Brave / Opera / Vivaldi

1. Adres çubuğuna şunu yazın:
   - Chrome / Brave / Vivaldi: `chrome://extensions`
   - Edge: `edge://extensions`
   - Opera: `opera://extensions`
2. Sağ üstteki (Edge'de sol alttaki) **Geliştirici modu** anahtarını açın.
3. **Paketlenmemiş öğe yükle** (*Load unpacked*) düğmesine basın ve KDM klasörünün içindeki **`extension`**
   klasörünü seçin.
4. Araç çubuğundaki yapboz simgesine tıklayın ve **KDM Yakalayıcı**'nın yanındaki iğneye basarak sabitleyin.
5. Eklenti simgesine tıklayın. **“KDM çalışıyor”** yazıyorsa her şey hazırdır.

> - **Klasörü taşımayın veya silmeyin.** Eklenti doğrudan o klasörden çalışır. Taşırsanız eklentiyi kaldırıp
>   yeni konumdan tekrar yükleyin.
> - Chrome, açılışta *“Geliştirici modu eklentilerini devre dışı bırakın”* diye uyarabilir. Uyarıyı kapatmanız
>   yeterlidir; eklenti çalışmaya devam eder.
> - Güncellemeden sonra eklentiler sayfasında KDM Yakalayıcı'nın **↻ (yenile)** düğmesine basın.

### Firefox (121 ve üstü)

1. `about:debugging#/runtime/this-firefox` → **Geçici Eklenti Yükle** → `extension/manifest.json` dosyasını seçin.
2. `about:addons` → KDM Yakalayıcı → **İzinler** sekmesinde **“Tüm sitelerdeki verilerinize erişme”** iznini açın.
   Firefox bu izni varsayılan olarak kapalı getirir ve izin kapalıyken yakalama çalışmaz.

> Firefox geçici eklentileri **tarayıcı kapanınca kaldırır**, her açılışta yeniden yüklemeniz gerekir.
> Kalıcı kullanım için Chromium tabanlı bir tarayıcı (Chrome, Brave, Edge) önerilir.

---

## Kullanım

### Eğitim platformundan veya bir siteden video indirme

1. KDM'nin açık olduğundan emin olun.
2. Siteye tarayıcıda **giriş yapın** ve videonun olduğu sayfayı açın.
3. **Videoyu oynatın** (birkaç saniye yeterli). Oynatıcı videoyu yüklerken eklenti onu yakalar ve
   simgenin üzerinde bir sayı belirir.
4. Videonun üstünde çıkan **“⬇ Bu videoyu indir”** düğmesine veya eklenti simgesine tıklayın.
5. Açılan pencerede:
   - **Kaynak:** En uygun kaynak otomatik seçilir (BBB kaydı > HLS ana liste > DASH > dosya). Genelde dokunmanıza
     gerek yoktur.
   - **Dosya adı:** Sayfa başlığından otomatik doldurulur (“… izle | SiteAdı” gibi ekler temizlenir).
   - **Kalite:** 1080p, 720p… veya “Yalnızca ses”.
   - **Ses dili:** Birden fazla ses izi varsa çıkar (bkz. [Çift sesli yayınlar](#çift-sesli-dual-yayınlar)).
   - **Altyazılar:** İstediğiniz dilleri işaretleyin.
6. **İndirmeyi Başlat**. İlerlemeyi ana pencerede izleyebilirsiniz.

> Video bir iframe içindeyse (Vimeo, Wistia, JW Player gibi gömülü oynatıcılar) de çalışır, çünkü eklenti
> sayfadaki tüm çerçeveleri görür.

### Dizi indirme ve altyazılar

- **Altyazı seçeneği:** Siteden gelen altyazılar ve oynatıcının ayrıca yüklediği altyazı dosyaları listelenir.
  Seçtikleriniz videoyla aynı adla kaydedilir (`Bölüm 1.tr.srt`). VTT dosyaları otomatik olarak SRT'ye çevrilir.
- **“Altyazıları videonun içine göm”** seçilirse altyazılar MKV dosyasının içine konur. VLC, MPV, IINA ve
  Infuse gibi oynatıcılarda altyazıyı menüden açıp kapatabilirsiniz.
- **Bölüm bölüm:** Her bölümü açıp birkaç saniye oynatın ve eklentiden gönderin. Hepsi kuyruğa girer ve sırayla
  (aynı anda 3 tane) iner.
- **Sezon/liste sayfası:** Site liste olarak tanınıyorsa bağlantıyı **“+ Yeni İndirme”**ye yapıştırdığınızda
  bölüm listesi çıkar. İstediklerinizi seçip tek seferde kuyruğa ekleyebilirsiniz.

### Çift sesli (DUAL) yayınlar

Türkçe dublaj ve orijinal ses gibi birden fazla ses izi varsa ekleme penceresinde **Ses dili** seçeneği çıkar:

- Tek bir dil seçerseniz sadece o ses indirilir.
- **“Hepsi”**ni seçerseniz bütün diller tek bir **MKV** dosyasına konur ve dili oynatıcıdan değiştirebilirsiniz.
- Türkçe iz varsa varsayılan olarak o seçilir.

> **MKV ve MP4 hakkında:** Birden fazla ses izi veya gömülü altyazı varsa dosya MKV olarak kaydedilir, yoksa MP4.
> MKV dosyaları Windows'ta *Medya Oynatıcı* ve VLC'de, Mac'te **IINA** veya **VLC** ile sorunsuz oynar.
> Mac'in kendi QuickTime oynatıcısı MKV açamaz.
> Mac için önerilen oynatıcı: `brew install --cask iina` (ücretsiz).

### BigBlueButton ders kayıtları

BBB kayıtları tek bir video değildir. Ekran paylaşımı **sessizdir**, ses kamera dosyasındadır, slaytlar ise ayrı
resimlerdir. KDM bir BBB kayıt sayfasını (`…/playback/presentation/2.3/…`) otomatik tanır ve bu parçaları
birleştirir. Kayıt sayfasını açıp eklentiye tıklamanız yeterlidir; kaynak olarak “BigBlueButton kaydı”
otomatik seçilir. Modlar:

| Mod | Sonuç |
|---|---|
| **Sunum (önerilen)** | Slaytlar ve ekran paylaşımı, kayıttaki zamanlamalarına göre sesle birlikte tek bir MP4'te |
| **Sunum + kamera** | Aynısı, ek olarak sağ alt köşede konuşmacının kamerası |
| **Yalnızca ekran paylaşımı + ses** | En hızlısı, ancak slayt bölümleri boş kalır |
| **Yalnızca kamera + ses** | Kamera görüntüsü ve ses |
| **Yalnızca ses (m4a)** | Sadece ses |

2,5 saatlik bir ders tipik bir bilgisayarda yaklaşık 3–5 dakikada hazırlanır. Beyaz tahta üzerindeki çizimler ve
sohbet videoya eklenmez.

### Elle bağlantı ekleme

**“+ Yeni İndirme”**ye bir video sayfası, `.m3u8` / `.mpd` akış bağlantısı veya doğrudan dosya bağlantısı
yapıştırın. Birden fazla bağlantı için **“Toplu ekle”** bölümünü kullanın (her satıra bir bağlantı).

Site giriş gerektiriyorsa **Ayarlar → “Elle eklenen bağlantılar için tarayıcı çerezleri”** bölümünden
tarayıcınızı seçin. Eklentiyle gönderilen indirmelerde buna gerek yoktur.

### Görev düğmeleri

| Düğme | İşlev |
|---|---|
| ⏸ / ▶ | Duraklat / sürdür. Uygulama kapansa bile kaldığı yerden devam eder. |
| 📂 | Dosyanın bulunduğu klasörü açar |
| 📜 | Görev günlüğü: hata ayrıntıları ve yeniden denemeler |
| 🗑 | Listeden kaldırır; isterseniz yarım dosyaları da siler |

Geçici bir hata olursa (sunucu bir parçayı vermedi, bağlantı koptu vb.) KDM görevi 10, 20 ve 30 saniye sonra
kendisi yeniden dener.

---

## Ayarlar

Arayüzdeki ⚙ **Ayarlar** penceresinden değiştirilebilir:

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| İndirme klasörü | `İndirilenler/KDM` | Dosyaların kaydedileceği yer |
| Eşzamanlı indirme | 3 | Aynı anda kaç görev çalışsın |
| Bağlantı sayısı | 8 | Doğrudan dosyalarda parça sayısı (akışlarda en fazla 5) |
| Hız sınırı | 0 (sınırsız) | KB/s |
| Altyazı biçimi | srt | |
| Altyazıyı göm | kapalı | |

Ayarlar ve görev listesi şu klasörde saklanır:
- Windows: `C:\Users\<kullanıcı>\.kdm`
- macOS / Linux: `~/.kdm`

Port değiştirmek isterseniz (`start.bat --port 9700` veya `./start.sh --port 9700`), eklentinin açılır
penceresindeki port ayarını da aynı değere getirin.

---

## Güncelleme ve uzun süreli kullanım

KDM'nin kendisi bir sunucuya veya hesaba bağlı değildir, yani kodu bilgisayarınızda durduğu sürece çalışır.
Zamanla bozulabilecek tek şey **sitelerin kendileridir**: siteler oynatıcılarını ve video adreslerini
değiştirebilir. Bunun için:

### Ayda bir (veya bir site çalışmayı bıraktığında) güncelleyin

- **Windows:** `update.bat`'a çift tıklayın.
- **macOS / Linux:** `./update.sh`

Güncelleme betiği iki şey yapar:
1. GitHub'dan KDM'nin son halini çeker (`git pull`).
2. Python paketlerini, özellikle site desteğinin büyük kısmını sağlayan **yt-dlp**'yi günceller.

Ardından KDM'yi kapatıp yeniden açın. Eklentide değişiklik olduysa tarayıcının eklentiler sayfasında ↻ düğmesine
basın.

### Uzun vadede dikkat edilecekler

- **ffmpeg** ara sıra güncellenebilir: `winget upgrade ffmpeg` / `brew upgrade ffmpeg`.
- **Python** büyük sürüm değiştirirse (ör. 3.12 → 3.14) ve KDM açılmazsa projedeki `.venv` klasörünü silin.
  Bir sonraki `start` paketleri yeniden kurar. Görevleriniz ve ayarlarınız `.kdm` klasöründe olduğu için kaybolmaz.
- **Yeni bilgisayara taşıma:** Yeni bilgisayarda kurulumu yapın (`git clone` + `start`). Görev geçmişini ve
  ayarları da taşımak isterseniz eski bilgisayardaki `.kdm` klasörünü kopyalayın.
- **Kendi değişikliklerinizi saklama:** Kodda bir değişiklik yaparsanız `git add -A && git commit -m "..." && git push`
  ile GitHub'a gönderin. Böylece diğer bilgisayarlarınız `update` ile aynı sürümü alır.

---

## Sorun giderme

| Sorun | Çözüm |
|---|---|
| Eklentide “KDM çalışmıyor” yazıyor | Uygulamayı (`start.bat` / `start.command`) başlatın. Port değiştirdiyseniz eklentide aynı portu girin. |
| `start.bat` açılıp hemen kapanıyor / Python bulunamadı | Python'u “Add python.exe to PATH” işaretli olarak yeniden kurun. |
| macOS: “Python 3.10 veya daha yenisi bulunamadı” | `brew install python`, ardından `rm -rf .venv` ve tekrar başlatın. |
| macOS: `start.command` açılmıyor | Sağ tık → Aç. Olmazsa `chmod +x start.sh start.command update.sh`. |
| “ffmpeg bulunamadı” uyarısı | ffmpeg'i kurun (yukarıdaki adımlar) ve KDM'yi yeniden başlatın. |
| Hiç medya yakalanmıyor | Videoyu gerçekten oynatın. Sayfayı yenileyip tekrar oynatın. Firefox'ta site erişim iznini kontrol edin. |
| 403 / 401 hatası | Sitede oturumunuz açık olmalı. Bazı siteler bağlantıları birkaç dakikada geçersiz kılar: sayfayı yenileyip videoyu tekrar oynatın ve eklentiden yeniden gönderin. |
| Bir site eskiden çalışıyordu, artık çalışmıyor | `update.bat` / `./update.sh` ile güncelleyin. |
| “DRM ile korunuyor” | Bu içerik teknik olarak indirilemez (bkz. Sınırlamalar). |
| Ses yok / görüntü yok | ffmpeg kurulu olmalı. BBB kayıtlarında kaynak olarak “BigBlueButton kaydı”nı seçin. |
| Mac'te MKV açılmıyor | QuickTime MKV desteklemez; IINA veya VLC kullanın. |
| “Tamamlandı (N parça atlandı)” | Sunucu birkaç parçayı 15 denemeye rağmen vermedi. Videoda birkaç saniyelik atlama olabilir. İsterseniz görevi silip tekrar deneyin. |
| Klasörde `…part-Frag12` gibi dosyalar | Yarım kalmış akış parçalarıdır. Görevi ▶ ile sürdürün veya 🗑 → “dosyaları da sil” ile temizleyin. |
| Port kullanımda | KDM zaten açıktır; tarayıcıda <http://127.0.0.1:9614> adresini açın. |

Her görevin ayrıntılı hata kaydı için görevdeki 📜 düğmesine bakın.

---

## Sınırlamalar

- **DRM korumalı içerikler** (Netflix, Disney+, Prime Video, BluTV gibi Widevine / PlayReady / FairPlay kullanan
  platformlar) **desteklenmez**. KDM bunu algılar ve size bildirir. Standart AES-128 şifreli HLS akışları DRM
  değildir ve desteklenir.
- BigBlueButton kayıtlarında beyaz tahta çizimleri ve sohbet videoya eklenmez.
- Safari eklentisi yoktur (Mac'te Chrome, Brave, Edge veya Firefox kullanın).

---

## Mimari

```
extension/                 Tarayıcı eklentisi (Manifest V3, Chrome + Firefox)
  background.js            Ağ isteklerini izler, medya/altyazı yakalar, çerezleri toplar
  content.js               Videoların üzerine "İndir" düğmesi
  popup.html/js            Yakalanan medya listesi ve ayarlar
kdm/                       Masaüstü uygulaması (Python)
  server.py                127.0.0.1 üzerinde API + web arayüzü
  manager.py               Kuyruk, eşzamanlılık, otomatik yeniden deneme, durum kaydı
  engines/http_engine.py   Çok bağlantılı, devam ettirilebilir HTTP motoru
  engines/ytdlp_engine.py  Akış/site motoru (HLS, DASH, liste, altyazı, çoklu ses)
  engines/bbb_engine.py    BigBlueButton kayıtlarını birleştirme (slayt + ekran + ses)
  subtitles.py             Altyazı indirme, SRT'ye çevirme, gömme
  static/                  Web arayüzü
run.py                     Giriş noktası (python run.py --no-browser --port 9614)
start.bat / start.sh / start.command   Başlatıcılar (ilk kurulumu da yapar)
update.bat / update.sh     Güncelleyiciler
```

**Güvenlik:** Sunucu yalnızca `127.0.0.1` adresini dinler, başka bilgisayarlardan erişilemez. Başka web
sitelerinden gelen istekleri reddeder. Eklentinin aktardığı oturum çerezleri, ilgili indirme bitince silinir.

## Yasal not

Bu araç kişisel kullanım içindir. Yalnızca erişim hakkınız olan içerikleri indirin; platformların kullanım
koşullarına ve telif haklarına uyun.
