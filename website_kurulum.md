# Alan Adını (ai-org.online) Sunucuya Bağlama Rehberi

Bu rehber, hiç sunucu veya alan adı tecrübesi olmayan birinin baştan sona okuyup
uygulayabileceği şekilde yazıldı. Önce kavramları anlatıyor, sonra adım adım
ne yapılacağını gösteriyor, en sonda da sorun çıkarsa ne yapılacağını anlatıyor.

**Hedef:** Tarayıcıya `https://ai-org.online` yazıldığında, şu an
`https://38-45-81-29.sslip.io` adresinde çalışan Linko arayüzünün açılması.

---

## İçindekiler

1. [Önce kavramlar: Bu işin parçaları neler?](#1-önce-kavramlar-bu-işin-parçaları-neler)
2. [Bizim mevcut düzenimiz](#2-bizim-mevcut-düzenimiz)
3. [Yapılacakların kısa özeti](#3-yapılacakların-kısa-özeti)
4. [Adım 1 — Hostinger'da DNS kayıtlarını ayarlamak](#4-adım-1--hostingerda-dns-kayıtlarını-ayarlamak)
5. [Adım 2 — DNS'in yayıldığını kontrol etmek](#5-adım-2--dnsin-yayıldığını-kontrol-etmek)
6. [Adım 3 — Sunucuya bağlanmak (SSH)](#6-adım-3--sunucuya-bağlanmak-ssh)
7. [Adım 4 — Caddy'ye yeni alan adını tanıtmak](#7-adım-4--caddyye-yeni-alan-adını-tanıtmak)
8. [Adım 5 — Güvenlik duvarını kontrol etmek](#8-adım-5--güvenlik-duvarını-kontrol-etmek)
9. [Adım 6 — Test etmek](#9-adım-6--test-etmek)
10. [Sonrasında güncellenmesi gerekenler](#10-sonrasında-güncellenmesi-gerekenler)
11. [Alternatif: Alt alan adı kullanmak (linko.ai-org.online)](#11-alternatif-alt-alan-adı-kullanmak-linkoai-orgonline)
12. [Sorun giderme](#12-sorun-giderme)
13. [Güvenlik ve bakım notları](#13-güvenlik-ve-bakım-notları)
14. [Sözlük](#14-sözlük)
15. [Hızlı komut listesi](#15-hızlı-komut-listesi)

---

## 1. Önce kavramlar: Bu işin parçaları neler?

Bir web sitesinin açılması için birbirinden bağımsız **üç parça** birlikte çalışır.
Bu üçünü ayrı ayrı anlamak, ileride bir şey bozulduğunda nereye bakacağınızı bilmenizi sağlar.

### 1.1 Sunucu (VPS) — "Evin kendisi"

**Sunucu**, 7/24 açık duran, internete bağlı bir bilgisayardır. Bizim sunucumuz
Euronodes firmasından kiralanmış bir **VPS**'tir (*Virtual Private Server* — Sanal Özel Sunucu).
Yani fiziksel bir makinenin içinde bize ayrılmış sanal bir bilgisayar.

Linko uygulaması bu bilgisayarda çalışıyor: ilanları topluyor, veritabanına yazıyor ve
web arayüzünü sunuyor.

### 1.2 IP adresi — "Evin açık adresi"

İnternetteki her sunucunun bir **IP adresi** vardır. Bu, telefon numarası ya da
açık adres gibidir. Bizim sunucunun IP adresi:

```
38.45.81.29
```

Bilgisayarlar birbirini bu numaralarla bulur. Ama insanlar için `38.45.81.29`
akılda tutulması zor ve güven vermeyen bir şeydir.

### 1.3 Alan adı (Domain) — "Evin tabelası / kısa adı"

**Alan adı**, IP adresine verilen akılda kalıcı bir isimdir: `ai-org.online`.
Bu ismi Hostinger'dan satın aldınız. Ekran görüntüsünde görüldüğü üzere:

- **Bitiş tarihi:** 2027-10-17 (bu tarihte yenilenmezse alan adı elinizden çıkar)
- **Otomatik yenileme:** Açık (iyi, açık kalsın)
- **Durum:** Etkin

> Önemli: Alan adını satın almak, onu bir sunucuya **bağlamak** anlamına gelmez.
> Şu an alan adınız Hostinger'ın "park sayfasına" yönleniyor. Yani tabelanız var
> ama tabela henüz bizim evi göstermiyor.

### 1.4 DNS — "İnternetin telefon rehberi"

**DNS** (*Domain Name System*), alan adlarını IP adreslerine çeviren sistemdir.
Birisi tarayıcıya `ai-org.online` yazdığında, bilgisayarı önce DNS'e
"`ai-org.online`'ın IP adresi ne?" diye sorar, DNS de "`38.45.81.29`" diye cevap verir.
Sonra tarayıcı o IP adresine bağlanır.

Bu rehberin **en önemli adımı**, DNS rehberine "`ai-org.online` → `38.45.81.29`"
satırını yazmaktır.

### 1.5 Ad Sunucuları (Nameservers) — "Rehberi kim tutuyor?"

**Ad sunucuları**, alan adınızın DNS kayıtlarını tutan sunuculardır. Ekran görüntüsünde:

```
byte.dns-parking.com
pixel.dns-parking.com
```

Bunlar **Hostinger'ın** ad sunucularıdır. Bu şu anlama gelir: DNS kayıtlarınızı
**Hostinger panelinden** düzenleyeceksiniz. Ad sunucularını **değiştirmeyin**;
olduğu gibi kalsın.

### 1.6 DNS kayıt türleri

DNS rehberinde farklı türde satırlar (kayıtlar) vardır. Bizi ilgilendirenler:

| Tür | Ne işe yarar | Örnek |
|---|---|---|
| **A** | Bir ismi **IPv4** adresine bağlar. Bizim asıl ihtiyacımız bu. | `ai-org.online` → `38.45.81.29` |
| **AAAA** | Bir ismi **IPv6** adresine bağlar (yeni nesil, uzun IP adresleri). | `ai-org.online` → `2a02:...` |
| **CNAME** | Bir ismi **başka bir isme** yönlendirir ("o neredeyse ben de oradayım"). | `www.ai-org.online` → `ai-org.online` |
| **MX** | E-postaların hangi sunucuya gideceğini söyler. Web sitesiyle ilgisi yok. | — |
| **TXT** | Doğrulama amaçlı serbest metin (Google doğrulaması, SPF vb.). | — |
| **CAA** | Bu alan adı için hangi firmanın SSL sertifikası verebileceğini sınırlar. | `0 issue "letsencrypt.org"` |

Kayıtlardaki **isim (Name / Ad / Host)** alanında:

- `@` işareti **alan adının kendisi** demektir (`ai-org.online`).
- `www` ise `www.ai-org.online` demektir.
- `linko` yazsaydınız `linko.ai-org.online` olurdu (alt alan adı).

### 1.7 TTL ve "yayılma" (propagation)

**TTL** (*Time To Live*), bir DNS cevabının dünyadaki diğer bilgisayarlar tarafından
ne kadar süre **hafızada tutulacağını** (saniye cinsinden) belirtir. Örneğin TTL = 3600
ise, bir bilgisayar cevabı 1 saat boyunca tekrar sormadan kullanır.

Bu yüzden DNS'te bir değişiklik yaptığınızda, bazı insanlar yeni adresi hemen görür,
bazıları eski adresi bir süre daha görmeye devam eder. Buna **yayılma (propagation)**
denir. Genelde **5 dakika ile birkaç saat** arasında sürer, nadiren 24-48 saate çıkabilir.
Sabırlı olun; bu normaldir.

### 1.8 Port — "Evin hangi kapısı"

Bir sunucuda birden çok program aynı anda çalışabilir. Gelen bağlantının hangi programa
gideceğini **port numarası** belirler. Kapı numarası gibi düşünün:

| Port | Kullanımı |
|---|---|
| **22** | SSH — sunucuyu uzaktan yönetmek için |
| **80** | HTTP — şifresiz web |
| **443** | HTTPS — şifreli web (tarayıcıdaki kilit simgesi) |
| **8016** | Linko uygulamasının kendisi (yalnızca sunucunun içinden erişilebilir) |

### 1.9 Caddy — "Kapıdaki görevli / resepsiyon"

Linko uygulaması güvenlik nedeniyle **dışarıya doğrudan açık değildir**; yalnızca
sunucunun kendi içinden (`127.0.0.1:8016`) erişilebilir.

Dışarıdan gelen ziyaretçileri **Caddy** adlı bir program karşılar. Caddy bir
**ters vekil sunucudur** (*reverse proxy*). Görevleri:

1. 80 ve 443 numaralı kapılarda (portlarda) bekler.
2. Ziyaretçiden **kullanıcı adı ve şifre** ister (basic auth).
3. Bağlantıyı **HTTPS ile şifreler**.
4. Doğrulanan isteği içerideki Linko uygulamasına iletir, cevabı geri taşır.

> Neden şifre şart? Linko uygulaması, sunucunun kendi içinden gelen isteklere
> anahtar sormadan güvenir. Caddy'deki şifre olmasa, internetteki herkes
> arayüze ve verilere erişebilirdi. Bu yüzden şifre korumasını **asla kaldırmayın**.

### 1.10 HTTPS, SSL sertifikası ve Let's Encrypt

**HTTPS**, tarayıcı ile sunucu arasındaki trafiğin şifrelenmesidir. Bunun için
sunucunun bir **SSL/TLS sertifikasına** ihtiyacı vardır. Sertifika, "bu sunucu gerçekten
`ai-org.online`'a ait" diyen dijital bir kimlik belgesidir.

**Let's Encrypt** ücretsiz sertifika veren bir kuruluştur. **Caddy, sertifikayı
kendisi otomatik olarak alır ve yeniler.** Sizin sertifika satın almanıza veya
Hostinger'daki SSL seçeneklerine dokunmanıza gerek yoktur.

Ama Let's Encrypt sertifika vermeden önce bir kontrol yapar: "`ai-org.online`
gerçekten bu sunucuyu mu gösteriyor?" Bu yüzden **önce DNS ayarlanmalı, sonra Caddy
ayarlanmalı.** Sıra önemlidir.

### 1.11 Büyük resim

```
 Ziyaretçi tarayıcıya "ai-org.online" yazar
            │
            ▼
 ┌─────────────────────┐   "ai-org.online nerede?"
 │  DNS (Hostinger)     │ ──────────────────────────►  "38.45.81.29"
 └─────────────────────┘
            │
            ▼  https://38.45.81.29 (port 443)
 ┌──────────────────────────────────────────────────────┐
 │  VPS (Euronodes, 38.45.81.29)                        │
 │                                                      │
 │   ┌──────────────┐  şifre doğru  ┌────────────────┐  │
 │   │    Caddy     │ ────────────► │ Linko uygulaması│  │
 │   │  (80 / 443)  │               │ 127.0.0.1:8016 │  │
 │   └──────────────┘               └────────────────┘  │
 │   HTTPS + şifre sorma                                │
 └──────────────────────────────────────────────────────┘
```

---

## 2. Bizim mevcut düzenimiz

| Bileşen | Değer |
|---|---|
| Sunucu sağlayıcısı | Euronodes (VPS adı: `trace-vps`) |
| İşletim sistemi | Ubuntu 24.04 |
| Sunucu IP adresi | `38.45.81.29` |
| SSH erişimi | `ssh root@38.45.81.29` (anahtar: `~/.ssh/id_ed25519`, şifreyle giriş kapalı) |
| Uygulama kodu | `/opt/linko` |
| Uygulama verisi | `/var/lib/linko` |
| Uygulama ayarları | `/etc/linko.env` |
| Uygulama servisi | `linko.service` (`127.0.0.1:8016` dinler) |
| Ön kapı (reverse proxy) | Caddy, ayar dosyası `/etc/caddy/Caddyfile` |
| Şu anki adres | `https://38-45-81-29.sslip.io` |
| Arayüz kullanıcı adı | `trace` (şifre: `SIFRELER.txt` içinde) |
| Şifre istemeyen yollar | `/api/v1/*` ve `/healthz` (bunlar kendi API anahtarıyla korunur) |
| Alan adı | `ai-org.online` (Hostinger, ad sunucuları `*.dns-parking.com`) |

> `sslip.io` nedir? IP adresini isim gibi yazmanıza yarayan ücretsiz bir hizmettir:
> `38-45-81-29.sslip.io` otomatik olarak `38.45.81.29`'a çözülür. Alan adınız
> olmadığı için geçici çözüm olarak kullanıldı. Alan adı çalıştıktan sonra
> bu adres de çalışmaya devam edebilir (yedek olarak), isterseniz kaldırırsınız.

---

## 3. Yapılacakların kısa özeti

| # | Nerede | Ne yapılacak | Süre |
|---|---|---|---|
| 1 | Hostinger paneli | `@` ve `www` için A kaydı → `38.45.81.29`; park kayıtlarını sil | 5 dk |
| 2 | Kendi bilgisayarınız | DNS'in yeni IP'yi gösterdiğini doğrula | 5 dk – birkaç saat bekleme |
| 3 | Kendi bilgisayarınız | Sunucuya SSH ile bağlan | 1 dk |
| 4 | Sunucu | Caddyfile'a `ai-org.online` ekle, Caddy'yi yeniden yükle | 5 dk |
| 5 | Sunucu | 80 ve 443 portlarının açık olduğunu doğrula | 2 dk |
| 6 | Tarayıcı | `https://ai-org.online` adresini aç, şifreyle gir | 1 dk |

---

## 4. Adım 1 — Hostinger'da DNS kayıtlarını ayarlamak

### 4.1 DNS sayfasını açmak

1. [hpanel.hostinger.com](https://hpanel.hostinger.com) adresine giriş yapın.
2. Sol menüden **Domainler**'e tıklayın.
3. Üstteki **Domain seçin** kutusunda `ai-org.online` seçili olsun.
4. Sol taraftaki alt menüden **DNS / Ad Sunucuları**'na tıklayın.
5. Açılan sayfada iki sekme görürsünüz: **DNS kayıtları** ve **Ad sunucuları**.
   **DNS kayıtları** sekmesinde kalın.

> **Ad sunucuları** sekmesinde hiçbir şeyi değiştirmeyin. Orada
> `byte.dns-parking.com` / `pixel.dns-parking.com` yazması doğrudur.

### 4.2 Mevcut kayıtları incelemek

Sayfanın alt kısmında **"DNS kayıtlarını yönet"** gibi bir başlığın altında
mevcut kayıtların listesi vardır. Hostinger yeni alınan alan adlarına genellikle
şu "park" kayıtlarını ekler:

| Tür | Ad | İçerik / Hedef | Açıklama |
|---|---|---|---|
| A | `@` | Hostinger'a ait bir IP (ör. `2.57.x.x`, `84.32.x.x`) | Park sayfasını gösterir — **değiştirilecek** |
| AAAA | `@` | Hostinger'a ait IPv6 adresi | Park sayfası — **silinecek** |
| CNAME | `www` | `ai-org.online` veya Hostinger'a ait bir isim | **kontrol edilecek** |
| AAAA | `www` | Hostinger IPv6 | varsa **silinecek** |
| MX, TXT | `@` | e-posta ile ilgili | **dokunmayın** |
| CAA | `@` | sertifika firmaları | **kontrol edilecek** (aşağıda) |

Listede birebir aynısını görmeyebilirsiniz; önemli olan mantık:
**`@` ve `www` isimleri için web trafiğini Hostinger'a gönderen her A / AAAA / CNAME kaydı
ya bizim IP'ye çevrilmeli ya da silinmeli.**

> Neden AAAA kayıtları silinmeli? Bir ismin hem A (IPv4) hem AAAA (IPv6) kaydı varsa,
> IPv6 destekli cihazlar (çoğu mobil hat, birçok ev interneti) **AAAA'yı tercih eder**.
> AAAA hâlâ Hostinger'ı gösteriyorsa, bu ziyaretçiler park sayfasına gider ve
> Let's Encrypt sertifika doğrulaması da başarısız olabilir. Sunucumuza bir IPv6
> adresi tanımlamadığımız için AAAA kaydı **hiç olmamalı**.

### 4.3 Kök alan adı (`@`) için A kaydı

**Eğer listede `@` için bir A kaydı varsa:** Yanındaki **Düzenle** (kalem simgesi)
butonuna tıklayın ve şöyle değiştirin:

| Alan | Değer |
|---|---|
| Tür (Type) | `A` |
| Ad (Name) | `@` |
| Şuna yönlendirir / İçerik (Points to) | `38.45.81.29` |
| TTL | `3600` (veya varsayılan; değişiklik denemeleri sırasında `300` yapabilirsiniz) |

**Eğer yoksa:** Sayfanın üstündeki **kayıt ekleme formunu** aynı değerlerle doldurup
**Kayıt Ekle / Add Record** butonuna basın.

> `@` için **birden fazla** A kaydı olmamalı. İki A kaydı varsa, ziyaretçiler rastgele
> birine gider. Fazla olanı silin.

### 4.4 `www` için kayıt

İnsanlar alışkanlıkla `www.ai-org.online` yazabilir. Bunun da çalışması için iki seçenek var,
**ikisinden birini** yapın:

**Seçenek A (önerilen) — CNAME:**

| Alan | Değer |
|---|---|
| Tür | `CNAME` |
| Ad | `www` |
| Hedef | `ai-org.online` |
| TTL | `3600` |

Mevcut `www` CNAME kaydı zaten `ai-org.online`'ı gösteriyorsa **hiçbir şey yapmanıza
gerek yok**; `@` kaydını değiştirdiğinizde `www` de otomatik olarak yeni IP'ye gider.
Başka bir şeyi gösteriyorsa düzenleyip `ai-org.online` yapın.

**Seçenek B — A kaydı:** `www` için CNAME'i silip `Ad: www`, `İçerik: 38.45.81.29`
olan bir A kaydı ekleyin.

> Aynı isim için hem CNAME hem A kaydı **olamaz**. Hostinger izin vermez; önce
> diğerini silmeniz gerekir.

### 4.5 AAAA kayıtlarını silmek

`@` ve `www` için AAAA kaydı varsa, her birinin yanındaki **Sil** (çöp kutusu) simgesine
tıklayıp onaylayın.

### 4.6 CAA kayıtlarını kontrol etmek

Listede **CAA** türünde kayıt **yoksa** bu adımı atlayın (CAA olmaması "her firma
sertifika verebilir" demektir, sorun yok).

**CAA kayıtları varsa:** İçlerinden birinde `letsencrypt.org` yazmalı, örneğin:

```
0 issue "letsencrypt.org"
```

Yazmıyorsa, yukarıdaki değerle yeni bir CAA kaydı ekleyin (Ad: `@`, Tür: `CAA`,
Flag: `0`, Tag: `issue`, Değer: `letsencrypt.org`). Aksi halde Caddy sertifika
alamaz ve site HTTPS ile açılmaz.

### 4.7 Dokunmamanız gerekenler

- **MX** ve e-postayla ilgili **TXT** kayıtları (ör. `v=spf1 ...`, `_dmarc`): Bunlar
  e-posta içindir. Silerseniz ileride `@ai-org.online` e-postası kurarken sorun yaşarsınız.
- **Ad sunucuları** sekmesi.
- Panelde gördüğünüz **"Hemen başla"**, **"Bir web sitesi olmadan kullanın"**,
  **"Website Builder"** gibi seçenekler: Bunlar Hostinger'ın kendi barındırma
  hizmetine yöneliktir. Bizim sitemiz kendi VPS'imizde çalıştığı için bunlara
  **gerek yok**. Bunları seçerseniz Hostinger DNS kayıtlarını kendi sunucularına
  geri çevirebilir.

### 4.8 Son hal

Doğru ayarlandığında web ile ilgili kayıtlar şöyle görünmeli:

| Tür | Ad | İçerik | TTL |
|---|---|---|---|
| A | `@` | `38.45.81.29` | 3600 |
| CNAME | `www` | `ai-org.online` | 3600 |

(Artı varsa MX / TXT / CAA kayıtları — onlara dokunulmadı.)
`@` veya `www` için **başka hiçbir A, AAAA veya CNAME kaydı olmamalı.**

---

## 5. Adım 2 — DNS'in yayıldığını kontrol etmek

DNS değişikliği hemen her yere ulaşmaz (bkz. [1.7](#17-ttl-ve-yayılma-propagation)).
Bir sonraki adıma geçmeden önce yeni kaydın göründüğünü doğrulayın.

### 5.1 Windows'ta komutla kontrol

**PowerShell** veya **Komut İstemi**'ni açın (Başlat menüsüne `powershell` yazın) ve:

```powershell
nslookup ai-org.online 8.8.8.8
nslookup www.ai-org.online 8.8.8.8
nslookup ai-org.online 1.1.1.1
```

Burada `8.8.8.8` Google'ın, `1.1.1.1` Cloudflare'in herkese açık DNS sunucusudur.
Böylece kendi bilgisayarınızın eski hafızasına (önbelleğine) takılmadan sorgularsınız.

**Beklenen çıktı** (önemli olan son satırlar):

```
Name:    ai-org.online
Address:  38.45.81.29
```

- `Address` satırında **yalnızca** `38.45.81.29` görüyorsanız: Hazırsınız, Adım 3'e geçin.
- Farklı bir IP görüyorsanız: Henüz yayılmamış. 10-15 dakika bekleyip tekrar deneyin.
- Bir de IPv6 adresi (iki nokta üst üsteli uzun adres) görüyorsanız: AAAA kaydı
  hâlâ duruyor demektir; [4.5](#45-aaaa-kayıtlarını-silmek)'e dönün.

IPv6 kaydı kalmadığından emin olmak için:

```powershell
nslookup -type=AAAA ai-org.online 8.8.8.8
```

Burada adres **dönmemeli** ("No answer" / yanıt yok benzeri bir şey yazmalı).

### 5.2 Tarayıcıdan dünya çapında kontrol

[dnschecker.org](https://dnschecker.org) sitesine girin, kutuya `ai-org.online` yazın,
türü `A` seçip **Search**'e basın. Dünya haritasındaki DNS sunucularının çoğunda
yeşil tik ve `38.45.81.29` görüyorsanız yayılma tamamlanmış demektir.

### 5.3 Kendi bilgisayarınızın önbelleğini temizlemek

Komut doğru IP'yi gösterdiği hâlde tarayıcınız hâlâ park sayfasını açıyorsa,
bilgisayarınız eski cevabı hafızada tutuyordur:

```powershell
ipconfig /flushdns
```

Ardından tarayıcıyı tamamen kapatıp açın (veya gizli pencere kullanın).

---

## 6. Adım 3 — Sunucuya bağlanmak (SSH)

**SSH** (*Secure Shell*), uzaktaki sunucuya güvenli şekilde bağlanıp komut çalıştırmanızı
sağlar. Bir nevi sunucunun klavyesini ve ekranını internet üzerinden kullanmak gibidir.

Bilgisayarınızda PowerShell açın ve yazın:

```powershell
ssh root@38.45.81.29
```

- `root`: sunucudaki en yetkili kullanıcı (yönetici).
- Şifre sorulmaz; bilgisayarınızdaki `C:\Users\eminf\.ssh\id_ed25519` anahtar dosyası
  sizi otomatik tanıtır. **Bu dosyayı kimseyle paylaşmayın, kaybetmeyin.**

Bağlandığınızda komut satırının başı şuna benzer olur:

```
root@trace-vps:~#
```

Artık yazdığınız her komut **sunucuda** çalışır. Çıkmak için `exit` yazın.

> İlk kez bağlanıyorsanız "Are you sure you want to continue connecting?" sorusu
> gelebilir; `yes` yazıp Enter'a basın. Bu, sunucunun kimliğini bilgisayarınıza kaydeder.

---

## 7. Adım 4 — Caddy'ye yeni alan adını tanıtmak

Caddy şu an yalnızca `38-45-81-29.sslip.io` ismiyle gelen isteklere cevap veriyor.
`ai-org.online` ile gelen istekleri de kabul etmesini ve bu isim için sertifika
almasını söylememiz gerekiyor.

> **Hatırlatma:** Bu adıma ancak Adım 2'de DNS'in `38.45.81.29`'u gösterdiğini
> doğruladıktan sonra geçin. Aksi halde Caddy sertifika almaya çalışır, başarısız olur
> ve bir süre tekrar denemeyi bekletir.

### 7.1 Önce yedek alın

Ayar dosyasını değiştirmeden önce bir kopyasını alın; bir şey ters giderse geri
dönebilirsiniz:

```bash
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.yedek-$(date +%F)
```

### 7.2 Mevcut dosyaya bakın

```bash
cat /etc/caddy/Caddyfile
```

Dosya aşağıdakine **benzer** bir yapıdadır (şifre satırındaki uzun karmaşık metin,
şifrenin kendisi değil, şifrenin geri çevrilemez özetidir — *hash*):

```caddyfile
38-45-81-29.sslip.io {
    @korumali not path /api/v1/* /healthz
    basic_auth @korumali {
        trace $2a$14$............................................
    }
    reverse_proxy 127.0.0.1:8016
}
```

Satırların anlamı:

| Satır | Anlamı |
|---|---|
| `38-45-81-29.sslip.io {` | "Bu isimle gelen istekler için aşağıdaki kurallar geçerli." Caddy bu isim için otomatik sertifika alır. |
| `@korumali not path /api/v1/* /healthz` | "API ve sağlık kontrolü dışındaki tüm yollar" için bir etiket tanımlar. |
| `basic_auth @korumali { ... }` | Bu yollar için kullanıcı adı/şifre ister. |
| `reverse_proxy 127.0.0.1:8016` | Geçen istekleri içerideki Linko uygulamasına iletir. |

(Sizdeki dosyada etiket adı, `basicauth` / `basic_auth` yazımı vb. küçük farklar
olabilir. Önemli değil; **içeriğe dokunmayacağız, sadece ilk satırı değiştireceğiz.**)

### 7.3 Dosyayı düzenleyin

Sunucuda basit bir metin düzenleyici olan **nano** ile dosyayı açın:

```bash
nano /etc/caddy/Caddyfile
```

**Yapılacak tek değişiklik:** İlk satırdaki site adresinin başına yeni alan adlarını
virgülle ekleyin.

Önce:

```caddyfile
38-45-81-29.sslip.io {
```

Sonra:

```caddyfile
ai-org.online, www.ai-org.online, 38-45-81-29.sslip.io {
```

Böylece aynı kurallar (şifre koruması dahil) üç isim için de geçerli olur.
`sslip.io` adresini şimdilik bırakıyoruz; yeni alan adında bir sorun çıkarsa
yedek kapı olarak işe yarar.

**nano'da kaydetme ve çıkma:**

1. `Ctrl + O` (harf O) → alt satırda dosya adı görünür → `Enter` ile kaydet.
2. `Ctrl + X` → nano'dan çık.

#### (İsteğe bağlı) `www`'yi ana adrese yönlendirmek

`www.ai-org.online` yazanların adres çubuğunda otomatik olarak `ai-org.online`
görmesini isterseniz, ilk satıra `www`'yi **eklemeyin**, bunun yerine dosyanın
**en sonuna** ayrı bir blok ekleyin:

```caddyfile
www.ai-org.online {
    redir https://ai-org.online{uri} permanent
}
```

Bu durumda ilk satır şöyle olur:

```caddyfile
ai-org.online, 38-45-81-29.sslip.io {
```

### 7.4 Dosyanın doğru yazıldığını kontrol edin

Yazım hatası Caddy'nin çalışmasını durdurabilir. Uygulamadan önce kontrol edin:

```bash
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

- Sonunda `Valid configuration` yazıyorsa: Doğru.
- Hata yazıyorsa: Hata mesajında satır numarası olur; `nano` ile o satıra bakın
  (genelde eksik `{` / `}` veya virgül hatasıdır). Çözemezseniz yedeği geri yükleyin:
  `cp /etc/caddy/Caddyfile.yedek-TARİH /etc/caddy/Caddyfile`

İsteğe bağlı: Dosyanın girintilerini düzeltmek için
`caddy fmt --overwrite /etc/caddy/Caddyfile` çalıştırabilirsiniz.

### 7.5 Caddy'yi yeniden yükleyin

```bash
systemctl reload caddy
```

`reload`, Caddy'yi kapatmadan yeni ayarları okutur; siteye bağlı olanlar kesinti yaşamaz.

Durumunu kontrol edin:

```bash
systemctl status caddy --no-pager
```

`Active: active (running)` yazmalı.

### 7.6 Sertifikanın alındığını izleyin

Caddy, yeni isimler için Let's Encrypt'ten sertifika ister. Bu genelde 10-60 saniye sürer.
Kayıtlarını canlı izlemek için:

```bash
journalctl -u caddy -f
```

Aradığınız satırlar şunlara benzer:

```
... "certificate obtained successfully" ... "identifier":"ai-org.online"
... "certificate obtained successfully" ... "identifier":"www.ai-org.online"
```

İzlemeyi bırakmak için `Ctrl + C`.

`error` içeren satırlar görürseniz [12. Sorun giderme](#12-sorun-giderme) bölümüne bakın.

> Linko uygulamasının kendisini (`linko.service`) yeniden başlatmanıza **gerek yok**.
> Uygulama hangi isimle çağrıldığını önemsemez; sadece Caddy'nin kendisine ilettiği
> istekleri cevaplar.

---

## 8. Adım 5 — Güvenlik duvarını kontrol etmek

**Güvenlik duvarı (firewall)**, sunucunun hangi kapılarının (portlarının) dışarıya
açık olduğunu belirler. Let's Encrypt doğrulaması ve ziyaretçiler için **80** ve **443**
açık olmalı.

`sslip.io` adresi zaten HTTPS ile çalıştığı için bu portlar büyük ihtimalle açıktır.
Yine de kontrol edin:

```bash
ufw status
```

- `Status: inactive` → Ubuntu güvenlik duvarı kapalı; ek bir şey yapmanıza gerek yok.
- `Status: active` → Listede `80/tcp`, `443/tcp` ve `22/tcp` (veya `OpenSSH`) için
  `ALLOW` görmelisiniz. Eksikse:

```bash
ufw allow 80/tcp
ufw allow 443/tcp
```

> **Dikkat:** `ufw`'yi etkinleştirecekseniz (`ufw enable`) önce mutlaka
> `ufw allow OpenSSH` çalıştırın. Aksi halde SSH bağlantınız kesilir ve sunucuya
> yalnızca Euronodes panelindeki konsoldan girebilirsiniz.
>
> **8016 numaralı portu asla dışarıya açmayın.** Uygulama bu porttan gelen
> isteklere şifre sormadan güvenir; Caddy'nin şifre korumasını atlamış olursunuz.

Euronodes panelinde ayrıca bir "ağ güvenlik duvarı" ayarı varsa, orada da 80 ve 443'ün
açık olduğundan emin olun.

---

## 9. Adım 6 — Test etmek

### 9.1 Tarayıcıdan

1. Tarayıcıda **gizli pencere** açın (`Ctrl + Shift + N`).
2. `https://ai-org.online` adresine gidin.
3. Kullanıcı adı ve şifre soran bir pencere çıkmalı.
   Kullanıcı adı: `trace`, şifre: `SIFRELER.txt` dosyasındaki şifre.
4. Linko arayüzü açılmalı. Adres çubuğunda **kilit simgesi** olmalı.
5. Kilide tıklayıp sertifika bilgisine bakarsanız, verenin **Let's Encrypt**
   (genelde `R10`, `R11`, `E5` gibi kısa adlar) olduğunu görürsünüz.
6. `https://www.ai-org.online` adresini de deneyin.
7. `http://ai-org.online` (s'siz) yazarsanız, Caddy sizi otomatik olarak
   `https://`'e yönlendirmeli.

### 9.2 Komut satırından

Kendi bilgisayarınızda PowerShell'de (`curl.exe` yazımına dikkat; PowerShell'deki
`curl` farklı bir komuttur):

```powershell
# Sağlık kontrolü — şifre istemez, 200 dönmeli
curl.exe -I https://ai-org.online/healthz

# Ana sayfa — şifresiz 401 (yetkisiz) dönmeli; bu, korumanın çalıştığını gösterir
curl.exe -I https://ai-org.online/
```

Beklenen:

```
HTTP/1.1 200 OK          ← /healthz için
HTTP/1.1 401 Unauthorized ← / için (şifre sorulduğunu gösterir — doğru davranış)
```

Ana sayfa şifresiz **200** dönüyorsa, şifre koruması devre dışı kalmış demektir;
hemen [7.2](#72-mevcut-dosyaya-bakın)'deki `basic_auth` bloğunu kontrol edin.

### 9.3 Mobil cihazdan

Telefonunuzda Wi-Fi'yi kapatıp mobil veriyle `https://ai-org.online` açın.
Mobil operatörler genelde IPv6 kullanır; burada da çalışıyorsa AAAA tarafında
sorun yok demektir.

---

## 10. Sonrasında güncellenmesi gerekenler

Alan adı çalışınca, eski `sslip.io` adresini kullanan yerleri yeni adresle güncelleyin:

- **Tarayıcı yer imleri** ve şifre yöneticisindeki kayıt (`38-45-81-29.sslip.io` →
  `ai-org.online`).
- **API'yi kullanan betikler / araçlar:** `https://38-45-81-29.sslip.io/api/v1/...`
  adreslerini `https://ai-org.online/api/v1/...` yapın. API anahtarları değişmez.
- **`SIFRELER.txt`** içindeki adres notu.
- **Belgeler:** README / SERVICE.md içinde adres geçiyorsa.

**Değiştirmeniz gerekmeyenler:**

- **GitHub otomatik dağıtımı** (`.github/workflows/deploy.yml`): Sunucuya SSH ile
  `DEPLOY_HOST` sırrındaki adres üzerinden bağlanır. Bu IP adresi olarak kalabilir;
  alan adına geçirmek zorunda değilsiniz.
- **`/etc/linko.env`** ve **`linko.service`**: Uygulama `127.0.0.1:8016`'da çalışmaya
  devam eder. `JOBAPP_HOST`'u **değiştirmeyin**.
- **SSH komutu:** `ssh root@38.45.81.29` aynen çalışır. İsterseniz `ssh root@ai-org.online`
  da artık çalışır (ilk seferde yine "Are you sure..." sorusu gelir).

Bir süre her şey sorunsuz çalıştıktan sonra, isterseniz `sslip.io` adresini
Caddyfile'ın ilk satırından silip `systemctl reload caddy` ile kapatabilirsiniz.

---

## 11. Alternatif: Alt alan adı kullanmak (linko.ai-org.online)

İleride `ai-org.online` ana adresinde başka bir şey (tanıtım sitesi, blog vb.)
yayınlamak isteyebilirsiniz. Bu durumda Linko'yu bir **alt alan adına** koymak
daha esnek bir çözümdür:

1. Hostinger DNS'e **A** kaydı ekleyin: Ad `linko`, İçerik `38.45.81.29`.
2. Caddyfile ilk satırına `linko.ai-org.online` ekleyin (`ai-org.online` yerine veya yanına).
3. `caddy validate ...` ve `systemctl reload caddy`.

Alt alan adları için yeni bir şey satın almanız gerekmez; istediğiniz kadar
(`api.ai-org.online`, `panel.ai-org.online`...) oluşturabilirsiniz.

---

## 12. Sorun giderme

### Tarayıcı Hostinger'ın park / "yapım aşamasında" sayfasını gösteriyor

- DNS henüz yayılmamış veya `@` için hâlâ Hostinger IP'li bir A / AAAA kaydı duruyor.
- `nslookup ai-org.online 8.8.8.8` ile kontrol edin ([5.1](#51-windowsta-komutla-kontrol)).
- `ipconfig /flushdns` çalıştırıp gizli pencerede deneyin.
- Hostinger panelinde "Website Builder" / "Hemen başla" ile bir site kurulumu
  başlattıysanız, Hostinger kayıtları geri değiştirmiş olabilir; DNS kayıtlarını tekrar kontrol edin.

### "Bu siteye ulaşılamıyor" / ERR_CONNECTION_REFUSED / zaman aşımı

- Caddy çalışıyor mu? `systemctl status caddy --no-pager`
- Portlar açık mı? [8. bölüm](#8-adım-5--güvenlik-duvarını-kontrol-etmek).
- `https://38-45-81-29.sslip.io` çalışıyor mu? Çalışıyorsa sorun büyük ihtimalle DNS'tedir.

### "Bağlantınız gizli değil" / NET::ERR_CERT_... sertifika hatası

Caddy sertifika alamamış demektir. Kayıtlara bakın:

```bash
journalctl -u caddy --since "30 min ago" --no-pager | grep -i -E "error|ai-org"
```

Sık nedenler:

| Kayıtta görülen | Anlamı | Çözüm |
|---|---|---|
| `NXDOMAIN` / `no valid A records` | DNS henüz yayılmamış veya kayıt yanlış | Adım 1-2'yi kontrol edin, bekleyin |
| `Timeout during connect` / `connection refused` | Let's Encrypt sunucuya 80/443'ten ulaşamıyor | Güvenlik duvarı, AAAA kaydı (yanlış IPv6'ya gidiyor) |
| `CAA record ... prevents issuance` | CAA kaydı Let's Encrypt'e izin vermiyor | [4.6](#46-caa-kayıtlarını-kontrol-etmek) |
| `too many failed authorizations` / `rateLimited` | Çok fazla başarısız deneme yapıldı | DNS'i düzeltin, ardından **1 saat bekleyin**, sonra `systemctl reload caddy` |

DNS düzeldikten sonra Caddy genelde kendiliğinden tekrar dener. Hızlandırmak için
`systemctl reload caddy` yeterlidir.

### Şifre penceresi çıkmıyor, site doğrudan açılıyor

**Bu ciddi bir güvenlik sorunudur.** Caddyfile'daki `basic_auth` bloğu yeni alan adına
uygulanmıyor demektir (ör. yeni adı ayrı bir blok olarak, şifre satırları olmadan eklediniz).
[7.3](#73-dosyayı-düzenleyin)'teki gibi yeni adı **mevcut bloğun ilk satırına**
eklediğinizden emin olun.

### Şifre doğru ama kabul etmiyor

- Kullanıcı adı `trace` (küçük harf).
- Tarayıcı eski hatalı denemeyi hatırlıyor olabilir: gizli pencere deneyin.
- Şifreyi `SIFRELER.txt` veya sunucudaki `/root/linko-ui-credentials`
  dosyasından tekrar kopyalayın (başta/sonda boşluk olmasın).

### 502 Bad Gateway

Caddy çalışıyor ama arkadaki Linko uygulaması cevap vermiyor:

```bash
systemctl status linko --no-pager
journalctl -u linko -n 50 --no-pager
```

Gerekirse `systemctl restart linko`.

### Caddy reload sonrası hiçbir site açılmıyor

Caddyfile'da yazım hatası olabilir. Yedeği geri yükleyin:

```bash
cp /etc/caddy/Caddyfile.yedek-TARİH /etc/caddy/Caddyfile
systemctl reload caddy
```

(`TARİH` yerine `ls /etc/caddy/` ile gördüğünüz yedek dosyasının tarihini yazın.)

---

## 13. Güvenlik ve bakım notları

- **Gizlilik koruması (WHOIS Privacy):** Hostinger panelinde "Domain Sahipliği" kısmında
  adınız, e-postanız ve telefon numaranız görünüyor. **Gizlilik koruması**'nı açın;
  aksi halde bu bilgiler herkese açık WHOIS sorgularında görünebilir ve spam / dolandırıcılık
  aramalarına yol açabilir.
- **Domain kilidi (Transfer Lock):** "Transfer" bölümündeki **Domain kilidi**'nin açık
  olduğundan emin olun. Bu, alan adınızın izniniz olmadan başka bir firmaya taşınmasını engeller.
  **Yetkilendirme kodunu (EPP / Auth code)** kimseyle paylaşmayın.
- **Otomatik yenileme:** Açık kalsın. Ödeme yönteminizin 2027-10-17'den önce geçerli
  olduğundan emin olun. Süresi dolan alan adları kısa sürede başkaları tarafından alınabilir.
- **Hostinger hesabı:** İki adımlı doğrulamayı (2FA) açın. Bu hesaba erişen biri DNS'i
  değiştirip sitenizi başka yere yönlendirebilir.
- **SSL sertifikası:** Caddy sertifikaları (yaklaşık 90 günde bir) **otomatik yeniler**.
  Sizin bir şey yapmanız gerekmez. Hostinger'ın sattığı SSL ürünlerine ihtiyacınız yok.
- **Şifre koruması:** Caddy'deki `basic_auth`'ı kaldırmayın, 8016 portunu dışarı açmayın,
  `JOBAPP_HOST`'u dış arayüze çevirmeyin. Uygulama sunucu içinden gelen isteklere
  anahtarsız güvenir; tek kalkan Caddy'dir.
- **Sunucu ödemesi:** Euronodes VPS'in faturasını takip edin; sunucu kapanırsa alan adı
  çalışsa bile site açılmaz.

---

## 14. Sözlük

| Terim | Kısa açıklama |
|---|---|
| **VPS** | Kiralık sanal sunucu; uygulamamızın çalıştığı bilgisayar. |
| **IP adresi** | Sunucunun internetteki numarası (`38.45.81.29`). |
| **IPv4 / IPv6** | IP adresinin eski kısa (`38.45.81.29`) ve yeni uzun (`2a02:4780::1`) biçimleri. |
| **Alan adı (domain)** | IP'ye verilen akılda kalıcı isim (`ai-org.online`). |
| **Alt alan adı (subdomain)** | Alan adının önüne eklenen isim (`www.`, `linko.`). |
| **Kök alan adı / apex** | Önünde hiçbir şey olmayan hali (`ai-org.online`); DNS'te `@` ile gösterilir. |
| **Kayıt firması (registrar)** | Alan adını satın aldığınız firma (Hostinger). |
| **DNS** | İsimleri IP'lere çeviren dünya çapındaki rehber sistemi. |
| **Ad sunucusu (nameserver)** | Alan adınızın DNS kayıtlarını tutan sunucu. |
| **A / AAAA / CNAME / MX / TXT / CAA** | DNS kayıt türleri; bkz. [1.6](#16-dns-kayıt-türleri). |
| **TTL** | DNS cevabının önbellekte kalma süresi (saniye). |
| **Yayılma (propagation)** | DNS değişikliğinin dünyaya ulaşması için geçen süre. |
| **Port** | Sunucudaki programların "kapı numarası" (80, 443, 22...). |
| **HTTP / HTTPS** | Web'in şifresiz / şifreli iletişim biçimi. |
| **SSL/TLS sertifikası** | Sitenin kimliğini kanıtlayan, HTTPS'i mümkün kılan dijital belge. |
| **Let's Encrypt** | Ücretsiz ve otomatik sertifika veren kuruluş. |
| **Reverse proxy (ters vekil)** | Dışarıdan gelen istekleri karşılayıp içerideki uygulamaya ileten ara program (Caddy). |
| **Caddy** | Bizim kullandığımız reverse proxy; HTTPS'i otomatik yönetir. |
| **Caddyfile** | Caddy'nin ayar dosyası (`/etc/caddy/Caddyfile`). |
| **Basic auth** | Tarayıcının açtığı kullanıcı adı/şifre penceresiyle yapılan basit kimlik doğrulama. |
| **SSH** | Sunucuya güvenli uzaktan bağlantı. |
| **SSH anahtarı** | Şifre yerine kullanılan, bilgisayarınızdaki gizli dosya. |
| **root** | Linux'ta en yetkili kullanıcı. |
| **systemd / systemctl** | Sunucudaki servisleri (Caddy, Linko) başlatan/durduran sistem ve onun komutu. |
| **journalctl** | Servislerin kayıtlarını (log) gösteren komut. |
| **ufw** | Ubuntu'nun basit güvenlik duvarı aracı. |
| **nano** | Sunucuda dosya düzenlemek için basit metin editörü. |
| **sslip.io** | IP adresini isim gibi kullanmaya yarayan ücretsiz hizmet (geçici çözümümüz). |

---

## 15. Hızlı komut listesi

**Kendi bilgisayarınızda (PowerShell):**

```powershell
nslookup ai-org.online 8.8.8.8           # DNS doğru IP'yi gösteriyor mu?
nslookup -type=AAAA ai-org.online 8.8.8.8 # IPv6 kaydı kalmış mı? (kalmamalı)
ipconfig /flushdns                        # Bilgisayarın DNS önbelleğini temizle
ssh root@38.45.81.29                      # Sunucuya bağlan
curl.exe -I https://ai-org.online/healthz # 200 dönmeli
curl.exe -I https://ai-org.online/        # 401 dönmeli (şifre koruması çalışıyor)
```

**Sunucuda (SSH ile bağlandıktan sonra):**

```bash
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.yedek-$(date +%F)   # Yedek al
nano /etc/caddy/Caddyfile                                        # Düzenle
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile # Kontrol et
systemctl reload caddy                                           # Uygula
systemctl status caddy --no-pager                                # Caddy durumu
journalctl -u caddy -f                                           # Caddy kayıtlarını canlı izle
systemctl status linko --no-pager                                # Linko durumu
ufw status                                                       # Güvenlik duvarı
exit                                                             # Sunucudan çık
```
