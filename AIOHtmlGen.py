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
  * uses PB Tech's own category when the CSV has one (newScrape.py collects it);
    otherwise assigns one from the product name, with the part-number prefix as a
    tiebreaker (CATEGORY_RULES / PREFIX_HINTS below are heuristics - edit them)
  * stamps the page with the time this script ran

THE PAGE
  * product cards (with optional photos, off by default - toggle "Images")
  * Sort By + Then By; price sorts group into price ranges, best deals first
  * filters + title at the top on desktop, slide-out filter panel on phones
  * click the PB Deals logo to reset everything

LINKS
  Product name / View button -> the PB Tech product page
  G button                   -> a Google search for the part number and name
  Part number / promo code   -> click to copy

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
# Money: ads + affiliate links.  Everything is OFF while these are blank.
# --------------------------------------------------------------------------- #
# 1. Paste your AdSense publisher ID (AdSense > Account > Account information).
#    With ONLY this set, Google "Auto ads" place ads for you (turn Auto ads on in
#    your AdSense dashboard). The script also writes ads.txt + privacy.html.
ADSENSE_CLIENT = ""            # e.g. "ca-pub-1234567890123456"

# 2. Optional: your own ad units (AdSense > Ads > By ad unit > Display ads).
#    Paste just the data-ad-slot number of each. Leave blank to skip that spot.
AD_SLOT_TOP = ""               # banner between the filters and the results
AD_SLOT_FEED = ""              # full-width ad between rows of product cards
AD_FEED_EVERY = 16             # cards between in-feed ads
AD_FEED_MAX_PER_PAGE = 2       # cap, so ads never crowd the deals

# 3. Optional: affiliate link wrapper for "View on PB Tech" links, if you join a
#    network that offers one. Use {url} where the product link goes, e.g.
#    "https://network.example/click?id=123&url={url}"
AFFILIATE_URL = ""

# 4. Shown on privacy.html (AdSense requires a privacy policy).
CONTACT_EMAIL = ""             # e.g. "you@example.com"


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

        image = (r.get("Image") or "").strip()
        if image and not image.startswith(("http://", "https://")):
            image = ""

        out.append([
            part or "-", name or "(no name)", orig, disc, pct, promo or "",
            (r.get("Category") or "").strip() or categorise(name, part),   # PB's own category if newScrape found it
            {"promo": 0, "special": 1, "unknown": 2}[status],
            image,
        ])

    return out, dupes, unnamed


# --------------------------------------------------------------------------- #
# Page template
# --------------------------------------------------------------------------- #

