"""
AIOHtmlGen.py - turns cat.csv into a single self-contained deals browser page.

    python AIOHtmlGen.py                          # cat.csv  -> deals.html
    python AIOHtmlGen.py --csv cat.csv --out deals.html
    python AIOHtmlGen.py --open                   # also open it in your browser

Standard library only. Output is ONE html file with the data embedded.

WHAT IT DOES
  * de-duplicates on Part Number (first occurrence wins), reports the count
  * classifies every row:
      PROMO   - promo code and a real before/after price
      SPECIAL - discounted, but no promo code (PB's "Special price" items)
      UNKNOWN - no discounted price, so the saving can't be worked out
  * assigns a category from the product name, with the part-number prefix as a
    tiebreaker (CATEGORY_RULES / PREFIX_HINTS below are heuristics - edit them)
  * stamps the page with the time this script ran

LINKS
  Product name / row  -> the PB Tech product page
  G button            -> a Google search for the part number and name

  Product URLs are https://www.pbtech.co.nz/product/<PART>/<slug>, where <slug>
  is the name with spaces turned into hyphens, non-alphanumerics dropped, cut
  to 50 chars, trailing hyphens stripped. That rule reproduces real PB URLs
  exactly. PB generally resolves on the part number regardless.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# Categorisation - edit freely, first match wins
# --------------------------------------------------------------------------- #

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("Storage & NAS", [
        "ssd", "hard drive", "hdd", " nas ", "nas ", "microsd", "sd card",
        "flash drive", "usb drive", "external drive", "m.2", "nvme", "portable drive",
    ]),
    ("Phones & Wearables", [
        "iphone", "smartphone", "smart watch", "smartwatch", "fitness tracker",
        "phone case", "screen protector", "galaxy s", "pixel ", "mobile phone",
        "wearable", "smart band", "fitness band", "redmi watch", "watch -",
    ]),
    ("Monitors & Displays", [
        "monitor", "projector", "ultrawide", "display panel", "smart tv",
        "television", "oled tv", "led tv", "digital signage",
    ]),
    ("Audio", [
        "headphone", "earphone", "earbud", "speaker", "soundbar", "microphone",
        "headset", "subwoofer", "turntable", "amplifier", "airpods", "audio interface",
        "dac", "hi-fi", "hifi",
    ]),
    ("Cameras, Drones & 3D", [
        "camera", "drone", "gimbal", "camera lens", "gopro", "3d printer",
        "filament", "tripod", "action cam", "instax", "mirrorless",
    ]),
    ("Gaming", [
        "playstation", "xbox", "nintendo", "steam deck", "controller", "gamepad",
        "gaming mouse", "gaming keyboard", "vr headset", "joy-con", "dualsense",
        "racing wheel", "gaming chair",
    ]),
    ("Computers & Tablets", [
        "laptop", "macbook", "notebook pc", "desktop pc", "tablet", "ipad",
        "chromebook", "all-in-one", "mini pc", "workstation", "thinkpad",
        "server", "nuc",
    ]),
    ("PC Parts (Components)", [
        "motherboard", "graphics card", "processor", "cpu cooler", "power supply",
        "psu", "ddr4", "ddr5", "ram ", "geforce", "radeon", "pc case", "chassis",
        "aio cooler", "thermal paste", "case fan", "watercool",
    ]),
    ("PC Peripherals", [
        "keyboard", "mouse", "mousepad", "webcam", "kvm", "usb hub",
        "docking station", "graphics tablet", "numpad", "trackball",
    ]),
    ("Networking", [
        "router", "access point", "network switch", "modem", "mesh wifi",
        "wi-fi 6", "wifi 6", "ethernet", "poe ", "firewall", "powerline",
        "range extender", "sfp",
    ]),
    ("Security & Surveillance", [
        "security camera", "cctv", "doorbell", "alarm", "nvr", "dvr",
        "smart lock", "surveillance", "motion sensor",
    ]),
    ("Smart Home & Appliances", [
        "air fryer", "vacuum", "dehumidifier", "purifier", "kettle", "toaster",
        "microwave", "heater", "smart bulb", "smart plug", "toothbrush",
        "coffee machine", "blender", "washing machine", "fridge", "shaver",
        "smart home", "robot vac", "humidifier", "fan heater",
    ]),
    ("Furniture & Mounts", [
        "chair", "standing desk", "tv wall mount", "monitor arm", "monitor stand",
        "vesa", "wall bracket", "desk mount", "laptop stand",
    ]),
    ("Cables & Power", [
        "cable", "adapter", "charger", "power bank", "powerbank", "ups ",
        "surge protector", "extension lead", "multi-box", "battery",
        "usb-c to", "hdmi ", "displayport", "power board", "inverter",
    ]),
    ("Printing & Office", [
        "printer", "ink cartridge", "toner", "scanner", "laminator", "shredder",
        "label maker", "paper", "stationery", "whiteboard", "pen ", "notebook ",
    ]),
    ("POS & Barcode", ["barcode", "receipt printer", "pos ", "cash drawer", "till "]),
    ("Car & Travel", [
        "dash cam", "dashcam", "car charger", "car mount", "luggage", "backpack",
        "jump starter", "gps navigat",
    ]),
    ("Tools & Workshop", [
        "drill", "screwdriver", "multimeter", "soldering", "tool kit",
        "spanner", "heat gun", "workbench",
    ]),
    ("Gift Cards & Services", [
        "gift card", "warranty", "installation service", "subscription",
        "licence", "license", "software",
    ]),
]

PREFIX_HINTS: dict[str, str] = {
    "HST": "Audio",       "SPK": "Audio",       "MIC": "Audio",
    "MON": "Monitors & Displays",                "PRJ": "Monitors & Displays",
    "CAB": "Cables & Power",                     "BAP": "Cables & Power",
    "PWR": "Cables & Power",                     "UPS": "Cables & Power",
    "NET": "Networking",  "WIR": "Networking",
    "CHR": "Furniture & Mounts",                 "MOA": "Furniture & Mounts",
    "DSK": "Furniture & Mounts",
    "HOM": "Smart Home & Appliances",            "HEA": "Smart Home & Appliances",
    "CHA": "PC Parts (Components)",              "CPU": "PC Parts (Components)",
    "MBO": "PC Parts (Components)",              "VGA": "PC Parts (Components)",
    "MEM": "PC Parts (Components)",              "FAN": "PC Parts (Components)",
    "KEY": "PC Peripherals",                     "MSE": "PC Peripherals",
    "HDD": "Storage & NAS",                      "SSD": "Storage & NAS",
    "MEC": "Storage & NAS",
    "NBK": "Computers & Tablets",                "WKS": "Computers & Tablets",
    "TAB": "Computers & Tablets",                "EXW": "Computers & Tablets",
    "PHO": "Phones & Wearables",                 "WAT": "Phones & Wearables",
    "WTH": "Phones & Wearables",
    "CAM": "Cameras, Drones & 3D",               "DRN": "Cameras, Drones & 3D",
    "GAM": "Gaming",                             "CON": "Gaming",
    "GUN": "Gaming",
    "PRT": "Printing & Office",                  "INK": "Printing & Office",
    "TON": "Printing & Office",                  "BOK": "Printing & Office",
    "DVA": "Monitors & Displays",
    "SEC": "Security & Surveillance",
}

OTHER = "Other"


def categorise(name: str, part: str) -> str:
    low = f" {(name or '').lower()} "
    for cat, keys in CATEGORY_RULES:
        for k in keys:
            if k in low:
                return cat
    m = re.match(r"([A-Z]{3})", (part or "").upper())
    if m and m.group(1) in PREFIX_HINTS:
        return PREFIX_HINTS[m.group(1)]
    return OTHER


# --------------------------------------------------------------------------- #
# Load + clean
# --------------------------------------------------------------------------- #

def to_float(v):
    if v is None:
        return None
    s = str(v).replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def load(csv_path: Path):
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    seen: set[str] = set()
    out, dupes, unnamed = [], 0, 0

    for r in rows:
        part = (r.get("Part Number") or "").strip()
        name = (r.get("Name") or "").strip()
        if not part and not name:
            continue
        if part:
            if part in seen:
                dupes += 1
                continue
            seen.add(part)
        else:
            unnamed += 1

        orig = to_float(r.get("Original Price"))
        disc = to_float(r.get("Discounted Price"))
        pct = to_float(r.get("% Off"))
        promo = (r.get("Promo Code") or "").strip().upper() or None

        if disc is None or orig is None:
            status, pct = "unknown", None
        elif promo:
            status = "promo"
        else:
            status = "special"

        if pct is None and status != "unknown" and orig:
            pct = round((orig - disc) / orig * 100, 2)

        out.append([
            part or "-", name or "(no name)", orig, disc, pct, promo or "",
            categorise(name, part),
            {"promo": 0, "special": 1, "unknown": 2}[status],
        ])

    return out, dupes, unnamed


# --------------------------------------------------------------------------- #
# Page template
# --------------------------------------------------------------------------- #

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PB Deals &middot; __COUNT__ products</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{
  --page:#080B11; --panel:#132340; --panel2:#0F1B31;
  --surface:#101724; --row:#141C2B; --rowhi:#1B2536; --sunk:#0B111B;
  --line:#233150; --line2:#1A2438;
  --ink:#F4F8FD; --muted:#B3C3D8; --faint:#8296AF;
  --accent:#F2762B; --accent-ink:#160800; --accent-soft:#2A1A0E;
  --ok:#3FBF87;
  --pill-bg-l:19%; --pill-bg-s:44%; --pill-tx-l:75%; --pill-tx-s:80%;
  --shadow:0 1px 2px rgba(0,0,0,.5),0 14px 34px -20px rgba(0,0,0,.9);
}
html[data-theme="light"]{
  --page:#E7EBF1; --panel:#152743; --panel2:#1B3155;
  --surface:#FFFFFF; --row:#FFFFFF; --rowhi:#F3F6FA; --sunk:#EEF2F7;
  --line:#D6DEE9; --line2:#E4EAF2;
  --ink:#0E1826; --muted:#4E6178; --faint:#75879C;
  --accent:#D65A12; --accent-ink:#FFFFFF; --accent-soft:#FBEDE4;
  --ok:#1E8F5F;
  --pill-bg-l:93%; --pill-bg-s:72%; --pill-tx-l:29%; --pill-tx-s:58%;
  --shadow:0 1px 2px rgba(16,28,42,.07),0 12px 30px -20px rgba(16,28,42,.4);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--page);color:var(--ink);
  font:15px/1.45 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}
.mono{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
a{color:inherit;text-decoration:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}

/* ---------- contained shell ---------- */
.shell{max-width:1280px;margin:0 auto;padding:18px 20px 40px}

/* ---------- header card ---------- */
.head{background:var(--panel);border-radius:16px;padding:16px 20px;box-shadow:var(--shadow)}
.headtop{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap}
.title{margin-right:auto;min-width:0}
.title h1{font-family:"Space Grotesk",sans-serif;font-size:23px;font-weight:700;
  margin:0;color:#fff;letter-spacing:-.02em}
.title .stamp{display:block;margin-top:3px;font-size:11.5px;color:#8FA6C4;letter-spacing:.02em}
.hbtns{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.found{font-family:"JetBrains Mono",monospace;font-size:12px;color:#8FA6C4;
  white-space:nowrap;margin-right:4px}
.found b{color:var(--accent);font-size:17px;display:block;line-height:1.1}
.btn{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);color:#EAF1FA;
  padding:8px 14px;border-radius:9px;font-size:13.5px;font-weight:600;
  transition:background .12s,border-color .12s}
.btn:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.3)}
.btn.go{background:var(--accent);border-color:transparent;color:#fff}
.btn.go:hover{filter:brightness(1.1)}

/* ---------- filters ---------- */
.frow{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:13px}
.frow.chipsrow{align-items:flex-start;gap:10px;padding-top:12px;
  border-top:1px solid rgba(255,255,255,.09)}
.grow{flex:1 1 240px;min-width:170px}
.field{background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.14);color:#F2F7FC;
  padding:9px 13px;border-radius:9px;font-size:14px;width:100%}
.field::placeholder{color:#7D93B0}
.field:focus{border-color:var(--accent);outline:none;background:rgba(0,0,0,.4)}
.seg{display:flex;align-items:center;gap:6px;background:rgba(0,0,0,.28);
  border:1px solid rgba(255,255,255,.14);border-radius:9px;padding:4px 11px;flex:none}
.seg .cap{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#8FA6C4;font-weight:700}
.seg .field{background:transparent;border:0;padding:4px 0;width:58px;text-align:center;font-size:13px}
.seg .sep{color:#6F86A5}
.flabel{font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;
  color:#8FA6C4;flex:none;width:62px;padding-top:7px}
.toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;
  color:#A9BDD6;flex:none;user-select:none}
.toggle input{appearance:none;width:34px;height:19px;background:rgba(255,255,255,.16);
  border-radius:999px;position:relative;transition:background .15s;flex:none;cursor:pointer}
.toggle input::after{content:"";position:absolute;top:2px;left:2px;width:15px;height:15px;
  border-radius:50%;background:#fff;transition:transform .15s}
.toggle input:checked{background:var(--accent)}
.toggle input:checked::after{transform:translateX(15px)}
.toggle input:checked+span{color:#fff;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:6px;flex:1}
.chip{background:rgba(0,0,0,.26);border:1px solid rgba(255,255,255,.13);color:#BACBE0;
  padding:5px 11px;border-radius:999px;font-size:12.5px;font-weight:600;
  display:inline-flex;align-items:center;gap:6px;transition:all .12s;line-height:1.2}
.chip:hover{border-color:rgba(255,255,255,.4);color:#fff}
.chip .n{opacity:.6;font-size:10.5px;font-family:"JetBrains Mono",monospace;font-weight:500}
.chip .sw{width:8px;height:8px;border-radius:50%;flex:none}

/* ---------- results ---------- */
.panel{background:var(--surface);border:1px solid var(--line2);border-radius:16px;
  margin-top:16px;box-shadow:var(--shadow);overflow:hidden}
.pbar{display:flex;align-items:center;gap:9px;padding:11px 16px;flex-wrap:wrap;
  border-bottom:1px solid var(--line2);background:var(--rowhi)}
.pbar .range{font-size:12.5px;color:var(--muted);font-family:"JetBrains Mono",monospace;
  margin-right:auto;font-weight:500}
.sel{background:var(--sunk);border:1px solid var(--line);color:var(--ink);
  padding:6px 10px;border-radius:8px;font-size:13px}
.pg{display:flex;gap:5px;align-items:center}
.pg button{background:var(--sunk);border:1px solid var(--line);color:var(--ink);
  padding:6px 12px;border-radius:8px;font-size:13px;font-weight:600}
.pg button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.pg button:disabled{opacity:.3;cursor:default}
.pg input{width:54px;text-align:center;background:var(--sunk);border:1px solid var(--line);
  padding:6px;border-radius:8px;font-family:"JetBrains Mono",monospace;font-size:13px}

table{width:100%;border-collapse:collapse;table-layout:fixed}
thead th{text-align:left;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--faint);font-weight:700;padding:11px 14px;white-space:nowrap;
  border-bottom:1px solid var(--line2);cursor:pointer;user-select:none;background:var(--surface)}
thead th:hover{color:var(--ink)}
thead th .ar{color:var(--accent);font-size:9px}
.cw-rail{width:5px}.cw-part{width:132px}.cw-price{width:126px}
.cw-pct{width:84px}.cw-promo{width:118px}.cw-g{width:52px}
tbody tr{border-bottom:1px solid var(--line2);transition:background .1s}
tbody tr:last-child{border-bottom:0}
tbody tr:hover{background:var(--rowhi)}
td{padding:10px 14px;vertical-align:middle}
td.rail{padding:0}
.railbar{width:5px;height:100%;min-height:46px;display:block}
.pname{font-size:13.5px;line-height:1.35;font-weight:500;cursor:pointer;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pname:hover{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.catline{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:11px;font-weight:600}
.catdot{width:7px;height:7px;border-radius:50%;flex:none}
.part{font-family:"JetBrains Mono",monospace;font-size:11.5px;color:var(--muted);
  border:1px solid transparent;padding:3px 6px;border-radius:6px;cursor:copy;
  display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.part:hover{color:var(--accent);border-color:var(--line);background:var(--sunk)}
td.num{font-family:"JetBrains Mono",monospace;text-align:right;white-space:nowrap}
.was{color:var(--faint);text-decoration:line-through;font-size:11.5px;display:block;line-height:1.3}
.now{font-weight:700;font-size:14.5px;line-height:1.3}
.pct{display:inline-block;padding:4px 0;border-radius:7px;font-family:"JetBrains Mono",monospace;
  font-weight:700;font-size:12.5px;color:#fff;width:62px;text-align:center}
.tag{display:inline-block;padding:4px 9px;border-radius:7px;font-size:10.5px;font-weight:700;
  letter-spacing:.05em;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.tag.plain{background:var(--sunk);border:1px solid var(--line);color:var(--faint)}
.tag.spec{background:var(--accent-soft);color:var(--accent);
  border:1px solid color-mix(in srgb,var(--accent) 38%,transparent)}
.gbtn{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;
  border-radius:8px;border:1px solid var(--line);background:var(--sunk);
  font-family:"Space Grotesk",sans-serif;font-weight:700;font-size:15px;color:var(--faint);
  transition:all .12s}
.gbtn:hover{color:#fff;background:var(--accent);border-color:transparent}
.empty{padding:64px 20px;text-align:center;color:var(--muted)}
.empty b{display:block;font-family:"Space Grotesk",sans-serif;font-size:18px;
  color:var(--ink);margin-bottom:6px}
.toast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,14px);background:var(--ink);
  color:var(--page);padding:10px 18px;border-radius:10px;font-size:13px;font-weight:700;
  opacity:0;pointer-events:none;transition:all .18s;z-index:90}
.toast.on{opacity:1;transform:translate(-50%,0)}

/* ---------- responsive ---------- */
#more{display:none}
@media (max-width:1080px){
  .cw-part{display:none}
  td.cpart{display:none}
}
@media (max-width:860px){
  .shell{padding:12px 12px 32px}
  .head{padding:14px;border-radius:14px}
  .title h1{font-size:20px}
  #more{display:inline-flex}
  .fold{display:none}
  .head.open .fold{display:flex}
  .flabel{width:100%;padding-top:0;margin-bottom:-2px}

  thead{display:none}
  tbody tr{display:grid;grid-template-columns:5px 1fr auto;gap:0 12px;
    padding:0 14px 12px 0;align-items:start}
  td{padding:0;border:0}
  td.rail{grid-row:1/span 3;align-self:stretch}
  .railbar{min-height:100%}
  td.cname{grid-column:2/span 2;padding:12px 0 6px}
  .pname{-webkit-line-clamp:3;font-size:14px}
  td.cprice{grid-column:2;text-align:left;display:flex;gap:9px;align-items:baseline}
  .was{display:inline;font-size:12px}
  td.cpct{grid-column:3;grid-row:2;justify-self:end}
  td.ctag{grid-column:2;padding-top:8px}
  td.cgo{grid-column:3;padding-top:8px;justify-self:end}
  .pbar{padding:10px 12px;gap:7px}
  .pbar .range{width:100%;margin:0 0 2px}
  .pg{flex:1;justify-content:space-between}
  .seg,.grow{flex:1 1 100%}
  .seg .field{width:100%}
}
</style>
</head>
<body>
<div class="shell">

  <div class="head" id="head">
    <div class="headtop">
      <div class="title">
        <h1>PB Deals</h1>
        <span class="stamp mono">Scraped __GENERATED__ &middot; prices incl. GST</span>
      </div>
      <div class="hbtns">
        <span class="found">FOUND<b id="found">0</b></span>
        <button class="btn" id="more">Filters</button>
        <button class="btn" id="export">Export</button>
        <button class="btn" id="theme">Light</button>
      </div>
    </div>

    <div class="frow">
      <input class="field grow" id="q" placeholder="Search name, part # or promo" autocomplete="off">
      <div class="seg"><span class="cap">NZ$</span>
        <input class="field mono" id="pmin" placeholder="min" inputmode="decimal">
        <span class="sep">–</span>
        <input class="field mono" id="pmax" placeholder="max" inputmode="decimal"></div>
      <div class="seg"><span class="cap">% off</span>
        <input class="field mono" id="dmin" placeholder="0" inputmode="numeric">
        <span class="sep">–</span>
        <input class="field mono" id="dmax" placeholder="100" inputmode="numeric"></div>
      <label class="toggle"><input type="checkbox" id="tSpecial" checked><span>Specials</span></label>
      <label class="toggle"><input type="checkbox" id="tUnknown"><span>Unknown</span></label>
      <button class="btn" id="reset">Reset</button>
    </div>

    <div class="frow chipsrow fold">
      <span class="flabel">Promo</span>
      <div class="chips" id="promos"></div>
    </div>
    <div class="frow chipsrow fold">
      <span class="flabel">Category</span>
      <div class="chips" id="cats"></div>
    </div>
  </div>

  <div class="panel">
    <div class="pbar">
      <span class="range" id="range"></span>
      <select class="sel" id="rows">
        <option>25</option><option selected>50</option>
        <option>100</option><option>250</option><option>500</option>
      </select>
      <div class="pg">
        <button id="first">&laquo;</button><button id="prev">Prev</button>
        <input class="mono" id="pageno" value="1">
        <button id="next">Next</button><button id="last">&raquo;</button>
      </div>
    </div>
    <table>
      <colgroup>
        <col class="cw-rail"><col><col class="cw-part"><col class="cw-price">
        <col class="cw-pct"><col class="cw-promo"><col class="cw-g">
      </colgroup>
      <thead><tr>
        <th></th>
        <th data-s="name">Product <span class="ar"></span></th>
        <th data-s="part">Part # <span class="ar"></span></th>
        <th data-s="price" style="text-align:right">Price <span class="ar"></span></th>
        <th data-s="pct" style="text-align:right">% Off <span class="ar">▼</span></th>
        <th data-s="promo">Promo <span class="ar"></span></th>
        <th></th>
      </tr></thead>
      <tbody id="tb"></tbody>
    </table>
    <div class="empty" id="empty" hidden>
      <b>Nothing matches these filters</b>
      Widen the price or discount range, or switch on Unknown items.
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const RAW = __DATA__;
const STATUS=["promo","special","unknown"];
const D=RAW.map(r=>({part:r[0],name:r[1],orig:r[2],disc:r[3],pct:r[4],promo:r[5],
                     cat:r[6],st:STATUS[r[7]],
                     hay:(r[0]+" "+r[1]+" "+r[5]).toLowerCase()}));

const slug=n=>n.replace(/ /g,"-").replace(/[^A-Za-z0-9-]/g,"").slice(0,50).replace(/-+$/,"");
const pbUrl=d=>`https://www.pbtech.co.nz/product/${encodeURIComponent(d.part)}/${slug(d.name)}`;
const gUrl=d=>`https://www.google.com/search?q=${encodeURIComponent(d.part+" "+d.name.slice(0,70))}`;

/* discount heat - warm ramp, readable on both themes */
const HEAT=[[60,"#E0417A"],[40,"#EE5B39"],[25,"#F0871F"],[10,"#D9A81C"],[0,"#6C7F99"]];
const HEAT_L=[[60,"#C21E5C"],[40,"#D0421D"],[25,"#C46A08"],[10,"#A8820A"],[0,"#5A6C85"]];
const isDark=()=>document.documentElement.dataset.theme!=="light";
function heat(p){
  const t=isDark()?HEAT:HEAT_L;
  if(p==null)return t[4][1];
  for(const [min,c] of t) if(p>=min) return c;
  return t[4][1];
}

/* curated hues, assigned by sorted index so colours are stable and distinct */
const HUES=[210,168,142,30,266,330,190,104,352,44,238,296,158,14,318,80];
const catIdx={},promoIdx={};
[...new Set(D.map(d=>d.cat))].sort().forEach((c,i)=>catIdx[c]=HUES[i%HUES.length]);
[...new Set(D.map(d=>d.promo).filter(Boolean))].sort().forEach((p,i)=>promoIdx[p]=HUES[(i+5)%HUES.length]);
const hueFor=(v,map)=>map[v]??210;
function pill(v,map){
  const h=hueFor(v,map);
  return isDark()?`background:hsl(${h} 44% 19%);color:hsl(${h} 80% 76%)`
                 :`background:hsl(${h} 72% 93%);color:hsl(${h} 58% 28%)`;
}
const solid=(v,map)=>`hsl(${hueFor(v,map)} ${isDark()?"62% 62%":"56% 42%"})`;

const money=v=>v==null?"":"$"+v.toLocaleString("en-NZ",{minimumFractionDigits:2,maximumFractionDigits:2});
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const S={q:"",pmin:null,pmax:null,dmin:null,dmax:null,special:true,unknown:false,
         promos:new Set(),cats:new Set(),sort:"pct",dir:-1,page:1,rows:50};

/* ---- chips ---- */
function tally(key){
  const m=new Map();
  D.forEach(d=>{const v=d[key];if(v)m.set(v,(m.get(v)||0)+1)});
  return [...m.entries()].sort((a,b)=>b[1]-a[1]);
}
const CHIPS=[];
function chipRow(host,items,set,map){
  const draw=()=>{host.innerHTML=items.map(([v,n])=>{
    const on=set.has(v);
    return `<button class="chip" data-v="${esc(v)}" aria-pressed="${on}" `+
      `style="${on?pill(v,map)+";border-color:transparent":""}">`+
      `<span class="sw" style="background:${solid(v,map)}"></span>${esc(v)}`+
      `<span class="n">${n}</span></button>`}).join("")};
  host.onclick=e=>{const b=e.target.closest(".chip");if(!b)return;
    const v=b.dataset.v;set.has(v)?set.delete(v):set.add(v);S.page=1;draw();render()};
  CHIPS.push(draw);draw();
}
chipRow($("#promos"),tally("promo"),S.promos,promoIdx);
chipRow($("#cats"),tally("cat"),S.cats,catIdx);

/* ---- filter + sort ---- */
function pass(d){
  if(d.st==="unknown"&&!S.unknown)return false;
  if(d.st==="special"&&!S.special)return false;
  if(S.q&&!d.hay.includes(S.q))return false;
  const p=d.disc!=null?d.disc:d.orig;
  if(S.pmin!=null&&(p==null||p<S.pmin))return false;
  if(S.pmax!=null&&(p==null||p>S.pmax))return false;
  if(S.dmin!=null||S.dmax!=null){
    if(d.pct==null)return false;
    if(S.dmin!=null&&d.pct<S.dmin)return false;
    if(S.dmax!=null&&d.pct>S.dmax)return false;
  }
  if(S.promos.size&&!S.promos.has(d.promo))return false;
  if(S.cats.size&&!S.cats.has(d.cat))return false;
  return true;
}
const KEY={name:d=>d.name.toLowerCase(),part:d=>d.part,promo:d=>d.promo,
           price:d=>d.disc!=null?d.disc:(d.orig!=null?d.orig:-1),
           pct:d=>d.pct==null?-1:d.pct};

let view=[];
function render(){
  view=D.filter(pass);
  const k=KEY[S.sort];
  view.sort((a,b)=>{const x=k(a),y=k(b);return (x>y?1:x<y?-1:0)*S.dir});
  $("#found").textContent=view.length.toLocaleString();

  const pages=Math.max(1,Math.ceil(view.length/S.rows));
  if(S.page>pages)S.page=pages;
  const a=(S.page-1)*S.rows,b=Math.min(a+S.rows,view.length);
  $("#range").textContent=view.length
    ?`${(a+1).toLocaleString()}–${b.toLocaleString()} of ${view.length.toLocaleString()}`:"0 results";
  $("#pageno").value=S.page;
  $("#first").disabled=$("#prev").disabled=S.page<=1;
  $("#last").disabled=$("#next").disabled=S.page>=pages;
  $("#empty").hidden=view.length>0;

  $("#tb").innerHTML=view.slice(a,b).map(d=>{
    const hc=heat(d.pct);
    const price=d.disc!=null
      ?`<span class="was">${money(d.orig)}</span><span class="now" style="color:${hc}">${money(d.disc)}</span>`
      :`<span class="now">${money(d.orig)}</span>`;
    const pct=d.pct!=null?`<span class="pct" style="background:${hc}">${d.pct.toFixed(1)}%</span>`:"";
    const tag=d.promo?`<span class="tag" style="${pill(d.promo,promoIdx)}">${esc(d.promo)}</span>`
      :d.st==="special"?`<span class="tag spec">SPECIAL</span>`
      :`<span class="tag plain">UNKNOWN</span>`;
    return `<tr>
      <td class="rail"><span class="railbar" style="background:${hc}"></span></td>
      <td class="cname">
        <div class="pname" data-u="${esc(pbUrl(d))}" title="${esc(d.name)}">${esc(d.name)}</div>
        <div class="catline" style="color:${solid(d.cat,catIdx)}">
          <span class="catdot" style="background:${solid(d.cat,catIdx)}"></span>${esc(d.cat)}</div>
      </td>
      <td class="cpart"><span class="part" data-c="${esc(d.part)}" title="Copy part number">${esc(d.part)}</span></td>
      <td class="num cprice">${price}</td>
      <td class="num cpct">${pct}</td>
      <td class="ctag">${tag}</td>
      <td class="cgo"><a class="gbtn" href="${esc(gUrl(d))}" target="_blank" rel="noopener"
        title="Compare prices on Google">G</a></td>
    </tr>`}).join("");
}

/* ---- interaction ---- */
let toastT;
function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("on");
  clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove("on"),1300)}

$("#tb").onclick=e=>{
  if(e.target.closest(".gbtn"))return;            /* let the Google link do its thing */
  const p=e.target.closest(".part");
  if(p){navigator.clipboard?.writeText(p.dataset.c);toast("Copied "+p.dataset.c);return}
  const n=e.target.closest(".pname");
  if(n)window.open(n.dataset.u,"_blank","noopener");
};

let t;const deb=f=>{clearTimeout(t);t=setTimeout(f,140)};
$("#q").oninput=e=>deb(()=>{S.q=e.target.value.trim().toLowerCase();S.page=1;render()});
const numf=(id,key)=>$(id).oninput=e=>deb(()=>{
  const v=parseFloat(e.target.value);S[key]=isNaN(v)?null:v;S.page=1;render()});
numf("#pmin","pmin");numf("#pmax","pmax");numf("#dmin","dmin");numf("#dmax","dmax");
$("#tSpecial").onchange=e=>{S.special=e.target.checked;S.page=1;render()};
$("#tUnknown").onchange=e=>{S.unknown=e.target.checked;S.page=1;render()};

document.querySelectorAll("thead th[data-s]").forEach(th=>th.onclick=()=>{
  const s=th.dataset.s;
  if(S.sort===s)S.dir*=-1;else{S.sort=s;S.dir=(s==="pct"||s==="price")?-1:1}
  document.querySelectorAll("thead .ar").forEach(x=>x.textContent="");
  th.querySelector(".ar").textContent=S.dir>0?"▲":"▼";
  render();
});
$("#rows").onchange=e=>{S.rows=+e.target.value;S.page=1;render()};
const top0=()=>scrollTo({top:0,behavior:"smooth"});
$("#first").onclick=()=>{S.page=1;render();top0()};
$("#prev").onclick=()=>{S.page--;render();top0()};
$("#next").onclick=()=>{S.page++;render();top0()};
$("#last").onclick=()=>{S.page=Math.ceil(view.length/S.rows);render();top0()};
$("#pageno").onchange=e=>{const v=parseInt(e.target.value);if(v>0){S.page=v;render()}};

$("#reset").onclick=()=>{
  Object.assign(S,{q:"",pmin:null,pmax:null,dmin:null,dmax:null,
                   special:true,unknown:false,sort:"pct",dir:-1,page:1});
  S.promos.clear();S.cats.clear();
  ["#q","#pmin","#pmax","#dmin","#dmax"].forEach(i=>$(i).value="");
  $("#tSpecial").checked=true;$("#tUnknown").checked=false;
  document.querySelectorAll("thead .ar").forEach(x=>x.textContent="");
  document.querySelector('th[data-s="pct"] .ar').textContent="▼";
  CHIPS.forEach(f=>f());render();
};
$("#more").onclick=()=>$("#head").classList.toggle("open");

const setTheme=t=>{document.documentElement.dataset.theme=t;
  $("#theme").textContent=t==="dark"?"Light":"Dark";
  try{localStorage.setItem("pbtheme",t)}catch(e){}
  CHIPS.forEach(f=>f());render()};
$("#theme").onclick=()=>setTheme(isDark()?"light":"dark");
try{const s=localStorage.getItem("pbtheme");if(s)setTheme(s)}catch(e){}

$("#export").onclick=()=>{
  const head=["Part Number","Name","Original Price","Discounted Price","% Off","Promo Code","Category","Status","URL"];
  const q=v=>`"${String(v??"").replace(/"/g,'""')}"`;
  const csv=[head.join(",")].concat(view.map(d=>
    [d.part,d.name,d.orig??"",d.disc??"",d.pct??"",d.promo,d.cat,d.st,pbUrl(d)].map(q).join(","))).join("\r\n");
  const u=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
  const a=document.createElement("a");a.href=u;a.download="pb-deals-view.csv";a.click();
  URL.revokeObjectURL(u);toast("Exported "+view.length+" rows");
};

addEventListener("keydown",e=>{
  if(e.key==="/"&&document.activeElement.tagName!=="INPUT"){e.preventDefault();$("#q").focus()}
});

render();
</script>
</body>
</html>
"""


