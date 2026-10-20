# Arayüz ve toplama entegrasyonu — 20 Ekim 2026

## Eşzamanlı çalışma ve sahiplik

Kullanıcı başka bir Codex'in de entegrasyon yaptığını bildirdi. Bu çalışma yalnız
`integrate/ui-and-reliable-collection-20261020` dalında,
`.qa/ui-collection-integration` worktree'sinde sürdürülür. Ana çalışma klasöründeki
arayüz dosyaları, index ve mevcut dal değiştirilmez; diğer Codex'in devam eden
değişiklikleri bu worktree'den kopyalanarak ezilmez. Main'e merge veya push yapılmadı.

## Korunan kayıtlar

- Başlangıç: `f3d681977335088a93c4891c3a35d73bfc325a2c`.
- Toplama değişiklikleri: `8873d24619b1f046b3dcfbb5789a82fe97a9ce97`,
  `snapshot/reliable-collection-20261020` dalı; 30 dosya.
- Arayüz anlık kopyası: `72fb05aaf8662f38088fef93ab6844024fde45b3`; üç uygulama
  arayüz dosyası ve bir referans HTML dosyası.
- İki commit'in gerçek merge'i: `db0a4bbbc417fd9298d284f8403b18b40fe781da`.
- İlk anlık kopya ve SHA-256 kayıtları:
  `.qa/ui-collection-snapshot-20261020/manifest.json`.
- Sonraki eşzamanlı `index.html` değişiklikleri (başlıkta Linko adı ve
  quick-filters kapsayıcısı) ayrı anlık kopyadan üç yönlü merge ile alındı.
  Kaynak dosyaya yazılmadı. Son kaynak kaydı aynı klasörde `latest-ui.json`.

## Birlikte çalışması için düzeltilenler

- Filtre kurulumunda `.fields` ile yeni `.filter-body-inner` kapsayıcıları birlikte
  desteklenir. Yetenek filtreleri taşınırken kontroller kaybolmaz.
- Kaldırılmış eski `filter-toggle` yerine yeni mobil düğme kullanılır; filtre
  paneli kapatma, Escape ve masaüstüne dönüşü destekler.
- Eksik analiz durum alanları ve geçmişte tümünü yeniden tarama düğmesi korunur.
- `hidden` niteliği flex/grid ile geçersiz kılınmaz. Sistem menüsü ve mobil alt
  menünün gizleme biçimleri JavaScript ile uyumludur.
- İlan detay paneli Escape ile kapanır; bekleyen detay isteği iptal edilir;
  yeniden açma, geçiş ve kapatma zamanlayıcıları birlikte çalışır.
- Kart/liste seçimi, yeni kart çizim fonksiyonunu yeniden çalıştırır. Geliştirici
  kimlik düğmeleri iki görünümde de korunur.
- `components.css`, JavaScript'in ürettiği filtre, kuyruk, kayıt, mobil menü ve
  Panel grafiklerinin stillerini yeni açık/koyu tema değişkenleriyle tamamlar.
  Grafik geometrisi başlangıç sürümünden korunmuştur.
- Kaynak bekleme rozeti küçük ekranda başlığı taşırmaz; bekleme şeridi bilgi verir.
- Test sunucusunun portu `LINKO_UI_PORT` ile ayrılabilir; bu koşu 8037 kullandı.

## Doğrulama

Python: **248/248 geçti**, 604,524 saniye. Kaynak HTTP ve sağlayıcı çağrıları
testlerde taklit edilir; geçici test veritabanları kullanılır.
Son HTML değişikliklerinden sonra `test_light` ayrıca **11/11 geçti** (206,247 saniye).
Kayıt: ana çalışma klasöründe `.qa/ui-collection-unit.log`.
İlk sandbox koşusu geçici SQLite dosyalarına erişemedi; izinli koşu geçti.
Sonuç yazdırıcısının Windows konsol kodlaması hatası testlerin `OK` sonucundan
sonra oluştu; yazdırıcı sonraki koşular için UTF-8 olarak düzeltildi.

Tarayıcı koşusu tamamen geçti; JavaScript hatası yok. Kabul kaydı: bu worktree
içinde `.qa/ui-smoke-result.json`.
İçindeki `ok` ve `browserErrors` alanları son başarılı koşuyu gösterir.
`tests/ui_smoke.cjs`; filtreler, Panel, manuel seçili alan onarımı, üç kuyruk
katmanı, geçmiş/provenans, silme/geri alma, kalıcı arama taslağı, mobil gezinme,
bekleme şeridi, iş alarmları ve geliştirici modunu uçtan uca kontrol eder.
Ekran görüntüleri aynı `.qa/` klasöründedir.

## Sonraki ajan

Önce mevcut worktree/dal listesini ve bu dalın son commit'ini kontrol et. Diğer
Codex'in sonradan kaydettiği arayüz commit'lerini temiz, ayrı bir worktree'de
normal Git merge ile al; eski anlık kopyayı ana klasöre geri yükleme. Bu dalın
toplama ve arayüz uyum düzeltmelerini birlikte koru. Testler geçtikten sonra
üretime geçiş ve 24–72 saat doğal iş yükü gözlemi ayrı aşamadır.