# Favicon (orange bolt on PB navy) - embedded so the page stays one file.
FAVICON_SVG = "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+CiAgPGRlZnM+CiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImJnIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+PHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjMUIzMzU4Ii8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjMEMxNjI2Ii8+PC9saW5lYXJHcmFkaWVudD4KICAgIDxsaW5lYXJHcmFkaWVudCBpZD0iYm9sdCIgeDE9IjAiIHkxPSIwIiB4Mj0iMCIgeTI9IjEiPjxzdG9wIG9mZnNldD0iMCIgc3RvcC1jb2xvcj0iI0ZGQjQ1QyIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0YyNzYyQiIvPjwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSI2NCIgcng9IjE1IiBmaWxsPSJ1cmwoI2JnKSIvPgogIDxwYXRoIGQ9Ik0zNi41IDggMTUgMzZoMTMuNUwyNSA1NmwyNC0zMC41SDM1LjJMMzYuNSA4eiIgZmlsbD0idXJsKCNib2x0KSIvPgo8L3N2Zz4K"
FAVICON_32 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAEnklEQVR4nJxXX4hUVRj/nXvvOO0m7aYxrtof/+BulCsJPShRkIJYYFAsZRGtRYKQ0EPQS4IPPfXUQyAIK2hgQS9JQgix4sI+6ItIyZKLiFTaLrvbZO5sO87c8/mde+6fc8+cmb3MoHvv78w53/l+v+/PORPA+mx84a1DJMR+ItrOcIikDIQAGIMf/JTRvEKYByTJpge6ISV+Y3hhbnr8jLmfSF7W7Xiz4vvBGEgeIBBiK9H/HFaIWrGIN81wvC76F2P9/bnGcvOje39MVlMHNu4c2SuJvhNCVBSDzJhm1A1zVi6yTtLC2t6fYSjeq966NOlB+3yYByumEc3ExJ2epjPZOjhxNO8p35NHIwU27Bw5yM/vE6aSPTVjLg1F2jHfVvHhM/h9tqmZupQgMwxqgrIr3vUYH2k1Sm2xPf7oKoFvP1iN5YbMnFMxFy4ltLJI54VHOARyU24TaON6UpZgNqYYn3i7F5sfF/hnMcw7JxN72TqbBJHYFLCjA/ksLR7zj3eVsG/Qh2xK3FvW7IRVJSY5tFQLBgKOcbmbOh9e7+H4vjIoDLFQM2KujAu79MxqyjlTDkQhxnkm/Y8AZ94pw1fO8JCSX8ec2sQ8zxyG3SCJeVHmavHYSBnrehlLEX1frUkdc6Fj3imRYY0HKzGH5cznr/jY/SRUfaZyL9RCR4zRkXmSmAEVqPMEv7pF4NNdPBrKuNRExLzM8u9+2svar8H05nwTs4sm80xJtYEYGD5ARXr7+tWE8UM++spCs4kyDvHHjW9XJfaeWkStnu+wMEo+KMK85AOn3hDoK1HU2YTiqpQTIs72VrzEjen9H/7Pbe46Y4KVYq5MHn+ZsOMJfgvVuIibS+fn0fP1SH475gnzVAGscKq9vkVilG8GavOIIbU+46af4pNXQ/w83XTGXCuY9YvALY9m/sxjEl/v4YQLY5mhjWmeGSYDX75D+HLiQU5R2AobiSoqz71GXZznuHiQMLhGxPP1c3YJ2HO2gX+XXYrmmVN86gaumLs7WoJ5EZfdVlZHhvpGo1bzcYDRn2S6OVxnC1r7TD4HYsY57Ojt29bwu5QpczXxiwm+9M2tHHOdO5kzgYt5dp67e/uz/aoNyzgXgB9vAmenRPuYt3mqeV6OKYzYdTjPlQNRSfKcX2cJn02IdJ3Z8QRRpkSUA3EjSsPOISgScxsP9YWRAtU68OEvJdSb7evcrUAW9kgB3R1dCUPWIo2VAyFn3eFxHzM1PZ5jSpRXwmJuKuVxDV4pcodLlOjlA3ygHOKrqz4uz4h0fqvzreOwTkO2e4V/tNC1onc49Xm+v4mLf3k4cd1vH3NDMTvmphNM8xpfSr0xLpUwYw60P88lenzCJ5Ol2EnpZN4p5okd/hP6Qp70lxZu3e1du3kDL37Rvre75Lt9H2hIWNltYT2QKWPJHx/o3/z399Tp6JfRKkHHePP5vIe2x+iqzp12pLzT08Qx9R45cHf60nyjHg7yV+c6Gemmzh2JeN7vKW+fm5tS9yTEaZx91m59aZR/MOznmcOckEMivrTAuskgHbMwkKsmHuIuIW+ws9cZXbg/M3Xa3O8hAAAA//+wCEKOAAAABklEQVQDAI+kzMVRaJbCAAAAAElFTkSuQmCC"
FAVICON_180 = "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAYAAAA9zQYyAAAQAElEQVR4nOx9CbhlVXXmv8+979VASRU1QAFVDApFgSJll8aAE9qadhaFUmMciWicNW07JK2tzefQnaTtNomRFlHJ1/mi5gMcQ2xQBOIsmIiABLWQqaCoKmp+9eq9s3LOvWfvvdba+wz33XurXtW7m8Tzzt1nr73Xv9b+93/Xfe9WG7OgHf/Yl6yCSdalBisBOsYYcwwoXYnsSmnauSfCEmOy3uwHdH/oXPN7w2x17u3r7uoeL57PXkdxpTR43g/wz2c/ASixp+dzT8f7+QPl9sv80OsP19MIn4rxYt7U4fNw9vgD2RMPgMymbPgDxf2mzOy909PTt2y987p7cJCbwUFqx60/fy1S86IMqBdnt7+TLcSQ6/VBK259EsRfkI0njXjaPy/NsSSIG0SJweJWrTdqH3K57p6q56OYtyX49ORP7PGS9df4bx0hY35kKL0ypfQrW+647nYchHYgE9qsOmvDE6YNnZeB9+IMvLWS0WLMI5lJUYkwXslobp4YM8WZuWt/GMzM1++zotJujJkjfgT4xDZdFT4BTjX4MD/c897/2zM7V6bAlVvuuPYnKGWfwbahJ/SqszcsoAl6c+b3O/Nbnyw9MM/QmBng64kYRCkzuSQrIV43AJHlNvMjJPbwJID2o1dmRgU+MT96iAcjgUyKmP89f8+eT91zz/f3YohteAl97rnt43cs/8NMon4wm+W4oWvCkWbuHx+umdl8AT6R+ar8Z4/fRyl9+KHj6TJcd90UhtCGkdDm+LPO30BJcnHmxpr8BQECBs/MFrTmzNyEyUI5EBzflfZRslwqWb/SzGJ5Jczc0B8rB8LHy5i54mSKvGDvtD8V9u/I+v/r5l9++x9QFtQZtoEm9Kp1F5ybaab/lXnzuGqNBhwamrlOazZhZopo5pky82zTzPFxzU7Kjt2fZNf3b/m3667BgNpAEvqMMzaMPzwfl2SrfK3o4NoO0BK0YJw6JqhoQRDBNgsqpGszZg5vVRJHx2PGfih1EuLT2A/+oJrGJVfVqpoxc+gGxfZWaFebA136UHvFW3DrlyfRZ0vQZ1vxhA0rt8/DDd1kNg5jckEqtBYKMCEZGgW4IHusE/gLGhR7jDm7BSjSfjGfsE/MfrGPjU2aYj4YZh9s/fAaEzLphH23EP8AiQNZ4aP8qMUHCBizFB/nD5w/gqE7eCl8hOPMf/B4eHLSfhjhh4XZyh2GD6Dsm9cv27/5u8tPf8qx6LP1xdArH7fhaZkLf58ZWSk6xPEU29f9aeYqZrZNmpPriRhEPTP3qJndPVXPRz3g05M/scdL1l/jf108GmjmcHlxfO5PCS/JPqD5AWbYZszQx6274D2JwbXZpyGdZJbMbCQzwyZF5wmnoeyOjTFzGJSQ0TxzMkYDCvuMQbmYA/w8sNcmzEyMZ+GObW+f2TVAqPm5H8ZfIZmZJ3OAjzXEz3XnBSn7fj7OzA4fQJ0sDlB2AjB8apmZPLwRf9hAZd9Pm7VjjaHvLj/16W/ADJvp8flOXXl6ApdnAy8o33mzhZkRTa7IgsNbg6jWjDIP1dgt8SMk9vAkgPajV2ZGBT4xP3pmZrmcZsxcg0/n2DJfnD+x73W91q17YuhV684/dXqCfuiTublmlsyMUmamxsyMEmYekGYmqZmL4dI+ZzRh3yCKj/KjFh9AMZo81gO7iGhmjo/hdeoKzRyJRzkzoyEzQ+SHt2+7lR+gl00smPf9JSc/40T00HpK6DQxH8mWciZfpTjOiETQu77LEg/46Vb08xeMmlMcZ8yunceC4ZiIyx0e3e6D4B9q+PUzjMFKWbGTxtkHsw9mX74gj3te4qrAx8JSzMeZOYoPyL8BE48rfIgnqZ+PHxUmEg+xZ1VpDpB7ztl18ZAA+k3E4uk2Hcercz2r3Zr6H+ihtZo+mGnmD2XLebOlRg6acBIIFwnDkh6KOdmVtbCuyRjAGEQ1s036Us3MmVPZJWa3TDPbpAo0cxD2anzs603wEVeGjxpXNp/DB2AnF7cLcQKAJTsfV1ZnBvRJoE4u7UcxQOdJeTzwmIVLT963d+vGG9GgmSYPHb/ugg1k8KWggy8aOmWAUZ1Z+kFUg09jP/iDahq3WapWVeVH+Uh+slTiE5hr5ofeuwyfNCG8YvOvrv9ijaF6yXH8ug3ryJgvdO9GdWb9wKjO3FQzA5WaWazfx6Own2SfQH9uxSlPfRxqWiVDZ3XmFVnG/zQzulp08K0ERPa1erfeIxNUMTNfOJWsJ2IQ9cxsauxDLtfdU/V81AM+PfkTe7xk/TX+18VDa+a4fbW8pvgg5m4Yj6LdPQZav+nOGzajpJUydF6eyzqvzGZZbSe1zsEYycywScEWwxgtxsxhUEJG88zJGA3AqM4sTwLOzA4fQJ0sDlB2AjB8apk5ppm9P2ygsu+n9X6YUmYGYu+RHD6rJwlXYP36MZS00oSe3kdvzKw8CcyJLvj+GJNaLfJu3ckSAALUcNf6N1xg9gFZbfDHtTcXr2Z4BiiOLbd+7wcxPyCehj9+OfNpPzijm9CPympPxI+AqhhMvApgrwE+xPCJ+CFPGukH38zWD75ZAJmrQFk1IxJnkduGrZ+Yu54EpazyfhTk8uSl2xe+BSUtmtCPXL9hcWblvZoJfJJWMA/VaWaZzE01swVDMiegmXlUZ+bzccel/zoe5cyMhswMkR/evu0O/ShnZh8P7XDnecJ7Vq06ewEiLZrQE9P0LtP5/Qx1nGlmjjFPsEHlC0bNNaozS2aO4oMIM5sIPsSTNM7Ms6vOXNiLxAOoxOfYvfPH3oFICxI6Z+fMmXdy5jFD1sxGMPMgNbNkAm9/BppZrF9r2Ihmpgp8inlgr14/uLZskfH2g/n4JirwAcNHJC1kUvNkZ+MGq5klMxvMWDPH8encpu9dctK5S6BakNATRO/KjC+u08wGIRPENTNbHGt1mtkxMoCZa2aKMLP0ww8P/YD2QzGz9oO0Hxof5QeifgAnL2/hrecuZPNwZpZ+OHwifiDqhz9JwDe10swGenl1mlkO8LkXZ2aZ5HE/xGaBgD8fvyRJpt4J1URCd7Rz2vljVtRp5lGdOfSjFh9ABimCz/w28LevPRJ7JknNB8HMXbwUPsJx5j94PFjSKD8OYp3ZhhPaYZLwi02VjX+HZmmR0BMpvT8btNgfu4rR2E7tRzPHmRkYlGb2m4szc4+a2Y23L8DbV8FojE8xH4tugM9fvfwROHVFC9t2p5DMrJIPbDPxZFXMLPAhlTzAUDSzS34MSDPzPSlPmCWt9tT7OH4uofM/o8oef5NIniFpZsnMNEDNjApmlsGs1cyk18/9iGhmjQ8i+FhDEc2cP/+6s+fj+WeOd17f2klongyD0MyoYOZ+NDMUMw9BM/NNBXZypfRHYEi6hN46TudkTx05qjMzP9imrNPMAT4RP0SwIMxj3fFjuPgFR7j1PryXQnyI4RPxgzOz9oNvZusH3yyAzNVyZo7EWeReL8ws/SjFh5jd4gUvi8zipac86YkWR5fQiUmf7ZO0gnmIFBGTYGaCTOammtmCIZkT0Mx8ONaZFy8w+PyrF2Gs5de3ZVca4sM2qQuuYmYqiUc5M6MhM3P7htm33QyfWmb28dDMTE2ZmXg8zXkWT6+hKTkvYOYY8wQbVL5gINuoziyZR+OTJAaX/P4iHLe4JZKty9AKH+JJWqGZVTzEnh2CZvabbjiamTQzs83SeTUlmdD5Fydmg04blmYe1ZkNw8t60e1/x7nz8fQ14wGzb909PQDNzOIZxKMfzSyZeSh1ZpCyz+PBSaazSU9bdtLZa/Ofuwyd4jwedILfGZwJ4pqZLY61UZ05gg+DKR9/ziPbeM+zFkLIpjwc2fvBnROSoWN+IOqHP0nAN7XSzAZ6eXWaWQ4wzI8YMw+gziz9cBwn4wx7TZIOSyfdF8x5bu1QxwjVaWbZmmpmu2kgmBPQzNxYMzsmkKkv7AtG4/Z9eDgTaD9q8QFkkCrwWZ59EvjZP3hEFoAwWbZkFY4uXgof4TjzHzweLGmUH4danVnGA4KZHT5wm7OT0ObE9S85dnLa3Ju9OPp+5th8FPO2BJ+G/rQTwlVvOBKPP6Ed7b/jwWk89RMPi/mq/K+Lh9bMiPgjB6A5Poi5G8ZDLahBvGOPV63fULIfq5JJorO6yTw4zYyhaWZUMHOPmplC0LwfEc2s8UEEH4m+SHLOaB94zhFYv7oV4laMf3gPqRPGQDOziAeaMHM/mhmKmYermYFazcw4xOFj0nHz2HaSmpVpYTV4t26ThuysxK6yjerMBgHzMJisJvxPp4/hjeeMO3+NuubNfaii/JAnjfSDb2brB08GQOYqUKeZpR9G+aE1MxCrZpDwoxQfYnaLF7wsMnJzQsYbLF8N0pVJltgrQ2YGBPOwF6gxM6OEmQekmYlwqNSZ7fXkZS186qVHeH8gk83eb9tTfOwtHJf+63hQZL7Dps4smJmvX+GT5XJCBitDZkYpM9u12DaqM0vmieKT/TdvDPjCK4/AonG9KcL7rZ2EjjPznKwzE2fmsLpkHczuc4amlaM6c0QzU4yZTTTodZo5H/cX5y3EmhWtMPiR+22ZhtbMLOIhgqrIgwahmSUzz4I6M9u0hNL3FISViSkYGjxpBDOzxbE2qjNH8GEwcUZ75ePHcMFZ44ppUHrfYWieZMIPf5KAb2qlmQ308uo0sxxgIn5wZj7gdWY3nDGz9gO0JCuD0kpJxCSYWadyU81M8MejZ05AM/PhWme2855+TAsfed4CtulJrDt232Vo5j94PHhwgTLN7GKMppoZ6EUz23iITWXxAcNHwo+Z1pndlSccwMirY2BlOxu00icPIJiA4powzswymDYpMAPN7DcXZ+YeNbMbb1+At6+CIRktopk5hg00s7W7eD5w+R8sxHiLgc+CEDBQce1UOUwEH1LJAwxFM7vkx3A0M6LMrDYn2GYCu/KEgyfNAp9cQ2Nxr5pZMjMNUDPztZFiZhnMWs1Mev3cj4hmVkzWT53ZMs8lL12IVYuNXkB3WErB6/a6bS/JeKAJM/ejmaGYebiaWTJzH5rZImLXY8ySNtjOY9kE3UZ1Zsk8fj4bM+ZHdn3bU+bhaY9qQeDpyIDjEfZv202BH3wzWz94Mrjhyh/uB7gfkH6YiB/1zMw2WRU+VMLMzI/u+sN4C2au8KMYNy/RzDyqM5PATmQJT8YYPsV8j88+BXz/M+eJfvd8Gh/P+zcXdeheNDNQx8xg+Bpm33aHfpQzs4M7vlmDeABRzcz86K7fqPUDIuHg88PNp/BJNDPbtdg2qjNL5oniAx/0ox9hcNnLFyAxkJsCze53T1KR9Ix5EGPmwWlmT0rD0cyDqjO7/KFyfBK7U1HBzKM6s/GgOi94MLrz5Ul82csWYMURCeSxbBrfdz/25kFV5EGD0MySmQ+ZOrOLdzk+CfjiWBvVmY0MGjcPQGvm/Pon/3FeR25oP6D9qujvvCEUyen9IIppf9Qwc8wPw9T6JgAAEABJREFUThZxZp6VdWaX5CX4ZP8lOpWbamaCp3/PnIBm5sO9zmzne9aaNt7yZPnhSXCsGtT2i19MAlCmmW08ZPIbKLhBIh6Smb39kJltPETSWHzA8JHwY8h1ZlS+p8j+S+xabBvVmQ1HH1F8FPMcf6TB35w/X4GLGd0/vNfylJ+PywwAihh718wu+SPMDPSvmRFl5jL/KzQzPGlKZi7Hx/2RbDkz0wA1M18bKWaWi63VzCS5UzJzRDMrJhtEnTlvY9kZd/krFmDhGHX/QoIzkVt/cd+gv/uLSYgwM3GixVysMxd3lfi4hB7VmSXz+PlszJgfjHk+/rz5OP1oA3C7elMJJqru73zsDWBUZ27AzMwP625SzswoYWbJLJqZ50Kd2Q674LFt/P66tnvBMQ2p+x76OUOP6sz1mlm5i/aoziyZx8bKNl1nto+vWZHgL54/LtZXthl66X94L09mTwb1zMzwEZuEk9JwNPOBrDMLzWzj6ZfXZehRndl4UJ0XIRPY+0XzDD7/0nGMtyXDDuKa/8X3qM7Mk16RK4s3e9zN2y7TzI6RAcxcM1OEmdmOBR+uNLNhdkk86e0XYIGDyP1QTBDVzIEfNmbMD8E8Bn993jhOXpoMPJnz68PF93GYoLtOM8sBJuIHZ+ZDtc4cnjAMH8rr0HyjMGYmePr3zAloZp4rdWZr/41PbOP31rTCYA3ounW3PSHhNxPs1UDBDRLxaK6ZbTxE0lhHmcMk4cfBrjP7eeL4tD2jyWA6hja9a2bYyYgzc4+a2Y0X7olj0jojGS2imTmGMU3IWqzObB9ff7zBnz5jDF6+yPnl/cz6t7lvHZX+wMUjgg9pZiYcrnVmyOUF+CSjOjMcGNK+ny9/fMl84LIN89AyavOr5Qbk0EN//v8799EMNDMUMw9XM8fwmZFmLvprmZm/p4j5wwBIRnVmGzPmB6TWzC1eev44li+UuUREJdeZ9W/O3xAqf7gf4H5A+mEiftQzM0uiKnyohJnh4wzljx/ei2ZWzMz8gAGCk4sUPkDB0G6n8neP1J9mJsKhXme29t/7tDGcfULC7JNIDu9Xf/2dkh3KmJnj69lDMjMaMrOPh3aYGjMzi6dgZr5+QDAzfH64+aqYmfmBkngLfLLWtov1zNy7ZhaTYoaa2dmXL8jjjCWHkUw26Dqznfdpj0zw1rPbCmwM5V7+6ijQVDN7UhqOZp5NdeYoPvAGku7PM9XMkgnsjj7U68zW/uolCT6dlegSgyCJhnHvf3WUM49KCiBg5rlUZ47iw66Oof0aetHMFGFmtmPBhyvNbJhdEk96+wVY4CA6bEImiGrmwA8bM+aHYJ6uH2PZVv/c+WNYPA8BHsO6dx97C2aO+cHJIs7Mh2udWeBj/WAnQQLBnIBm5rlWZ7YMcfGz2jjj6Njmrk7OfvpzDa3gBol4NNfMNh4iafT8Ba5lzFyFTzdHVdI7+55BZ6qZvdvVmpn4fNmANmagme0xIJm5R83MNhYCZpbB4MxsGWAYdWa7vuedZvDqx7XBN6M4STTTDKh/694UCu4gCUVwMRzNXIdPY80MYNB1Zm3A8PkcQzfWzHxtpJhZLrZWM5PkTlI7LtDMaqcOus5sQT11mcH/ef6Y9Bc4IPfuO+1UUkhiUvgQBq6Zq/DpPN5UMxf9tczskto9jqaa2Z9k3WvSm2ZmzBzTUlDM7BhU2SXxZAESHFigUDMHzAxgUHVmu775bcIXLhjDgpbce34P8vcMg+/fuoevX/phIn7UMzNLoip8qISZ4eMMIBpvwczOUSCumRUzMz9g5F4G6jRzBB8CEs3Mc7HObJnsk88bw4mL4UHk4+38KQ2tf9uE998zW2w9dczs46EdpsbMzDchZ+bhaGaUxFukI/Pf25f4yL/6ZjsVggnQv2Z29uUL8jgjwWRRZrY+GkSZx8bKtro6swXj9etbeO4aw8COX4fZn0sOnYQGfNMNRzMfSnVmrZk1Pol/mMMQ12h2Rx8udWbLPGetTPCBpydsPhZEdT/M/m0T5KLGmWdUZ+ZXuBPc5SPbZG33kNhL5HZCyMw8GGDDlWY2zC6JJ739AixwEB02IRNENbN21sWM+SGYR/qxdAFw2YtbaCd+3QfrunZ59qZ0aQthI+dmwKA8WX34ZJIRGjWxWdiw/AOf2x6cLu570cwkmRmxEwbipOmO4pvPsHn8AD+9cfPk49qcrt3xpUDTpRWJWdjPH3DMGtiP2GXPc2YqDyLb6S4okrGq/Mm/7f2SFyZYuYhj5pnHH7vmgPR/6eXzwOvyot/ifYD7p6YJL7p8d5E0JthEjslVPKryI4iHineQP1H7hb1U2k3mYp3ZzvfH5xicc4JxO588iu654oc52/+haybwk3unIJiZXGBxoOvMLq52PgPP/LDfbYeKagY44/m5HDO6HWQXwZxmzWPH52OaGXKxw6oz2yD87mqDd55t3S/skbJPmNP937x9Cp/58T7MpjqzkKFFnHk+JqXMrLQms+2Z2TEom5zPDp/Uxu04trOqmBnAoOvMdr5jFhE+88KW3w/antqMc7E/18xv+Wr+WfzsqjNrzWy51CqFpJSZ7c7iiwQkM/MdWzxAIu0lU7qrYe/WoZiZSGAnUDAeBB8LZlfMx+0bB3LLED53XgtHzWfjyM8j7udo/46s2vLKL+3BxH5iicHw5vGoYmYMvs7M4xzkozGd90VyUhyedWY774ee3sKZxzj03U4f3Xfv8x9ff8Ue3LuDEGjmIj/Aks5TF3w8yMtUBAdr75qZFy60ZobS6IkIvnt4BprZJXGxaLbjDnad2RTzPj/74OS167w/YH6N7rv3f37jPtywcRqCmXmSgTOzYd0UxJs9jt40c3mduYyZ7bxm5Zkv8BsUcsfxFPWzxR4In5TD2E4Vw0tm4iBWGw6nYZuF9560BPj/r0qwcEwuf3T11+uzRH7Z3+91ZCFgdvGIZ0b3Mf+eiEtgaSg+srLbMbpad2SiJGRmOQhUopnZDuLnBmdKsEnd3FDHCN/JsGh4VLSPXEbI+SCYubvRu/YXZh8ffe5FppvM3HxhzyD2+tzq/822FBddOQHizOzix+Phk8v1OztGJLNnZHs1bCAfb/NKaWbj+0N/yBcYijGuDu0XE+6EUs1sWBKyZXgta5wzHNTuMaU0M8ewgWYWIBmZzFBO5x2feLbBmqVKlvD1iPu5179nkvCqf5jA9n3qX7Dt9PIASRlq48FlBmT4YOPdjRZBG4hpZnCyc2Qr81H8FiCsX/avvmeimUlyJ6kdF2hmtVOHXWe2y33NYzPtfKqR/mB0z+/f9vV9uPOhaXim5PFtwMwuydzj6E0zsz1jT17EmRliPhtvv7K24YuDYmZB+67Dz84EgXE7ju0sqmBmAMOqM1v7Zx4NfPhc2T+6yuulP92Pb9yxX5EVWBwqmBl0wOvM+vezi2GwC08IKGdmvmOLB2Z7ndnaP3Ie4bIX5t915ge4+Uquc63/pvtSfOjafQBjUNLxaKiZURJvP5CPN8y+7Q7jXMrMxRhLbn4CY//qWzGz23EEqDFGvSCPe/KLMIgzs9txaKyZe6kzW3Q//VyDlUfIoFJFsOda/0N7CK+5Yi+mbb9NSoTMbPMjbwe7zoxiPd4tvkKy38sR7gTvBfmra1rDRjQzxZjZQDCzA5OdV3axCJnAz8c3USE74O2+/XcMnrI6HkwqCf5c6p/K3vu99oqJLKnBcoHFeRbXmQFFqs5Q994xdKCZPWX7xShm7g4rdjJLYiLgQP0+c7fX79yzVxv85yfy49Uyjb7O3f4PZDLjp/enFmhAxIONBz/epWYOw1enmSEGeK40bh7OzL5qUq2ZwUmXoL6XA4yZ2Q7i5wZnSnc1B7fObO2uWAhc8hzqfNNRAHJwnZv9V9y6H5//2TTA4yjiwZNG2p0NdWY5gZFca/hffRu/eJ7URrrHGJPtLCK2ASOamfnURDMLkIxMZiinbRDaLYNLn0dYOt/3g8L18fu51n/b5hTv+qdJ/yCAQ63OLNjW5iPLV/a9HFD0LbmT1I4LNLPaqQeqzoyCOf7knBTrV3Im0czCgzv3+vMPTV515SQmp6Di24CZXZK5x9GbZuakZvMmzswQ89l4dzqAot8bBLPfNdQGYz6pmY03AtRq5oCZAQy7zmx39DNPJly0DiKoKLnOxf7pNMPna5O4dwf/ZqYGzMw0MxgHuXiTjHMxECzrUTzAuLKIczGukpkFQzO7jnTZy8UCE091EDsISqOISczBrzNbUE46kvBXv0ceJNUPdT8X+//n96Zww0b2L9TyeFQxM2ZfnZlKmJmKBSZQY4x6QR73DDSDODNbH9nO89npFwu36N7rzHbTjbUIn3t+/stH5Yw116/X/CbFJ3+wP2AyzsyC08zsrjObCDPzTZHAUyl80xo2opkpxswGgpnttUYz91pntkH5s2cQTjmKuPdsgtH9XdsJb/r6JGPkTgcO5TpzjJkNOwkS8bBi5o7xEs18sOrMNhiveDThJaemJU6P7vdmpPyqqyaxewqAiAc/KUkysziRdfjqNDPEALcZbJwBDKLOrE8aw+bLu5NDqc5sr6cvA/77U1IBhg0WKYNztf9t/7gfd24lUBAPnjQyzodCnZkzs5yvaz8x0j3GmGxnEbENGNHMzCc00MwCJCOTGcppF4TiemT+z6s9ZxrzWhCbya1fuDM3+z/1k2l881fd0+twqzOXMbMl2QTCGN9RxRWIvrs90HVmG5RPPWsaq44s7BDEJnD3Zu72/+CeFB/95ykIaqtjZpdk7nH0ppldeDDsOnPAzMRJ1/iErtPMATMDOFB1ZjvPm9dN42mrie1MdQ127tzq37QrxYVf3480RYlmVswMH2cwDnLxJhlnnyhhnI27FnG266piZsHQzK41SKhnZsOVgv23vqF2upk9dWYblPVHE977u6lgJhdk8owyV/v3TxNe87Wp7r+kxeOBCmaGjzNK4u0HQsTR27fdYZyDTSjiW6aZGzIzIJi52539dMyjn0ue/sn+n9iALpkhk5VlrR4gu+GdkI/75+2OsyPEK9ll7TLCUfPi/fbO2ye/c4sHDItNOICbo5L1s/mYu5c+F51/KUvgQ5DzY/j9/+XaafzdLSn6wkcAVNYoEh6FD1Q8FTNHbap4h/ZjT4frbxNJTSNKN2AyQzwHx+QiuhEnY+P0GxE/j+zndm/fAoZ6UjyfRMcZk7B7lPrDmYwdGf54rPHjiHGDxeOMKYzcrAfq/ou3pVkyTws/qnCVfiCMS1N8SvOkbD6JK2d6kT+leVJj1+RVjsKYX5y1zYQ9OO0XOcW3ND8mitZvnZktxHbYibv2ihF25wabBnp5kXfrpX4wu8wPkQTZf49eRmoYlVyH1//zzYT3XDtdopkVPhE/BD6k8CniAR4Pjg8xfIpxPuc9KQXrLpB1diGT2dl18xALV0z7e5wSP6ndgJKZ5OLBkoyEprFNJmlEM9sdVSxOL9oHBWKxAPlkd6DI4D5ztdUAABAASURBVApGtrEQyW/YQGbfGBc8382DYEJmzP47fbnNCirWr5NquP0PTwCv/up+TBGPRwU+wo8G+DD/HTNzfIzCx83j4yHIwYiVgeeHjIe1X66ZLTlaMrak05aLAABVzTAyx9Q55RYLt2gjQTIymaGc9owcZ2bDty4Hh80nZArknitnZmvfPcjsE8qY2TJZ3n+a+9idB9/b8/eD78//7aE//MY0HtzdIz4yfHF8mAFjJKAy+f3mNiw/gniAuyUDYJoyM+QmMmIz+WtimWy21JnZVvTHEZowM3GiRfm7dbVp4Kf1fphSZu4Gobue/BPLMPni10H3f/R70/jBfQV7mx7wifmj8RFXKFLj8QiZGSS1bQEv2K5kBrl9ijMzIz9ezRAnDNsV7VJmBt8RCJhZoAdgEHVmzswCRVQxDw9eE2Y2UVBNxI8yZrbzWQ3NGQUl10H2f/POFH9zMwk/ovhAa02FDyl8AKisl/gQw6cYV8nMgqGZXREPZpfKNXPIzKEf+YhkttSZ9U5tzjxoyMzcvmH24YOq/Chj5vz22CNQfFceBxdhMAfc/29bCW+/JvXxqMKH+QFqgA/z39uvwMfN013ggagzy3jwJ7stCZjZ7Ti/81h02VC7aM8EQIlmRkQzo0IzK+bhSx6GZuZ11CbMnP/v2mVsvGYWF4TB9u+ezD48+UaKvfsb4sNO2H40c4BPHTPDwQsdABNhZooxM1tflWaGmLH4N1YO1u8zc2b29lmys3GlmhB1zKM2jQ0C88OgmWZ2J032/2uPSpV5Gvr9m77V/R1nSQoV+BRw9q6ZDQsPl6HD0cymD83sWmE/gWBmv6OlhmKLKdpcqDNrJuB+rF1mgr0yzOtf3kS4tvNnVIatX+ETPWEYPqTwKeIBHg+ODzF8AMyGOjP3QyZk114iF6/RNHyIWrTfsfCPe4YoFqcXzba+WKylktlUZ5YlSIZP1k7LGJoz1TCvN95D+LMfpvX4CD8a4MP8d8zM8TEKH70+JUPjmhmReFj75ZrZkiNIkiYUM5NKwDYnRsugHBU/1C7aSJCMTGYopz0jV2hm761MHmAomtkFN8pocc3srqb7gfuaoxAy0xCu9+4CLro6zerOkc0Vw0eGL44PMxDTzD75h6OZ3TxE6mm/iZpqZqPyNQExp+yqajSzZOZBamZUMHM/mhmKmXvXzByfRy0xGDOxkwdBsPrpn8w+0c7fBO7c3wM+MX80PuIKyPDweAxHMwtmJhLMDEJPmtk+aO0zhg62Nt8ImIt1Zu2Hxce/ISRxBVH09Zn2//F3Uty+tQIfaK2p8CGFj/UDYZyNu/r5ZmOd2bWYkqDim5N8svHBiIAe0cycyQyvQ1ZoZodec83sfEBTzayYIHLClDNzMZ9bv8SnU7JT6x30/eW/IFx1Z3PNDGqAD/Pf+YMKfNw8Xf9nQ52ZIvFwbpriu+2CTGdtrtaZ3TWCz2lLUmbfqPn6v79pE+GD/9wAH8ds6EszH0p1ZhOJB+fIRKDBsnmu15mhmIDbzxmaUpY03L69n2H/Q3sJF37LYH/aAJ8Czt41s2HhKfABw8fFvYin6U8zD7LOLJnZWHdcviaBs0Wb63VmkcQMn7EMsRMXkcxxxUCgmfXn30F34T+ZzrfrR/FB7IRh+JDCx/oB7QfbDCweh0KdWWpm6UduN2FD1KL9jrWTcWa2i4sFizOzWJxprpltrsrk58zD7DMq58zs7YfMXFdn9kwA8AfOWObfEGrmDPzpsf/iHxr89IEKfIQfDfBh/jtm5vgYhY9a12ysM2vNzEkut5v4oXbRikGNTGYopz0jV2hm761MHgCzsc4cMoF/4PSlzH+EeIhrD/3/+BuDS/+1AT5yeXF8mIGYZvbJPxzN7HEj9bTfRP1oZh93z8yOoeFMcAYZlmZGBTP3o5mhmHmwmpkzwZrsDaGzRyxogtl66//VduDt30EzfGL+aHzEFZDh4fEYjmYWzCz8N8X6Z6qZ7aZDwMx2Hv+9HHzHIaY1I8zSGdiLZo4xDw9eE2Y2UVBNxI96ZpZ+iGR2HQA/aSxDWzzCq+mpf+ekwWuuNpiYiuADrTUVPqTwsX4g9MMoP2wcK5lZMDSzK+LB7FK5Zg6ZOfQDjJnRmJkBXu1JQrDhJvNMaTzI4tgC3/pip8LtVBJLLdPMzgc01cyKCSInTDkzw4WojAnsA2JTZS90SnYEEVuA31Pj/ry94Rrgrh0l+DA/QA3wYf47f6rwcfN013Uo1JlDZhbp1v2r71GdmVCmmTkTLJ5HWL7Az++JZWb3n7jJ4MZ7TTk+jHn60cyHU51Za2aNT8KZoLumQWpmI3aqt9+vZpbMM+g6cxkTPCb/kyuZXTO+v+GePKGTanxsELU/Gh9xLfAh78fhVGfWmlnjk4TMbMSirBHnoulFM1OEebjT3Jc6zSwH+NyLM/NM68z2arQf2Q+nLU5D8GdwvXcn4Y3fTkAaH8ROGIYPKXysH9B+kGA068fhUGcWfoi91rWbhETid9xcrDNrzcwfX7uUQCo5qeRa1r9nP+G130qwYzKCj/CjAT7Mf8fMHB+j8HHz+HgIcjDMsPJfxsPaL9fMlhxBUs5CMfNMNbPDh+RJ3JYbg4MLRvv8aq1BMACgwHEgDV4zu+BiOJoZipnt42uXpNH1UHTTx/vf+d0Wbt9myvGRy4vjwwA2RgIqk384mjnKzJCbqB/N7OPOmdmg9D0Fy9tksJoZFczcj2aGYubhambJzB6fNUcRYoxs1H1Z/2d/keCbd5lqfGL+aHzEFZDh4fEYjmYWzCw2rSnWP1PNbDcd0FQze/vd1h7VmYFSZmZ+nPgIwoIWB7e3682bDS7+USLxgdaaCh9S+Fg/EPphIn7UMrNgaGZXxIPZpXLNHDJz6AcYM6MxM6MRM9uWjOrMPPmlZjbMj9OWSKaQSVt9v2WvwYXXtDFNCh/mh8vRKnyY/86fKnzcPJDMDB8PHQBqyswA4szM48Gf5OsP40GReMTqzGXMbFviB/tkEseW4dH1OxVsx/IlH8p1Zm8fimmyTwiV3HB4QSa/7p/KCiMXXtvClokIPmXMo/GBBzimmedSnbmMmW1Luo/MVDMbsVNdME2/mlkyz4GqM/v1ez9sEE5jbwijQRb3vv+//ajVkRtRfAo4A380PuJa4EPej7lUZ0bAzBKftjXiukwvmpkizMyd5nPVaWY5wOdenJmHUWcmAqJ1+Oya/x2hZoa665W/Mvjb2xOPD2InDELmgdzcgPaDBKNZPzgzH651Zu4HtB8kvpeDGLMZuVPt4kxzzWxzFajQhA4U45zmzOzth8w8jDozZ2YbvPzJ8SwnH3lk+KFKMB+75qW5d3+vjTLNLBitDB/mv2Nmjo9R+Lh5vB+CHAwzrPyX8bD2yzWz3fwgzpz8Sb5+Hg9y7iDKzIxLix+qNLPGJ/GMXKGZvbcyeQAcTnVmmXwerFOyTwgTtU7BROq6Yx/hdde2O19DMKozx+MRMrPBTDSzxidn6O2jOrP3wwbB80wuN4glr/Y/vP+j747hnl2I4xPzR+MjroAMD4/HcDSzYGYapGa2mw4YlGaW+JjteWF0U3PNHGNm9MjMJgqqt98LM7NNZoKtjVpmZn7o4Pnh+RvCaRixXslgIM+Yf/6zFm68P8GozizjYSJ+cM3cnJkVPtwdSjfmJ+kmzszEmdk018zOBzTVzIoJwBdfx8zetTImsA80rTODBc+vv/vg2iWkTg5E7799bwuf/NeWx4f54WJQhQ/z3/lThY+bp7vOuVBnDvAhbzd7flP+7aMbZabbLWLkTnUgDV4zz4Y6s2FgiWM961i7OJXMxfyw97/dafCW68cwqjOH8aAoMw9GM4tNB8oSmtJNwawiqGDBBgajmSXzzIY6s9+0JDb1woxwj11I4ns0Ou6w+4n8O+i+PYbdUwofG0Ttj8ZHXBEyD4armQ+lOnMUnyI/spc2ZR99m03+PGA72QUXPug8GaBjUaeZ5QCfe3FmPtB1Zj/cMOYkPHpp6oPPn2c4vOPGMfx6R4JRnZnUSSn9IO2H2Gt1mhnQzKz9MIScoWmTW5xprpltrsrkNyKpPBMY5zRnZm8/ZOYDWWcWm9dv/U47bfG0Co68fvoXLVx9dwtaMwtGK8OH+e+Yh+NjFD42DiweghwMM6z8l/Gw9ss1s938IM6c/Em+fh4P8vCpeAyizsyZ2ds3dr4soZOMob23MnkAzIU6s9bMzkGg+4bQJZXchD94IMHHfzYu8ZHLi+PDAI5pQp/8w9HMiDEz5CbqRzP7uHNmNhiUZgaR8MMyf5pmbwqnJ3FztqjJemYmTrQ4nOrMpXV45Ak97edlAD2wG3jD9eOdr+8a1ZmbMDNL9ki8meF6fEzkPR5ocnxy4qZk26+v2Z49/H1FHJhLdWaSlCL8ePRRaZCM+/PfoLt+HrZNQmlNhQ8pfKwfCP0wET9qmVn54ewKP5hdijCzMSXMHPoBxsxozMzokZkVPiaCj2LmrpvmO1u33rmj+LJGXM13rAu+2Kl1zAzGBH5RkpnRkJm9a2VMYB+o1MzMD7Dg+fUDgpnhkzN/Pf+3CPNf6tfzf+DH4/j5FoNRnbm5ZgbVMXMJPsTsihNM4QNcnf9PJ6FTTF0VMvPgNHNQR61lZg96GRPYBwZRZ5ZMYFySn3bkdODPl3/dxt/d2cKozsyYkmLMPDjN7DddyMwWHzKJT+gtd1x3e/biL13wTb+aWTLPbK4zs60uqCS3m/9RrJcThFu2Jnjfj8YxqjNbZjbWHRyIOnOUmbt2f7nzvp/fnt/677Yz5iqRDNCxqNPMcoDPvTgzz5Y6c+iHZwJbssvHb580eF2mm+2fUYVu12nmCD7KD87Mozpz6IfQzAIfc5W15hJ6etpcNRfrzFwzwxixqdYu7pbs8q6LsmR+cK/6Bw/q8GH+O+bh+BiFDyAZlCcPiwcPAEXjYe2Xa2a7+QuGgyUFKGaeqWZ2+FBTzYyAmb39kJkFPpS6hOYzmOVrnrEtuy62HX4fkVoFf4AQNvGASALb74/Z2PBgQMR+7HH/erh+9gqPGUX6gc4XZ//ygl0Yyz5L/di/zMMlt4+z5A/9KW8UMa/wCbqlZo7ajPlTsh7f7Z8P12+AGcaDdDwPLD7379x06/G2O+GWs2c+nf/Qu2aGZB4MVzNLZu5DM1u4FDPn7eRF0xjPkvnqu9sumY1I5l40MyTzYLiaGUPTzKhg5n40s8KnVjNzfOhysFznCY2p/cnHsst2p3l4EjmfTRRUn3vFMW94shX2yDvv7NrVKI3Gfe/aV/LBnVJSm1nn/fDmmhnwfpyefUJ45/YE7/rhfB9M4nuhTjNH8FF+1FYzlB/OrvCD2aVyzQwjNz8ifrC8QFwzSz+4ZkYQvjrNzAFV+FComQN8un48ODa5/6PMuEzozocswMclszFfHRP4RUlmRkNm9q6VMYF9YJh15hgzW/BXHzGNC29cgD1TKkfRVDM3wMeuv1jnqM7M4owqZrYdQgdEAAAHGUlEQVTzmY/lH6Zw+8GMJ5107vxdY2Zj1nOMXwU8I/Bd7LrJMQ/DAlxD9aOZ+SaQj5NwhNgI8QrpB+QLMqRdu0fNQ+eTQPtAP5owwAd6Of1p5gAf100V65eIyenkgAAfDFYzzwSfrH/jjvl7TsfGjRPceqKn27jxuonsHdGHGGUxRrPWJPMcqnVmzQTevsG2fRXM4yhL+VE8r5lnVGeuwacnzWzXgw/rZAYiDN1tG1or1my5OTNypkuGyhYys2eIOiZAxYam8HHDgoZm40RSV4x0mo3KDgyqnq/GDz6720QVJ1O5H/F+zszV7jZj5nAUqfVXryeYr2Y9lfjIeW7Zuem2ddkP09pSwNDd9uXpFOkHPRMUed+DZj4U6sx+/Z7RBIYGyr5hAyH8d8zD8TEKHzeP9wNUp5nFLeZknblIZrf+BB9AJJmBUobutuWnPv3/ZQZeEfbIrRZu7P40MyqYmS+cStYjYkaR/mA58t0zIv6UN0KcORk+QXd/mrmKme0L/WjmcDWD1cz94JO9+sUdm257edlsCSra+O5FF2XWb5LEZJkjzsx2p/ajmSUz96GZi/5aZg7ePaNHzQzJPBiuZsbQNHMVM/ejmRU+M9DM3Xlw8472ztehohnUtKMe+cwTWq39P84ePVoveujMDO8sXzDVjJNJXcHMCLVmyPzxkSLpov3oiXkQGxFlttjTZcwZHwe2nqaaOW6/AT5R+BvgE4yjzVNJa/3e+265GxWtkqHzltWmf2vQ2pBNknbnbMLM3RZj5tlSZ9aa2QULTTUzofY9hZsHknms+0asDP7kQz0zAyXMPBzNXM/MJfgIZmZxRhUz+/mKle3PKm8vqUvmvLXQoO3Z+pu7Fi49edIYeiZ/w0QWhSpmVgM0BPL3mfXjMWbmxydFbuUL/K5r3x9n/BNQ7Y+YmF1NdHqC/H1muKvzu5SZ1Xoj/miSEMxcun7lB/Nfx0PgAy8XG+ET2K/BR6+uAT6G6N1ZVeNLaNAaJXTe9m7deOPCZSetyeY8U2raCs2ss59FhYNmAsY3aKSZXfaw+eCZ2Wgm4MlMMc1smH1lV8zH1lvjR1QTFn4AEXwYM/tf9Sz3wzMzUKuZjRHM7KtFMT8q8BHMrP2I4FMRjyrN3GVy+uLOB257Nxo2gx7accetXzi5cNEN2VT/wTFE1Y4t1VDugfBxC17VMN3Dk69i5KjOXL2e2VNnduu5eVd755Nwzz170bDVamje7rvvp3vG9+x6SrbTvjKqM5NjUuuHYx4oBrLuG7Ey4T9nZoeTKdfMRMBhW2fuGv7KkcnCJ/eSzIVLM2pm2SlPzX8z773R3h6ZiSczXxiJ59krPGYU6Q+WE757lssrW2fRF2Uq/0LYfaCrGdX+N2Nmg9lQZ+70Gvrgrvtv+0jNxNHWWEPrtnfrXdccsfTEO7Ppn50tbgyzQjMrJhuYZgYOD83siBSD1cwYiGbOnt+TXV66a9Ntn8EMm0GfbcUpT31cCvp6Zuq4npkZ3lm+IKoZJ5KvipkRas2Q+eMjXZRK+3tmHgyemePjwNZTz8xy+mbMzLM49lgDfNS47NWNU1lpbs99t96MPlpPGjrWNt95/c2mlT4hW+T3uEYrVolRnZlPMKoz65Og+wN9j1r0+H6TuXBxQO3cc9tL70lfk9UM818cOZF38Tpq556BxxcimbOOyfwLMqQQx7d9oB9NyOuo4exAv8wc4IPBauYAHwxWM88Un+yZ32avXbzzgWM+D1w3hQG0wSW0bWecMb5scvlFSNM/zbw4Vmu0uLb1zMafl1qTQk0Ipp2jduXmMXxcid1Ac1JcazbxgzOZOJ7LxqPGrhonsyq2/iZ+oNSfwnDEjxIcauPh7N6f/e9Hdy3F/8Wtt05igG3wCV20VavOXrBnXuvN2RTvy9xYnr8mwEMVD1B4a5OvoWbuSWty5qzo57PboPXyniF+0sS6qcbdZswcjiK1/ur1BPPVrKcSn27H/dnlozvaOz7bazmuaRtaQtu24oxzF9G+6TelRG/NfDsh3LFpwBwcBP7uGIIB0ZyZA/sImDK0X9hLyxnS6PUU/XwCrhlRNz7qTxphOHa8x9Zf438zZkaN/V6YuSMt/npne+dfDiuRbRt6QvO2/FFPXp8l9guzH1+YTbzOQxeIMr8yivSrJoJRPNaPJkSJRq/ThKjzpwEz2xf60czhagarmRvgQxk+P0mBr1KCr+2+9xf/ggPUDmhC87ZszdnHm6nkBWk3uZ+RYTBPHk8RzYYemdk01cxNGK1C2wKzRDMPgpnjfpTi6mQM7cvuv5NS+lVKW1fsfvCWB3AQ2kFLaNk2tJacfO+qDKjVQLoaaXY15oQMptVZXXF1lvSrrQ7nbVRnbsLMcvpmzMyT2j5GD2X/c3d2n/8K593ZS3ebvEoBurtFdPfD9z/mnvxP93CQ278DAAD//zZOnx0AAAAGSURBVAMAVxVj6BpUb8AAAAAASUVORK5CYII="

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PB Deals &middot; __COUNT__ products</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,__FAV_SVG__">
<link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,__FAV_32__">
<link rel="apple-touch-icon" sizes="180x180" href="data:image/png;base64,__FAV_180__">
<meta name="theme-color" content="#0C1626">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
__ADS_HEAD__
<style>
:root{
  --page:#070A10; --panel:#0F1D34; --panel2:#132744;
  --surface:#111827; --surface2:#162033; --sunk:#0B111C;
  --line:#22304A; --line2:#1A253A;
  --ink:#F3F7FC; --muted:#AFBFD4; --faint:#7F93AD;
  --accent:#F2762B; --accent2:#FFB45C; --accent-soft:rgba(242,118,43,.14);
  --hdr-ink:#FFFFFF; --hdr-muted:#94A9C6; --hdr-field:rgba(0,0,0,.30); --hdr-line:rgba(255,255,255,.13);
  --shadow:0 1px 2px rgba(0,0,0,.45),0 18px 40px -24px rgba(0,0,0,.95);
  --media-bg:#FFFFFF;
}
html[data-theme="light"]{
  --page:#E9EDF3; --panel:#13284A; --panel2:#1A3460;
  --surface:#FFFFFF; --surface2:#F6F8FB; --sunk:#EEF2F7;
  --line:#D5DDE8; --line2:#E3E9F1;
  --ink:#0E1828; --muted:#4D6078; --faint:#71849B;
  --accent:#D65A12; --accent2:#F2762B; --accent-soft:rgba(214,90,18,.10);
  --shadow:0 1px 2px rgba(16,28,42,.06),0 14px 32px -22px rgba(16,28,42,.45);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--page);color:var(--ink);font:15px/1.45 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;min-height:100vh;
  background-image:radial-gradient(900px 420px at 0% -10%,rgba(242,118,43,.10),transparent 60%),
                   radial-gradient(800px 400px at 100% 0%,rgba(60,120,220,.10),transparent 60%);
  background-attachment:fixed}
