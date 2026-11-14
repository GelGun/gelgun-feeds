"""
feeds_meta_de.py — primary product feed for the separate Meta catalog "GelGun DE".

The main Meta catalog ("Shopify Product Catalog") is filled by the Shopify Facebook &
Instagram app for the Czech market only, and that source outranks any override feed.
So DE/AT ads use their own catalog, fed only by this file:

  docs/feeds/meta-de.csv   German title/description, EUR price, gel-gun.de link

id = Shopify variant id, the same content_id the Meta pixel sends on gel-gun.de, so
the pixel matches both catalogs.

Text comes from the Shopify German translations (locale "de"); prices from Shopify's
own DACH price list (contextualPricing, country DE), never converted from CZK.
Fail-closed: a product without a German title, or a variant without an EUR price,
is left out rather than shown in Czech or in Kč.

product_type holds a stable family key (blaster / set / ammo / accessory) that the
catalog's product sets filter on.
"""

import csv
import html
import json
import os
import re

import requests

import shopify

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "feeds")
DE_DOMAIN = "www.gel-gun.de"
FB_PUBLICATION = "gid://shopify/Publication/106325967114"   # Facebook & Instagram
UTM = "utm_source=facebook&utm_content=Facebook_DE"
BRAND = "GelGun"

FAMILY = {
    "Dětské zbraně": "blaster",
    "Gel Gun": "blaster",
    "Gelový blaster": "blaster",
    "Výhodné sety": "set",
}

_DE_OPTS = {
    "modrá": "Blau", "modré": "Blau", "modrý": "Blau",
    "červená": "Rot", "červené": "Rot", "červený": "Rot",
    "černá": "Schwarz", "černé": "Schwarz", "černý": "Schwarz",
    "zelená": "Grün", "zelené": "Grün", "zelený": "Grün",
    "oranžová": "Orange", "oranžové": "Orange",
    "bílá": "Weiß", "bílé": "Weiß", "žlutá": "Gelb", "žluté": "Gelb",
    "růžová": "Rosa", "fialová": "Lila", "mix": "Mix",
}

FIELDS = ["id", "item_group_id", "title", "description", "availability", "condition",
          "price", "sale_price", "link", "image_link", "additional_image_link",
          "brand", "product_type", "google_product_category"]

_Q = """
query($cursor:String){
  products(first:40, after:$cursor, query:"status:active"){
    pageInfo{ hasNextPage endCursor }
    nodes{
      id legacyResourceId handle title productType
      publishedOnPublication(publicationId:"%s")
      translations(locale:"de"){ key value }
      images(first:6){ nodes{ url } }
      variants(first:50){ nodes{
        legacyResourceId availableForSale
        image{ url }
        selectedOptions{ name value }
        contextualPricing(context:{country:DE}){
          price{ amount currencyCode } compareAtPrice{ amount currencyCode }
        }
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


def load_products():
    out, cursor = [], None
    while True:
        d = _gql(_Q, {"cursor": cursor})["products"]
        out += d["nodes"]
        if not d["pageInfo"]["hasNextPage"]:
            return out
        cursor = d["pageInfo"]["endCursor"]


def build(products):
    rows, skipped = [], []
    for p in products:
        if not p.get("publishedOnPublication"):
            continue
        tr = {t["key"]: t["value"] for t in p["translations"]}
        title = (tr.get("title") or "").strip()
        if not title:
            skipped.append(f"{p['title']} (no German title)")
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
            cp = v.get("contextualPricing") or {}
            price = cp.get("price") or {}
            if price.get("currencyCode") != "EUR" or not price.get("amount"):
                skipped.append(f"{p['title']} / {vid} (no EUR price)")
                continue
            amount = float(price["amount"])
            cmp_ = cp.get("compareAtPrice") or {}
            regular = max(amount, float(cmp_["amount"]) if cmp_.get("amount") else 0.0)
            vtitle = title
            if len(variants) > 1:
                # Option values are Czech in Shopify; only add ones we can say in German.
                opts = [_DE_OPTS[o["value"].strip().lower()] for o in v["selectedOptions"]
                        if o["value"].strip().lower() in _DE_OPTS]
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
                "link": f"https://{DE_DOMAIN}/products/{p['handle']}?variant={vid}&{UTM}",
                "image_link": main,
                "additional_image_link": ",".join(u for u in imgs if u != main)[:2000],
                "brand": BRAND,
                "product_type": family,
                "google_product_category": "Toys & Games > Toys > Toy Weapons & Gadgets",
            })
    return rows, skipped


def generate(write=True):
    rows, skipped = build(load_products())
    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "meta-de.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
    return rows, skipped


if __name__ == "__main__":
    r, s = generate(write=True)
    print(f"meta DE rows: {len(r)}, skipped: {len(s)}")
    for x in s:
        print("  skipped:", x)
