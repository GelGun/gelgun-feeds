"""
feeds.py — Self-hosted product feeds for GelGun (replaces paid feed apps).

Emits THREE platform-tailored feeds from a single Shopify read:
  • tiktok.xml   — TikTok Catalog (Google-Shopping format). SAFE PRODUCTS ONLY:
                   realistic / dark / replica blasters are filtered out to stay
                   inside TikTok's toy/imitation-firearm ad policy.
  • heureka.xml  — Heureka.cz (SHOP / SHOPITEM).
  • zbozi.xml    — Zbozi.cz / Seznam (SHOP / SHOPITEM, Zbozi dialect).

Design:
  • Reuses Olda-connector's shopify.py auth (_shopify_get). Read-only.
  • Writes static files into ./docs/feeds/ ; these are pushed to the PUBLIC
    'gelgun-feeds' repo (GitHub Pages) so Google/TikTok/Heureka/Zbozi can fetch
    them on a schedule.
  • <id> = Shopify VARIANT id — identical to content_id in the TikTok purchase
    pixel, so CompletePayment events match catalog products for DPA/retargeting.
"""

import html
import re
import os
from xml.sax.saxutils import escape

import shopify  # Olda-connector Shopify Admin API client (auth reused)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
STORE_DOMAIN   = "gel-gun.cz"
CURRENCY       = "CZK"
BRAND_FALLBACK = "GEL GUN"
OUTPUT_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "feeds")

# product_type → (google_product_category, heureka/zbozi CATEGORYTEXT)
CATEGORY_MAP = {
    "Dětské zbraně":                    ("Toys & Games > Toys > Toy Weapons",
                                         "Hračky | Zbraně a pistole na kuličky"),
    "Gel Gun":                          ("Toys & Games > Toys > Toy Weapons",
                                         "Hračky | Zbraně a pistole na kuličky"),
    "Gelový blaster":                   ("Toys & Games > Toys > Toy Weapons",
                                         "Hračky | Zbraně a pistole na kuličky"),
    "Výhodné sety":                     ("Toys & Games > Toys > Toy Weapons",
                                         "Hračky | Zbraně a pistole na kuličky"),
    "Příslušenství pro dětské zbraně":  ("Toys & Games > Toys > Toy Weapons Accessories",
                                         "Hračky | Příslušenství ke zbraním na kuličky"),
}
CATEGORY_FALLBACK = ("Toys & Games > Toys", "Hračky")

# ── TikTok safety filter ──────────────────────────────────────────────────────
# TikTok ad policy: toy/imitation firearms are allowed only when brightly coloured
# or fully transparent; predominantly dark/realistic/replica items are restricted.
# Accessories & ammo are safe (except a realistic suppressor). New products default
# to INCLUDED unless they hit the dark/realistic keyword guard below.
#
# Explicit exclusions (single source of truth, easy to curate):
TIKTOK_EXCLUDE_TITLES = {
    "AK47 Imitace Dřeva - Blaster na gelové kuličky",
    "Desert Eagle na gelové kuličky",
    "Glock (Extra Blowback) pistole na gelové kuličky",
    "Glock ČERVENO-ČERNÝ pistole na vodní gelové kuličky",
    "GLOCK ČERVENO-ČERNÝ: Výhodný set",
    "GelGun Imitace Taktického Tlumiče",
    "HK416 Blaster na Gelové Kuličky",
    "HK416: Výhodný set s 50 000 kuličkami",
    "M416 Mini Písková na gelové kuličky",
    "M416 TACTICAL - Černý Blaster na Gelové kuličky (PŘEDOBJEDNÁVKA)",
    "M416 TACTICAL: Výhodný set",
    "M416 ČERNÁ: Výhodný set",
    "M416 ČERNÝ Blaster na Gelové Kuličky",
    "M416 ČERVENO-ČERNÁ: Výhodný set",
    "M416 ČERVENO-ČERNÝ Blaster na Gelové Kuličky",
    "MP5 samopal na gelové kuličky",
    "P90 Mini na vodní gelové kuličky černá",
    "P90 MINI ČERNÁ: Výhodný set",
}
# Secondary guard so future SKUs don't slip through (accessories are exempt,
# except a realistic suppressor):
_DARK_REALISTIC_KEYWORDS = ["čern", "tactical", "imitace dřeva", "desert eagle",
                            "deagle", "blowback", "mp5 samopal", "písková", "hk416"]