.mono{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
a{color:inherit;text-decoration:none}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
::selection{background:var(--accent);color:#fff}

.shell{max-width:1400px;margin:0 auto;padding:18px 22px 48px}

/* ---------------- header ---------------- */
.head{position:relative;overflow:hidden;border-radius:20px;padding:18px 22px 16px;color:var(--hdr-ink);
  background:linear-gradient(135deg,var(--panel2),var(--panel) 55%);box-shadow:var(--shadow);
  border:1px solid rgba(255,255,255,.06)}
.head::before{content:"";position:absolute;right:-120px;top:-160px;width:420px;height:420px;border-radius:50%;
  background:radial-gradient(circle,rgba(242,118,43,.22),transparent 65%);pointer-events:none}
.headtop{position:relative;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;margin-right:auto;min-width:0;background:none;border:0;padding:0;text-align:left;color:inherit}
.logo{width:44px;height:44px;border-radius:12px;flex:none;box-shadow:0 8px 22px -8px rgba(242,118,43,.6);transition:transform .25s}
.brand:hover .logo{transform:rotate(-8deg) scale(1.05)}
.brand h1{font-family:"Space Grotesk",sans-serif;font-size:24px;font-weight:700;margin:0;letter-spacing:-.02em;line-height:1.1}
.brand h1 span{color:var(--accent2)}
.stamp{display:flex;align-items:center;gap:6px;margin-top:3px;font-size:11.5px;color:var(--hdr-muted);letter-spacing:.02em}
.stamp i{color:#3FBF87;font-size:10px}
.stats{display:flex;gap:8px;flex-wrap:wrap}
.stat{background:rgba(0,0,0,.24);border:1px solid var(--hdr-line);border-radius:12px;padding:6px 12px;min-width:86px}
.stat small{display:block;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--hdr-muted);font-weight:700}
.stat b{font-family:"JetBrains Mono",monospace;font-size:17px;line-height:1.2;color:#fff}
.stat.hot b{color:var(--accent2)}
.hbtns{display:flex;gap:8px;align-items:center}
.btn{display:inline-flex;align-items:center;gap:7px;background:rgba(255,255,255,.07);border:1px solid var(--hdr-line);color:#EAF1FA;
  padding:8px 13px;border-radius:10px;font-size:13px;font-weight:600;transition:background .15s,border-color .15s,transform .15s;white-space:nowrap}
.btn:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.3)}
.btn:active{transform:scale(.97)}
.btn .badge{background:var(--accent);color:#fff;border-radius:99px;font-size:10.5px;padding:0 6px;line-height:17px;min-width:17px;text-align:center}
.btn .badge:empty{display:none}
#filtersBtn{display:none}

/* filters (desktop: inside header) */
.filters{position:relative}
.frow{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:14px}
.search{position:relative;flex:1 1 260px;min-width:200px}
.search i{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--hdr-muted);font-size:13px;pointer-events:none}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);font:600 11px "JetBrains Mono",monospace;color:var(--hdr-muted);
  border:1px solid var(--hdr-line);border-radius:5px;padding:1px 6px}
