#!/usr/bin/env python3
import csv
import os

INPUT_FILE = "pbtech_deals_raw.csv"
OUTPUT_FILE = "pbtech_deals_cleaned.csv"

UNDESIRABLE_PROMOS = [
    "FREE SHIPPING",
    "1 PER CUSTOMER",
    "NEW ARRIVAL",
    "REMANUFACTURED"
]

def is_undesirable(promo_code):
    if not promo_code: return False
    promo_upper = str(promo_code).upper()
    for code in UNDESIRABLE_PROMOS:
        if code in promo_upper: return True
    return False

def get_product_key(row):
    part_num = row.get("Part Number")
    if part_num and str(part_num).strip(): return part_num
    link = row.get("Link") or ""
    name = row.get("Product name") or ""
    return f"{link}|{name}"

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found. Make sure scraper runs first.")
        return

    print(f"Reading items from '{INPUT_FILE}'...")
    try:
        with open(INPUT_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames: return
            all_rows = list(reader)
    except Exception as e:
        print(f"Error reading {INPUT_FILE}: {e}")
        return

    if not all_rows: return

    print(f"Processing {len(all_rows)} items for duplicates...")
    best_items = {} 

    for row in all_rows:
        key = get_product_key(row)
        if key not in best_items:
            best_items[key] = row
        else:
            existing_is_bad = is_undesirable(best_items[key].get("PromoCode"))
            new_is_bad = is_undesirable(row.get("PromoCode"))
            if existing_is_bad and not new_is_bad:
                best_items[key] = row
            
    final_list = list(best_items.values())
    print(f"Removed {len(all_rows) - len(final_list)} undesirable duplicates.")

    try:
        with open(OUTPUT_FILE, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(final_list)
        print(f"Successfully saved {len(final_list)} unique products to '{OUTPUT_FILE}'")
    except Exception as e:
        print(f"Error writing to {OUTPUT_FILE}: {e}")

if __name__ == "__main__":
    main()
