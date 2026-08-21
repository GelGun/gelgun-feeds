"""
feeds_sk.py — Slovak Google Merchant Center feed for gel-gun.cz.

Emits docs/feeds/google-sk.xml: the same 29 items as google.xml, but

  • linked to the Slovak storefront   /sk-sk/products/<handle>?variant=<id>&view=safe
  • titled and described from the SLOVAK translations of the safe.* metafields,
    so the feed text is exactly what the Slovak page renders
  • priced in EUR, read from the live /sk-sk/ storefront rather than converted

Product selection is shared with feeds.py — this module never decides on its own
which products may be published. It calls feeds.google_excluded().

Fail-closed in three places:
  • a product with no Slovak safe.title is skipped
  • a product with no Slovak safe.description is skipped
  • a variant with no EUR price is skipped
so the Slovak feed can never fall back to Czech text or a CZK price.
"""

import json
import os
import re
from xml.sax.saxutils import escape

import requests

import feeds
import shopify

OUTPUT_DIR = feeds.OUTPUT_DIR
SK_DOMAIN = "www.gel-gun.cz"
SK_PATH = "/sk-sk"
SK_CURRENCY = "EUR"
SK_PRODUCT_TYPE = "Hračky > Hry s gélovými guľôčkami"

UA = {"User-Agent": "Mozilla/5.0 (compatible; GelGunFeedBuilder/1.0)"}

_GQL = None


def _gql(query, variables=None):
    global _GQL
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


_PRODUCT_Q = """
query($h:String!){
  productByHandle(handle:$h){
    id
    metafields(first:10, namespace:"safe"){ nodes{ id key } }
  }
}
"""

_TRANSLATION_Q = """
query($ids:[ID!]!){
  translatableResourcesByIds(resourceIds:$ids, first:50){
    nodes{ resourceId translations(locale:"sk"){ key value } }
  }
}
"""


def load_sk_text(handles):
    """handle -> {'title':…, 'description':…, 'features':…} in Slovak."""
    out = {}
    for h in handles:
        try:
            d = _gql(_PRODUCT_Q, {"h": h})["productByHandle"]
            if not d:
                continue
            by_id = {m["id"]: m["key"] for m in d["metafields"]["nodes"]}
            if not by_id:
                continue
            sk = {}
            nodes = _gql(_TRANSLATION_Q, {"ids": list(by_id)})["translatableResourcesByIds"]["nodes"]
            for n in nodes:
                key = by_id.get(n["resourceId"])
                for t in n["translations"]:
                    if t["key"] == "value" and key:
                        sk[key] = t["value"]
            out[h] = sk
        except Exception as e:                                   # noqa: BLE001
            print(f"  ! sk text lookup failed for {h}: {e}")
    return out


def load_sk_prices(handles):
    """handle -> {variant_id(str): {'price': cents, 'compare_at': cents|None}} in EUR."""
    out = {}
    for h in handles:
        try:
            r = requests.get(f"https://{SK_DOMAIN}{SK_PATH}/products/{h}.js",
                             headers=UA, timeout=40)
            if r.status_code != 200:
                print(f"  ! sk price fetch {h} -> HTTP {r.status_code}")
                continue
            out[h] = {str(v["id"]): {"price": v["price"], "compare_at": v.get("compare_at_price")}
                      for v in r.json()["variants"]}
        except Exception as e:                                   # noqa: BLE001
            print(f"  ! sk price fetch failed for {h}: {e}")
    return out


def _money(cents):
    return f"{cents / 100:.2f} {SK_CURRENCY}"


def sk_description(sk):
    """Intro + feature bullets, exactly the text the Slovak page renders."""
    parts = [sk.get("description", "").strip()]
    feats = [ln.strip() for ln in (sk.get("features") or "").splitlines() if ln.strip()]
    if feats:
        parts.append(" ".join(f if f.endswith(".") else f + "." for f in feats))
    text = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", text).strip()


def sk_link(handle, variant_id):
    return (f"https://{SK_DOMAIN}{SK_PATH}/products/{handle}"
            f"?variant={variant_id}&view=safe")


def build(items):
    handles = sorted({feeds.google_handle(i) for i in items})
    print(f"  Slovak feed: resolving {len(handles)} handles")
    text = load_sk_text(handles)
    prices = load_sk_prices(handles)

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">',
           '  <channel>',
           '    <title>GelGun – Slovensko</title>',
           f'    <link>https://{SK_DOMAIN}{SK_PATH}</link>',
           '    <description>Detské hračky na vodné gélové guľôčky</description>']

    skipped = []
    count = 0
    for it in items:
        h = feeds.google_handle(it)
        sk = text.get(h, {})
        vid = str(it["id"])
        price = (prices.get(h) or {}).get(vid)

        if not sk.get("title"):
            skipped.append((h, vid, "no sk safe.title"));  continue
        if not sk.get("description"):
            skipped.append((h, vid, "no sk safe.description"));  continue
        if not price or not price.get("price"):
            skipped.append((h, vid, "no EUR price"));  continue

        label = feeds._g_option_label(it)
        title = f'{sk["title"]} – {label}' if label else sk["title"]

        rows = [
            ('id', vid),
            ('item_group_id', it["item_group_id"]),
            ('title', title),
            ('description', sk_description(sk)),
            ('link', sk_link(h, vid)),
            ('image_link', feeds.google_image(it)),
            ('availability', feeds.google_availability(it)),
        ]
        p, c = price["price"], price.get("compare_at")
        if c and c > p:
            rows += [('price', _money(c)), ('sale_price', _money(p))]
        else:
            rows += [('price', _money(p))]
        rows += [
            ('brand', feeds.GOOGLE_BRAND),
            ('condition', 'new'),
            ('age_group', feeds.GOOGLE_AGE_GROUP),
            ('google_product_category', feeds.GOOGLE_CATEGORY_ID),
            ('product_type', SK_PRODUCT_TYPE),
        ]
        color, size = feeds.google_variant_attrs(it)
        if color:
            rows.append(('color', color))
        if size:
            rows.append(('size', size))
        if it.get("gtin"):
            rows.append(('gtin', it["gtin"]))
        if it.get("sku"):
            rows.append(('mpn', it["sku"]))
        if not it.get("gtin") and not it.get("sku"):
            rows.append(('identifier_exists', 'no'))

        out.append('    <item>')
        for tag, val in rows:
            out.append(f'      <g:{tag}>{escape(str(val))}</g:{tag}>')
        for extra in feeds.google_additional_images(it):
            out.append(f'      <g:additional_image_link>{escape(extra)}</g:additional_image_link>')
        out.append('    </item>')
        count += 1

    out += ['  </channel>', '</rss>']
    if skipped:
        print(f"  Slovak feed: skipped {len(skipped)} item(s)")
        for h, v, why in skipped[:10]:
            print(f"    - {h} / {v}: {why}")
    print(f"  Slovak feed: {count} items")
    return "\n".join(out), count, skipped


def generate(write=True):
    products = feeds.fetch_published_products()
    items = [i for i in feeds.iter_items(products) if not feeds.google_excluded(i)]
    xml, count, skipped = build(items)
    if write:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "google-sk.xml"), "w", encoding="utf-8") as f:
            f.write(xml)
    return xml, count, skipped


if __name__ == "__main__":
    generate(write=True)
