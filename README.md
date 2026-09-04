# gelgun-feeds

Self-hosted product feeds for **gel-gun.cz**, generated from Shopify.

| Feed | URL | Platform |
|------|-----|----------|
| Google CZ | `/feeds/google.xml` | Google Merchant Center, Česko — curated toy titles, CZK, links to the `?view=safe` product pages |
| Google SK | `/feeds/google-sk.xml` | Google Merchant Center, Slovensko — Slovak titles from the `safe.*` translations, EUR, links to `/sk-sk/…?view=safe` |
| TikTok | `/feeds/tiktok.xml` | TikTok Catalog — brightly-coloured range only |
| Heureka | `/feeds/heureka.xml` | Heureka.cz — základní XML feed 2.0 |
| Heureka dostupnost | `/feeds/heureka-availability.xml` | Heureka.cz — dostupnostní XML soubor |
| Zbozi | `/feeds/zbozi.xml` | Zbozi.cz / Seznam |

Served via GitHub Pages: `https://gelgun.github.io/gelgun-feeds/feeds/<name>.xml`

## Auto-update

`.github/workflows/feeds.yml` regenerates every 6h, and on any push that changes
`feeds.py`, `feeds_cz.py`, `feeds_sk.py`, `run_feeds.py` or `validate_cz.py`. It needs
three repository secrets (Settings → Secrets and variables → Actions):
`SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`.

Before anything is committed, the workflow validates the Czech feeds with
`validate_cz.py` — root element and namespace per file, mandatory tags, Heureka
category paths, known `DELIVERY_ID`s, availability ids matching the product feed,
no two variants sharing a name, and `zbozi.xml` never being a copy of
`heureka.xml` — and **both** Google feeds: every item must link to a `?view=safe`
page, no curated field may contain a model name, prices must be in the feed's own
currency, the Slovak feed's links must stay under `/sk-sk/`, and the item counts
must be sane. A run that fails either check publishes nothing, so the last good
feeds stay live.

## Czech comparison sites

Built by `feeds_cz.py` — not by `feeds.py`, whose `build_heureka` / `build_zbozi`
are superseded and no longer what gets published.

**The two Heureka files are different schemas and go into different fields.** Putting
one where the other belongs makes Heureka reject the file element by element,
starting with `Neočekávaný element SHOP na řádku 2`.

| File | Root | Heureka admin field |
|------|------|---------------------|
| `heureka.xml` | `<SHOP>` / `<SHOPITEM>` | Nastavení → Profil obchodu → **URL XML obchodu** |
| `heureka-availability.xml` | `<item_list>` / `<item id="…">` | Nastavení → **Dostupnostní XML soubor** |

Every offer appears in the availability feed, including the out-of-stock ones —
an offer left out shows as "info v obchodě" on Heureka even when the product feed
says it is in stock. Each item carries **exactly one** of `stock_quantity` /
`delivery_time`: an item with neither means "cannot be delivered", and an item with
both is rejected by Heureka's schema (`Extra element delivery_time in interleave`).
Out of stock is therefore `stock_quantity` 0 alone, and the restock horizon reaches
Heureka through `DELIVERY_DATE` in the product feed.

`zbozi.xml` carries the mandatory `xmlns="http://www.zbozi.cz/ns/offer/1.0"`. Without
it Seznam rejects every element the same way, which is what happened while it was a
byte-for-byte copy of `heureka.xml`.

Every offer carries `<DELIVERY>` for Zásilkovna domů (99 Kč) and Z-BOX (79 Kč),
dropping to 0 Kč at the `FREE_SHIPPING_FROM_CZK` threshold — shipping is computed per
offer, so it overrides whatever is set under Ceny dopravy in the admin.
`DELIVERY_PRICE_COD` adds the 39 Kč dobírka surcharge on top and still charges it on a
free-shipping order; set `COD_ON_FREE_SHIPPING = False` if the promo waives the dobírka
fee as well. Heureka blocks shops for untrue delivery data, so these have to stay in
step with the real price list.

`CATEGORYTEXT` has to be a real path in Heureka's own tree or the tag counts as
missing — that is what "Chybějící údaj `<CATEGORYTEXT>`" meant for 46 of 49 offers
while the feed sent `Hračky | Zbraně a pistole na kuličky`. The two live paths are in
`HEUREKA_CAT_WEAPONS` / `HEUREKA_CAT_ACCESSORIES`; re-check them against the
breadcrumb on heureka.cz if Heureka reorganises the catalogue.

`PRODUCTNAME` gets the Shopify variant label appended when a product has more than one
variant — Heureka splits variants onto separate catalogue cards and blocks offers it
cannot tell apart.

`EAN` is the one warning the feed cannot fix on its own: it comes from the Shopify
variant barcode, so a missing EAN has to be filled in Shopify.

## Google feed

Titles come from `GOOGLE_SAFE_TITLES` in `feeds.py`, keyed by Shopify handle.
A product with no entry there is not published — so a newly added SKU never
appears with an uncurated title. `GOOGLE_SAFE_ONLY` additionally drops anything
without a `?view=safe` page, which keeps feed title and landing-page title in
agreement.

**Changing a title takes two edits, both required:** `GOOGLE_SAFE_TITLES` here,
and the `safe.title` metafield on the product in Shopify. They are what the feed
and the page each read, and Merchant Center compares them.

## TikTok exclusions

Edit `TIKTOK_EXCLUDE_TITLES` / the keyword guard in `feeds.py` to change which
SKUs TikTok sees. `content_id` = Shopify variant id, matching the purchase pixel.

## Slovak feed

`feeds_sk.py` builds `google-sk.xml` from the **Slovak translations** of the
`safe.*` metafields — title, description and features — so the feed text is
exactly what the Slovak page renders. EUR prices are read from the live
`/sk-sk/` storefront, never converted from CZK.

Which products appear is decided by `feeds.py` alone: `feeds_sk` calls
`feeds.google_excluded()` and never makes its own selection. It is fail-closed
three times over — a product with no Slovak title, no Slovak description, or no
EUR price is skipped rather than falling back to Czech text or a CZK price.
