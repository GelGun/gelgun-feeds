"""
feeds_meta_de.py — country and language override feeds for the Meta catalog.

The Meta catalog "Shopify Product Catalog" is filled by the Shopify Facebook &
Instagram app with Czech data only (Czech names, CZK, gel-gun.cz links). These two
files add the other markets to the SAME catalog:

  docs/feeds/meta-country.csv   override = DE / AT / SK → EUR price, sale price,
                                 availability and the market's own store link
  docs/feeds/meta-language.csv  override = de_DE / sk_SK → title + description

In Commerce Manager → Data sources → Configure sources, both feeds are ranked above
Shopify for those attributes. They only hold DE/AT/SK and German/Slovak rows, so
Czech viewers keep Shopify's data unchanged.

id = Shopify variant id = the retailer_id the Shopify app uses (and the pixel's
content_id). Prices come from Shopify's own price lists via contextualPricing for
the market's country — never converted from CZK. Fail-closed: a product without a
translated title, or a variant without an EUR price, gets no row for that market, so
it falls back to the Czech data rather than showing something half-translated.
A product with a price but no translated title still gets its country row (EUR
price, own store link) and keeps the Czech text.
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

# market key -> settings
MARKETS = {
    "de": {
        "price_country": "DE",          # contextualPricing country (DACH price list)
        "countries": ("DE", "AT"),      # country override rows
        "language": "de_DE",            # language override value
        "base": "https://www.gel-gun.de",
        "utm": "utm_source=facebook&utm_content=Facebook_DE",
    },
    "sk": {
        "price_country": "SK",
        "countries": ("SK",),
        "language": "sk_SK",
        "base": "https://www.gel-gun.cz/sk-sk",
        "utm": "utm_source=facebook&utm_content=Facebook_SK",
    },
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

_Q = """
query($cursor:String){
  products(first:30, after:$cursor, query:"status:active"){
    pageInfo{ hasNextPage endCursor }
    nodes{
      handle title
      publishedOnPublication(publicationId:"%s")
      de: translations(locale:"de"){ key value }
      sk: translations(locale:"sk"){ key value }
      variants(first:50){ nodes{
        legacyResourceId availableForSale
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


def build(products):
    country_rows, lang_rows, skipped = [], [], []
    for p in products:
        if not p.get("publishedOnPublication"):
            continue
        variants = p["variants"]["nodes"]
        for key, m in MARKETS.items():
            tr = {t["key"]: t["value"] for t in p[key]}
            title = (tr.get("title") or "").strip()
            if not title:
                # Price/link rows still go out (EUR + own store); only the text
                # stays Czech until the product is translated.
                skipped.append(f"{key}: {p['title']} (no translated title, text stays Czech)")
            desc = _plain(tr.get("body_html")) or title
            for v in variants:
                vid = v["legacyResourceId"]
                cp = v.get("p" + m["price_country"]) or {}
                price = cp.get("price") or {}
                if price.get("currencyCode") != "EUR" or not price.get("amount"):
                    skipped.append(f"{key}: {p['title']} / {vid} (no EUR price)")
                    continue
                amount = float(price["amount"])
                cmp_ = cp.get("compareAtPrice") or {}
                regular = max(amount, float(cmp_["amount"]) if cmp_.get("amount") else 0.0)
                link = f"{m['base']}/products/{p['handle']}?variant={vid}&{m['utm']}"
                for c in m["countries"]:
                    country_rows.append({
                        "id": vid, "override": c,
                        "price": f"{regular:.2f} EUR",
                        "sale_price": f"{amount:.2f} EUR",
                        "link": link,
                        "availability": "in stock" if v["availableForSale"] else "out of stock",
                    })
                if not title:
                    continue
                vtitle = title
                if len(variants) > 1:
                    opts = [w for w in (_opt(key, o["value"]) for o in v["selectedOptions"]) if w]
                    if opts:
                        vtitle = f"{title} – {' / '.join(opts)}"
                lang_rows.append({"id": vid, "override": m["language"],
                                  "title": vtitle[:200], "description": desc, "link": link})
    return country_rows, lang_rows, skipped


def _write(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def generate(write=True):
    country_rows, lang_rows, skipped = build(load_products())
    # Fail-closed on a broken run: never publish (near-)empty files, which would make
    # Meta drop every override and fall back to Czech data / CZK for DE and SK.
    if len(country_rows) < 50 or len(lang_rows) < 50:
        raise RuntimeError(f"too few rows (country {len(country_rows)}, language {len(lang_rows)})")
    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        _write(os.path.join(OUTPUT_DIR, "meta-country.csv"), country_rows,
               ["id", "override", "price", "sale_price", "link", "availability"])
        _write(os.path.join(OUTPUT_DIR, "meta-language.csv"), lang_rows,
               ["id", "override", "title", "description", "link"])
    return country_rows, lang_rows, skipped


if __name__ == "__main__":
    c, l, s = generate(write=True)
    print(f"meta country rows: {len(c)}, language rows: {len(l)}, skipped: {len(s)}")
    for x in s:
        print("  skipped:", x)
