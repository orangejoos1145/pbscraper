import pandas as pd
import html
import re
import json
import sys
from datetime import datetime
import pytz 

IN_CSV = "pbtech_deals.csv"
OUT_HTML = "index.html"
QUICK_FILTER_CSV = "quickfilters.csv"
GST_RATE = 1.15

# ---- Utility Functions ----
def esc(x):
    if pd.isna(x): return ""
    return html.escape(str(x)).replace("\n", " ").replace("\r", " ").replace(",", "&#44;")

def to_numeric_price(val):
    try:
        if pd.isna(val) or val == "": return None
        s = str(val).strip().replace("$", "").replace(",", "")
        return float(s)
    except Exception: return None

def fmt_price(val):
    try:
        if pd.isna(val) or val == "": return ""
        v = float(str(val).replace("$", "").replace(",", ""))
        return f"${v:,.2f}"
    except Exception: return esc(str(val).strip())

def fmt_pct(val):
    try:
        if pd.isna(val) or val == "": return ""
        v = float(val)
        return f"{int(v)}%" if abs(v - int(v)) < 0.001 else f"{v:.2f}%"
    except Exception: return esc(str(val).strip())

def generate_quick_filters_html():
    try:
        df_filters = pd.read_csv(QUICK_FILTER_CSV)
        df_filters.fillna("None", inplace=True)
        filters_tree = {}
        for _, row in df_filters.iterrows():
            s = row["Section"]; ss = row["Subsection"]; sss = row["SubSubSection"]; fmt = row["Format"]
            if s not in filters_tree: filters_tree[s] = {}
            if ss not in filters_tree[s]: filters_tree[s][ss] = {}
            if sss not in filters_tree[s][ss]: filters_tree[s][ss][sss] = []
            filters_tree[s][ss][sss].append(fmt)
        html_out = '<ul class="qf-menu" id="qsContainer">' 
        for s, ss_dict in filters_tree.items():
            html_out += f'<li><span>{esc(s)}</span><ul>'
            for ss, sss_dict in ss_dict.items():
                if list(sss_dict.keys()) == ["None"]:
                    html_out += "<li>"
                    for fmt in sss_dict["None"]: html_out += (f'<a href="#" class="qf-format-btn" data-format="{esc(fmt)}">{esc(ss)} ({esc(fmt)})</a>')
                    html_out += "</li>"
                else:
                    html_out += f"<li><span>{esc(ss)}</span><ul>"
                    for sss, fmt_list in sss_dict.items():
                        html_out += "<li>"
                        for fmt in fmt_list: html_out += (f'<a href="#" class="qf-format-btn" data-format="{esc(fmt)}">{esc(sss)} ({esc(fmt)})</a>')
                        html_out += "</li>"
                    html_out += "</ul></li>"
            html_out += "</ul></li>"
        html_out += "</ul>"
        return html_out
    except: return ""

def generate_promo_filters_html(promo_list):
    if not promo_list: return ""
    html_out = '<div class="controls-promo-filters"><span class="small" style="color: rgba(255,255,255,0.7); font-size: 14px; margin-right: 5px;">Filter By Promo:</span><button class="btn toggle active" data-promo="all">All</button>'
    for promo in promo_list:
        promo_esc = esc(promo)
        html_out += (f'<button class="btn toggle promo-filter-btn" data-promo="{promo_esc.lower()}">{promo_esc}</button>')
    html_out += "</div>"
    return html_out

def get_str_or_empty(x):
    if pd.isna(x): return ""
    return str(x).strip()

# --- LOAD CSV (With Safety Check) ---
try:
    df = pd.read_csv(IN_CSV)
except FileNotFoundError:
    print(f"Error: Input file '{IN_CSV}' not found. Stopping generator.")
    sys.exit(0)

if df.empty:
    print(f"Warning: Input file '{IN_CSV}' is empty. Stopping generator.")
    sys.exit(0)

# --- PROCESS DATA ---
df["orig_inc"] = df.get("Original Price", pd.Series(dtype=str)).apply(to_numeric_price)
df["orig_ex"] = df["orig_inc"] / GST_RATE
df["disc_inc"] = df.get("Discount Price", pd.Series(dtype=str)).apply(to_numeric_price)
df["disc_ex"] = df["disc_inc"] / GST_RATE
df.loc[df["disc_inc"].isna(), "disc_ex"] = pd.NA
df["pct_raw"] = df.get("% Discount", pd.Series(dtype=str)).apply(get_str_or_empty)

