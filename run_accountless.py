"""Collect multiple title/location searches in a queue into separate frontend-format folders."""

import argparse
import json
import os

from jobapp import config
from jobapp.pipeline import run_scrape


def parse_titles_from_file(filepath: str) -> list[str]:
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Başlık dosyası bulunamadı: {filepath}")
    titles = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                titles.append(line)
    return titles


def main():
    parser = argparse.ArgumentParser(
        description="Toplu başlık ve konum kuyruğu ile hesapsız LinkedIn iş ilanı toplayıcı."
    )
    parser.add_argument(
        "--title",
        action="append",
        default=[],
        help="Arama başlığı (Birden fazla kez kullanılabilir: --title 'AI' --title 'Backend')",
    )
    parser.add_argument(
        "--titles",
        nargs="+",
        default=[],
        help="Birden fazla başlık listesi (Boşlukla veya virgülle ayrılmış: --titles 'AI Engineer' 'Data Scientist')",
    )
    parser.add_argument(
        "--titles-file",
        "--file",
        dest="titles_file",
        default=None,
        help="Her satırında bir başlık bulunan metin dosyası yolu",
    )
    parser.add_argument(
        "--location",
        "--locations",
        dest="locations",
        nargs="+",
        default=[],
        help="Arama konumu (Örn: 'Istanbul, Turkey' veya birden fazla konum)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Çıktı klasörü (Varsayılan: accountless_searches/)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help=f"İstekler arası bekleme süresi saniye (Varsayılan: {config.REQUEST_INTERVAL})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help=f"Hız sınırı/hata durumunda yeniden deneme sayısı (Varsayılan: {config.MAX_RETRIES})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Her bir başlık için toplanacak maksimum ilan sayısı (Örn: 100)",
    )
    mode.add_argument(
        "--unlimited",
        action="store_true",
        help="Her başlık için erişilebilir tüm kamuya açık ilanları topla",
    )
    parser.add_argument("--mode", choices=("incremental", "full"), default="incremental")
    parser.add_argument("--refresh-details", action="store_true", help="Geçerli detay önbelleğini de yenile")
    parser.add_argument("--source-status", action="store_true", help="Ortak kaynak bekleme durumunu göster")
    parser.add_argument("--acknowledge-source", action="store_true", help="Bekleme bittiyse erişim kontrolünü onayla")
    args = parser.parse_args()
    if args.source_status or args.acknowledge_source:
        from jobapp.db import init_db
        from jobapp.transport import Coordinator, SourcePaused
        init_db()
        try:
            state = Coordinator().acknowledge() if args.acknowledge_source else Coordinator().state()
        except SourcePaused as exc:
            print(str(exc), flush=True)
            return 2
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    # Collect and normalize all titles
    raw_titles = []
    if args.title:
        raw_titles.extend(args.title)
    if args.titles:
        for t in args.titles:
            # Handle comma-separated input in a single string: "AI, Backend, Data"
            if "," in t:
                raw_titles.extend(sub.strip() for sub in t.split(",") if sub.strip())
            else:
                raw_titles.append(t.strip())
    if args.titles_file:
        try:
            raw_titles.extend(parse_titles_from_file(args.titles_file))
        except Exception as e:
            parser.error(str(e))

    # Clean and deduplicate while preserving order
    titles = []
    seen = set()
    for t in raw_titles:
        cleaned = t.strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            titles.append(cleaned)

    if not titles:
        parser.error("En az bir arama başlığı belirtilmelidir (--title, --titles veya --titles-file).")

    locations = [loc.strip() for loc in args.locations if loc.strip()]
    if not locations:
        locations = [config.DEFAULT_LOCATION]

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit pozitif bir tam sayı olmalıdır.")

    if args.interval is not None:
        if args.interval < 1.0:
            parser.error("--interval en az 1.0 saniye olmalıdır.")
        config.REQUEST_INTERVAL = args.interval
        from jobapp.scraper.accountless import AccountlessScraper
        AccountlessScraper.REQUEST_INTERVAL = args.interval

    if args.max_retries is not None:
        if args.max_retries < 0:
            parser.error("--max-retries negatif olamaz.")
        config.MAX_RETRIES = args.max_retries

    total_tasks = len(titles) * len(locations)
    target_per_task = f"{args.limit} ilan" if args.limit else "Limitsiz"
    total_target = f"~{len(titles) * args.limit} ilan" if args.limit else "Limitsiz"

    print("\n" + "=" * 64)
    print("  Linko Scrapper Light - Toplu Kuyruk Taraması")
    print("=" * 64)
    print(f"  Planlanan Başlık Sayısı : {len(titles)}")
    for idx, t in enumerate(titles, 1):
        print(f"    {idx:2d}. {t} (Hedef: {target_per_task})")
    print(f"  Konum(lar)              : {', '.join(locations) if any(locations) else 'Tümü / Varsayılan'}")
    print(f"  Toplam Görev            : {total_tasks}")
    print(f"  Toplam Tahmini Hedef    : {total_target}")
    print(f"  Ortak İstek Aralığı     : {max(config.MIN_REQUEST_INTERVAL, config.REQUEST_INTERVAL):.1f}s")
    print(f"  Hata/Soğuma Toleransı   : {config.MAX_RETRIES} tekrar deneme")
    print("=" * 64 + "\n", flush=True)

    failed = False

    def emit(kind, data):
        nonlocal failed
        if kind in ("log", "error"):
            print(data.get("msg", ""), flush=True)
        if kind == "error":
            failed = True

    try:
        stats = run_scrape(
            keywords=titles,
            locations=locations,
            limit=args.limit,
            require_login=False,
            output_dir=args.output_dir,
            emit=emit,
            mode=args.mode,
            refresh_details=args.refresh_details,
        )
        print("\n" + "=" * 64)
        print("  Kuyruk duraklatıldı; aynı süreçten arayüzde devam edebilirsiniz." if stats.get("paused") else "  Kuyruk Tamamlandı!")
        print(f"  Yeni Eklenen: {stats.get('new', 0)} | Güncellenen: {stats.get('updated', 0)} | Atlanan: {stats.get('skipped', 0)}")
        print("=" * 64)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\n[DURDURULDU] Kullanıcı isteği ile durduruldu. Kaydedilen tüm veriler korundu.")
        return 130
    return 2 if stats.get("paused") else 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
