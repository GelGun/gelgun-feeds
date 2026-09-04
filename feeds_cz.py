"""
feeds_cz.py — Czech comparison-site feeds for GelGun (Heureka.cz, Zbozi.cz).

Owns three files in ./docs/feeds/, and they are THREE DIFFERENT SCHEMAS:

  heureka.xml               <SHOP> / <SHOPITEM>
                            → Heureka admin: Nastavení → Profil obchodu
                              → URL XML obchodu
  heureka-availability.xml  <item_list> / <item id="…">
                            → Heureka admin: Nastavení → Dostupnostní XML soubor
  zbozi.xml                 <SHOP xmlns="http://www.zbozi.cz/ns/offer/1.0">
                            → Zbozi.cz / Sklik Shopping

Putting one of these where another belongs makes the validator reject the file
element by element, starting with "Neočekávaný element SHOP na řádku 2" — which
is exactly what happened when the product feed URL was pasted into the
availability field. validate_cz.py now fails the build on that shape.

feeds.py still contains the original build_heureka / build_zbozi. They are
superseded by this module and are no longer what gets published; run_feeds.py
writes these versions last. Delete them from feeds.py when convenient.

Specs:
  https://sluzby.heureka.cz/napoveda/xml-feed/
  https://sluzby.heureka.cz/napoveda/dostupnostni-feed/
  https://napoveda.sklik.cz/en/shopping-ads/xml-feed-shopping/
"""

import os
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import feeds

OUTPUT_DIR = feeds.OUTPUT_DIR

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
# Heureka pairs an offer to its catalogue only when CATEGORYTEXT is a real path
# in THEIR tree, starting with "Heureka.cz | ". A made-up path counts as a
# missing tag — that is what "Chybějící údaj <CATEGORYTEXT>" meant for 46 of 49
# offers while the feed sent "Hračky | Zbraně a pistole na kuličky".
# Live paths, from the heureka.cz breadcrumb (Sept 2026):
#   hracky.heureka.cz → detske-zbrane-prislusenstvi.heureka.cz → zbrane.heureka.cz
HEUREKA_CAT_WEAPONS     = "Heureka.cz | Hračky | Dětské zbraně a příslušenství | Dětské zbraně"
HEUREKA_CAT_ACCESSORIES = "Heureka.cz | Hračky | Dětské zbraně a příslušenství | Příslušenství pro dětské zbraně"

# Zbozi.cz has its own tree and accepts a free-form path, so it keeps the
# original shop-side wording rather than borrowing Heureka's.
ZBOZI_CAT_WEAPONS     = "Hračky | Zbraně a pistole na kuličky"
ZBOZI_CAT_ACCESSORIES = "Hračky | Příslušenství ke zbraním na kuličky"

# product_type → (heureka CATEGORYTEXT, zbozi CATEGORYTEXT). Keys mirror
# feeds.CATEGORY_MAP; an unknown product_type falls back to the weapons path.
CZ_CATEGORY_MAP = {
    "Dětské zbraně":                    (HEUREKA_CAT_WEAPONS, ZBOZI_CAT_WEAPONS),
    "Gel Gun":                          (HEUREKA_CAT_WEAPONS, ZBOZI_CAT_WEAPONS),
    "Gelový blaster":                   (HEUREKA_CAT_WEAPONS, ZBOZI_CAT_WEAPONS),
    "Výhodné sety":                     (HEUREKA_CAT_WEAPONS, ZBOZI_CAT_WEAPONS),
    "Příslušenství pro dětské zbraně":  (HEUREKA_CAT_ACCESSORIES, ZBOZI_CAT_ACCESSORIES),
}
CZ_CATEGORY_FALLBACK = (HEUREKA_CAT_WEAPONS, ZBOZI_CAT_WEAPONS)

# ── Doprava ──────────────────────────────────────────────────────────────────
# Heureka blocks shops for untrue delivery data, so this mirrors the real GelGun
# price list and nothing more. DELIVERY_PRICE_COD is deliberately NOT sent: the
# cash-on-delivery surcharge is not confirmed, and the spec says to omit the tag
# rather than guess it. Prices in the feed override whatever is set under
# Nastavení → Ceny dopravy in the admin.
FREE_SHIPPING_FROM_CZK = 1500.0
HEUREKA_DELIVERY = [
    ("ZASILKOVNA_NA_ADRESU", 99.0),   # Zásilkovna domů
    ("Z_BOX",                79.0),   # Z-BOX, výdejní box
]

# ── Dostupnost ───────────────────────────────────────────────────────────────
# Restock horizon for anything out of stock, in days. Kept equal to the
# DELIVERY_DATE the product feed declares, so the two feeds never contradict
# each other.
OUT_OF_STOCK_DAYS = 7
DELIVERY_ETA_HOUR = "18:00"      # when a parcel typically reaches the customer
ORDER_DEADLINE_HOUR = "12:00"    # order by this time for the ETA to hold


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _tag(indent, tag, val):
    return f"{indent}<{tag}>{escape(str(val))}</{tag}>" if val not in (None, "") else None


