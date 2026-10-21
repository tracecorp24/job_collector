# Arama dili ve konum düzeltmesi — 21 Ekim 2026

NextStep incelemesinde kaynakta iki eksik bulundu: kullanıcı sorgusu hedef ülke
diline çevrilmiyordu; Ümraniye gibi yerel ilçeler ülkesiz kalabiliyordu.

- Kalıcı görev işçisi aramadan önce Groq ile hedef konumun yerel iş piyasası
  dilindeki sorguyu hazırlar. Teknik adlar ve görev kapsamı korunur.
- Kullanıcının özgün sorgusu görevde kalır; kullanılan sorgu, dil ve durum
  `stats.search_plan` içinde denetlenebilir. Aynı görev devam ederken çeviri
  yenilenmez. Önceden başlamış eski görevler özgün sorguyla devam eder.
- Henüz sayfalama başlamamış görev düzenlenirse eski çeviri yeniden kullanılmaz.
- Anahtar, kota veya servis yoksa özgün sorgu korunur. Çeviri ağı için istek
  başına zaman aşımı 8 saniyedir; normal Groq sınıflandırma varsayılanı değişmez.
- Kaynak konum normalizasyonu 81 il ve büyük şehir ilçelerini tanır. Açık yabancı
  ülke varsa yerel eşadlı ilçe bu ülkeyi ezmez. Bilinmeyen şehre İstanbul atanmaz.
- Dil verim raporu, kullanıcı giriş dilini değil gerçekten kullanılan sorgu
  dilini gösterir. Özgün sorgu plan içinde korunur.

Regresyonlar: `tests/test_query_translation.py`,
`tests/test_collection_resume.py` içindeki yerelleştirilmiş sorguyla devam testi,
mevcut `tests/test_locations.py`. NextStep karşılığı:
`tracecorp24/next_step_v2` reposunda `docs/SISTEM_DENETIMI_2026-10-21.md`.

Yalıtılmış çalışma ağacında 4 sorgu/çeviri testi, 4 mevcut konum testi ve 1 gerçek
işçi duraklat/devam entegrasyonu geçti: **9/9**. Temel Ruff kontrolleri temiz.

Çeviri kalitesi modelin dil desteğine bağlıdır; tüm dillerde kusursuz anlama
garantisi verilmez. Doğrudan `run_accountless.py` gibi kalıcı görev işçisini
kullanmayan eski komut satırı yolları özgün sorguyla çalışır.