.field{background:var(--hdr-field);border:1px solid var(--hdr-line);color:#F2F7FC;padding:9px 13px;border-radius:10px;font-size:14px;width:100%;transition:border-color .15s,background .15s}
.search .field{padding-left:36px;padding-right:36px}
.field::placeholder{color:#7D93B0}
.field:focus{border-color:var(--accent);outline:none;background:rgba(0,0,0,.42)}
select.field{cursor:pointer;padding-right:30px;appearance:none;
  background-image:linear-gradient(45deg,transparent 50%,#94A9C6 50%),linear-gradient(135deg,#94A9C6 50%,transparent 50%);
  background-position:calc(100% - 15px) 50%,calc(100% - 10px) 50%;background-size:5px 5px;background-repeat:no-repeat}
select.field option{background:#13284A;color:#fff}
.seg{display:flex;align-items:center;gap:6px;background:var(--hdr-field);border:1px solid var(--hdr-line);border-radius:10px;padding:3px 11px;flex:none}
.seg .cap{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--hdr-muted);font-weight:700;white-space:nowrap}
.seg .field{background:transparent;border:0;padding:5px 0;width:60px;text-align:center;font-size:13px}
.seg .sep{color:#6F86A5}
.toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-size:13px;color:#A9BDD6;flex:none;user-select:none}
.toggle input{appearance:none;width:36px;height:20px;background:rgba(255,255,255,.18);border-radius:999px;position:relative;transition:background .2s;flex:none;cursor:pointer;margin:0}
.toggle input::after{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.4)}
.toggle input:checked{background:var(--accent)}
.toggle input:checked::after{transform:translateX(16px)}
.toggle input:checked+span{color:#fff;font-weight:600}
.toggle input:disabled{opacity:.4;cursor:not-allowed}
.toggle.off{opacity:.55;cursor:not-allowed}

.sortrow{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.09)}
.flabel{font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--hdr-muted);flex:none;width:70px}
.sortbox{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sortbox select{width:auto;min-width:190px}
.thenby{display:flex;align-items:center;gap:8px;animation:fadeIn .25s ease}
.thenby[hidden]{display:none}
.thenby .arrow{color:var(--accent2);font-size:12px}
.thenby .lbl{font-size:12px;color:var(--hdr-muted);font-weight:600;white-space:nowrap}
.hint{font-size:11.5px;color:var(--hdr-muted);margin-left:4px}
@keyframes fadeIn{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:none}}

.chipsrow{display:flex;gap:10px;align-items:flex-start;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.09)}
.chipsrow .flabel{padding-top:7px}
.chips{display:flex;flex-wrap:wrap;gap:6px;flex:1}
.chip{background:rgba(0,0,0,.24);border:1px solid var(--hdr-line);color:#C2D1E4;padding:5px 11px;border-radius:999px;font-size:12.5px;font-weight:600;
  display:inline-flex;align-items:center;gap:6px;transition:all .15s;line-height:1.2}
.chip:hover{border-color:rgba(255,255,255,.4);color:#fff}
.chip i{font-size:11px;opacity:.85}
.chip .n{opacity:.6;font-size:10.5px;font-family:"JetBrains Mono",monospace;font-weight:500}
.chip[aria-pressed="true"]{background:var(--accent);border-color:transparent;color:#fff}
.chip[aria-pressed="true"] .n{opacity:.85}

/* ---------------- results ---------------- */
.pbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:20px 2px 14px}
.pbar .title{margin-right:auto;min-width:0}
.pbar h2{font-family:"Space Grotesk",sans-serif;font-size:20px;margin:0;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pbar .range{font-size:12.5px;color:var(--muted);font-family:"JetBrains Mono",monospace}
.sel{background:var(--surface);border:1px solid var(--line);color:var(--ink);padding:7px 10px;border-radius:9px;font-size:13px}
.pg{display:flex;gap:5px;align-items:center}
.pg button{background:var(--surface);border:1px solid var(--line);color:var(--ink);min-width:36px;height:36px;padding:0 10px;border-radius:9px;font-size:13px;font-weight:600;transition:all .15s}
.pg button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.pg button:disabled{opacity:.3;cursor:default}
.pg input{width:56px;height:36px;text-align:center;background:var(--surface);border:1px solid var(--line);padding:0 6px;border-radius:9px;font-family:"JetBrains Mono",monospace;font-size:13px}
.pg .of{font-size:12px;color:var(--muted);font-family:"JetBrains Mono",monospace}
.pbar.bottom{justify-content:center;margin-top:22px}
.pbar.bottom .title,.pbar.bottom .sel{display:none}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}
.band{grid-column:1/-1;display:flex;align-items:center;gap:10px;margin:8px 0 -2px}
.band:first-child{margin-top:0}
.band b{font-family:"Space Grotesk",sans-serif;font-size:16px;white-space:nowrap}
.band span{font-size:11.5px;font-weight:600;color:var(--muted);background:var(--surface);border:1px solid var(--line);padding:2px 9px;border-radius:99px;white-space:nowrap}
.band::after{content:"";flex:1;height:1px;background:var(--line)}

.card{position:relative;display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line2);border-radius:16px;overflow:hidden;
  box-shadow:var(--shadow);transition:transform .2s,border-color .2s,box-shadow .2s;opacity:0;transform:translateY(10px);
  content-visibility:auto;contain-intrinsic-size:340px}
.card.show{opacity:1;transform:none}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--heat)}
.card:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--heat) 55%,transparent);
  box-shadow:0 18px 40px -22px color-mix(in srgb,var(--heat) 70%,transparent),var(--shadow)}