def category_for(item):
    """(heureka CATEGORYTEXT, zbozi CATEGORYTEXT) for one feed item."""
    ptype = (item["product"].get("product_type") or "")
    return CZ_CATEGORY_MAP.get(ptype, CZ_CATEGORY_FALLBACK)


def variant_label(item):
    """Distinguishing variant label, sentence-cased, or "" for a single-variant
    product. Heureka splits variants onto separate catalogue cards and blocks
    offers it cannot tell apart, so two variants must never share a PRODUCTNAME."""
    if item["variant_count"] < 2:
        return ""
    raw = (item["variant"].get("option1") or "").strip()
    if not raw or raw.lower() == "default title":
        return ""
    return raw.capitalize() if raw.isupper() else raw


def variant_param(item):
    """(PARAM_NAME, VAL) from the Shopify option, or None when the product has no
    real option — Shopify's placeholder option is literally named "Title"."""
    label = variant_label(item)
    if not label:
        return None
    name = (item["option_names"][0] if item["option_names"] else "").strip()
    if not name or name.lower() == "title":
        return None
    return name, label


# Colour is stated in the product title but lives in no Shopify field, so it is
# read back out of the title. Compound needles first — "červeno-čern" has to win
# over both "čern" and "červen".
_COLOR_NEEDLES = [
    ("červeno-čern", "červeno-černá"),
    ("modr",         "modrá"),
    ("čern",         "černá"),
    ("červen",       "červená"),
    ("zelen",        "zelená"),
    ("oranžov",      "oranžová"),
    ("pískov",       "písková"),
    ("žlut",         "žlutá"),
    ("bíl",          "bílá"),
]


def color_param(title):
    low = title.lower()
    for needle, val in _COLOR_NEEDLES:
        if needle in low:
            return val
    return None


def product_name(item):
    """PRODUCTNAME, capped at the spec's 200 chars, with the variant label
    appended when the product has more than one variant and the title does not
    already carry it."""
    base = item["title"]
    label = variant_label(item)
    if label and label.lower() not in base.lower():
        base = f"{base} – {label}"
    return base[:200]


def delivery_date(item):
    return 0 if item["availability"] == "in_stock" else OUT_OF_STOCK_DAYS


def _param_rows(indent, item):
    rows, seen = [], set()
    pairs = []
    vp = variant_param(item)
    if vp:
        pairs.append(vp)
    color = color_param(item["title"])
    if color:
        pairs.append(("Barva", color))
    for name, val in pairs:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        rows += [f"{indent}<PARAM>",
                 f"{indent}  <PARAM_NAME>{escape(name)}</PARAM_NAME>",
                 f"{indent}  <VAL>{escape(val)}</VAL>",
                 f"{indent}</PARAM>"]
    return rows


def _delivery_rows(indent, item):
    """<DELIVERY> per carrier, free over FREE_SHIPPING_FROM_CZK — so the price is
    computed per offer rather than declared once in the admin."""
    free = float(item["selling"]) >= FREE_SHIPPING_FROM_CZK
    rows = []
    for delivery_id, price in HEUREKA_DELIVERY:
        rows += [f"{indent}<DELIVERY>",
                 f"{indent}  <DELIVERY_ID>{delivery_id}</DELIVERY_ID>",
                 f"{indent}  <DELIVERY_PRICE>{0 if free else price:.0f}</DELIVERY_PRICE>",
                 f"{indent}</DELIVERY>"]
    return rows