def build(rows, generated: str) -> str:
    return (TEMPLATE
            .replace("__DATA__", json.dumps(rows, separators=(",", ":")))
            .replace("__GENERATED__", generated)
            .replace("__COUNT__", str(len(rows))))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a deals browser page from cat.csv")
    ap.add_argument("--csv", default="cat.csv")
    ap.add_argument("--out", default="index.html")
    ap.add_argument("--open", action="store_true", help="open the page when done")
    args = ap.parse_args()

    src = Path(args.csv)
    if not src.exists():
        sys.exit(f"Can't find {src}. Run the scraper first, or pass --csv <path>.")

    rows, dupes, unnamed = load(src)
    if not rows:
        sys.exit(f"{src} has no usable rows.")

    generated = datetime.now().strftime("%d/%m/%Y at %I:%M %p").lstrip("0")
    out = Path(args.out)
    out.write_text(build(rows, generated), encoding="utf-8")

    st = Counter(r[7] for r in rows)
    cats = Counter(r[6] for r in rows)
    print(f"[done] {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"       {len(rows):,} products  |  {dupes:,} duplicate part numbers dropped")
    print(f"       {st[0]:,} promo   {st[1]:,} special   {st[2]:,} unknown")
    if unnamed:
        print(f"       {unnamed:,} rows had no part number (kept, not de-duplicated)")
    print("       top categories: " +
          ", ".join(f"{c} {n}" for c, n in cats.most_common(5)))
    if cats.get(OTHER, 0) > len(rows) * 0.25:
        print(f"       note: {cats[OTHER]:,} landed in 'Other' - "
              f"add keywords to CATEGORY_RULES to sharpen this")

    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()