.cbody{display:flex;flex-direction:column;gap:9px;padding:15px 15px 14px;flex:1}
.ctop{display:flex;align-items:center;gap:8px}
.cat{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;letter-spacing:.02em;padding:4px 9px;border-radius:99px;
  min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:70%}
.pct{margin-left:auto;font-family:"JetBrains Mono",monospace;font-weight:700;font-size:13px;color:#fff;background:var(--heat);padding:3px 9px;border-radius:8px;flex:none}
.media{position:relative;display:grid;place-items:center;aspect-ratio:4/3;border-radius:12px;overflow:hidden;background:var(--media-bg)}
.media img{width:100%;height:100%;object-fit:contain;padding:10px;opacity:0;transition:opacity .35s}
.media img.ok{opacity:1}
.media .ph{position:absolute;inset:0;display:grid;place-items:center;font-size:34px;color:#B8C2D0;
  background:linear-gradient(110deg,#F3F5F8 30%,#FFFFFF 50%,#F3F5F8 70%);background-size:200% 100%;animation:shim 1.2s linear infinite}
.media .ph.done{animation:none;background:#F5F7FA}
@keyframes shim{to{background-position:-200% 0}}
.icon{display:grid;place-items:center;height:64px;border-radius:12px;font-size:24px;color:var(--heat);
  background:linear-gradient(135deg,var(--surface2),var(--sunk));border:1px solid var(--line2)}
.name{font-weight:600;font-size:14px;line-height:1.38;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.name:hover{color:var(--accent)}
.meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.part{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--muted);background:var(--sunk);border:1px solid var(--line2);
  padding:3px 7px;border-radius:6px;cursor:copy;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.part:hover{color:var(--accent);border-color:var(--accent)}
.tag{display:inline-flex;align-items:center;gap:5px;padding:3px 8px;border-radius:6px;font-size:10.5px;font-weight:700;letter-spacing:.05em;
  white-space:nowrap;cursor:copy;border:1px solid transparent}
.tag.spec{background:var(--accent-soft);color:var(--accent);border-color:color-mix(in srgb,var(--accent) 35%,transparent);cursor:default}
.tag.plain{background:var(--sunk);color:var(--faint);border-color:var(--line);cursor:default}
.prices{margin-top:auto;padding-top:10px;border-top:1px dashed var(--line);display:flex;align-items:flex-end;justify-content:space-between;gap:8px}
.now{font-family:"JetBrains Mono",monospace;font-weight:700;font-size:21px;line-height:1.1;letter-spacing:-.02em}
.was{display:block;font-family:"JetBrains Mono",monospace;color:var(--faint);text-decoration:line-through;font-size:12px}
.save{font-size:11.5px;font-weight:700;color:var(--heat);white-space:nowrap;text-align:right}
.actions{display:flex;gap:8px}
.view{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:9px;border-radius:10px;font-size:12.5px;font-weight:700;
  letter-spacing:.02em;background:var(--surface2);border:1px solid var(--line);transition:all .18s}
.view:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.view i{transition:transform .18s}
.view:hover i{transform:translateX(3px)}
.gbtn{display:inline-grid;place-items:center;width:38px;border-radius:10px;border:1px solid var(--line);background:var(--surface2);
  font-family:"Space Grotesk",sans-serif;font-weight:700;font-size:15px;color:var(--faint);transition:all .18s}
.gbtn:hover{color:#fff;background:#4285F4;border-color:#4285F4}

.empty{padding:64px 20px;text-align:center;color:var(--muted);background:var(--surface);border:1px dashed var(--line);border-radius:16px}
.empty i{font-size:34px;color:var(--accent);margin-bottom:10px}
.empty b{display:block;font-family:"Space Grotesk",sans-serif;font-size:18px;color:var(--ink);margin-bottom:6px}
.toast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,14px);background:var(--ink);color:var(--page);padding:10px 18px;border-radius:10px;
  font-size:13px;font-weight:700;opacity:0;pointer-events:none;transition:all .2s;z-index:200}
.toast.on{opacity:1;transform:translate(-50%,0)}
.totop{position:fixed;right:18px;bottom:18px;z-index:80;width:46px;height:46px;border-radius:14px;border:0;background:var(--accent);color:#fff;
  font-size:16px;box-shadow:0 10px 26px -8px rgba(242,118,43,.7);opacity:0;transform:translateY(10px);pointer-events:none;transition:all .25s}
.totop.on{opacity:1;transform:none;pointer-events:auto}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(3px);z-index:140;opacity:0;pointer-events:none;transition:opacity .25s}
.overlay.on{opacity:1;pointer-events:auto}
.drawer-head{display:none}

/* ---------------- ads ---------------- */
.ad{grid-column:1/-1;background:var(--surface);border:1px dashed var(--line);border-radius:16px;padding:8px 10px 10px;overflow:hidden}
.ad-top{margin-top:16px}
.ad-label{display:block;font-size:9.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.ad:has(ins[data-ad-status="unfilled"]){display:none}      /* no ad available -> no empty box */
.foot{max-width:1400px;margin:0 auto;padding:6px 22px 34px;text-align:center;font-size:12px;color:var(--faint)}
.foot a{color:var(--muted);text-decoration:underline;text-underline-offset:2px}
.mobile-search{display:none}

/* ---------------- phones & small screens: slide-out filters ---------------- */
@media (max-width:900px){
  .shell{padding:12px 12px 40px}
  .head{padding:14px;border-radius:16px}
  .brand h1{font-size:20px}
  .logo{width:38px;height:38px}
  .stats{order:3;width:100%}
  .stat{flex:1;min-width:0;padding:6px 10px}
  .stat b{font-size:15px}
  .stat small{font-size:8.5px;letter-spacing:.06em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .stamp{font-size:10.5px}
  #filtersBtn{display:inline-flex}
  .hbtns .label{display:none}
  .mobile-search{display:block;margin-top:12px}
  .filters{position:fixed;top:0;left:0;bottom:0;z-index:150;width:88%;max-width:360px;overflow-y:auto;overscroll-behavior:contain;
    background:linear-gradient(160deg,var(--panel2),var(--panel));padding:18px 16px 28px;border-radius:0 18px 18px 0;
    transform:translateX(-105%);transition:transform .3s cubic-bezier(.22,1,.36,1);box-shadow:20px 0 40px rgba(0,0,0,.4)}
  .filters.open{transform:none}
  .drawer-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
  .drawer-head b{font-family:"Space Grotesk",sans-serif;font-size:18px}
  .filters .frow{flex-direction:column;align-items:stretch}
  .filters .frow .search{display:none}
  .seg{width:100%}
  .seg .cap{width:52px;flex:none}
  .seg .field{flex:1 1 0;min-width:0;width:0}
  .toggle{padding:4px 0}
  .sortrow,.chipsrow{flex-direction:column;align-items:stretch}
  .flabel{width:auto}
  .sortbox,.thenby{flex-direction:column;align-items:stretch}
  .sortbox select{width:100%;min-width:0}
  .thenby .arrow{display:none}
  .hint{margin:0}
  .pbar{margin:16px 0 12px}
  .pbar .title{width:100%}
  .pg{flex:1;justify-content:flex-end}
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
  .cbody{padding:12px 11px 11px;gap:7px}
  .cat{max-width:62%;font-size:10px;padding:3px 7px}
  .pct{font-size:11.5px;padding:2px 7px}
  .icon{height:50px;font-size:20px}
  .name{font-size:12.5px}
  .part{font-size:10px}
  .now{font-size:17px}
  .prices{flex-direction:column;align-items:flex-start;gap:2px}
  .save{text-align:left}
  .view{font-size:11px;padding:8px 4px}
  .view .long{display:none}
  .gbtn{width:34px}
}
@media (max-width:360px){.grid{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}.card{opacity:1;transform:none}}
</style>
</head>
<body>
<div class="shell">

  <header class="head" id="head">
    <div class="headtop">
      <button class="brand" id="brand" title="Back to the start (resets filters)">
        <img class="logo" alt="" src="data:image/svg+xml;base64,__FAV_SVG__">
        <div>
          <h1>PB <span>Deals</span></h1>
          <div class="stamp mono"><i class="fa-solid fa-circle"></i> Scraped __GENERATED__ &middot; incl. GST</div>
        </div>
      </button>
      <div class="hbtns">
        <button class="btn" id="filtersBtn"><i class="fa-solid fa-sliders"></i> Filters <span class="badge" id="fcount"></span></button>
        <button class="btn" id="export" title="Download what's showing as CSV"><i class="fa-solid fa-file-arrow-down"></i><span class="label">Export</span></button>
        <button class="btn" id="theme" title="Light / dark"><i class="fa-solid fa-sun"></i></button>
      </div>
      <div class="stats">
        <div class="stat hot"><small>Found</small><b id="found">0</b></div>
        <div class="stat"><small>Best deal</small><b id="best">–</b></div>
        <div class="stat"><small>Promo codes</small><b id="npromo">–</b></div>
      </div>
    </div>

    <div class="mobile-search">
      <div class="search"><i class="fa-solid fa-magnifying-glass"></i>
        <input class="field" id="q2" placeholder="Search name, part # or promo" autocomplete="off"></div>
    </div>

    <div class="filters" id="filters">
      <div class="drawer-head"><b>Filters</b>
        <button class="btn" id="closeFilters" aria-label="Close filters"><i class="fa-solid fa-xmark"></i></button></div>

      <div class="frow">
        <div class="search"><i class="fa-solid fa-magnifying-glass"></i>
          <input class="field" id="q" placeholder="Search name, part # or promo" autocomplete="off"><kbd>/</kbd></div>
        <div class="seg"><span class="cap">NZ$</span>
          <input class="field mono" id="pmin" placeholder="min" inputmode="decimal"><span class="sep">–</span>
          <input class="field mono" id="pmax" placeholder="max" inputmode="decimal"></div>
        <div class="seg"><span class="cap">% off</span>
          <input class="field mono" id="dmin" placeholder="0" inputmode="numeric"><span class="sep">–</span>
          <input class="field mono" id="dmax" placeholder="100" inputmode="numeric"></div>
        <label class="toggle"><input type="checkbox" id="tSpecial" checked><span>Specials</span></label>
        <label class="toggle"><input type="checkbox" id="tUnknown"><span>No discount</span></label>
        <label class="toggle" id="imgToggle"><input type="checkbox" id="tImages"><span>Images</span></label>
        <button class="btn" id="reset"><i class="fa-solid fa-rotate-left"></i> Reset</button>
      </div>

      <div class="sortrow">
        <span class="flabel">Sort</span>
        <div class="sortbox">
          <select class="field" id="sort">
            <option value="pct">Biggest Discount (%)</option>
            <option value="save">Biggest Saving ($)</option>
            <option value="price_asc">Lowest Price</option>
            <option value="price_desc">Highest Price</option>
            <option value="name">Name (A–Z)</option>
          </select>
          <div class="thenby" id="thenWrap">
            <i class="fa-solid fa-arrow-turn-up fa-rotate-90 arrow"></i><span class="lbl">Then by</span>
            <select class="field" id="then"></select>
          </div>
          <span class="hint" id="hint"></span>
        </div>
      </div>

      <div class="chipsrow"><span class="flabel">Promo</span><div class="chips" id="promos"></div></div>
      <div class="chipsrow"><span class="flabel">Category</span><div class="chips" id="cats"></div></div>
    </div>
  </header>

  __AD_TOP__
  <div class="pbar" id="pbarTop">
    <div class="title"><h2 id="heading">All deals</h2><span class="range" id="range"></span></div>
    <select class="sel" id="rows" aria-label="Per page">
      <option value="24">24 / page</option><option value="48" selected>48 / page</option>
      <option value="96">96 / page</option><option value="200">200 / page</option>
    </select>
    <div class="pg">
      <button data-go="prev" aria-label="Previous page"><i class="fa-solid fa-chevron-left"></i></button>
      <input class="pageno" value="1" aria-label="Page"><span class="of"></span>
      <button data-go="next" aria-label="Next page"><i class="fa-solid fa-chevron-right"></i></button>
    </div>
  </div>

  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" hidden><i class="fa-solid fa-magnifying-glass"></i>
    <b>Nothing matches these filters</b>Widen the price or discount range, or switch on "No discount" items.</div>

  <div class="pbar bottom" id="pbarBottom">
    <div class="pg">
      <button data-go="prev" aria-label="Previous page"><i class="fa-solid fa-chevron-left"></i></button>
      <input class="pageno" value="1" aria-label="Page"><span class="of"></span>
      <button data-go="next" aria-label="Next page"><i class="fa-solid fa-chevron-right"></i></button>
    </div>
  </div>
</div>
<footer class="foot">Prices and stock from pbtech.co.nz at the time of scraping and may have changed. Not affiliated with PB Tech.__FOOT_LINKS__</footer>
<div class="overlay" id="overlay"></div>
<button class="totop" id="totop" aria-label="Back to top"><i class="fa-solid fa-arrow-up"></i></button>
<div class="toast" id="toast"></div>

<script>
const RAW = __DATA__;
const ADS = __ADS_JSON__;
const STATUS=["promo","special","unknown"];
const D=RAW.map(r=>{
  const now=r[3]!=null?r[3]:r[2];
  return {part:r[0],name:r[1],orig:r[2],disc:r[3],pct:r[4],promo:r[5],cat:r[6],st:STATUS[r[7]],img:r[8]||"",
    now, save:(r[3]!=null&&r[2]!=null)?Math.round((r[2]-r[3])*100)/100:null,
    hay:(r[0]+" "+r[1]+" "+r[5]).toLowerCase()};
});
const HAS_IMAGES=D.some(d=>d.img);

const slug=n=>n.replace(/ /g,"-").replace(/[^A-Za-z0-9-]/g,"").slice(0,50).replace(/-+$/,"");
const rawPbUrl=d=>`https://www.pbtech.co.nz/product/${encodeURIComponent(d.part)}/${slug(d.name)}`;
const pbUrl=d=>ADS.affiliate?ADS.affiliate.replace("{url}",encodeURIComponent(rawPbUrl(d))):rawPbUrl(d);
const gUrl=d=>`https://www.google.com/search?q=${encodeURIComponent(d.part+" "+d.name.slice(0,70))}`;
const $=s=>document.querySelector(s);
const $$=s=>document.querySelectorAll(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money=v=>v==null?"":"$"+v.toLocaleString("en-NZ",{minimumFractionDigits:2,maximumFractionDigits:2});
const isDark=()=>document.documentElement.dataset.theme!=="light";

/* discount heat - readable on both themes */
const HEAT=[[60,"#E0417A"],[40,"#EE5B39"],[25,"#F0871F"],[10,"#D9A81C"],[0,"#6C7F99"]];
const HEAT_L=[[60,"#C21E5C"],[40,"#D0421D"],[25,"#C46A08"],[10,"#A8820A"],[0,"#5A6C85"]];
function heat(p){const t=isDark()?HEAT:HEAT_L;if(p==null)return t[4][1];for(const [m,c] of t)if(p>=m)return c;return t[4][1]}

const HUES=[210,168,142,30,266,330,190,104,352,44,238,296,158,14,318,80];
const catHue={};[...new Set(D.map(d=>d.cat))].sort().forEach((c,i)=>catHue[c]=HUES[i%HUES.length]);
const pill=c=>{const h=catHue[c]??210;return isDark()?`background:hsl(${h} 44% 18%);color:hsl(${h} 80% 76%)`:`background:hsl(${h} 72% 93%);color:hsl(${h} 58% 28%)`};
const promoHue={};[...new Set(D.map(d=>d.promo).filter(Boolean))].sort().forEach((p,i)=>promoHue[p]=HUES[(i+5)%HUES.length]);
const ppill=p=>{const h=promoHue[p]??30;return isDark()?`background:hsl(${h} 44% 18%);color:hsl(${h} 85% 76%);border-color:hsl(${h} 50% 30%)`:`background:hsl(${h} 72% 93%);color:hsl(${h} 60% 28%);border-color:hsl(${h} 50% 80%)`};

const CAT_ICON={"Storage & NAS":"fa-hard-drive","Phones & Wearables":"fa-mobile-screen","Monitors & Displays":"fa-desktop","Audio":"fa-headphones",
  "Cameras, Drones & 3D":"fa-camera","Gaming":"fa-gamepad","Computers & Tablets":"fa-laptop","PC Parts (Components)":"fa-microchip",
  "PC Peripherals":"fa-keyboard","Networking":"fa-wifi","Security & Surveillance":"fa-shield-halved","Smart Home & Appliances":"fa-house-signal",
  "Furniture & Mounts":"fa-chair","Cables & Power":"fa-plug","Printing & Office":"fa-print","POS & Barcode":"fa-barcode","Car & Travel":"fa-car",
  "Tools & Workshop":"fa-screwdriver-wrench","Gift Cards & Services":"fa-gift","Other":"fa-box-open"};
const ICON_RULES=[[/laptop|notebook|macbook|chromebook/,"fa-laptop"],[/tablet|ipad/,"fa-tablet-screen-button"],[/phone|mobile/,"fa-mobile-screen"],
  [/watch|wearable|fitness/,"fa-clock"],[/monitor|display|screen|tv|television|projector/,"fa-desktop"],[/audio|headphone|speaker|sound|earbud/,"fa-headphones"],
  [/camera|drone|photo|video/,"fa-camera"],[/gaming|game|console/,"fa-gamepad"],[/storage|drive|ssd|nas|memory card/,"fa-hard-drive"],
  [/component|cpu|graphics|motherboard|ram|parts/,"fa-microchip"],[/keyboard|mouse|peripheral/,"fa-keyboard"],[/network|router|wifi|modem/,"fa-wifi"],
  [/security|surveillance|cctv/,"fa-shield-halved"],[/smart home|appliance|kitchen|vacuum|home/,"fa-house-signal"],[/cable|power|charger|battery|adapter/,"fa-plug"],
  [/print|office|ink|toner|scanner/,"fa-print"],[/furniture|chair|desk|mount/,"fa-chair"],[/car|auto|travel/,"fa-car"],[/tool/,"fa-screwdriver-wrench"],
  [/gift|software|service|licen/,"fa-gift"],[/computer|desktop|pc/,"fa-computer"],[/toy|kid|hobby/,"fa-puzzle-piece"],[/health|beauty|personal/,"fa-heart-pulse"]];
const icon=c=>{if(CAT_ICON[c])return CAT_ICON[c];const n=(c||"").toLowerCase();for(const [re,ic] of ICON_RULES)if(re.test(n))return ic;return "fa-box-open"};

/* ---------------- sorting: Sort + Then by ---------------- */
const num=(v,miss)=>(typeof v==="number"&&!isNaN(v))?v:miss;
const SORTS={
  pct:       {label:"Biggest Discount (%)",cmp:(a,b)=>num(b.pct,-1)-num(a.pct,-1)},
  save:      {label:"Biggest Saving ($)",  cmp:(a,b)=>num(b.save,-1)-num(a.save,-1)},
  price_asc: {label:"Lowest Price",        cmp:(a,b)=>num(a.now,Infinity)-num(b.now,Infinity)||0},
  price_desc:{label:"Highest Price",       cmp:(a,b)=>num(b.now,-Infinity)-num(a.now,-Infinity)||0},
  name:      {label:"Name (A–Z)",          cmp:(a,b)=>a.name.localeCompare(b.name)},
};
const THEN={
  pct:       [["price_asc","Lowest Price"],["price_desc","Highest Price"],["save","Biggest Saving ($)"],["name","Name (A–Z)"],["none","Nothing (exact % order)"]],
  save:      [["pct","Biggest Discount (%)"],["price_asc","Lowest Price"],["name","Name (A–Z)"],["none","Nothing (exact $ order)"]],
  price_asc: [["pct","Biggest Discount (%)"],["save","Biggest Saving ($)"],["name","Name (A–Z)"],["none","Nothing (exact price order)"]],
  price_desc:[["pct","Biggest Discount (%)"],["save","Biggest Saving ($)"],["name","Name (A–Z)"],["none","Nothing (exact price order)"]],
  name:      [],
};
const THEN_DEFAULT={pct:"price_asc",save:"pct",price_asc:"pct",price_desc:"pct"};
const HINT={pct:"Groups discounts into ranges (70%+, 50–70%…), then sorts inside each.",
  save:"Groups savings into ranges ($500+, $200–500…), then sorts inside each.",
  price_asc:"Groups prices into ranges, best deals first in each.",price_desc:"Groups prices into ranges, best deals first in each."};

/* Ranges used to group results when a "Then by" is chosen.
   Each: thresholds (ascending), whether higher ranges come first, the value, and a label. */
const fmtB=v=>"$"+v.toLocaleString("en-NZ");
const rangeIndex=(v,cuts)=>{if(typeof v!=="number"||isNaN(v))return -1;let i=0;while(i<cuts.length&&v>=cuts[i])i++;return i};
const RANGES={
  price:{cuts:[25,50,100,250,500,1000,2000],value:d=>d.now,
    label:(i,c)=>i<0?"No price":i===0?`Under ${fmtB(c[0])}`:i===c.length?`${fmtB(c[i-1])}+`:`${fmtB(c[i-1])} – ${fmtB(c[i])}`},
  pct:{cuts:[10,20,30,40,50,70],value:d=>d.pct,
    label:(i,c)=>i<0?"No discount":i===0?`Under ${c[0]}% off`:i===c.length?`${c[i-1]}%+ off`:`${c[i-1]}–${c[i]}% off`},
  save:{cuts:[20,50,100,200,500],value:d=>d.save,
    label:(i,c)=>i<0?"No saving":i===0?`Save under ${fmtB(c[0])}`:i===c.length?`Save ${fmtB(c[i-1])}+`:`Save ${fmtB(c[i-1])} – ${fmtB(c[i])}`},
};
const GROUPING={price_asc:["price",1],price_desc:["price",-1],pct:["pct",-1],save:["save",-1]};   // [range, direction]
let groupBy=null;
const groupOf=d=>{const r=RANGES[groupBy[0]];return rangeIndex(r.value(d),r.cuts)};
const groupLabel=i=>{const r=RANGES[groupBy[0]];return r.label(i,r.cuts)};

function updateThen(force){
  const opts=THEN[S.sort]||[];
  if(!opts.length){$("#thenWrap").hidden=true;$("#hint").textContent="";S.then="";return}
  const vals=opts.map(o=>o[0]);
  S.then=(!force&&vals.includes(S.then))?S.then:THEN_DEFAULT[S.sort];
  $("#then").innerHTML=opts.map(([v,l])=>`<option value="${v}">${l}</option>`).join("");
  $("#then").value=S.then;$("#thenWrap").hidden=false;$("#hint").textContent=HINT[S.sort]||"";
}

/* ---------------- state ---------------- */
const DEFAULTS={q:"",pmin:null,pmax:null,dmin:null,dmax:null,special:true,unknown:false,images:false,sort:"pct",then:"",page:1,rows:48};
const S={...DEFAULTS,promos:new Set(),cats:new Set()};
let view=[];

/* ---------------- chips ---------------- */
function tally(key){const m=new Map();D.forEach(d=>{const v=d[key];if(v)m.set(v,(m.get(v)||0)+1)});return [...m.entries()].sort((a,b)=>b[1]-a[1])}
const CHIPS=[];
function chipRow(host,items,set,withIcon){
  const draw=()=>{host.innerHTML=items.map(([v,n])=>`<button class="chip" data-v="${esc(v)}" aria-pressed="${set.has(v)}">`+
    (withIcon?`<i class="fa-solid ${icon(v)}"></i>`:"")+`${esc(v)}<span class="n">${n}</span></button>`).join("")};
  host.onclick=e=>{const b=e.target.closest(".chip");if(!b)return;const v=b.dataset.v;set.has(v)?set.delete(v):set.add(v);S.page=1;draw();render()};
  CHIPS.push(draw);draw();
}
chipRow($("#promos"),tally("promo"),S.promos,false);
chipRow($("#cats"),tally("cat"),S.cats,true);

/* ---------------- filter + sort ---------------- */
function pass(d){
  if(d.st==="unknown"&&!S.unknown)return false;
  if(d.st==="special"&&!S.special)return false;
  if(S.q&&!S.q.split(/\s+/).every(t=>d.hay.includes(t)))return false;
  if(S.pmin!=null&&(d.now==null||d.now<S.pmin))return false;
  if(S.pmax!=null&&(d.now==null||d.now>S.pmax))return false;
  if(S.dmin!=null||S.dmax!=null){if(d.pct==null)return false;if(S.dmin!=null&&d.pct<S.dmin)return false;if(S.dmax!=null&&d.pct>S.dmax)return false}
  if(S.promos.size&&!S.promos.has(d.promo))return false;
  if(S.cats.size&&!S.cats.has(d.cat))return false;
  return true;
}
function sortView(){
  const primary=SORTS[S.sort]||SORTS.pct, secondary=SORTS[S.then]||null;
  groupBy=(secondary&&GROUPING[S.sort])||null;
  view.sort((a,b)=>{
    if(groupBy){const x=groupOf(a),y=groupOf(b);if(x!==y)return (x-y)*groupBy[1];
      return secondary.cmp(a,b)||primary.cmp(a,b)||a.name.localeCompare(b.name)}
    return primary.cmp(a,b)||(secondary?secondary.cmp(a,b):0)||a.name.localeCompare(b.name);
  });
}

/* ---------------- cards ---------------- */
const reveal=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("show");reveal.unobserve(e.target)}}),{rootMargin:"0px 0px 120px 0px"});
function card(d){
  const hc=heat(d.pct);
  const visual=(S.images&&d.img)
    ?`<a class="media" href="${esc(pbUrl(d))}" target="_blank" rel="noopener"><span class="ph"><i class="fa-solid ${icon(d.cat)}"></i></span>`+
      `<img src="${esc(d.img)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"></a>`
    :`<div class="icon"><i class="fa-solid ${icon(d.cat)}"></i></div>`;
  const tag=d.promo?`<span class="tag" data-c="${esc(d.promo)}" title="Copy promo code" style="${ppill(d.promo)}"><i class="fa-solid fa-ticket"></i>${esc(d.promo)}</span>`
    :d.st==="special"?`<span class="tag spec">SPECIAL</span>`:`<span class="tag plain">NO DISCOUNT</span>`;
  const price=d.disc!=null
    ?`<div><span class="now">${money(d.disc)}</span><span class="was">${money(d.orig)}</span></div>${d.save?`<span class="save">Save ${money(d.save)}</span>`:""}`
    :`<div><span class="now">${money(d.orig)}</span></div>`;
  return `<article class="card" style="--heat:${hc}"><div class="cbody">
    <div class="ctop"><span class="cat" style="${pill(d.cat)}"><i class="fa-solid ${icon(d.cat)}"></i>${esc(d.cat)}</span>
      ${d.pct!=null?`<span class="pct">-${Math.round(d.pct)}%</span>`:""}</div>
    ${visual}
    <a class="name" href="${esc(pbUrl(d))}" target="_blank" rel="noopener" title="${esc(d.name)}">${esc(d.name)}</a>
    <div class="meta"><span class="part" data-c="${esc(d.part)}" title="Copy part number">${esc(d.part)}</span>${tag}</div>
    <div class="prices">${price}</div>
    <div class="actions"><a class="view" href="${esc(pbUrl(d))}" target="_blank" rel="noopener"><span>View<span class="long">&nbsp;on PB Tech</span></span><i class="fa-solid fa-arrow-right"></i></a>
      <a class="gbtn" href="${esc(gUrl(d))}" target="_blank" rel="noopener" title="Compare prices on Google">G</a></div>
  </div></article>`;
}

function render(){
  view=D.filter(pass);sortView();
  const pages=Math.max(1,Math.ceil(view.length/S.rows));
  if(S.page>pages)S.page=pages;
  const a=(S.page-1)*S.rows,b=Math.min(a+S.rows,view.length);

  $("#found").textContent=view.length.toLocaleString();
  const best=view.reduce((m,d)=>d.pct!=null&&d.pct>m?d.pct:m,-1);
  $("#best").textContent=best>=0?`-${Math.round(best)}%`:"–";
  $("#npromo").textContent=new Set(view.map(d=>d.promo).filter(Boolean)).size;
  $("#range").textContent=view.length?`${(a+1).toLocaleString()}–${b.toLocaleString()} of ${view.length.toLocaleString()}`:"0 results";
  const parts=[...S.cats];if(S.promos.size)parts.push([...S.promos].join(", "));
  $("#heading").textContent=S.q?`Results for "${S.q}"`:(parts.length?parts.join(" · "):"All deals");
  $$(".pageno").forEach(i=>i.value=S.page);$$(".pg .of").forEach(o=>o.textContent=`/ ${pages}`);
  $$('[data-go="prev"]').forEach(x=>x.disabled=S.page<=1);$$('[data-go="next"]').forEach(x=>x.disabled=S.page>=pages);
  $("#empty").hidden=view.length>0;$("#pbarBottom").style.display=pages>1?"":"none";

  const counts={};if(groupBy)view.forEach(d=>{const k=groupOf(d);counts[k]=(counts[k]||0)+1});
  /* In-feed ads only go between complete rows, so they never leave a half-empty row. */
  const cols=Math.max(1,getComputedStyle($("#grid")).gridTemplateColumns.split(" ").filter(Boolean).length);
  let last=null,html="",rowPos=0,sinceAd=0,ads=0;
  for(const d of view.slice(a,b)){
    if(groupBy&&groupOf(d)!==last)rowPos=0;                 /* a range header starts a fresh row */
    if(ADS.feedSlot&&rowPos===0&&sinceAd>=ADS.every&&ads<ADS.maxPerPage){
      html+=`<div class="ad ad-feed"><span class="ad-label">Advertisement</span><ins class="adsbygoogle" style="display:block" data-ad-client="${ADS.client}" data-ad-slot="${ADS.feedSlot}" data-ad-format="auto" data-full-width-responsive="true"></ins></div>`;
      ads++;sinceAd=0}
    rowPos=(rowPos+1)%cols;sinceAd++;
    if(groupBy){const k=groupOf(d);if(k!==last){html+=`<div class="band"><b>${groupLabel(k)}</b><span>${counts[k].toLocaleString()} deals</span></div>`;last=k}}
    html+=card(d);
  }
  const grid=$("#grid");grid.innerHTML=html;
  grid.querySelectorAll("ins.adsbygoogle").forEach(()=>{try{(window.adsbygoogle=window.adsbygoogle||[]).push({})}catch(e){}});
  grid.querySelectorAll(".card").forEach(c=>reveal.observe(c));
  grid.querySelectorAll(".media img").forEach(img=>{
    const ph=img.previousElementSibling;
    img.onload=()=>{img.classList.add("ok");ph.style.display="none"};
    img.onerror=()=>{ph.classList.add("done");img.remove()};   /* keep the category icon */
  });

  const active=(S.q?1:0)+(S.pmin!=null||S.pmax!=null?1:0)+(S.dmin!=null||S.dmax!=null?1:0)+S.promos.size+S.cats.size+(S.unknown?1:0)+(S.special?0:1);
  $("#fcount").textContent=active||"";
}

/* ---------------- interaction ---------------- */
let toastT;function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("on");clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove("on"),1400)}
$("#grid").onclick=e=>{const c=e.target.closest("[data-c]");if(!c)return;e.preventDefault();
  navigator.clipboard?.writeText(c.dataset.c).then(()=>toast("Copied "+c.dataset.c),()=>toast(c.dataset.c))};

