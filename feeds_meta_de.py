"""
feeds_meta_de.py — primary product feeds for the per-market Meta catalogs.

The main Meta catalog ("Shopify Product Catalog") is filled by the Shopify Facebook &
Instagram app with Czech data only, and Shopify outranks every country/language
override feed there (tested 13–14 Nov 2026: price, link, title and description from
override feeds were all rejected with "Shopify has higher priority", and Configure
sources does not list override feeds). So each extra market gets its OWN catalog,
fed only by its file here:

  docs/feeds/meta-de.csv   catalog "GelGun DE" — German text, EUR, gel-gun.de links
  docs/feeds/meta-sk.csv   catalog "GelGun SK" — Slovak text, EUR, gel-gun.cz/sk-sk links

id = Shopify variant id, the same content_id the Meta pixel sends on every storefront,
so the pixel matches all catalogs.

Prices come from Shopify's own price lists (contextualPricing for the market's
country), never converted from CZK. A variant without an EUR price is left out.
A product without a translated title is left out of that market's feed (Czech text
in a German/Slovak catalog would look broken).

product_type holds a stable family key (blaster / set / ammo / accessory) that the
catalogs' product sets filter on.
"""

import csv
import html
import json
import os
import re

import requests

import shopify

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "feeds")
FB_PUBLICATION = "gid://shopify/Publication/106325967114"   # Facebook & Instagram
BRAND = "GelGun"
GPC = "Toys & Games > Toys > Toy Weapons & Gadgets"

MARKETS = {
    "de": {"file": "meta-de.csv", "price_alias": "pDE",
           "base": "https://www.gel-gun.de",
           "utm": "utm_source=facebook&utm_content=Facebook_DE"},
    "sk": {"file": "meta-sk.csv", "price_alias": "pSK",
           "base": "https://www.gel-gun.cz/sk-sk",
           "utm": "utm_source=facebook&utm_content=Facebook_SK"},
}

FAMILY = {
    "Dětské zbraně": "blaster",
    "Gel Gun": "blaster",
    "Gelový blaster": "blaster",
    "Výhodné sety": "set",
}

# Option values are Czech in Shopify; a variant suffix is only added when we can
# say it in the target language.
_OPTS = {
    "de": {"modr": "Blau", "červen": "Rot", "čern": "Schwarz", "zelen": "Grün",
           "oranž": "Orange", "bíl": "Weiß", "žlut": "Gelb", "růžov": "Rosa",
           "fialov": "Lila"},
    "sk": {"modr": "Modrá", "červen": "Červená", "čern": "Čierna", "zelen": "Zelená",
           "oranž": "Oranžová", "bíl": "Biela", "žlut": "Žltá", "růžov": "Ružová",
           "fialov": "Fialová"},
}

FIELDS = ["id", "item_group_id", "title", "description", "availability", "condition",
          "price", "sale_price", "link", "image_link", "additional_image_link",
          "brand", "product_type", "google_product_category"]

_Q = """
query($cursor:String){
  products(first:25, after:$cursor, query:"status:active"){
    pageInfo{ hasNextPage endCursor }
    nodes{
      legacyResourceId handle title productType
      publishedOnPublication(publicationId:"%s")
      de: translations(locale:"de"){ key value }
      sk: translations(locale:"sk"){ key value }
      images(first:6){ nodes{ url } }
      variants(first:50){ nodes{
        legacyResourceId availableForSale
        image{ url }
        selectedOptions{ value }
        pDE: contextualPricing(context:{country:DE}){
          price{ amount currencyCode } compareAtPrice{ amount currencyCode } }
        pSK: contextualPricing(context:{country:SK}){
          price{ amount currencyCode } compareAtPrice{ amount currencyCode } }
      }}
    }
  }
}
""" % FB_PUBLICATION


def _gql(query, variables=None):
    token = shopify._get_access_token()
    r = requests.post(
        f"{shopify.BASE_URL}/admin/api/2025-01/graphql.json",
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}}, timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"])[:500])
    return d["data"]


def _plain(body):
    text = re.sub(r"<[^>]+>", " ", body or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    if len(text) > 4900:
        text = text[:4900].rsplit(" ", 1)[0] + " …"
    return text


def _opt(lang, value):
    v = value.strip().lower()
    for stem, word in _OPTS[lang].items():
        if v.startswith(stem):
            return word
    return None


def load_products():
    out, cursor = [], None
    while True:
        d = _gql(_Q, {"cursor": cursor})["products"]
        out += d["nodes"]
        if not d["pageInfo"]["hasNextPage"]:
            return out
        cursor = d["pageInfo"]["endCursor"]


def build(products, key):
    m = MARKETS[key]
    rows, skipped = [], []
    for p in products:
        if not p.get("publishedOnPublication"):
            continue
        tr = {t["key"]: t["value"] for t in p[key]}
        title = (tr.get("title") or "").strip()
        if not title:
            skipped.append(f"{p['title']} (no {key} title)")
            continue
        imgs = [i["url"] for i in p["images"]["nodes"]]
        if not imgs:
            skipped.append(f"{p['title']} (no image)")
            continue
        desc = _plain(tr.get("body_html")) or title
        family = FAMILY.get(p.get("productType") or "",
                            "ammo" if re.search(r"kuli[čc]k", p["title"], re.I) else "accessory")
        variants = p["variants"]["nodes"]
        for v in variants:
            vid = v["legacyResourceId"]
            cp = v.get(m["price_alias"]) or {}
            price = cp.get("price") or {}
            if price.get("currencyCode") != "EUR" or not price.get("amount"):
                skipped.append(f"{p['title']} / {vid} (no EUR price)")
                continue
            amount = float(price["amount"])
            cmp_ = cp.get("compareAtPrice") or {}
            regular = max(amount, float(cmp_["amount"]) if cmp_.get("amount") else 0.0)
            vtitle = title
            if len(variants) > 1:
                opts = [w for w in (_opt(key, o["value"]) for o in v["selectedOptions"]) if w]
                if opts:
                    vtitle = f"{title} – {' / '.join(opts)}"
            main = (v.get("image") or {}).get("url") or imgs[0]
            rows.append({
                "id": vid,
                "item_group_id": p["legacyResourceId"],
                "title": vtitle[:200],
                "description": desc,
                "availability": "in stock" if v["availableForSale"] else "out of stock",
                "condition": "new",
                "price": f"{regular:.2f} EUR",
                "sale_price": f"{amount:.2f} EUR" if amount < regular else "",
                "link": f"{m['base']}/products/{p['handle']}?variant={vid}&{m['utm']}",
                "image_link": main,
                "additional_image_link": ",".join(u for u in imgs if u != main)[:2000],
                "brand": BRAND,
                "product_type": family,
                "google_product_category": GPC,
            })
    return rows, skipped


def generate(write=True):
    products = load_products()
    result = {}
    for key, m in MARKETS.items():
        rows, skipped = build(products, key)
        # Fail-closed: never publish a (near-)empty file — the scheduled fetch would
        # then delete most of the catalog.
        if len(rows) < 30:
            raise RuntimeError(f"{key}: only {len(rows)} rows, not writing")
        if write:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            with open(os.path.join(OUTPUT_DIR, m["file"]), "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows(rows)
        result[key] = (rows, skipped)
    return result


if __name__ == "__main__":
    for key, (rows, skipped) in generate(write=True).items():
        print(f"meta {key}: {len(rows)} rows, skipped {len(skipped)}")
        for x in skipped:
            print("  skipped:", x)
