# gelgun-feeds

Self-hosted product feeds for **gel-gun.cz**, generated from Shopify.

| Feed | URL | Platform |
|------|-----|----------|
| Google CZ | `/feeds/google.xml` | Google Merchant Center, Česko — curated toy titles, CZK, links to the `?view=safe` product pages |
| Google SK | `/feeds/google-sk.xml` | Google Merchant Center, Slovensko — Slovak titles from the `safe.*` translations, EUR, links to `/sk-sk/…?view=safe` |
| TikTok | `/feeds/tiktok.xml` | TikTok Catalog — brightly-coloured range only |
| Heureka | `/feeds/heureka.xml` | Heureka.cz |
| Zbozi | `/feeds/zbozi.xml` | Zbozi.cz / Seznam |

Served via GitHub Pages: `https://gelgun.github.io/gelgun-feeds/feeds/<name>.xml`

## Auto-update

`.github/workflows/feeds.yml` regenerates every 6h, and on any push that changes
`feeds.py`, `feeds_sk.py` or `run_feeds.py`. It needs three repository secrets (Settings →
Secrets and variables → Actions): `SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET`.

Before anything is committed, the workflow validates **both** Google feeds: every
item must link to a `?view=safe` page, no curated field may contain a model name,
prices must be in the feed's own currency, the Slovak feed's links must stay under
`/sk-sk/`, and the item counts must be sane. A run that fails the check publishes
nothing, so the last good feeds stay live.

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