let deb;const later=f=>{clearTimeout(deb);deb=setTimeout(f,140)};
const setQ=v=>{S.q=v.trim().toLowerCase();S.page=1;render()};
$("#q").oninput=e=>{$("#q2").value=e.target.value;later(()=>setQ(e.target.value))};
$("#q2").oninput=e=>{$("#q").value=e.target.value;later(()=>setQ(e.target.value))};
const numf=(id,key)=>$(id).oninput=e=>later(()=>{const v=parseFloat(e.target.value);S[key]=isNaN(v)?null:v;S.page=1;render()});
numf("#pmin","pmin");numf("#pmax","pmax");numf("#dmin","dmin");numf("#dmax","dmax");
$("#tSpecial").onchange=e=>{S.special=e.target.checked;S.page=1;render()};
$("#tUnknown").onchange=e=>{S.unknown=e.target.checked;S.page=1;render()};
$("#tImages").onchange=e=>{S.images=e.target.checked;render()};
if(!HAS_IMAGES){$("#tImages").disabled=true;$("#imgToggle").classList.add("off");$("#imgToggle").title="No images in this scrape yet - run the updated scraper"}
$("#sort").onchange=e=>{S.sort=e.target.value;updateThen(false);S.page=1;render()};
$("#then").onchange=e=>{S.then=e.target.value;S.page=1;render()};
$("#rows").onchange=e=>{S.rows=+e.target.value;S.page=1;render()};
const toResults=()=>$("#pbarTop").scrollIntoView({behavior:"smooth",block:"start"});
$$('[data-go]').forEach(b=>b.onclick=()=>{S.page+=b.dataset.go==="next"?1:-1;render();toResults()});
$$(".pageno").forEach(i=>i.onchange=()=>{const v=parseInt(i.value);if(v>0){S.page=v;render();toResults()}});