def tiktok_excluded(product):
    title = product.get("title", "")
    if title in TIKTOK_EXCLUDE_TITLES:
        return True
    low = title.lower()
    is_accessory = (product.get("product_type") or "").startswith("Příslušenství")
    if is_accessory:
        return "tlumič" in low          # suppressor stays out even as an accessory
    return any(k in low for k in _DARK_REALISTIC_KEYWORDS)


# ─────────────────────────────────────────────────────────────────────────────
# Shopify fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_published_products():
    products, since_id = [], 0
    while True:
        batch = shopify._shopify_get("/products.json", {
            "limit": 250, "since_id": since_id, "status": "active",
        }).get("products", [])
        if not batch:
            break
        products.extend(batch)
        since_id = batch[-1]["id"]
        if len(batch) < 250:
            break
    return [p for p in products if p.get("published_at")]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def variant_image(product, variant):
    if variant.get("image_id"):
        for img in product.get("images", []):
            if img.get("id") == variant["image_id"]:
                return img.get("src")
    imgs = product.get("images", [])
    return imgs[0]["src"] if imgs else None


def availability(variant):
    if variant.get("inventory_management") is None:
        return "in_stock"
    if (variant.get("inventory_quantity") or 0) > 0:
        return "in_stock"
    if variant.get("inventory_policy") == "continue":
        return "in_stock"
    return "out_of_stock"


def price_pair(variant):
    price = float(variant.get("price") or 0)
    cmp_at = float(variant.get("compare_at_price") or 0)
    if cmp_at > price:
        return f"{cmp_at:.2f}", f"{price:.2f}"
    return f"{price:.2f}", None


def category_for(product):
    return CATEGORY_MAP.get(product.get("product_type"), CATEGORY_FALLBACK)


def iter_items(products):
    for p in products:
        gcat, hcat = category_for(p)
        for v in p.get("variants", []):
            reg, sale = price_pair(v)
            img = variant_image(p, v)
            if not img:
                continue                          # every feed requires an image
            yield {
                "id": str(v["id"]),
                "item_group_id": str(p["id"]),
                "title": p.get("title", ""),
                "description": strip_html(p.get("body_html")) or p.get("title", ""),
                "link": f"https://{STORE_DOMAIN}/products/{p.get('handle')}?variant={v['id']}",
                "image": img,
                "availability": availability(v),
                "price": reg, "sale_price": sale,
                "selling": sale or reg,
                "brand": p.get("vendor") or BRAND_FALLBACK,
                "gtin": v.get("barcode") or "",
                "sku": v.get("sku") or "",
                "google_category": gcat,
                "cz_category": hcat,
                "product": p,
            }


# ─────────────────────────────────────────────────────────────────────────────
# Feed builders
# ─────────────────────────────────────────────────────────────────────────────
def _tag(indent, tag, val):
    return f"{indent}<{tag}>{escape(str(val))}</{tag}>" if val not in (None, "") else None


