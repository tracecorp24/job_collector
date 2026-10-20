# NextStep canlı hesap işlemleri — 20 Ekim 2026

Kullanıcının açık talebiyle canlı NextStep veritabanında uygulandı.
İşlem zamanı: 19:39:25 UTC / 22:39:25 İstanbul.

## Envanter ve sonuç

| Hesap | Önce | İşlem | Sonra |
| --- | --- | --- | --- |
| trace.corp24@gmail.com | E-postası doğrulanmış, user | Admin rolü verildi | Doğrulanmış admin |
| prodtest-verify@example.com | Doğrulanmamış, boş profil | Silindi | Bulunmuyor |
| testui2026@example.com | Doğrulanmamış, boş profil | Silindi | Bulunmuyor |

Toplam kullanıcı sayısı 3'ten 1'e indi. Eski seed aracının 20 demo kullanıcısı
canlıda yoktu. Silinen iki test hesabında başvuru, kaydedilmiş ilan, CV,
mülakat, AI kullanım kaydı veya açık oturum bulunmuyordu.

Silme yalnızca envanterdeki iki kesin UUID ve e-posta eşleşmesiyle yapıldı;
alan adına göre toplu silme kullanılmadı. Boş profil/doğrulanmamış hesap
koşulları işlem anında yeniden kontrol edildi. Admin ataması ve temizlik
audit_log'a yazıldı. Geçmiş denetim kayıtları korundu; silinen hesaplara ait
profil, doğrulama token'ı ve bildirim tercihleri foreign key kurallarıyla kaldırıldı.

## Yedek ve doğrulama

- İşlem öncesi tutarlı SQLite yedeği alındı; bütünlük kontrolü geçti.
- Sunucudaki yedek: `/var/backups/nextstep/accounts-20261020T193925Z-fb1da920/before.sqlite3`.
- SHA-256: `18fea6af33402b01d86c0550913705bb8fd940f3ae3abdeb73c7ef2aff1a828b`.
- Aynı özel dizinde `inventory-before.json` ve `result.json` bulunur.
  Dizin yalnızca root erişimine açık, dosyalar 0600 izinlidir.
- İşlem tek transaction ile tamamlandı. Foreign key ve quick_check sonucu: ok.
- İkinci bağımsız salt okunur sorgu: 1 kullanıcı, owner rolü admin, demo/test hesap yok.
- Canlı https://nextstep.ai-org.online/healthz: HTTP 200, status ok, db true.

Admin menüsü için açık sayfayı yenileyin; gerekirse çıkış yapıp tekrar giriş yapın.
Bu işlem uygulama kodu veya dağıtım değişikliği gerektirmedi.