function resetAll(){
  Object.assign(S,{...DEFAULTS,images:S.images,rows:48});S.promos.clear();S.cats.clear();
  ["#q","#q2","#pmin","#pmax","#dmin","#dmax"].forEach(i=>$(i).value="");
  $("#tSpecial").checked=true;$("#tUnknown").checked=false;$("#sort").value="pct";$("#rows").value="48";
  updateThen(true);CHIPS.forEach(f=>f());closeFilters();render();scrollTo({top:0,behavior:"smooth"});
}
$("#reset").onclick=resetAll;$("#brand").onclick=resetAll;

const openFilters=()=>{$("#filters").classList.add("open");$("#overlay").classList.add("on");document.body.style.overflow="hidden"};
const closeFilters=()=>{$("#filters").classList.remove("open");$("#overlay").classList.remove("on");document.body.style.overflow=""};
$("#filtersBtn").onclick=openFilters;$("#closeFilters").onclick=closeFilters;$("#overlay").onclick=closeFilters;

const setTheme=t=>{document.documentElement.dataset.theme=t;$("#theme").innerHTML=t==="dark"?'<i class="fa-solid fa-sun"></i>':'<i class="fa-solid fa-moon"></i>';
  try{localStorage.setItem("pbtheme",t)}catch(e){}render()};