def build_tiktok(items):
    """Google-Shopping RSS — the format TikTok Catalog ingests."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">',
           '  <channel>',
           '    <title>GelGun — TikTok</title>',
           f'    <link>https://{STORE_DOMAIN}</link>',
           '    <description>GelGun TikTok catalog (policy-safe products)</description>']
    for it in items:
        rows = [
            _tag('      ', 'g:id', it["id"]),
            _tag('      ', 'g:item_group_id', it["item_group_id"]),
            _tag('      ', 'g:title', it["title"]),
            _tag('      ', 'g:description', it["description"]),
            _tag('      ', 'g:link', it["link"]),
            _tag('      ', 'g:image_link', it["image"]),
            _tag('      ', 'g:availability', it["availability"]),
            _tag('      ', 'g:price', f'{it["price"]} {CURRENCY}'),
            _tag('      ', 'g:sale_price', f'{it["sale_price"]} {CURRENCY}') if it["sale_price"] else None,
            _tag('      ', 'g:brand', it["brand"]),
            _tag('      ', 'g:condition', 'new'),
            _tag('      ', 'g:google_product_category', it["google_category"]),
            _tag('      ', 'g:gtin', it["gtin"]) if it["gtin"] else None,
            _tag('      ', 'g:mpn', it["sku"]) if it["sku"] else None,
            _tag('      ', 'g:identifier_exists', 'no') if not it["gtin"] else None,
        ]
        out.append('    <item>')
        out.extend(r for r in rows if r)
        out.append('    </item>')
    out += ['  </channel>', '</rss>']
    return "\n".join(out)


def build_heureka(items):
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<SHOP>']
    for it in items:
        rows = [
            _tag('    ', 'ITEM_ID', it["id"]),
            _tag('    ', 'PRODUCTNAME', it["title"]),
            _tag('    ', 'PRODUCT', it["title"]),
            _tag('    ', 'DESCRIPTION', it["description"]),
            _tag('    ', 'URL', it["link"]),
            _tag('    ', 'IMGURL', it["image"]),
            _tag('    ', 'PRICE_VAT', it["selling"]),
            _tag('    ', 'MANUFACTURER', it["brand"]),
            _tag('    ', 'CATEGORYTEXT', it["cz_category"]),
            _tag('    ', 'EAN', it["gtin"]) if it["gtin"] else None,
            _tag('    ', 'PRODUCTNO', it["sku"]) if it["sku"] else None,
            _tag('    ', 'ITEMGROUP_ID', it["item_group_id"]),
            _tag('    ', 'DELIVERY_DATE', 0 if it["availability"] == "in_stock" else 7),
        ]
        out.append('  <SHOPITEM>')
        out.extend(r for r in rows if r)
        out.append('  </SHOPITEM>')
    out.append('</SHOP>')
    return "\n".join(out)


def build_zbozi(items):
    """Zbozi.cz / Seznam dialect of SHOP / SHOPITEM."""
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<SHOP>']
    for it in items:
        rows = [
            _tag('    ', 'ITEM_ID', it["id"]),
            _tag('    ', 'PRODUCTNAME', it["title"]),
            _tag('    ', 'PRODUCT', it["title"]),
            _tag('    ', 'DESCRIPTION', it["description"]),
            _tag('    ', 'URL', it["link"]),
            _tag('    ', 'IMGURL', it["image"]),
            _tag('    ', 'PRICE_VAT', it["selling"]),
            _tag('    ', 'MANUFACTURER', it["brand"]),
            _tag('    ', 'CATEGORYTEXT', it["cz_category"]),
            _tag('    ', 'EAN', it["gtin"]) if it["gtin"] else None,
            _tag('    ', 'PRODUCTNO', it["sku"]) if it["sku"] else None,
            _tag('    ', 'ITEMGROUP_ID', it["item_group_id"]),
            _tag('    ', 'DELIVERY_DATE', 0 if it["availability"] == "in_stock" else 7),
        ]
        out.append('  <SHOPITEM>')
        out.extend(r for r in rows if r)
        out.append('  </SHOPITEM>')
    out.append('</SHOP>')
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def generate(write=True):
    products = fetch_published_products()
    all_items    = list(iter_items(products))
    tiktok_items = [it for it in all_items if not tiktok_excluded(it["product"])]

    excluded_titles = sorted({p.get("title", "") for p in products if tiktok_excluded(p)})

    feeds = {
        "tiktok.xml":  build_tiktok(tiktok_items),
        "heureka.xml": build_heureka(all_items),
        "zbozi.xml":   build_zbozi(all_items),
    }
    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for name, xml in feeds.items():
            with open(os.path.join(OUTPUT_DIR, name), "w", encoding="utf-8") as f:
                f.write(xml)

    stats = {
        "products_published": len(products),
        "variants_all": len(all_items),
        "tiktok_items": len(tiktok_items),
        "tiktok_excluded_products": len(excluded_titles),
        "heureka_items": len(all_items),
        "zbozi_items": len(all_items),
    }
    return feeds, stats, excluded_titles


if __name__ == "__main__":
    _, s, excl = generate()
    print("Feeds written to", OUTPUT_DIR)
    for k, v in s.items():
        print(f"  {k}: {v}")
    print("\nExcluded from TikTok:")
    for t in excl:
        print("  -", t)
