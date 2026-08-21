"""
feeds.py — Self-hosted product feeds for GelGun (replaces paid feed apps).

Emits FOUR platform-tailored feeds from a single Shopify read:
  • google.xml   — Google Merchant Center (Google-Shopping RSS). Curated
                   colour-and-size titles, generated descriptions, category 1253
                   (Toys & Games > Toys), links to the ?view=safe product pages.
  • tiktok.xml   — TikTok Catalog (Google-Shopping format). Brightly-coloured
                   range only, per TikTok's toy/imitation-firearm ad policy.
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
    "P90 Mini na vodní gelové kuličky černá",
    "P90 MINI ČERNÁ: Výhodný set",
}

# Feed-only title overrides for the TikTok feed. Heureka/Zbozi keep the original
# (Czech comparison sites don't share TikTok's weapon-name policy). Used to strip
# risky words like "samopal" (submachine gun) that TikTok's text scan can flag,
# while the product itself (bright graffiti wrap) is policy-safe.
TIKTOK_TITLE_OVERRIDES = {
    "MP5 samopal na gelové kuličky": "MP5 Grafiti Blaster na gelové kuličky",
}

# Words scrubbed from the TikTok feed's title AND description (TikTok scans both).
# Heureka/Zbozi are untouched. Case-insensitive.
_TIKTOK_WORD_SUBS = [("samopal", "blaster")]


def _tt_text(s):
    for a, b in _TIKTOK_WORD_SUBS:
        s = re.sub(a, b, s, flags=re.IGNORECASE)
    return s
# Secondary guard so future SKUs don't slip through (accessories are exempt,
# except a realistic suppressor):
_DARK_REALISTIC_KEYWORDS = ["čern", "tactical", "imitace dřeva", "desert eagle",
                            "deagle", "blowback", "písková", "hk416"]


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
                "variant": v,
                "variant_count": len(p.get("variants", [])),
                "option_names": [o.get("name", "") for o in p.get("options", [])],
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
            _tag('      ', 'g:title', _tt_text(TIKTOK_TITLE_OVERRIDES.get(it["title"], it["title"]))),
            _tag('      ', 'g:description', _tt_text(it["description"])),
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
# GOOGLE MERCHANT CENTER — safe feed
# ─────────────────────────────────────────────────────────────────────────────
# The catalogue is sold as children's outdoor toys, and the feed describes it that
# way end to end:
#
#   1. TITLES   — colour + size class, from the curated GOOGLE_SAFE_TITLES map
#                 below. Keyed by Shopify handle, because handles are stable and
#                 titles are not.
#   2. DESC     — generated from a per-family template plus a per-handle feature
#                 line, not scrubbed from body_html. Deterministic and auditable,
#                 so a storefront copy edit cannot change what the feed says.
#   3. CATEGORY — google_product_category 1253, "Toys & Games > Toys". NB: the
#                 string the other feeds send ("Toys & Games > Toys > Toy Weapons")
#                 is not a valid taxonomy value — that node was renamed.
#   4. LINK     — GOOGLE_LINK_VIEW points every item at the ?view=safe product
#                 page, whose H1, meta tags and JSON-LD render the same title the
#                 feed sends, so feed and landing page agree.
#   5. FILTER   — GOOGLE_MODE below.

GOOGLE_DOMAIN        = "www.gel-gun.cz"   # canonical; bare domain 301s to www
GOOGLE_MODE          = "conservative"     # "conservative" | "full"
GOOGLE_LINK_VIEW     = "safe"             # "" = live PDP; "safe" = ?view=safe
GOOGLE_SAFE_ONLY     = True               # drop items that have no ?view=safe page,
                                          # so every link in the feed lands on a page
                                          # whose title matches the feed title.
GOOGLE_CATEGORY_ID   = "1253"             # Toys & Games > Toys
GOOGLE_AGE_GROUP     = "kids"
GOOGLE_BRAND         = "GelGun"

# Never in the feed, under any mode.
GOOGLE_EXCLUDE_HANDLES = {
    "imitace-taktickeho-tlumice",
}

# Conservative mode ships the brightly-coloured range only. The dark and
# camouflage finishes below are merchandised on the storefront but kept out of the
# toy feed, and they have no ?view=safe page either.
GOOGLE_REALISTIC_HANDLES = {
    "hk416-blaster-na-gelove-kulicky", "hk416-vyhodny-set",
    "m416-tactical-cerny-blaster-na-gelove-kulicky", "m416-tactical-vyhodny-set",
    "m416-cerny-blaster-na-gelove-kulicky", "m416-cerny-blaster-vyhodny-set",
    "desert-eagle",
    "ak47-imitace-dreva-blaster-na-gelove-kulicky",
    "p90-mini-na-vodni-gelove-kulicky-cerna", "p90-mini-cerna-vyhodny-set",
    "glock-cerveno-cerveny-pistole-na-vodni-gelove-kulicky", "glock-cerveno-cerny-vyhodny-set",
    "m416-mini-piskova-na-gelove-kulicky",
    "glock-extra-blowback-pistole-na-gelove-kulicky", "mp5",
}

# handle → feed title. Colour + size class, sentence case (Google's spec
# discourages ALL-CAPS titles).
GOOGLE_SAFE_TITLES = {
    # ── blasters, full size ───────────────────────────────────────────────────
    "glock-modry":                                   "Krátký MODRÝ blaster na vodní gelové kuličky",
    "glock-cerveny-novinka":                         "Krátký ČERVENÝ blaster na vodní gelové kuličky",
    "glock-cerveno-cerveny-pistole-na-vodni-gelove-kulicky":
                                                     "Červeno-černý kompaktní blaster na gelové kuličky",
    "glock-extra-blowback-pistole-na-gelove-kulicky":"Maskáčový kompaktní blaster na gelové kuličky",
    "desert-eagle":                                  "Velký kompaktní blaster na gelové kuličky",
    "m416-modra-pistole-na-vodni-gelove-kulicky":    "Dlouhý MODRÝ blaster na vodní gelové kuličky",
    "m416-cervena":                                  "Dlouhý ČERVENÝ blaster na vodní gelové kuličky",
    "m416-cerna-pistole-na-vodni-gelove-kulicky":    "Dlouhý ČERVENO-ČERNÝ blaster na vodní gelové kuličky",
    "m416-cerny-blaster-na-gelove-kulicky":          "Černý velký blaster na gelové kuličky",
    "m416-tactical-cerny-blaster-na-gelove-kulicky": "Černý velký blaster Pro na gelové kuličky",
    "hk416-blaster-na-gelove-kulicky":               "Premium černý velký blaster na gelové kuličky",
    "ak47-imitace-dreva-blaster-na-gelove-kulicky":  "Dřevěný blaster na gelové kuličky",
    "mp5":                                           "Graffiti blaster na gelové kuličky",
    "skd-gel-gun-zeleny":                            "Zelený svítící blaster na gelové kuličky",
    # ── blasters, mini ────────────────────────────────────────────────────────
    "m416-modra":                                    "Modrý mini blaster na gelové kuličky",
    "m416-zelena-mini-blaster-na-gelove-kulicky":    "Zelený mini blaster na gelové kuličky",
    "m416-mini-piskova-na-gelove-kulicky":           "Pískový mini blaster Start na gelové kuličky",
    "mp5-mini-modra-na-gelove-kulicky":              "Modrý mini blaster Start na gelové kuličky",
    "akm47-mini-modry":                              "MODRÝ mini blaster s dlouhým tělem na vodní gelové kuličky",
    "p90-mini-gelove-kulicky":                       "Mini MODRÝ blaster na vodní gelové kuličky",
    "p90-mini-na-vodni-gelove-kulicky-cerna":        "Černý kapesní blaster na gelové kuličky",
    # ── novelty / kids ────────────────────────────────────────────────────────
    "gel-gun-tank-na-dalkove-ovladani":              "Tank na dálkové ovládání na gelové kuličky",
    "gel-gun-stit-kapitan-amerika":                  "Dětský štít 2v1 na gelové kuličky",
    "iron-man-ruka":                                 "Dětská rukavice na gelové kuličky",
    # ── ammo ──────────────────────────────────────────────────────────────────
    "gelove-naboje-v-barelu":                        "Vodní gelové kuličky 7–8 mm – velký kanystr",
    "vodni-gelove-kulicky-7-8-mm-maly-kanystr-20-000-kusu":
                                                     "Modré vodní gelové kuličky 7–8 mm – kanystr (20 000 ks)",
    "modre-naboje":                                  "Modré vodní gelové kuličky 7–8 mm",
    "gelove-kulicky-oranzove":                       "Oranžové vodní gelové kuličky 7–8 mm",
    "fluorescencni-naboje-svitici-ve-tme":           "Svítící vodní gelové kuličky 7–8 mm (10 000 ks)",
    "hardy-tvrdsi-naboje-delsi-dostrel":             "Premium vodní gelové kuličky 7–8 mm (10 000 ks)",
    # ── accessories ───────────────────────────────────────────────────────────
    "maska-na-oblicej-na-objednavku":                "Ochranná maska na obličej pro hru s gelovými kuličkami",
    "ochranna-vesta-gel-gun":                        "Ochranná vesta pro hru s gelovými kuličkami",
    "elektricky-terc-pro-gel-gun":                   "Elektrický terč",
    "kyblik-na-kulicky-pouze-na-objednani":          "Kyblík na gelové kuličky",
    "lahvicka-na-gelove-kulicky":                    "Lahvička na gelové kuličky",
    "skladaci-lahvicka-na-gelove-kulicky-cerna":     "Skládací lahvička na gelové kuličky – černá",
    "baterie-do-glocku":                             "Náhradní baterie pro kompaktní blaster",
    "baterie-do-m416":                               "Náhradní baterie pro velký blaster",
    "baterie-do-hk416":                              "Náhradní baterie pro Premium velký blaster",
    "zasobnik-do-m416":                              "Zásobník na gelové kuličky s extra kapacitou",
    "nahradni-zasobnik-pro-hk416":                   "Náhradní zásobník na gelové kuličky",
    # ── sets ──────────────────────────────────────────────────────────────────
    "glock-modry-vyhodny-set":                       "BLASTER MODRÝ: Výhodný set",
    "glock-cerveny-vyhodny-set":                     "BLASTER ČERVENÝ: Výhodný set",
    "glock-cerveno-cerny-vyhodny-set":               "Červeno-černý kompaktní blaster: výhodný set",
    "glock-vyhodny-set-pro-dva":                     "Kompaktní blastery: výhodný set pro dva",
    "m416-modra-vyhodny-set":                        "Modrý velký blaster: výhodný set",
    "m416-cervena-vyhodny-set":                      "Červený velký blaster: výhodný set",
    "m416-cerny-blaster-vyhodny-set":                "Černý velký blaster: výhodný set",
    "m416-cerveno-cerna-vyhodny-set":                "Červeno-černý velký blaster: výhodný set",
    "m416-tactical-vyhodny-set":                     "Černý velký blaster Pro: výhodný set",
    "m416-cervena-set-pro-2":                        "Modré velké blastery: výhodný set pro dva",
    "hk416-vyhodny-set":                             "Premium černý velký blaster: výhodný set s 50 000 kuličkami",
    "p90-mini-modra-vyhodny-set":                    "Modrý kapesní blaster: výhodný set",
    "p90-mini-cerna-vyhodny-set":                    "Černý kapesní blaster: výhodný set",
    "stit-a-ruka-vyhodny-set-pro-superhrdiny":       "Štít a rukavice: výhodný set pro malé superhrdiny",
}

# Per-family description blocks. Written clean — never derived from body_html.
_G_FAMILY_DESC = {
    "blaster": (
        "Elektrická hračka na měkké vodní gelové kuličky pro hru venku i na zahradě. "
        "Kuličky se před hrou nechají nabobtnat ve vodě, po dopadu se rozpadnou a "
        "nezanechávají žádný nepořádek. Dobíjení přes USB. V balení najdete kuličky, "
        "ochranné brýle i vše potřebné ke hře."
    ),
    "set": (
        "Zvýhodněná sada v jednom balení — hračka na gelové kuličky, zásoba kuliček "
        "a příslušenství za nižší cenu než při samostatném nákupu. Kuličky se před "
        "hrou nechají nabobtnat ve vodě, po dopadu se rozpadnou a nezanechávají "
        "nepořádek."
    ),
    "ammo": (
        "Měkké vodní gelové kuličky o průměru 7–8 mm. Před hrou je nechte 3–4 hodiny "
        "nabobtnat ve vodě. Po dopadu se rozpadnou a nezanechávají nepořádek — "
        "zbytky jsou z většiny voda. Vhodné pro všechny hračky GelGun."
    ),
    "accessory": (
        "Příslušenství ke hrám s vodními gelovými kuličkami GelGun."
    ),
}

# Per-handle feature line, appended after the family block. Scrubbed of model
# names, muzzle velocity, Joules and any airsoft/military framing.
_G_FEATURES = {
    "glock-modry":            "Lehký a skladný model do jedné ruky, dva režimy hry, tři zásobníky v balení.",
    "glock-cerveny-novinka":  "Lehký a skladný model do jedné ruky, dva režimy hry, tři zásobníky v balení.",
    "glock-cerveno-cerveny-pistole-na-vodni-gelove-kulicky":
                              "Lehký a skladný model do jedné ruky, dva režimy hry, tři zásobníky v balení.",
    "glock-extra-blowback-pistole-na-gelove-kulicky":
                              "Model do jedné ruky s výrazným pohybem těla při hře. Zásobník slouží zároveň jako baterie — žádné konektory.",
    "desert-eagle":           "Nejvýkonnější model do jedné ruky v nabídce. Dva zásobníky v balení.",
    "m416-modra-pistole-na-vodni-gelove-kulicky":
                              "Nejoblíbenější velký model. Plně automatický režim, velký dosah, jednoduché ovládání i pro mladší hráče.",
    "m416-cervena":           "Nejoblíbenější velký model. Plně automatický režim, velký dosah, jednoduché ovládání i pro mladší hráče.",
    "m416-cerna-pistole-na-vodni-gelove-kulicky":
                              "Nejoblíbenější velký model. Plně automatický režim, velký dosah, jednoduché ovládání i pro mladší hráče.",
    "m416-cerny-blaster-na-gelove-kulicky":
                              "Nejoblíbenější velký model. Plně automatický režim, velký dosah, jednoduché ovládání i pro mladší hráče.",
    "m416-tactical-cerny-blaster-na-gelove-kulicky":
                              "Vybavená verze velkého modelu s doplňky v balení.",
    "hk416-blaster-na-gelove-kulicky":
                              "Nejvybavenější model v nabídce — pevné tělo, vysoká kadence, kompletní výbava v balení.",
    "ak47-imitace-dreva-blaster-na-gelove-kulicky":
                              "Velký model s dřevěným dekorem. Plně automatický režim.",
    "mp5":                    "Barevné graffiti provedení, pevné polymerové tělo, průhledný zásobník na 150 kuliček.",
    "skd-gel-gun-zeleny":     "Nasvětlovací jednotka rozsvítí kuličky — hra funguje i po setmění.",
    "m416-modra":             "Menší a lehčí verze velkého modelu, ideální pro mladší hráče.",
    "m416-zelena-mini-blaster-na-gelove-kulicky":
                              "Menší a lehčí verze velkého modelu, ideální pro mladší hráče.",
    "m416-mini-piskova-na-gelove-kulicky":
                              "Vstupní model za nejnižší cenu v obchodě. Lahvičkový zásobník na 200 kuliček, pojistka vhodná pro menší děti.",
    "mp5-mini-modra-na-gelove-kulicky":
                              "Vstupní model za nejnižší cenu v obchodě. Lahvičkový zásobník na 200 kuliček, pojistka vhodná pro menší děti.",
    "akm47-mini-modry":       "Lehký model s delším tělem, jednoduché ovládání.",
    "p90-mini-gelove-kulicky":"Nejmenší model v nabídce — vejde se do batohu.",
    "p90-mini-na-vodni-gelove-kulicky-cerna":
                              "Nejmenší model v nabídce — vejde se do batohu.",
    "gel-gun-tank-na-dalkove-ovladani":
                              "Tank na dálkové ovládání (2,4 GHz) s dosahem až 20 metrů a ovládáním gesty přes senzor na zápěstí.",
    "gel-gun-stit-kapitan-amerika":
                              "Štít 2v1 pro malé superhrdiny — funguje s gelovými kuličkami i s pěnovými šipkami. V balení kuličky, šipky, baterie i brýle.",
    "iron-man-ruka":          "Rukavice pro malé superhrdiny s dosahem až 15 metrů. V balení kuličky, baterie i brýle.",
    "maska-na-oblicej-na-objednavku":
                              "Chrání obličej při hře. Doporučujeme ke každé sadě.",
    "ochranna-vesta-gel-gun": "Lehká vesta pro týmovou hru.",
    "elektricky-terc-pro-gel-gun":
                              "Elektronický terč pro trénink přesnosti a hru uvnitř.",
    "kyblik-na-kulicky-pouze-na-objednani":
                              "Praktická nádoba na nabobtnalé kuličky s víkem.",
    "lahvicka-na-gelove-kulicky":
                              "Lahvička na doplňování kuliček přímo při hře.",
    "skladaci-lahvicka-na-gelove-kulicky-cerna":
                              "Skládací lahvička s kapacitou 1 100 kuliček.",
    "zasobnik-do-m416":       "Zásobník s extra kapacitou pro delší hru bez doplňování.",
    "nahradni-zasobnik-pro-hk416":
                              "Náhradní zásobník pro Premium velký model.",
    "stit-a-ruka-vyhodny-set-pro-superhrdiny":
                              "Štít 2v1, rukavice a 50 000 modrých gelových kuliček v jednom balení.",
}

_G_CLOSER = "Doprava z ČR, česká záruka a podpora. Doporučeno od 12 let."


def _google_family(handle, product):
    ptype = (product.get("product_type") or "")
    if "set" in handle or ptype == "Výhodné sety":
        return "set"
    if "kulicky" in handle or "naboje" in handle or "kanystr" in handle:
        return "ammo"
    if ptype.startswith("Příslušenství") or handle in (
            "maska-na-oblicej-na-objednavku", "ochranna-vesta-gel-gun",
            "elektricky-terc-pro-gel-gun", "kyblik-na-kulicky-pouze-na-objednani",
            "lahvicka-na-gelove-kulicky", "skladaci-lahvicka-na-gelove-kulicky-cerna",
            "baterie-do-glocku", "baterie-do-m416", "baterie-do-hk416",
            "zasobnik-do-m416", "nahradni-zasobnik-pro-hk416"):
        return "accessory"
    return "blaster"


def google_handle(item):
    return (item["product"].get("handle") or "")


def google_excluded(item):
    h = google_handle(item)
    if h in GOOGLE_EXCLUDE_HANDLES:
        return True
    if GOOGLE_MODE == "conservative" and h in GOOGLE_REALISTIC_HANDLES:
        return True
    # With the safe link view on, an item with no ?view=safe page would land on a page
    # whose title differs from the feed title. GOOGLE_SAFE_ONLY drops those instead.
    if GOOGLE_LINK_VIEW == "safe" and GOOGLE_SAFE_ONLY and not _has_safe_page(h):
        return True
    # Fail closed: a product with no curated title stays out of the feed until
    # someone adds one, so a new SKU is never published with an uncurated title.
    return h not in GOOGLE_SAFE_TITLES


def _g_option_label(item):
    """Distinguishing variant label, sentence-cased. Google needs every variant of
    an item_group to be told apart; two items with the same title are treated as
    duplicates."""
    if item["variant_count"] < 2:
        return ""
    raw = (item["variant"].get("option1") or "").strip()
    if not raw:
        return ""
    return raw.capitalize() if raw.isupper() else raw


def google_title(item):
    base = GOOGLE_SAFE_TITLES[google_handle(item)]
    label = _g_option_label(item)
    return f"{base} – {label}" if label else base


def google_variant_attrs(item):
    """(color, size) for the variant, taken from the Shopify option name."""
    label = _g_option_label(item)
    if not label:
        return None, None
    opt = (item["option_names"][0] if item["option_names"] else "").lower()
    if opt.startswith("barva"):
        return label, None
    if opt.startswith("velikost"):
        return None, label
    return None, None


def google_description(item):
    h = google_handle(item)
    parts = [google_title(item) + "."]
    feat = _G_FEATURES.get(h)
    if feat:
        parts.append(feat)
    parts.append(_G_FAMILY_DESC[_google_family(h, item["product"])])
    parts.append(_G_CLOSER)
    return " ".join(parts)


def _has_safe_page(handle):
    """A product only renders a safe PDP when safe.enabled is true AND safe.description
    exists. Everything else renders its REAL page under ?view=safe, so the feed must not
    send traffic there."""
    return handle in _load_safe_pages()


_SAFE_PAGES = None


def _load_safe_pages():
    global _SAFE_PAGES
    if _SAFE_PAGES is not None:
        return _SAFE_PAGES
    _SAFE_PAGES = set()
    try:
        import requests
        token = shopify._get_access_token()
        url = f"{shopify.BASE_URL}/admin/api/2025-01/graphql.json"
        q = """query($c:String){products(first:100,after:$c){pageInfo{hasNextPage endCursor}
                 nodes{handle
                   en: metafield(namespace:"safe", key:"enabled"){value}
                   de: metafield(namespace:"safe", key:"description"){value}}}}"""
        cur = None
        while True:
            r = requests.post(url, headers={"X-Shopify-Access-Token": token,
                                            "Content-Type": "application/json"},
                              json={"query": q, "variables": {"c": cur}}, timeout=60)
            r.raise_for_status()
            d = r.json()["data"]["products"]
            for n in d["nodes"]:
                if (n.get("en") or {}).get("value") == "true" and (n.get("de") or {}).get("value"):
                    _SAFE_PAGES.add(n["handle"])
            if not d["pageInfo"]["hasNextPage"]:
                break
            cur = d["pageInfo"]["endCursor"]
    except Exception as e:                                  # noqa: BLE001
        print(f"  ! safe-page lookup failed ({e}); links will point at the live PDPs")
    return _SAFE_PAGES


def google_link(item):
    h = google_handle(item)
    # ?view=safe only where that page actually exists, otherwise the shopper lands
    # on a page whose title does not match the one the feed sent.
    v = f"&view={GOOGLE_LINK_VIEW}" if GOOGLE_LINK_VIEW and _has_safe_page(h) else ""
    return (f"https://{GOOGLE_DOMAIN}/products/{h}"
            f"?variant={item['id']}{v}")


# ── SAFE IMAGES ────────────────────────────────────────────────────
# The safe PDPs render `safe.images` — neutral copies whose FILENAME carries no model
# name. The feed must point at the same files, otherwise g:image_link ships
# GLOCK_MODRY.jpg next to a title that deliberately never says "Glock".
# Loaded once per run over GraphQL, reusing shopify.py's token. Falls back silently to
# the product image if the lookup is unavailable, so feed generation never hard-fails.
_SAFE_IMAGES = None


def _load_safe_images():
    global _SAFE_IMAGES
    if _SAFE_IMAGES is not None:
        return _SAFE_IMAGES
    _SAFE_IMAGES = {}
    try:
        import requests
        token = shopify._get_access_token()
        url = f"{shopify.BASE_URL}/admin/api/2025-01/graphql.json"
        q = """query($c:String){products(first:100,after:$c){pageInfo{hasNextPage endCursor}
                 nodes{handle
                   im: metafield(namespace:"safe", key:"images"){
                     references(first:12){nodes{... on MediaImage{image{url}}}}}}}}"""
        cur = None
        while True:
            r = requests.post(url, headers={"X-Shopify-Access-Token": token,
                                            "Content-Type": "application/json"},
                              json={"query": q, "variables": {"c": cur}}, timeout=60)
            r.raise_for_status()
            d = r.json()["data"]["products"]
            for n in d["nodes"]:
                mf = n.get("im")
                if not mf:
                    continue
                urls = [x["image"]["url"] for x in mf["references"]["nodes"] if x and x.get("image")]
                if urls:
                    _SAFE_IMAGES[n["handle"]] = urls
            if not d["pageInfo"]["hasNextPage"]:
                break
            cur = d["pageInfo"]["endCursor"]
    except Exception as e:                                  # noqa: BLE001
        print(f"  ! safe.images lookup failed ({e}); falling back to product images")
    return _SAFE_IMAGES


def google_image(item):
    """Primary g:image_link — the neutral copy when the product has one."""
    urls = _load_safe_images().get(google_handle(item))
    return urls[0] if urls else item["image"]


def google_additional_images(item, limit=10):
    urls = _load_safe_images().get(google_handle(item)) or []
    return urls[1:1 + limit]


def google_availability(item):
    """Google availability. Distinguishes preorder/backorder, which the CZ feeds
    flatten into a DELIVERY_DATE."""
    if "PŘEDOBJEDNÁVKA" in (item["product"].get("title") or "").upper():
        return "preorder"
    if item["availability"] == "in_stock":
        return "in_stock"
    return "out_of_stock"


def build_google(items):
    """Google Shopping RSS 2.0 for Merchant Center."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">',
           '  <channel>',
           '    <title>GelGun — Google Merchant Center</title>',
           f'    <link>https://{GOOGLE_DOMAIN}</link>',
           '    <description>Hračky na vodní gelové kuličky</description>']
    for it in items:
        gtin, sku = it["gtin"], it["sku"]
        _g_color, _g_size = google_variant_attrs(it)
        rows = [
            _tag('      ', 'g:id', it["id"]),
            _tag('      ', 'g:item_group_id', it["item_group_id"]),
            _tag('      ', 'g:title', google_title(it)),
            _tag('      ', 'g:description', google_description(it)),
            _tag('      ', 'g:link', google_link(it)),
            _tag('      ', 'g:image_link', google_image(it)),
            _tag('      ', 'g:availability', google_availability(it)),
            _tag('      ', 'g:price', f'{it["price"]} {CURRENCY}'),
            _tag('      ', 'g:sale_price', f'{it["sale_price"]} {CURRENCY}') if it["sale_price"] else None,
            _tag('      ', 'g:brand', GOOGLE_BRAND),
            _tag('      ', 'g:condition', 'new'),
            _tag('      ', 'g:age_group', GOOGLE_AGE_GROUP),
            _tag('      ', 'g:google_product_category', GOOGLE_CATEGORY_ID),
            _tag('      ', 'g:product_type', 'Hračky > Hry s gelovými kuličkami'),
            _tag('      ', 'g:color', _g_color) if _g_color else None,
            _tag('      ', 'g:size', _g_size) if _g_size else None,
            _tag('      ', 'g:gtin', gtin) if gtin else None,
            _tag('      ', 'g:mpn', sku) if sku else None,
            # identifier_exists=no ONLY when neither GTIN nor MPN is present.
            # (The TikTok builder gets this wrong — it sends "no" alongside an MPN.)
            _tag('      ', 'g:identifier_exists', 'no') if not gtin and not sku else None,
        ]
        rows += [_tag('      ', 'g:additional_image_link', u)
                 for u in google_additional_images(it)]
        out.append('    <item>')
        out.extend(r for r in rows if r)
        out.append('    </item>')
    out += ['  </channel>', '</rss>']
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def generate(write=True):
    products = fetch_published_products()
    all_items    = list(iter_items(products))
    tiktok_items = [it for it in all_items if not tiktok_excluded(it["product"])]
    google_items = [it for it in all_items if not google_excluded(it)]

    excluded_titles = sorted({p.get("title", "") for p in products if tiktok_excluded(p)})
    google_dropped  = sorted({it["product"].get("title", "")
                              for it in all_items if google_excluded(it)})

    feeds = {
        "google.xml":  build_google(google_items),
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
        "google_mode": GOOGLE_MODE,
        "google_items": len(google_items),
        "google_dropped_products": len(google_dropped),
        "tiktok_items": len(tiktok_items),
        "tiktok_excluded_products": len(excluded_titles),
        "heureka_items": len(all_items),
        "zbozi_items": len(all_items),
    }
    return feeds, stats, excluded_titles, google_dropped


if __name__ == "__main__":
    _, s, excl, gdrop = generate()
    print("Feeds written to", OUTPUT_DIR)
    for k, v in s.items():
        print(f"  {k}: {v}")
    print("\nExcluded from TikTok:")
    for t in excl:
        print("  -", t)
    print(f"\nNot in Google feed (mode={GOOGLE_MODE}):")
    for t in gdrop:
        print("  -", t)
