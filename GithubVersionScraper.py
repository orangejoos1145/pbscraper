#!/usr/bin/env python3
import asyncio
import re
import os
from urllib.parse import urljoin
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

BASE = "https://www.pbtech.co.nz"
PER_PAGE = 100
MAX_PAGES = 300
REQUEST_DELAY = 0.5  # Increased slightly for stability

# --- CONFIGURATION ---
SITE_CONFIGS = {
    "1": { 
        "name": "HOT DEALS", 
        "base_url": "https://www.pbtech.co.nz/hot-deals/shop-all" 
    },
    "2": { 
        "name": "CLEARANCE ZONE", 
        "base_url": "https://www.pbtech.co.nz/clearance/shop-all" 
    },
}

money_re = re.compile(r"\$\s*([0-9,]+(?:\.[0-9]{1,2})?)")

def parse_money(text):
    if not text: return None
    m = money_re.search(text.replace("\u00A0", " "))
    if not m: return None
    try: return float(m.group(1).replace(",", ""))
    except: return None

def safe_text(el):
    return el.get_text(" ", strip=True) if el else ""

def make_page_url(base_url, page_num):
    return f"{base_url}?pg={page_num}"

def parse_price_from_ginc(price_el):
    if not price_el: return None
    dollar_el = price_el.select_one(".price-dollar")
    cents_el = price_el.select_one(".price-cents")
    if dollar_el:
        dollar = re.sub(r"[^\d]", "", dollar_el.get_text(" "))
        cents = re.sub(r"[^\d]", "", cents_el.get_text(" ")) if cents_el else "00"
        combined = f"{dollar}.{cents.zfill(2)[:2]}"
        return parse_money("$" + combined)
    else:
        fp = price_el.select_one(".full-price")
        if fp: return parse_money(fp.get_text(" "))
    return parse_money(price_el.get_text(" "))

def extract_product_from_card(card):
    call_out_el = card.select_one("div.call_out")
    call_out_text = safe_text(call_out_el).upper() if call_out_el else None
    
    name_el = card.select_one("h2.np_title") or card.select_one(".product-title-holder h2") or card.select_one(".js-product-link")
    name = safe_text(name_el)
    link_a = card.select_one("a.js-product-link")
    href = link_a["href"] if link_a and link_a.has_attr("href") else None
    link = urljoin(BASE + "/", href) if href else None

    part_num = None
    attr_blocks = card.select("div.product-attr-table div.col-4")
    for block in attr_blocks:
        label_el = block.select_one(".fw-semibold.text-slate-600")
        if label_el and "Part #:" in label_el.get_text():
            value_el = label_el.find_next_sibling("div")
            part_num = safe_text(value_el)
            if not part_num:
                 value_el = block.select_one("div:not(.fw-semibold)")
                 part_num = safe_text(value_el)
            break

    promo_code = None
    if call_out_text: promo_code = call_out_text
    
    if promo_code is None:
        promo_text_el = card.select_one(".card-additional-info .ginc")
        if promo_text_el:
            promo_text = safe_text(promo_text_el)
            match = re.search(r"Use promo code ([\w\d]+)", promo_text, re.IGNORECASE)
            if match: promo_code = match.group(1).upper()

    if promo_code is None:
        bf_image_el = card.select_one("img.promotion-icon[data-src*='imgad/promotion/icon/20251105145510_Icon-64x64.png']")
        if bf_image_el: promo_code = "BF SALE"
            
    is_clearance_icon_present = bool(card.select_one("img.promotion-icon[data-src*='20250219170256_Icon.png']"))

    original_price = None
    discount_price = None
    is_special_price = False
    is_non_promo_clearance = False

    price_label_el = card.select_one(".item-price-label .ginc")
    price_label_text = safe_text(price_label_el)

    if "Special price" in price_label_text:
        is_special_price = True
        main_price_el = card.select_one(".priceClass-special .ginc")
        discount_price = parse_price_from_ginc(main_price_el)
    elif "Without promo code" in price_label_text:
        original_price = parse_money(price_label_text)
        discount_price = parse_price_from_ginc(card.select_one(".item-price-amount .ginc"))
    else:
        normally_price_el = card.select_one("span.rrp_price")
        if normally_price_el: original_price = parse_money(safe_text(normally_price_el))

        if "With promo code" in price_label_text:
            discount_price = parse_money(price_label_text)
            if original_price is None:
                main_price_el = card.select_one(".item-price-amount .ginc")
                original_price = parse_price_from_ginc(main_price_el)
        
        if discount_price is None:
            main_price_el = card.select_one(".item-price-amount .ginc")
            discount_price = parse_price_from_ginc(main_price_el)

    is_clearance_item_with_single_price = False
    if call_out_text and original_price is None and discount_price is not None:
        is_clearance_item_with_single_price = True
    if is_special_price:
        is_clearance_item_with_single_price = True
    if is_clearance_icon_present and original_price is None and not is_special_price:
        is_non_promo_clearance = True
        is_clearance_item_with_single_price = True

    pct_discount = None
    if is_special_price: pct_discount = "SPECIAL"
    elif is_non_promo_clearance: pct_discount = "SPECIAL"
    else:
        try:
            if original_price and discount_price and not is_clearance_item_with_single_price:
                    if original_price > discount_price:
                        pct_discount = round((1.0 - (discount_price / original_price)) * 100, 2)
        except: pct_discount = None

    return {
        "Product name": name or None,
        "Part Number": part_num,
        "Original Price": original_price,
        "Discount Price": discount_price,
        "% Discount": pct_discount,
        "PromoCode": promo_code,
        "Link": link
    }