def compute_pct_numeric(row):
    raw = (row.get("pct_raw") or "").strip()
    if raw.upper() == "SPECIAL": return 100.0
    orig = row.get("orig_ex")
    disc = row.get("disc_ex")
    if pd.notna(orig) and pd.notna(disc) and orig > 0: return (orig - disc) / orig * 100.0
    if raw:
        try: return float(raw.replace("%", "").replace(",", ""))
        except: return None
    return None

df["pct_numeric"] = df.apply(compute_pct_numeric, axis=1)
df["price_numeric"] = df["disc_ex"].fillna(df["orig_ex"])
df = df[df["pct_numeric"].isna() | (df["pct_numeric"] >= 0)].reset_index(drop=True)

CATEGORY_KEYWORDS = {
    "case": ["case","cover","shell","protector","skin","sleeve","screen guard","spigen","otterbox","uag"],
    "cable": ["cable","usb","hdmi","lightning","usb-c","ethernet","adapter"],
    "power": ["power","charger","adapter","psu","powerbank","battery","ups"],
    "accessory": ["accessory","stand","mount","dock","hub","stylus","bag"],
    "storage": ["ssd","hdd","nvme","usb drive","sd card","nas","samsung evo","wd","seagate"],
    "mouse": ["mouse","mice","trackball","logitech","razer"],
    "keyboard": ["keyboard","keypad","mechanical kb","keychron"],
    "monitor": ["monitor","display","screen","ultrawide"],
    "headphone": ["headphone","earbuds","headset","airpods","jabra","sony","bose"],
    "speaker": ["speaker","soundbar","sonos","jbl","ue"],
    "component": ["cpu","gpu","motherboard","ram","graphics card","ryzen","geforce","intel","amd","rtx","gtx"],
    "appliance": ["vacuum","fryer","dyson","xiaomi","kettle","toaster"],
    "laptop": ["laptop","notebook","macbook","thinkpad","surface","zenbook"],
    "tablet": ["tablet","ipad","galaxy tab","kindle"],
    "phone": ["phone","mobile","iphone","samsung","pixel","oppo"],
}
PRIORITY_ORDER = ["case","cable","power","accessory","storage","mouse","keyboard","headphone","speaker","monitor","component","appliance","laptop","tablet","phone"]
keyword_to_cat = {}
for cat in PRIORITY_ORDER:
    if cat in CATEGORY_KEYWORDS:
        for k in CATEGORY_KEYWORDS[cat]: keyword_to_cat[k.lower()] = cat
SORTED_KEYWORDS = sorted(keyword_to_cat.keys(), key=lambda x: -len(x))

def detect_categories(name):
    name_l = (name or "").lower()
    if not name_l: return []
    found_cats = set()
    for kw in SORTED_KEYWORDS:
        if kw in name_l: found_cats.add(keyword_to_cat[kw])
    if not found_cats: found_cats.add("other")
    return sorted(list(found_cats))

deals_payload = []
for idx, row in df.iterrows():
    name_raw = str(row.get("Product name", "") or "")
    part_raw = str(row.get("Part Number", "") or "")
    promo_raw = str(row.get("PromoCode", "") or "")
    link = str(row.get("Link", "") or "")
    cats = detect_categories(name_raw)
    orig_ex = row.get("orig_ex"); orig_inc = row.get("orig_inc")
    disc_ex = row.get("disc_ex"); disc_inc = row.get("disc_inc")
    pct_val = row.get("pct_numeric")
    is_special = str(row.get("pct_raw","")).strip().upper() == "SPECIAL"
    has_orig = not pd.isna(orig_ex)
    is_unknown = (not is_special) and (not has_orig) and (str(row.get("pct_raw","")).strip() == "")
    pct_text = "SPECIAL" if is_special else (fmt_pct(pct_val) if pd.notna(pct_val) else "")
    deals_payload.append({
        "n": name_raw, "p": part_raw, "l": link, "pr": promo_raw,
        "oe": fmt_price(orig_ex), "oi": fmt_price(orig_inc),
        "de": fmt_price(disc_ex), "di": fmt_price(disc_inc),
        "pt": pct_text, "v": pct_val if pd.notna(pct_val) else 0,
        "pv": row.get("price_numeric") if pd.notna(row.get("price_numeric")) else 0,
        "c": ",".join(cats), "f": [1 if has_orig else 0, 1 if is_special else 0, 1 if is_unknown else 0]
    })