def _shopitem_rows(item, heureka_category, zbozi_category, for_heureka):
    return [
        _tag('    ', 'ITEM_ID', item["id"]),
        _tag('    ', 'PRODUCTNAME', product_name(item)),
        _tag('    ', 'PRODUCT', product_name(item)),
        _tag('    ', 'DESCRIPTION', item["description"]),
        _tag('    ', 'URL', item["link"]),
        _tag('    ', 'IMGURL', item["image"]),
        _tag('    ', 'PRICE_VAT', item["selling"]),
        _tag('    ', 'MANUFACTURER', item["brand"]),
        _tag('    ', 'CATEGORYTEXT', heureka_category if for_heureka else zbozi_category),
        _tag('    ', 'EAN', item["gtin"]) if item["gtin"] else None,
        _tag('    ', 'PRODUCTNO', item["sku"]) if item["sku"] else None,
        _tag('    ', 'ITEMGROUP_ID', item["item_group_id"]),
        _tag('    ', 'DELIVERY_DATE', delivery_date(item)),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Heureka.cz — základní XML feed 2.0
# ─────────────────────────────────────────────────────────────────────────────
def build_heureka(items):
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<SHOP>']
    for it in items:
        hcat, zcat = category_for(it)
        out.append('  <SHOPITEM>')
        out.extend(r for r in _shopitem_rows(it, hcat, zcat, True) if r)
        out.extend(_param_rows('    ', it))
        out.extend(_delivery_rows('    ', it))
        out.append('  </SHOPITEM>')
    out.append('</SHOP>')
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Heureka.cz — dostupnostní XML feed
# ─────────────────────────────────────────────────────────────────────────────
def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def _at(dt, hhmm):
    h, m = hhmm.split(":")
    return dt.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def _next_business_day(day):
    d = day + timedelta(days=1)
    while d.weekday() >= 5:          # Sat/Sun — nothing is dispatched
        d += timedelta(days=1)
    return d


def _next_order_deadline(now):
    """The next cut-off that has not passed yet. A feed built at 14:30 must not
    promise a same-day cut-off of 12:00 — that deadline is already gone, and a
    timestamp in the past is the kind of untrue delivery claim Heureka blocks
    shops for."""
    d = _at(now, ORDER_DEADLINE_HOUR)
    if d <= now:
        d = _at(now + timedelta(days=1), ORDER_DEADLINE_HOUR)
    while d.weekday() >= 5:
        d = _at(d + timedelta(days=1), ORDER_DEADLINE_HOUR)
    return d


def _availability_rows(indent, item, now):
    """At least one of stock_quantity / delivery_time has to be present: an item
    carrying neither means "cannot be delivered", and an item left out of the
    feed altogether shows as "info v obchodě" on Heureka even when the product
    feed says it is in stock. So every offer gets a row."""
    v = item["variant"]
    tracked = v.get("inventory_management") is not None
    qty = int(v.get("inventory_quantity") or 0)

    if item["availability"] != "in_stock":
        eta = _at(now + timedelta(days=OUT_OF_STOCK_DAYS), DELIVERY_ETA_HOUR)
        return [f"{indent}<stock_quantity>0</stock_quantity>",
                f"{indent}<delivery_time>{_fmt(eta)}</delivery_time>"]

    if tracked and qty > 0:
        return [f"{indent}<stock_quantity>{qty}</stock_quantity>"]

    # In stock but with no honest count (untracked, or overselling allowed):
    # declare a delivery time instead of inventing a quantity.
    deadline = _next_order_deadline(now)
    eta = _at(_next_business_day(deadline), DELIVERY_ETA_HOUR)
    return [f'{indent}<delivery_time orderDeadline="{_fmt(deadline)}">'
            f'{_fmt(eta)}</delivery_time>']


def build_heureka_availability(items, now=None):
    now = now or datetime.now()
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<item_list>']
    for it in items:
        out.append(f'  <item id="{escape(it["id"])}">')
        out.extend(_availability_rows('    ', it, now))
        out.append('  </item>')
    out.append('</item_list>')
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Zbozi.cz / Seznam
# ─────────────────────────────────────────────────────────────────────────────
ZBOZI_NS = "http://www.zbozi.cz/ns/offer/1.0"


def build_zbozi(items):
    """The namespace is mandatory. Without it Seznam rejects every element the
    same way Heureka does — which is what this feed was heading for while it was
    a byte-for-byte copy of heureka.xml."""
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           f'<SHOP xmlns="{ZBOZI_NS}">']
    for it in items:
        hcat, zcat = category_for(it)
        out.append('  <SHOPITEM>')
        out.extend(r for r in _shopitem_rows(it, hcat, zcat, False) if r)
        out.extend(_param_rows('    ', it))
        out.append('  </SHOPITEM>')
    out.append('</SHOP>')
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def generate(items=None, write=True):
    """Build the three Czech feeds. `items` is feeds.iter_items() output; when it
    is None the products are fetched here."""
    if items is None:
        items = list(feeds.iter_items(feeds.fetch_published_products()))
    items = list(items)

    out = {
        "heureka.xml":              build_heureka(items),
        "heureka-availability.xml": build_heureka_availability(items),
        "zbozi.xml":                build_zbozi(items),
    }
    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for name, xml in out.items():
            with open(os.path.join(OUTPUT_DIR, name), "w", encoding="utf-8") as f:
                f.write(xml)

    stats = {
        "heureka_items": len(items),
        "heureka_availability_items": len(items),
        "zbozi_items": len(items),
        "with_ean": sum(1 for it in items if it["gtin"]),
        "with_param": sum(1 for it in items if _param_rows("", it)),
        "free_shipping": sum(1 for it in items
                             if float(it["selling"]) >= FREE_SHIPPING_FROM_CZK),
    }
    return out, stats


if __name__ == "__main__":
    _, s = generate()
    print("Czech feeds written to", OUTPUT_DIR)
    for k, v in s.items():
        print(f"  {k}: {v}")