async def scrape_page(page, page_num, base_url):
    url = make_page_url(base_url, page_num)
    print(f"[Page {page_num}] Loading: {url}")
    try:
        # Changed to domcontentloaded and increased timeout to 60s
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        
        # Wait for products to exist
        await page.wait_for_selector("div.js-product-card", timeout=15000)
        
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.js-product-card")
        results = [extract_product_from_card(c) for c in cards]
        print(f"[Page {page_num}] Found {len(results)} products")
        await asyncio.sleep(REQUEST_DELAY)
        return results
    except PlaywrightTimeout:
        print(f"[Page {page_num}] Timeout or no products found")
        return []
    except Exception as e:
        print(f"[Page {page_num}] Error: {e}")
        return []

async def run_scraper_for_site(config):
    site_name = config['name']
    base_url = config['base_url']
    print(f"STARTING SCRAPE FOR: {site_name}")
    all_results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Block images/fonts/css to speed up loading
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        # Optional: Block resources to save bandwidth and time
        # await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,css,woff,woff2}", lambda route: route.abort())

        page = await context.new_page()

        # Retry logic for initial connection
        connected = False
        for attempt in range(3):
            try:
                print(f"Initial connection attempt {attempt+1}...")
                await page.goto(make_page_url(base_url, 1), timeout=60000, wait_until="domcontentloaded")
                connected = True
                break
            except Exception as e:
                print(f"Connection failed ({e}), retrying...")
                await asyncio.sleep(5)
        
        if not connected:
            print(f"Could not connect to {site_name} after 3 attempts. Skipping.")
            await browser.close()
            return []

        # Try to change view settings (optional)
        try:
            await page.select_option("select.rec_num.js-rec-num", str(PER_PAGE), timeout=5000)
            await asyncio.sleep(2)
        except: pass

        try:
            view_button = page.locator('div.js-change-view[title="View as expanded list"]')
            if "active" not in (await view_button.get_attribute("class") or ""):
                await view_button.click(timeout=5000)
                await page.wait_for_selector("div.js-product-card.col-xl-12", timeout=10000)
        except: pass

        for page_num in range(1, MAX_PAGES + 1):
            page_results = await scrape_page(page, page_num, base_url)
            if not page_results: break
            all_results.extend(page_results)
        
        await browser.close()
    return all_results

async def main():
    # AUTOMATED SELECTION: Scrape sites 1 and 2 by default
    valid_keys = ["1", "2"] 
    print(f"Automated mode. Scraping sites: {valid_keys}")
    
    master_results_list = []
    for key in valid_keys:
        config = SITE_CONFIGS[key]
        site_results = await run_scraper_for_site(config)
        if site_results: master_results_list.extend(site_results)

    cols = ["Product name", "Part Number", "Original Price", "Discount Price", "% Discount", "PromoCode", "Link"]
    output_filename = "pbtech_deals.csv"
    
    if master_results_list:
        df = pd.DataFrame(master_results_list)
        df = df.reindex(columns=cols)
        df.to_csv(output_filename, index=False, encoding="utf-8")
        print(f"\nSaved {len(df)} items to {output_filename}")
    else:
        print("\nNo products scraped. Creating empty CSV file.")
        df = pd.DataFrame(columns=cols)
        df.to_csv(output_filename, index=False, encoding="utf-8")

if __name__ == "__main__":
    asyncio.run(main())