json_data = json.dumps(deals_payload)
quick_filters_html = generate_quick_filters_html()
unique_promos = sorted(df[df["PromoCode"].notna() & (df["PromoCode"] != "")]["PromoCode"].unique())
promo_filters_html = generate_promo_filters_html(unique_promos)

# ---- TIMEZONE FIX ----
try:
    nz_tz = pytz.timezone('Pacific/Auckland')
    scrape_time_str = datetime.now(nz_tz).strftime("%d/%m/%Y @ %I:%M %p")
except Exception as e:
    scrape_time_str = datetime.now().strftime("%d/%m/%Y @ %I:%M %p UTC")

try:
    with open("whatsnew.txt", "r", encoding="utf-8") as f:
        whats_new_content = html.escape(f.read()).replace("\n", "<br />")
except: whats_new_content = "<i>whatsnew.txt not found.</i>"

html_content = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>PBTech Deals Filterer</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<script>
  (function() {{
    const theme = localStorage.getItem('theme');
    if (theme === 'dark') {{ document.documentElement.classList.add('dark'); }}
  }})();
</script>
<style>
  :root {{ --pb-navy: #022e58; --pb-orange: #f36f21; --pb-orange-hover: #d65b12; --accent: var(--pb-orange); --bg: #f5f5f5; --card: #ffffff; --text: #333333; --border: #dddddd; --header-bg: var(--pb-navy); --header-text: #ffffff; --row-even: #f9f9f9; --row-hover: #eef4fb; --no-discount-bg: #ffebee; --special-bg: #e8f5e9; }}
  :root.dark {{ --bg: #121212; --card: #1e1e1e; --text: #e0e0e0; --border: #333; --header-bg: #0d1b2a; --header-text: #eee; --row-even: #2a2a2a; --row-hover: #333; --no-discount-bg: #4a2020; --special-bg: #1b4d2e; }}
  body {{ font-family: "Open Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); margin: 0; padding: 24px; color: var(--text); }}
  .container {{ max-width: 1300px; margin: 0 auto; }}
  header {{ background: var(--header-bg); color: var(--header-text); border-radius: 4px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); margin-bottom: 24px; }}
  h1 {{ margin: 0; font-size: 24px; font-weight: 700; color: #fff; }}
  .scrape-time {{ color: rgba(255,255,255,0.7); font-size: 13px; font-family: monospace; }}
  .small {{ font-size: 13px; color: rgba(255,255,255,0.7); }}
  .btn {{ background: var(--pb-orange); color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; transition: background 0.2s; }}
  .btn:hover {{ background: var(--pb-orange-hover); }}
  .btn.secondary {{ background: rgba(255,255,255,0.15); color: white; border: 1px solid rgba(255,255,255,0.3); }}
  .btn.secondary:hover {{ background: rgba(255,255,255,0.25); }}
  .btn.reset {{ background: #444; color: #ddd; border: 1px solid #555; }} .btn.reset:hover {{ background: #555; }}
  .controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 15px; }}
  input[type="number"], input[type="search"], select {{ padding: 8px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; }}
  input[type="search"] {{ width: 250px; border-radius: 4px; border: none; padding: 10px; }}
  .btn.toggle {{ background: rgba(255,255,255,0.1); color: #ccc; border: 1px solid rgba(255,255,255,0.2); font-size: 12px; padding: 5px 10px; }}
  .btn.toggle.active {{ background: white; color: var(--pb-navy); border-color: white; font-weight: bold; }}
  .promo-code {{ background: #fff8e1; color: #e65100; padding: 2px 6px; border-radius: 3px; font-size: 12px; font-weight: bold; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px; }}
  .desktop-group {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  .mobile-row {{ display: contents; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 4px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
  th {{ background: #eee; color: #333; padding: 12px; text-align: left; font-size: 13px; text-transform: uppercase; font-weight: 700; cursor: pointer; user-select: none; }}
  th.sort-asc::after {{ content:'▲'; color: var(--pb-orange); float:right; }} th.sort-desc::after {{ content:'▼'; color: var(--pb-orange); float:right; }}
  :root.dark th {{ background: #2a2a2a; color: #ddd; }}
  td {{ padding: 10px 12px; border-top: 1px solid var(--border); font-size: 14px; }}
  tr.no-discount-row {{ background: var(--no-discount-bg); }} tr.special-row {{ background: var(--special-bg); }}
  .price {{ font-family: monospace; font-size: 15px; font-weight: 600; }}
  .discount {{ color: #d32f2f; font-weight: 700; }} :root.dark .discount {{ color: #ff6b6b; }}
  a.product-link {{ color: var(--text); text-decoration: none; font-weight: 600; }} a.product-link:hover {{ color: var(--pb-orange); }}
  .controls-pagination {{ display: flex; justify-content: space-between; padding: 15px; background: var(--card); border: 1px solid var(--border); border-radius: 4px; margin-top: 15px; align-items: center; }}
  .pagination-btns button {{ padding: 6px 12px; background: white; border: 1px solid #ccc; color: #333; border-radius: 3px; cursor: pointer; }} :root.dark .pagination-btns button {{ background: #333; border-color: #555; color: #eee; }}
  .quick-filter-menu-container {{ margin-top: 15px; border-top: 1px solid rgba(255,255,255,0.2); padding-top: 10px; }}
  ul.qf-menu {{ list-style: none; padding: 0; margin: 0; display: flex; gap: 8px; flex-wrap: wrap; }}
  ul.qf-menu > li > span {{ color: rgba(255,255,255,0.8); cursor: pointer; padding: 6px 12px; background: rgba(0,0,0,0.2); border-radius: 4px; font-size: 13px; font-weight:600; transition: background 0.2s, color 0.2s; }}
  ul.qf-menu > li > span:hover {{ background: var(--pb-orange); color: white; }}
  ul.qf-menu ul {{ display: none; position: absolute; background: white; border: 1px solid #ccc; z-index: 100; border-radius: 4px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); padding: 0; color: #333; min-width: 220px; }}
  :root.dark ul.qf-menu ul {{ background: #222; border-color: #444; color: #eee; }}
  ul.qf-menu li:hover > ul {{ display: block; }}
  ul.qf-menu ul li {{ position: relative; border-bottom: 1px solid #eee; }} :root.dark ul.qf-menu ul li {{ border-bottom: 1px solid #333; }}
  ul.qf-menu ul li:last-child {{ border-bottom: none; }}
  ul.qf-menu ul a, ul.qf-menu ul span {{ display: block; padding: 10px 15px; color: #333; text-decoration: none; font-size: 13px; cursor: pointer; }}
  :root.dark ul.qf-menu ul a, :root.dark ul.qf-menu ul span {{ color: #eee; }}
  ul.qf-menu ul li > span:hover, ul.qf-menu ul li > a:hover {{ background: #f0f0f0; color: var(--pb-orange); }}
  :root.dark ul.qf-menu ul li > span:hover, :root.dark ul.qf-menu ul li > a:hover {{ background: #333; color: var(--pb-orange); }}
  ul.qf-menu ul li > span::after {{ content: '▸'; float: right; color: #999; font-weight: bold; }} :root.dark ul.qf-menu ul li > span::after {{ color: #666; }}
  ul.qf-menu ul li > span:hover::after {{ color: var(--pb-orange); }}
  ul.qf-menu ul ul {{ top: 0; left: 100%; margin-top: -1px; margin-left: -5px; box-shadow: 4px 4px 10px rgba(0,0,0,0.1); }}
  .controls-promo-filters {{ margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.2); display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
  .modal-overlay {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; }}
  .modal-content {{ background: var(--card); padding: 25px; border-radius: 8px; width: 90%; max-width: 600px; max-height: 80vh; overflow-y: auto; color: var(--text); }}
  .modal-header {{ display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 15px; }}
  @media (max-width: 768px) {{
    .mobile-row {{ display: flex; gap: 10px; justify-content: space-between; width: 100%; }}
    .mobile-row label {{ width: 48%; }} .mobile-row input {{ width: 100%; }}
    .controls {{ flex-direction: column; align-items: stretch; }}
    th:nth-child(1), th:nth-child(3), th:nth-child(6), td:nth-child(1), td:nth-child(3), td:nth-child(6) {{ display: none; }}
    .controls-pagination {{ flex-direction: column; gap: 10px; }}
    ul.qf-menu {{ flex-direction: column; }}
    ul.qf-menu ul {{ position: static; display: none; margin-left: 15px; border: none; box-shadow: none; background: transparent; }}
    ul.qf-menu ul a, ul.qf-menu ul span {{ color: rgba(255,255,255,0.8); padding: 8px 0; border: none; }}
    ul.qf-menu ul li {{ border: none; }} ul.qf-menu ul li > span::after {{ display: none; }}
    #qsToggle {{ display: block; width: 100%; margin-top:10px; }}
    .quick-filter-menu-container {{ display: none; }} .quick-filter-menu-container.show-mobile {{ display: block; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-top">
      <div><h1>PBTech Deals Filterer</h1><div class="scrape-time">Last updated: {scrape_time_str}</div></div>
      <div style="display:flex; gap:10px">
        <button class="btn secondary" id="whatsNewBtn">What's New</button>
        <a href="https://www.buymeacoffee.com/polobaggyo" target="_blank" class="btn">☕ Coffee</a>
        <button class="btn secondary" id="toggleThemeBtn">🌙</button>
      </div>
    </div>
    <div class="controls">
      <div class="desktop-group" style="width:100%">
          <input id="searchInput" type="search" placeholder="Search (e.g. msi gpu, RTX 4090)" />
          <button class="btn" id="searchBtn">Search</button>
          <div class="mobile-row"><label style="color:white; font-size:13px;">Discount %<div style="display:flex; gap:5px"><input id="minDiscount" type="number" min="0" max="100" placeholder="Min" value="0" style="width:60px"><input id="maxDiscount" type="number" min="0" max="100" placeholder="Max" value="100" style="width:60px"></div></label></div>
          <button class="btn reset" id="resetDiscountBtn">Reset</button>
      </div>
      <div class="desktop-group" style="margin-top:10px; width:100%; justify-content:space-between;">
         <div class="mobile-row" style="flex-grow:1; gap:10px; display:flex;"><input id="minPrice" type="number" min="0" placeholder="Min $" style="width:80px"><input id="maxPrice" type="number" min="0" placeholder="Max $" style="width:80px"></div>
         <div style="display:flex; gap:15px; color:rgba(255,255,255,0.9); font-size:13px; flex-wrap:wrap;">
            <label><input type="checkbox" id="toggleHidden"> Show Unknown</label><label><input type="checkbox" id="toggleSpecial"> Show SPECIAL</label><label><input type="checkbox" id="toggleGST" checked> GST Inc.</label><span>Found: <b id="totalCount">0</b></span>
         </div>
      </div>
    </div>
    <button class="btn secondary" id="qsToggle" style="display:none">Show Categories ▼</button>
    <div class="quick-filter-menu-container" id="qsContainer">{quick_filters_html}</div>
    {promo_filters_html}
  </header>
  <div class="controls-pagination">
      <div style="display:flex; align-items:center; gap:10px;"><label class="small" style="color:var(--text)">Rows:</label><select id="rowsPerPage"><option value="50">50</option><option value="100" selected>100</option><option value="200">200</option><option value="500">500</option><option value="1000">1000</option></select><input type="number" id="customRows" placeholder="Custom" style="width:70px" min="1"></div>
      <div id="pageInfo" style="font-size:14px; font-weight:600;">0-0 of 0</div>
      <div class="pagination-btns"><button id="btnFirst">«</button><button id="btnPrev">‹ Prev</button><button id="btnNext">Next ›</button><button id="btnLast">»</button></div>
  </div>
  <div style="overflow:auto; margin-top:10px;">
  <table id="dealsTable"><thead><tr><th data-sort="p">Part #</th><th data-sort="n">Product Name</th><th data-sort="price">Original</th><th data-sort="price">Discounted</th><th data-sort="v">% Off</th><th>Promo</th><th>G</th></tr></thead><tbody id="tableBody"></tbody></table>
  </div>
  <div class="footer small" style="margin-top:20px;text-align:center; color:#888;">Site Designed and Coded by <a href="https://www.cheapies.nz/user/3665" target="_blank" style="color:var(--pb-orange)">PolobaggYo aka GeorgeOfTheJungle</a></div>
</div>
<div id="whatsNewModal" class="modal-overlay" style="display: none;"><div class="modal-content"><div class="modal-header"><h2>What's New</h2><button id="closeWhatsNewBtn" style="border:none;background:none;font-size:20px;cursor:pointer">&times;</button></div><div class="modal-body">{whats_new_content}</div></div></div>
<script>
const allDeals = {json_data};
const GST_RATE = 1.15;
const googleIconSvg = '<svg style="width:16px;height:16px;fill:#999" viewBox="0 0 24 24"><path d="M21.35,11.1H12.18V13.83H18.69C18.36,17.64 15.19,19.27 12.19,19.27C8.36,19.27 5.03,16.21 5.03,12.2C5.03,8.19 8.36,5.13 12.19,5.13C14.4,5.13 15.9,6.02 16.6,6.68L18.6,4.71C16.8,3.08 14.6,2 12.19,2C6.92,2 2.76,6.13 2.76,12.2C2.76,18.27 6.92,22.4 12.19,22.4C17.6,22.4 21.5,18.52 21.5,12.49C21.5,11.91 21.43,11.5 21.35,11.1Z"></path></svg>';
let state = {{ filtered: [], currentPage: 1, rowsPerPage: 100, sortCol: 'v', sortDir: 'desc', searchQuery: '', minPct: 0, maxPct: 100, minPrice: 0, maxPrice: Infinity, showHidden: false, showSpecial: false, showGst: true, activePromos: new Set(['all']) }};
const tbody = document.getElementById('tableBody'); const countEl = document.getElementById('totalCount'); const pageInfoEl = document.getElementById('pageInfo');
function init() {{ state.filtered = [...allDeals]; applyFilters(); setupListeners(); }}
function escapeHtml(text) {{ if (!text) return ''; return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;"); }}
function renderPage() {{
    const start = (state.currentPage - 1) * state.rowsPerPage; const end = start + state.rowsPerPage; const slice = state.filtered.slice(start, end); let html = '';
    slice.forEach(d => {{
        let rowClass = ''; if (d.f[2]) rowClass = 'no-discount-row'; else if (d.f[1]) rowClass = 'special-row';
        const googleLink = `https://www.google.com/search?q=${{encodeURIComponent(d.n)}}`; const origDisplay = state.showGst ? d.oi : d.oe; const discDisplay = state.showGst ? d.di : d.de; const promoHtml = d.pr ? `<span class="promo-code">${{escapeHtml(d.pr)}}</span>` : '';
        html += `<tr class="${{rowClass}}"><td style="font-family:monospace;color:#666">${{escapeHtml(d.p)}}</td><td><a class="product-link" href="${{d.l}}" target="_blank">${{escapeHtml(d.n)}}</a></td><td class="price" style="color:#666;text-decoration:line-through">${{origDisplay}}</td><td class="price">${{discDisplay}}</td><td class="discount">${{d.pt}}</td><td style="text-align:center">${{promoHtml}}</td><td style="text-align:center"><a href="${{googleLink}}" target="_blank">${{googleIconSvg}}</a></td></tr>`;
    }});
    tbody.innerHTML = html; updatePaginationUI();
}}
function updatePaginationUI() {{
    const total = state.filtered.length; const start = (state.currentPage - 1) * state.rowsPerPage + 1; const end = Math.min(start + state.rowsPerPage - 1, total);
    pageInfoEl.textContent = `${{total===0?0:start}}-${{end}} of ${{total}}`; countEl.textContent = total;
    document.getElementById('btnPrev').disabled = state.currentPage === 1; document.getElementById('btnFirst').disabled = state.currentPage === 1;
    const maxPage = Math.ceil(total / state.rowsPerPage); document.getElementById('btnNext').disabled = state.currentPage >= maxPage || maxPage === 0; document.getElementById('btnLast').disabled = state.currentPage >= maxPage || maxPage === 0;
}}
function applyFilters() {{
    const s = state; const term = s.searchQuery.toLowerCase().trim(); let regex = null; let textTokens = [];
    if (term.includes('*')) {{ try {{ regex = new RegExp('^' + term.replace(/\*/g, '.*') + '$', 'i'); }} catch(e){{}} }} else {{ textTokens = term.split(/\s+/).filter(Boolean); }}
    const limitMinPrice = s.showGst ? (s.minPrice / GST_RATE) : s.minPrice; const limitMaxPrice = s.showGst ? (s.maxPrice / GST_RATE) : s.maxPrice;
    state.filtered = allDeals.filter(d => {{
        if (d.f[1] && !s.showSpecial) return false; if (d.f[2] && !s.showHidden) return false;
        if (!s.activePromos.has('all')) {{ const pLower = (d.pr || "").toLowerCase(); if (!s.activePromos.has(pLower)) return false; }}
        if (d.pv < limitMinPrice) return false; if (s.maxPrice !== Infinity && d.pv > limitMaxPrice) return false; if (d.v < s.minPct) return false; if (d.v > s.maxPct) return false;
        if (term) {{ const searchStr = (d.n + " " + d.p + " " + d.c).toLowerCase(); if (regex) {{ if (!regex.test(d.p)) return false; }} else if (textTokens.length > 0) {{ if (!textTokens.every(t => searchStr.includes(t))) return false; }} }}
        return true;
    }});
    state.currentPage = 1; sortData();
}}
function sortData() {{
    const col = state.sortCol; const dir = state.sortDir === 'asc' ? 1 : -1;
    state.filtered.sort((a, b) => {{
        let valA, valB; if (col === 'price') {{ valA = a.pv; valB = b.pv; }} else if (col === 'v') {{ valA = a.v; valB = b.v; }} else if (col === 'n') {{ valA = a.n.toLowerCase(); valB = b.n.toLowerCase(); }} else if (col === 'p') {{ valA = a.p.toLowerCase(); valB = b.p.toLowerCase(); }}
        if (valA < valB) return -1 * dir; if (valA > valB) return 1 * dir; return 0;
    }});
    renderPage();
}}
function setupListeners() {{
    document.querySelectorAll('th[data-sort]').forEach(th => {{ th.addEventListener('click', () => {{ const col = th.dataset.sort; if (state.sortCol === col) {{ state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc'; }} else {{ state.sortCol = col; state.sortDir = 'desc'; }} document.querySelectorAll('th').forEach(h => h.classList.remove('sort-asc', 'sort-desc')); th.classList.add(state.sortDir === 'asc' ? 'sort-asc' : 'sort-desc'); sortData(); }}); }});
    document.getElementById('btnNext').addEventListener('click', () => {{ const max = Math.ceil(state.filtered.length / state.rowsPerPage); if (state.currentPage < max) {{ state.currentPage++; renderPage(); }} }});
    document.getElementById('btnPrev').addEventListener('click', () => {{ if (state.currentPage > 1) {{ state.currentPage--; renderPage(); }} }});
    document.getElementById('btnFirst').addEventListener('click', () => {{ state.currentPage = 1; renderPage(); }});
    document.getElementById('btnLast').addEventListener('click', () => {{ state.currentPage = Math.ceil(state.filtered.length / state.rowsPerPage); renderPage(); }});
    const rowsSel = document.getElementById('rowsPerPage'); const rowsCust = document.getElementById('customRows');
    rowsSel.addEventListener('change', (e) => {{ rowsCust.value = ""; state.rowsPerPage = parseInt(e.target.value); state.currentPage = 1; renderPage(); }});
    rowsCust.addEventListener('input', (e) => {{ const val = parseInt(e.target.value); if (val && val > 0) {{ state.rowsPerPage = val; state.currentPage = 1; renderPage(); }} }});
    const debounce = (fn, delay) => {{ let t; return (...args) => {{ clearTimeout(t); t = setTimeout(() => fn(...args), delay); }}; }};
    const runFilter = debounce(() => applyFilters(), 300);
    document.getElementById('searchInput').addEventListener('input', (e) => {{ state.searchQuery = e.target.value; runFilter(); }});
    document.getElementById('minDiscount').addEventListener('input', (e) => {{ state.minPct = parseFloat(e.target.value)||0; runFilter(); }});
    document.getElementById('maxDiscount').addEventListener('input', (e) => {{ state.maxPct = parseFloat(e.target.value)||100; runFilter(); }});
    document.getElementById('minPrice').addEventListener('input', (e) => {{ state.minPrice = parseFloat(e.target.value)||0; runFilter(); }});
    document.getElementById('maxPrice').addEventListener('input', (e) => {{ state.maxPrice = parseFloat(e.target.value)||Infinity; runFilter(); }});
    document.getElementById('toggleHidden').addEventListener('change', (e) => {{ state.showHidden = e.target.checked; applyFilters(); }});
    document.getElementById('toggleSpecial').addEventListener('change', (e) => {{ state.showSpecial = e.target.checked; applyFilters(); }});
    document.getElementById('toggleGST').addEventListener('change', (e) => {{ state.showGst = e.target.checked; applyFilters(); }});
    document.getElementById('resetDiscountBtn').addEventListener('click', () => {{ state.minPct = 0; state.maxPct = 100; state.minPrice = 0; state.maxPrice = Infinity; state.searchQuery = ''; state.showHidden = false; state.showSpecial = false; state.activePromos = new Set(['all']); document.getElementById('minDiscount').value = 0; document.getElementById('maxDiscount').value = 100; document.getElementById('minPrice').value = ''; document.getElementById('maxPrice').value = ''; document.getElementById('searchInput').value = ''; document.getElementById('toggleHidden').checked = false; document.getElementById('toggleSpecial').checked = false; document.querySelectorAll('.promo-filter-btn').forEach(b => b.classList.remove('active')); document.querySelector('[data-promo="all"]').classList.add('active'); applyFilters(); }});
    document.querySelectorAll('.qf-format-btn').forEach(btn => {{ btn.addEventListener('click', (e) => {{ e.preventDefault(); const val = e.target.dataset.format; document.getElementById('searchInput').value = val; state.searchQuery = val; const container = document.getElementById('qsContainer'); if (container.classList.contains('show-mobile')) {{ container.classList.remove('show-mobile'); document.getElementById('qsToggle').textContent = 'Show Categories ▼'; }} applyFilters(); }}); }});
    const qsToggle = document.getElementById('qsToggle'); const qsContainer = document.getElementById('qsContainer');
    qsToggle.addEventListener('click', () => {{ if(qsContainer.classList.contains('show-mobile')) {{ qsContainer.classList.remove('show-mobile'); qsToggle.textContent = 'Show Categories ▼'; }} else {{ qsContainer.classList.add('show-mobile'); qsToggle.textContent = 'Hide Categories ▲'; }} }});
    document.querySelectorAll('.qf-menu li > span').forEach(span => {{ span.addEventListener('click', (e) => {{ if (window.innerWidth <= 768) {{ const ul = e.target.closest('li').querySelector('ul'); if (ul) ul.style.display = (ul.style.display === 'block' ? 'none' : 'block'); }} }}); }});
    document.querySelectorAll('.promo-filter-btn, [data-promo="all"]').forEach(btn => {{ btn.addEventListener('click', (e) => {{ const promo = e.currentTarget.dataset.promo; if (promo === 'all') {{ state.activePromos.clear(); state.activePromos.add('all'); document.querySelectorAll('.promo-filter-btn').forEach(b => b.classList.remove('active')); e.currentTarget.classList.add('active'); }} else {{ document.querySelector('[data-promo="all"]').classList.remove('active'); state.activePromos.delete('all'); if (state.activePromos.has(promo)) {{ state.activePromos.delete(promo); e.currentTarget.classList.remove('active'); }} else {{ state.activePromos.add(promo); e.currentTarget.classList.add('active'); }} if (state.activePromos.size === 0) {{ state.activePromos.add('all'); document.querySelector('[data-promo="all"]').classList.add('active'); }} }} applyFilters(); }}); }});
    const themeBtn = document.getElementById('toggleThemeBtn');
    themeBtn.addEventListener('click', () => {{ const isDark = document.documentElement.classList.toggle('dark'); localStorage.setItem('theme', isDark ? 'dark' : 'light'); themeBtn.textContent = isDark ? '☀️' : '🌙'; }});
    if (document.documentElement.classList.contains('dark')) themeBtn.textContent = '☀️';
    const modal = document.getElementById('whatsNewModal');
    document.getElementById('whatsNewBtn').addEventListener('click', () => modal.style.display = 'flex');
    document.getElementById('closeWhatsNewBtn').addEventListener('click', () => modal.style.display = 'none');
    modal.addEventListener('click', (e) => {{ if (e.target === modal) modal.style.display = 'none'; }});
}}
init();
</script>
</body>
</html>
"""

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"✅ Generated {OUT_HTML} successfully.")