$("#theme").onclick=()=>setTheme(isDark()?"light":"dark");

$("#export").onclick=()=>{
  const head=["Part Number","Name","Original Price","Discounted Price","% Off","Promo Code","Category","Status","URL"];
  const q=v=>`"${String(v??"").replace(/"/g,'""')}"`;
  const csv=[head.join(",")].concat(view.map(d=>[d.part,d.name,d.orig??"",d.disc??"",d.pct??"",d.promo,d.cat,d.st,pbUrl(d)].map(q).join(","))).join("\r\n");
  const u=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
  const a=document.createElement("a");a.href=u;a.download="pb-deals-view.csv";a.click();URL.revokeObjectURL(u);toast("Exported "+view.length+" rows");
};
addEventListener("keydown",e=>{
  if(e.key==="/"&&!["INPUT","SELECT"].includes(document.activeElement.tagName)){e.preventDefault();(innerWidth<=900?$("#q2"):$("#q")).focus()}
  if(e.key==="Escape")closeFilters();
});
addEventListener("scroll",()=>$("#totop").classList.toggle("on",scrollY>700),{passive:true});
$("#totop").onclick=()=>scrollTo({top:0,behavior:"smooth"});

if(ADS.topSlot){try{(window.adsbygoogle=window.adsbygoogle||[]).push({})}catch(e){}}
updateThen(true);
let saved=null;try{saved=localStorage.getItem("pbtheme")}catch(e){}
if(saved)setTheme(saved);else render();
</script>
</body>
</html>
"""


CLIENT_RE = re.compile(r"^ca-pub-\d{10,20}$")


def ads_config() -> dict:
    """Ad settings for the page. Ads stay off unless ADSENSE_CLIENT looks valid."""
    client = ADSENSE_CLIENT.strip()
    if client and not CLIENT_RE.match(client):
        print(f"[warn] ADSENSE_CLIENT '{client}' doesn't look like ca-pub-XXXXXXXXXXXXXXXX - ads left off")
        client = ""
    slot = lambda v: str(v).strip() if client and str(v).strip().isdigit() else ""
    affiliate = AFFILIATE_URL.strip() if "{url}" in AFFILIATE_URL else ""
    if AFFILIATE_URL.strip() and not affiliate:
        print("[warn] AFFILIATE_URL needs {url} in it - affiliate links left off")
    return {"client": client, "topSlot": slot(AD_SLOT_TOP), "feedSlot": slot(AD_SLOT_FEED),
            "every": max(4, int(AD_FEED_EVERY)), "maxPerPage": max(0, int(AD_FEED_MAX_PER_PAGE)),
            "affiliate": affiliate}


def build(rows, generated: str, ads: dict) -> str:
    data = json.dumps(rows, separators=(",", ":")).replace("</", "<\\/")
    head = top = links = ""
    if ads["client"]:
        head = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ads["client"]}" '
                f'crossorigin="anonymous"></script>')
        links = ' &middot; <a href="privacy.html">Privacy</a>'
    if ads["topSlot"]:
        top = (f'<div class="ad ad-top"><span class="ad-label">Advertisement</span>'
               f'<ins class="adsbygoogle" style="display:block" data-ad-client="{ads["client"]}" data-ad-slot="{ads["topSlot"]}" '
               f'data-ad-format="auto" data-full-width-responsive="true"></ins></div>')
    return (TEMPLATE
            .replace("__ADS_HEAD__", head)
            .replace("__AD_TOP__", top)
            .replace("__FOOT_LINKS__", links)
            .replace("__ADS_JSON__", json.dumps(ads))
            .replace("__FAV_SVG__", FAVICON_SVG)
            .replace("__FAV_32__", FAVICON_32)
            .replace("__FAV_180__", FAVICON_180)
            .replace("__GENERATED__", generated)
            .replace("__COUNT__", f"{len(rows):,}")
            .replace("__DATA__", data))


PRIVACY_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy - PB Deals</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,__FAV_SVG__">
<style>
body{margin:0;background:#070A10;color:#E9EFF7;font:16px/1.65 Inter,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:40px 22px 60px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 6px;color:#FFB45C}
p,li{color:#C3D0E0}a{color:#FFB45C}small{color:#7F93AD}
</style></head><body><main>
<h1>Privacy</h1><small>Last updated __DATE__</small>
<h2>What this site is</h2>
<p>PB Deals lists discounted products scraped from pbtech.co.nz. It is not affiliated with PB Tech. Prices may have changed since the last update.</p>
<h2>Information we collect</h2>
<p>This site has no accounts and no forms, and doesn't collect your name, email or other personal details. Your light/dark theme choice is saved in your own browser (local storage) and never leaves your device.</p>
<h2>Advertising and cookies</h2>
<p>This site shows ads from Google AdSense. Google and its partners use cookies to serve ads based on your visits to this and other websites.
You can learn how Google uses this information at <a href="https://policies.google.com/technologies/partner-sites">policies.google.com/technologies/partner-sites</a>,
and turn off personalised ads at <a href="https://adssettings.google.com">adssettings.google.com</a>.</p>
<h2>Links to other sites</h2>
<p>Product links go to pbtech.co.nz (and Google search), which have their own privacy policies.__AFF_NOTE__</p>
__CONTACT__
<p><a href="./">&larr; Back to the deals</a></p>
</main></body></html>
"""


def write_ad_files(out: Path, ads: dict) -> None:
    pub = ads["client"].replace("ca-", "", 1)                 # ads.txt uses pub-XXXX
    (out.parent / "ads.txt").write_text(f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
    contact = (f"<h2>Contact</h2><p>Questions: <a href=\"mailto:{CONTACT_EMAIL.strip()}\">{CONTACT_EMAIL.strip()}</a></p>"
               if CONTACT_EMAIL.strip() else "")
    aff = " Some product links may be affiliate links, which can earn this site a small commission at no cost to you." if ads["affiliate"] else ""
    page = (PRIVACY_PAGE.replace("__FAV_SVG__", FAVICON_SVG).replace("__DATE__", datetime.now().strftime("%d %B %Y"))
            .replace("__CONTACT__", contact).replace("__AFF_NOTE__", aff))
    (out.parent / "privacy.html").write_text(page, encoding="utf-8")


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
    ads = ads_config()
    out.write_text(build(rows, generated, ads), encoding="utf-8")
    if ads["client"]:
        write_ad_files(out, ads)

    st = Counter(r[7] for r in rows)
    cats = Counter(r[6] for r in rows)
    print(f"[done] {out}  ({out.stat().st_size/1024:.0f} KB)")
    print(f"       {len(rows):,} products  |  {dupes:,} duplicate part numbers dropped")
    print(f"       {st[0]:,} promo   {st[1]:,} special   {st[2]:,} unknown")
    imgs = sum(1 for r in rows if r[8])
    print(f"       {imgs:,} with product images" + ("" if imgs else
          " - run the updated pbscraper.py to collect them (the Images toggle stays off until then)"))
    if unnamed:
        print(f"       {unnamed:,} rows had no part number (kept, not de-duplicated)")
    print("       top categories: " +
          ", ".join(f"{c} {n}" for c, n in cats.most_common(5)))
    if cats.get(OTHER, 0) > len(rows) * 0.25:
        print(f"       note: {cats[OTHER]:,} landed in 'Other' - "
              f"add keywords to CATEGORY_RULES to sharpen this")

    if ads["client"]:
        units = [n for n, v in (("top banner", ads["topSlot"]), ("in-feed", ads["feedSlot"])) if v]
        print(f"       ads ON ({ads['client']}) - " + (", ".join(units) + " units" if units else "Auto ads only")
              + "; wrote ads.txt + privacy.html")
        if not CONTACT_EMAIL.strip():
            print("       tip: set CONTACT_EMAIL so privacy.html has a contact - AdSense reviewers look for one")
    else:
        print("       ads off (set ADSENSE_CLIENT at the top of this file to turn them on)")
    if ads["affiliate"]:
        print("       affiliate links ON")

    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()