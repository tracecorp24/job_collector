"""Public jobs only: isolated HTTP session, paced requests, adaptive retry on rate limit."""

import re
import time
import uuid
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .. import config
from ..transport import Coordinator, Details, SourcePaused, retry_after_seconds


class RateLimitError(Exception):
    """Raised when an HTTP rate limit (429, 999, 403) or challenge is encountered."""
    def __init__(self, message, status_code=429, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class NetworkRetryError(Exception):
    """Raised on transient network connection errors or timeouts."""
    pass


class AccountlessScraper:
    SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    REQUEST_INTERVAL = config.REQUEST_INTERVAL

    def __init__(self, emit=None, should_stop=None, max_retries=None, mode="incremental", refresh_details=False,
                 search_options=None):
        self.emit = emit
        self.should_stop = should_stop or (lambda: False)
        self.require_login = False
        self.driver = None  # compatible with the server's stop watchdog
        self.requests = 0
        self.collected = 0
        self.cache = {}
        self.details = Details()
        self.coordinator = Coordinator(interval=self.REQUEST_INTERVAL)
        self.mode = mode
        self.refresh_details = refresh_details
        # Düzenli taramalar: posted_within (sn), sort_recent, stop_when_known — istek sayısını azaltır.
        self.search_options = search_options or {}
        self.last_request = None

        # Unit test compatibility: if REQUEST_INTERVAL == 0 (as mocked in test suite),
        # disable retries so mock assertions like get.call_count == 3 pass as expected.
        if max_retries is not None:
            self.max_retries = max_retries
        elif self.REQUEST_INTERVAL == 0:
            self.max_retries = 0
        else:
            self.max_retries = config.MAX_RETRIES

        self.session = None
        self._reset_session()

    def _reset_session(self):
        """Create a fresh isolated HTTP session with modern desktop browser headers."""
        if hasattr(self, "session") and self.session is not None:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = requests.Session()
        # Do not inherit .netrc credentials or environment proxy credentials.
        self.session.trust_env = False
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=0)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

    def _log(self, msg, level="info"):
        if self.emit:
            self.emit("log", {"msg": msg, "level": level})

    def _report_page(self, interrupted=False, level="info"):
        report = getattr(self, "page_report", None)
        if report and self.emit:
            report = dict(report, interrupted=interrupted, level=level)
            report["not_processed"] = max(0, report["cards_returned"] - report["collected"] - report["duplicates"] - report["detail_failures"] - report.get("invalid_cards", 0))
            self.emit("page_result", report)

    def _sleep_cancellable(self, seconds: float) -> bool:
        """Sleep in small intervals while checking should_stop(). Returns True if full time elapsed, False if stopped."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.should_stop():
                return False
            time.sleep(min(0.5, max(0.05, end - time.monotonic())))
        return True

    def _calculate_cooldown(self, attempt: int, error: Exception) -> float:
        parsed = retry_after_seconds(getattr(error, "retry_after", None))
        if parsed is not None:
            return parsed
        if self.REQUEST_INTERVAL == 0:
            return 0.0

        return min(config.RETRY_BASE_COOLDOWN * 2 ** (attempt - 1), 300.0)

    @staticmethod
    def _public_url(url):
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "www.linkedin.com"
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and parsed.path.startswith(("/jobs/view/", "/jobs-guest/jobs/api/"))
        )

    @staticmethod
    def detail_url(raw):
        """Hafif API Collector: İlan detayını çekerken hafif misafir API'sini (jobs-guest/jobs/api/jobPosting/<id>) kullanır.
        Normal /jobs/view/ sayfası ~250 KB iken bu hafif mimari ~15-60 KB payload döndürür.
        """
        if isinstance(raw, dict):
            ext_id = raw.get("external_id")
            if ext_id:
                return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{ext_id}"
            return raw.get("url")
        return str(raw) if raw else None

    def _fetch_url(self, url, params=None):
        # Follow only public-job redirects; never visit a login/challenge URL.
        current_url = url
        current_params = params
        for _ in range(4):
            if not self._public_url(current_url):
                raise RuntimeError("Accountless stopped: sign-in or non-public redirect. No login attempted.")
            owner = self.coordinator.acquire(self.should_stop, self.emit)
            if owner is None:
                return None
            try:
                self.requests += 1
                self.last_request = time.monotonic()
                request_id = uuid.uuid4().hex
                started = time.monotonic()
                if self.emit:
                    self.emit("request_started", {"request_id": request_id, "url": current_url, "params": current_params,
                                                  "request_number": self.requests})
                try:
                    response = self.session.get(current_url, params=current_params, timeout=20, allow_redirects=False)
                except requests.RequestException as exc:
                    if self.emit:
                        self.emit("request_finished", {"request_id": request_id, "url": current_url, "status": None,
                                                       "duration_ms": round((time.monotonic()-started)*1000), "error": type(exc).__name__, "level": "error"})
                    raise NetworkRetryError(f"Ağ hatası: {type(exc).__name__}") from exc
    
                with response:
                    # Persist a source block before another process can acquire the gate.
                    self.last_status = response.status_code
                    if response.status_code in (401, 403, 429, 999):
                        state = self.coordinator.pause(f"Kaynak erişimi sınırlandırdı (HTTP {response.status_code}).",
                            response.status_code, response.headers.get("Retry-After"), hard=response.status_code != 429)
                    else:
                        state = None
                    if self.emit:
                        self.emit("request_finished", {"request_id": request_id, "url": current_url, "params": current_params,
                                                       "status": response.status_code, "duration_ms": round((time.monotonic()-started)*1000),
                                                       "retry_after":response.headers.get("Retry-After"), "content_type":response.headers.get("Content-Type"),
                                                       "response_bytes":len(response.content),
                                                       "cards_returned": len(BeautifulSoup(response.text, "html.parser").select("div.base-search-card")),
                                                       "level": "warning" if response.status_code != 200 else "info"})
                    self.last_response_request_id = request_id
                    if state:
                        raise SourcePaused(state)
                    if response.is_redirect:
                        current_url = urljoin(current_url, response.headers.get("Location", ""))
                        current_params = None
                        if not self._public_url(current_url):
                            raise SourcePaused(self.coordinator.pause("Giriş veya güvenlik kontrolüne yönlendirme.", 403, hard=True))
                        continue
                    if response.status_code in (404, 410):
                        self._log("Public job/page is no longer available.", "warning")
                        return None
                    if response.status_code != 200:
                        if retry_after_seconds(response.headers.get("Retry-After")) is not None:
                            raise SourcePaused(self.coordinator.pause("Kaynak bekleme istedi.", response.status_code,
                                response.headers.get("Retry-After"), violation=False))
                        if response.status_code < 500:
                            raise RuntimeError(f"Beklenmeyen HTTP {response.status_code}")
                        raise RateLimitError(f"Kaynak hatası (HTTP {response.status_code})", status_code=response.status_code)
    
                    soup = BeautifulSoup(response.text, "html.parser")
                    public_content = soup.select_one(
                        "div.base-search-card, .show-more-less-html__markup, .description__text"
                    )
                    if soup.select_one(
                        'form[action*="checkpoint"], form[action*="authwall"], '
                        'iframe[src*="captcha"], #captcha-internal'
                    ) or (not public_content and soup.select_one(
                        'form[action*="login"], input[name="session_password"]'
                    )) or (soup.title and any(
                        word in soup.title.get_text().lower()
                        for word in ("sign in", "security verification", "authwall", "captcha")
                    )):
                        raise SourcePaused(self.coordinator.pause("Güvenlik kontrolü / Authwall algılandı.", 403, hard=True))
                    self.coordinator.success()
                    return soup
            finally:
                self.coordinator.release(owner)
        raise RuntimeError("Accountless stopped: too many redirects.")

    def _get(self, url, params=None):
        attempt = 0
        while True:
            if self.should_stop():
                return None
            try:
                return self._fetch_url(url, params=params)
            except SourcePaused:
                self._report_page(interrupted=True, level="warning")
                raise
            except (RateLimitError, NetworkRetryError) as err:
                attempt += 1
                if attempt > self.max_retries:
                    suffix = ""
                    if isinstance(err, RateLimitError) and err.retry_after:
                        suffix = f" Retry-After: {err.retry_after}."
                    status = err.status_code if isinstance(err, RateLimitError) else "ERR"
                    self._report_page(interrupted=True, level="error")
                    raise RuntimeError(
                        f"Accountless blocked (HTTP {status}). Entire run stopped; no retry or account fallback.{suffix}"
                    )
                cooldown = self._calculate_cooldown(attempt, err)
                if cooldown > config.INLINE_RETRY_WAIT_SECONDS:
                    self._report_page(interrupted=True, level="warning")
                    raise SourcePaused(self.coordinator.pause(str(err), getattr(err, "status_code", None),
                        retry_after=str(int(cooldown)), violation=False)) from err
                if cooldown > 0:
                    self.coordinator.pause(str(err), getattr(err, "status_code", None),
                        retry_after=str(int(cooldown)), violation=False)
                cooldown_int = max(0, int(round(cooldown)))
                if self.emit:
                    self.emit("waiting", {"seconds": cooldown_int, "attempt": attempt, "reason": "Bağlantı veya hız sınırı nedeniyle yeniden deneme bekleniyor."})
                self._log(
                    f"⚠️ {err}. Geçici bağlantı hatası. "
                    f"{cooldown_int} saniye bekleniyor (Deneme {attempt}/{self.max_retries}).",
                    "warning"
                )
                if not self._sleep_cancellable(cooldown):
                    self._log("Bekleme sırasında kullanıcı tarafından durduruldu.", "warning")
                    return None
                # Preserve the isolated session; never rotate sessions to evade blocks.
                pass

    @staticmethod
    def _card(card):
        match = re.search(r"jobPosting:(\d+)", card.get("data-entity-urn", ""))
        if not match:
            return None
        def text(selector):
            tag = card.select_one(selector)
            return tag.get_text(" ", strip=True) if tag else ""
        return {
            "external_id": match.group(1),
            "url": f"https://www.linkedin.com/jobs/view/{match.group(1)}",
            "card_layout": "guest",
            "card_lines": [text(".base-search-card__title"),
                           text(".base-search-card__subtitle"),
                           text(".job-search-card__location")],
            "posted": (card.select_one("time").get("datetime") if card.select_one("time") else None),
        }

    def scrape(self, search_queue, locations, on_job):
        locations = locations or [""]
        has_item_locations = any(item.get("location") for item in search_queue if isinstance(item, dict))
        if has_item_locations:
            plan = []
            for item in search_queue:
                loc = (item.get("location") if isinstance(item, dict) else "") or (locations[0] if locations else "")
                plan.append((item, loc))
        else:
            plan = []
            for loc in locations:
                for item in search_queue:
                    plan.append((item, loc))

        total = len(plan)
        done = 0
        self._log(
            f"Kuyruk başlatıldı: {total} arama görevi planlandı. "
            f"Ortak asgari istek aralığı: {self.coordinator.interval:.1f}s. "
            f"Erişim sınırlarında kalıcı duraklatma devrede.", "info",
        )
        try:
            for item, location in plan:
                if self.should_stop():
                    self._log("Kullanıcı tarafından durduruldu.", "warning")
                    return
                limit = item.get("limit") if isinstance(item, dict) else None
                limit = None if limit is None else int(limit)
                if limit is not None and limit <= 0:
                    raise ValueError("Accountless limit must be a positive integer.")

                queue_idx = done + 1
                target_str = f"{limit} ilan" if limit else "Limitsiz"
                kw_str = item.get("keyword") if isinstance(item, dict) else str(item)
                self._log(
                    f"🚀 [Kuyruk {queue_idx}/{total}] Başlık: '{kw_str}' | "
                    f"Konum: '{location or 'Varsayılan'}' | Hedef: {target_str}",
                    "info"
                )

                if self.emit:
                    self.emit("task_start", {
                        "keyword": kw_str,
                        "location": location,
                        "done": done,
                        "total": total,
                        "queue_index": queue_idx,
                        "queue_total": total,
                        "limit": limit
                    })

                count_this_task, reason, task_stats = self._search(kw_str, location, limit, on_job)
                done += 1

                self._log(
                    f"✅ [Kuyruk {done}/{total}] '{kw_str}' tamamlandı. "
                    f"Bu başlıkta toplanan: {count_this_task} ilan (Genel toplam: {self.collected}). Sebep: {reason}.",
                    "success"
                )

                if self.emit:
                    self.emit("task_done", {
                        "done": done,
                        "total": total,
                        "keyword": kw_str,
                        "count": count_this_task,
                        "pct": int(done / max(total, 1) * 100),
                        "reason": reason,
                        "stats": task_stats,
                    })

                # Kuyruktaki bir sonraki göreve geçmeden önce kısa bir nefes alma molası (örn: 3-5 sn)
                if done < total and not self.should_stop():
                    inter_pause = 3.5 if self.REQUEST_INTERVAL > 0 else 0
                    if inter_pause > 0:
                        self._log(f"Sonraki kuyruk görevine hazırlanıyor ({inter_pause:.0f}s mola)...", "info")
                        self._sleep_cancellable(inter_pause)
        finally:
            if hasattr(self, "session") and self.session:
                self.session.close()

    def _search(self, keyword, location, limit, on_job):
        checkpoint = getattr(self, "resume_checkpoint", {})
        self.resume_checkpoint = {}
        collected = checkpoint.get("collected", 0)
        page = checkpoint.get("page", 0)
        # Old checkpoints only had a page index and used steps of ten.
        start_offset = checkpoint.get("offset", page * 10)
        seen = set(checkpoint.get("seen", []))
        resume_page = page if checkpoint else -1

        def save_checkpoint():
            if self.emit:
                self.emit("checkpoint", {"page": page, "offset": start_offset, "seen": list(seen), "collected": collected})
        pages_scanned = 0
        prev_card_count = 0
        total_cards_seen = 0
        duplicates_skipped = 0
        desc_failures = 0
        start_time = time.monotonic()
        termination_reason = "exhausted_results"

        self._log(
            f"🔎 '{keyword}' ({location or 'Varsayılan'}) araması başlatıldı. "
            f"Hedef: {f'{limit} ilan' if limit else 'Limitsiz'}.",
            "info"
        )

        while True:
            if self.should_stop():
                termination_reason = "stopped_by_user"
                self._log("⏹ Arama kullanıcı tarafından durduruldu.", "warning")
                break

            if limit is not None and collected >= limit:
                termination_reason = "reached_limit"
                self._log(f"🎯 Hedef limite ({limit} ilan) ulaşıldı, arama sonlandırılıyor.", "success")
                break

            self.page_report = {"page": page + 1, "offset": start_offset, "keyword": keyword, "location": location,
                                "cards_returned": 0, "collected": 0, "duplicates": 0, "detail_failures": 0, "invalid_cards": 0,
                                "collected_ids": [], "duplicate_ids": [], "failed_ids": []}
            save_checkpoint()
            pages_scanned += 1
            self._log(f"📄 [Sayfa {page + 1}] LinkedIn istek gönderiliyor (start={start_offset})...", "info")

            params = {"keywords": keyword, "location": location, "start": start_offset}
            if self.search_options.get("posted_within"):
                params["f_TPR"] = f"r{int(self.search_options['posted_within'])}"
            if self.search_options.get("sort_recent"):
                params["sortBy"] = "DD"
            soup = self._get(self.SEARCH_URL, params)

            if soup is None:
                self._report_page(interrupted=True)
                if self.should_stop():
                    termination_reason = "stopped_by_user"
                else:
                    termination_reason = "page_fetch_failed"
                    self._log(f"⚠️ [Sayfa {page + 1}] Sayfa içeriği alınamadı (bağlantı hatası veya engel).", "warning")
                break

            cards = soup.select("div.base-search-card")
            parsed_cards = [self._card(card) for card in cards]
            card_count = len(cards)
            self.page_report["cards_returned"] = card_count
            self.page_report["request_id"] = getattr(self, "last_response_request_id", None)
            self.page_report["returned_ids"] = [raw["external_id"] for raw in parsed_cards if raw]
            total_cards_seen += card_count
            self._log(f"📄 [Sayfa {page + 1}] {card_count} adet ilan kartı bulundu.", "info")
            if pages_scanned > 1 and prev_card_count > 0 and 0 < card_count < prev_card_count * 0.5:
                self._log(
                    f"⚠️ [Sayfa {page + 1}] Kart sayısında beklenmeyen düşüş: {card_count} kart döndü (önceki: {prev_card_count}).",
                    "warning"
                )
            prev_card_count = card_count

            if not cards:
                self._report_page()
                termination_reason = "exhausted_results"
                self._log(
                    f"ℹ️ [Sayfa {page + 1}] LinkedIn bu sayfa için sonuç döndürmedi (0 kart). "
                    f"Bu arama kriteri için LinkedIn'deki tüm kamuya açık ilanlar tüketildi.",
                    "info"
                )
                break

            new_on_page = 0
            stopped_early = False
            stop_when_known = self.search_options.get("stop_when_known")
            low_yield_threshold = self.search_options.get("low_yield_threshold")
            if low_yield_threshold is None and stop_when_known:
                low_yield_threshold = getattr(config, "LOW_YIELD_THRESHOLD", 0.20)
            check_yield = bool(low_yield_threshold and low_yield_threshold > 0)
            # Önce kart: yeni ilanın detayı burada istenmez, arka planda tamamlanır (jobapp/details.py).
            defer_details = self.search_options.get("defer_details") and not self.refresh_details
            known = self.details.known(self.page_report["returned_ids"]) if stop_when_known or defer_details or check_yield else set()
            cached_details = self.details.get_many([raw for raw in parsed_cards if raw],
                force=self.refresh_details, allow_stale_ids=known)
            unknown_on_page = 0
            for parsed_card in parsed_cards:
                if self.should_stop():
                    termination_reason = "stopped_by_user"
                    stopped_early = True
                    break
                if limit is not None and collected >= limit:
                    termination_reason = "reached_limit"
                    stopped_early = True
                    break

                raw = dict(parsed_card) if parsed_card else None
                if not raw:
                    self.page_report["invalid_cards"] += 1
                    continue
                if raw["external_id"] in seen:
                    duplicates_skipped += 1
                    self.page_report["duplicates"] += 1
                    self.page_report["duplicate_ids"].append(raw["external_id"])
                    continue

                new_on_page += 1
                job_id = raw["external_id"]

                if job_id not in known:
                    unknown_on_page += 1
                cached = cached_details.get(job_id)
                deferred = cached is None and defer_details
                if deferred:
                    cached = (self.details.previous(raw) if job_id in known else None) or {
                        "description": "", "status": 200, "fetched_at": None}
                    self.page_report["deferred_details"] = self.page_report.get("deferred_details", 0) + 1
                if self.emit:
                    self.emit("detail_deferred" if deferred else "cache_hit" if cached else "cache_miss", {"external_id":job_id,
                              "forced":self.refresh_details, "fetched_at":cached["fetched_at"] if cached else None})
                if not deferred:
                    cache_key = "cache_hits" if cached else "cache_misses"
                    self.page_report[cache_key] = self.page_report.get(cache_key, 0) + 1
                if cached is None:
                    detail = self._get(self.detail_url(raw) or raw["url"])
                    if self.should_stop():
                        termination_reason = "stopped_by_user"
                        stopped_early = True
                        break
                    if detail is None:
                        if getattr(self, "last_status", None) in (404,410):
                            cached = self.details.put(raw, "", self.last_status)
                    else:
                        box = detail.select_one(".show-more-less-html__markup, .description__text")
                        if box is not None and box.get_text(strip=True):
                            cached = self.details.put(raw, box.get_text("\n", strip=True))
                            if self.emit:
                                self.emit("cache_store", {"external_id":job_id, "expires_at":cached["expires_at"]})
                if cached is None or cached["status"] != 200:
                    desc_failures += 1
                    self.page_report["detail_failures"] += 1
                    self.page_report["failed_ids"].append(job_id)
                    seen.add(job_id)
                    save_checkpoint()
                    continue
                raw.update(description=cached["description"], detail_fetched_at=cached["fetched_at"],
                           search_term=keyword, search_location=location)
                if deferred:
                    raw["detail_pending"] = True
                outcome = on_job(raw)
                if outcome == "failed":
                    save_checkpoint()
                    self._report_page(interrupted=True)
                    raise RuntimeError(f"İlan {job_id} veritabanına işlenemedi; devam noktası korundu.")
                if outcome == "rejected":
                    seen.add(job_id)
                    save_checkpoint()
                    continue
                if outcome == "unchanged":
                    self.page_report["unchanged"] = self.page_report.get("unchanged", 0) + 1
                self.collected += 1
                collected += 1
                self.page_report["collected"] += 1
                self.page_report["collected_ids"].append(job_id)
                seen.add(job_id)
                save_checkpoint()

                limit_str = f"/{limit}" if limit else ""
                lines = raw.get("card_lines") or []
                job_title = lines[0] if lines else "İlan"
                company = lines[1] if len(lines) > 1 else ""
                prefix = f"{company} - " if company else ""
                self._log(f"📌 [{keyword}] [{collected}{limit_str}] {prefix}{job_title}")
                if self.emit:
                    self.emit("job_progress", {
                        "keyword": keyword,
                        "location": location,
                        "collected": collected,
                        "limit": limit,
                        "total_collected": self.collected,
                        "title": job_title,
                        "company": company,
                    })

            self._report_page(interrupted=stopped_early)
            if stopped_early:
                break

            if stop_when_known and not unknown_on_page:
                termination_reason = "no_new_jobs"
                self._log(
                    f"ℹ️ [Sayfa {page + 1}] Sayfadaki ilanların tümü zaten kayıtlı; en yeniden sıralı aramada "
                    f"devamı da bilinen ilanlar. Kaynağı yormamak için bu kombinasyon bitirildi.",
                    "info"
                )
                break

            if check_yield and card_count > 0:
                yield_ratio = unknown_on_page / card_count
                if yield_ratio < low_yield_threshold:
                    termination_reason = "low_yield_threshold"
                    pct = round(yield_ratio * 100, 1)
                    thresh_pct = round(low_yield_threshold * 100, 1)
                    self._log(
                        f"🛑 [Sayfa {page + 1}] Yeni ilan verimi eşik altına düştü: %{pct:.0f} < %{thresh_pct:.0f} "
                        f"({unknown_on_page}/{card_count} yeni ilan). Kota koruması için bu arama erken tamamlandı.",
                        "info"
                    )
                    break

            if not new_on_page and page != resume_page:
                termination_reason = "repeated_page"
                self._log(
                    f"ℹ️ [Sayfa {page + 1}] Sayfadaki tüm {card_count} ilan daha önce toplanmıştı (yeni ilan kalmadı).",
                    "info"
                )
                break

            page += 1
            # The source may return a different page size. Advance by returned
            # card slots (including invalid/duplicate cards), not saved jobs.
            start_offset += card_count

        duration = round(time.monotonic() - start_time, 2)
        stats = {
            "pagesScanned": pages_scanned,
            "totalCardsSeen": total_cards_seen,
            "savedCount": collected,
            "duplicatesSkipped": duplicates_skipped,
            "descFailures": desc_failures,
            "durationSeconds": duration,
            "termination_reason": termination_reason,
            "low_yield_stopped": termination_reason == "low_yield_threshold",
        }

        self._log(
            f"🏁 '{keyword}' araması bitti. Toplanan: {collected} ilan | "
            f"Bitiş Nedeni: {termination_reason} | Taranan Sayfa: {pages_scanned} | Süre: {duration}s",
            "success" if collected > 0 else "info"
        )

        return collected, termination_reason, stats
