"""
PB Tech "Hot Deals" and "Clearance" scraper  ->  cat.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE = "https://www.pbtech.co.nz"
TARGET_URLS = [
    f"{BASE}/hot-deals/shop-all",
    f"{BASE}/promotions/clearance"
]
TOGGLE_RECORDS_URL = f"{BASE}/code/toggle_records_pdo.php"
TOGGLE_GST_URL = f"{BASE}/code/toggle_gst_pdo.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

AJAX_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE,
    "Accept": "*/*",
}

CSV_FIELDS = [
    "Part Number", "Name", "Original Price", "Discounted Price", "% Off", "Promo Code",
]

PRICE_RE = re.compile(r"\d[\d,]*\.?\d*")
PROMO_RE = re.compile(r"promo\s*code[:\s]*([A-Z0-9][A-Z0-9._-]+)", re.IGNORECASE)
TOTAL_RE = re.compile(r"([\d,]{2,})\s+products", re.IGNORECASE)

DEFAULT_PAGE_SIZE = 20


def clean_text(node) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def parse_price(text: str) -> float | None:
    if not text:
        return None
    m = PRICE_RE.search(text.replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def extract_part_number(card) -> str | None:
    node = card.select_one("[data-product-code]")
    if node and node.get("data-product-code", "").strip():
        return node["data-product-code"].strip()
    node = card.select_one('form[name="buy_form"] input[name="product"]')
    if node and node.get("value", "").strip():
        return node["value"].strip()
    node = card.select_one(".product-attr-table .text-orange") or card.select_one(".text-orange")
    return clean_text(node) or None


def extract_name(card) -> str | None:
    a = card.select_one("a.js-product-link[title]")
    if a and a.get("title", "").strip():
        return a["title"].strip()
    parts = [clean_text(h) for h in card.select(".product-title-holder .np_title")]
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip() or None


def extract_promo_code(card) -> str | None:
    text = clean_text(card.select_one(".ginc .hide-savings-for"))
    if not text:
        return None
    m = PROMO_RE.search(text)
    return m.group(1).strip().upper() if m else None


def extract_prices(card) -> tuple[float | None, float | None]:
    promo = parse_price(clean_text(card.select_one(".item-price-label .ginc .fw-semibold")))
    full = parse_price(clean_text(card.select_one(".item-price-amount .ginc .full-price")))

    if full is None:
        gd = clean_text(card.select_one(".item-price-amount .ginc .price-dollar"))
        gc = clean_text(card.select_one(".item-price-amount .ginc .price-cents"))
        if gd:
            full = parse_price(gd + gc)
    if promo is None:
        promo = parse_price(clean_text(card.select_one(".ginc .fw-semibold")))

    if full is None and promo is not None:
        return promo, None
    if promo is None:
        return full, None
    if promo > full:
        promo, full = full, promo
    if promo == full:
        return full, None
    return full, promo


def calc_percent_off(original: float | None, discounted: float | None) -> float | None:
    if original in (None, 0) or discounted is None or discounted >= original:
        return None
    return round(((original - discounted) / original) * 100, 2)


def parse_page(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for card in soup.select(".js-product-card"):
        original, discounted = extract_prices(card)
        rows.append({
            "Part Number": extract_part_number(card),
            "Name": extract_name(card),
            "Original Price": original,
            "Discounted Price": discounted,
            "% Off": calc_percent_off(original, discounted),
            "Promo Code": extract_promo_code(card),
        })
    return rows


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def set_records(sess, recnum: int, referer: str) -> None:
    headers = AJAX_HEADERS.copy()
    headers["Referer"] = referer
    try:
        sess.post(TOGGLE_RECORDS_URL, data={"recnum": str(recnum)},
                  headers=headers, timeout=30)
    except requests.RequestException as exc:
        print(f"[warn] recnum POST failed: {exc}", file=sys.stderr)


def gst_is_inclusive(html: str) -> bool | None:
    soup = BeautifulSoup(html, "lxml")
    card = soup.select_one(".js-product-card")
    if card is None:
        return None
    gex, ginc = card.select_one(".gex"), card.select_one(".ginc")
    if gex is None or ginc is None:
        return None
    gex_hidden = "d-none" in (gex.get("class") or [])
    ginc_hidden = "d-none" in (ginc.get("class") or [])
    if gex_hidden and not ginc_hidden:
        return True
    if ginc_hidden and not gex_hidden:
        return False
    return None


def ensure_gst(sess, html: str, referer: str) -> None:
    state = gst_is_inclusive(html)
    if state is True:
        print("[info] GST-inclusive pricing ON")
        return
    if state is None:
        print("[warn] could not read GST state - leaving it alone", file=sys.stderr)
        return
    print("[info] GST was OFF - toggling")
    headers = AJAX_HEADERS.copy()
    headers["Referer"] = referer
    sess.post(TOGGLE_GST_URL, data={}, headers=headers, timeout=30)
    if gst_is_inclusive(fetch(sess, referer)) is not True:
        print("[warn] toggle did not take - prices may be EX-GST", file=sys.stderr)


def fetch(sess, url: str, referer: str | None = None) -> str:
    headers = {"Referer": referer} if referer else None
    r = sess.get(url, headers=headers, timeout=120)
    r.raise_for_status()
    return r.text


STRATEGIES = [
    ("pg + repost",          "{base}?pg={page}",              True,  False, True),
    ("pg + repost + bare",   "{base}?pg={page}",              True,  True,  True),
    ("pg plain",             "{base}?pg={page}",              False, False, False),
    ("recnum first in qs",   "{base}?recnum={rec}&pg={page}", True,  False, True),
    ("pg + sortGroupForm",   "{base}?pg={page}#sortGroupForm", True, False, True),
]


def build_url(tmpl: str, base_url: str, page: int, recnum: int) -> str:
    return tmpl.format(base=base_url, page=page, rec=recnum)


def probe_pagination(sess, base_url: str, recnum: int, page1_parts: set[str]):
    print("\n[probe] testing how to reach page 2 at %d/page ..." % recnum)
    small_fallback = None

    for strat in STRATEGIES:
        name, tmpl, repost, bare_first, send_ref = strat
        try:
            if repost:
                set_records(sess, recnum, base_url)
            if bare_first:
                fetch(sess, base_url)
            html = fetch(sess, build_url(tmpl, base_url, 2, recnum),
                         referer=base_url if send_ref else None)
        except requests.RequestException as exc:
            print(f"[probe]   {name:22s} -> request failed ({exc})")
            continue

        rows = parse_page(html)
        parts = {r["Part Number"] for r in rows if r["Part Number"]}
        fresh = len(parts - page1_parts)
        print(f"[probe]   {name:22s} -> {len(rows):4d} cards, {fresh:4d} new")

        if fresh == 0:
            continue                      
        if len(rows) > DEFAULT_PAGE_SIZE:
            print(f"[probe] using '{name}'\n")
            return strat, rows
        if small_fallback is None:
            small_fallback = (strat, rows)

    if small_fallback:
        print(f"[probe] no large page available; falling back to "
              f"'{small_fallback[0][0]}' at {DEFAULT_PAGE_SIZE}/page\n")
    else:
        print("[probe] no working pagination strategy found\n", file=sys.stderr)
    return small_fallback if small_fallback else (None, None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape PB Tech hot deals to CSV")
    ap.add_argument("--out", default="cat.csv")
    ap.add_argument("--recnum", type=int, default=500)
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    sess = new_session()
    seen: set[str] = set()
    signatures: set[frozenset] = set()
    total = 0

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()

        def flush(batch) -> int:
            nonlocal total
            new = []
            for r in batch:
                pn = r["Part Number"]
                if pn and pn in seen:
                    continue
                if pn:
                    seen.add(pn)
                new.append(r)
            for r in new:
                writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_FIELDS})
            fh.flush()
            total += len(new)
            return len(new)

        for target_url in TARGET_URLS:
            print(f"\n[info] =========================================")
            print(f"[info] SCRAPING: {target_url}")
            print(f"[info] =========================================")

            fetch(sess, target_url)                       
            set_records(sess, args.recnum, target_url)
            html = fetch(sess, target_url)
            ensure_gst(sess, html, target_url)

            m = TOTAL_RE.search(BeautifulSoup(html, "lxml").get_text(" "))
            if m:
                print(f"[info] site reports {int(m.group(1).replace(',', '')):,} products")

            rows = parse_page(html)
            print(f"[info] page 1: {len(rows)} cards")
            if not rows:
                print(f"[warn] No products on page 1 of {target_url}. Skipping.")
                continue

            n = flush(rows)
            signatures.add(frozenset(r["Part Number"] or "" for r in rows))
            print(f"[info] page 1: {n} new, {total} total  (written)")

            strat, page2_rows = probe_pagination(sess, target_url, args.recnum, seen)
            if strat is None:
                print(f"[error] cannot paginate {target_url} - moving to next category.", file=sys.stderr)
                continue

            name, tmpl, repost, bare_first, send_ref = strat
            page_size = max(len(page2_rows), DEFAULT_PAGE_SIZE)

            n = flush(page2_rows)
            signatures.add(frozenset(r["Part Number"] or "" for r in page2_rows))
            print(f"[info] page 2: {len(page2_rows)} cards, {n} new, {total} total  (written)")

            for page in range(3, args.max_pages + 1):
                time.sleep(args.delay)
                try:
                    if repost:
                        set_records(sess, args.recnum, target_url)
                    if bare_first:
                        fetch(sess, target_url)
                    html = fetch(sess, build_url(tmpl, target_url, page, args.recnum),
                                 referer=target_url if send_ref else None)
                except requests.RequestException as exc:
                    print(f"[warn] page {page} failed ({exc}) - stopping", file=sys.stderr)
                    break

                rows = parse_page(html)
                if not rows:
                    print(f"[info] page {page}: 0 products - done")
                    break

                sig = frozenset(r["Part Number"] or "" for r in rows)
                if sig in signatures:
                    print(f"[info] page {page}: repeat of an earlier page - done")
                    break
                signatures.add(sig)

                n = flush(rows)
                print(f"[info] page {page}: {len(rows)} cards, {n} new, {total} total  (written)")

                if n == 0:
                    print("[info] no new products - done")
                    break

    print(f"\n[done] {total} unique products across all categories -> {args.out}")


if __name__ == "__main__":
    main()