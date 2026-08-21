# gelgun-feeds

Self-hosted product feeds for **gel-gun.cz**, generated from Shopify.

| Feed | URL | Platform |
|------|-----|----------|
| Google | `/feeds/google.xml` | Google Merchant Center — curated toy titles, links to the `?view=safe` product pages |
| TikTok | `/feeds/tiktok.xml` | TikTok Catalog — brightly-coloured range only |
| Heureka | `/feeds/heureka.xml` | Heureka.cz |
| Zbozi | `/feeds/zbozi.xml` | Zbozi.cz / Seznam |

Served via GitHub Pages: `https://gelgun.github.io/gelgun-feeds/feeds/<name>.xml`

## Auto-update

`.github/workflows/feeds.yml` regenerates every 6h, and on any push that changes
`feeds.py` or `run_feeds.py`. It needs three repository secrets (Settings →
Secrets and variables → Actions): `SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID`,
`SHOPIFY_CLIENT_SECRET`.

Before anything is committed, the workflow validates `google.xml`: every item must
link to a `?view=safe` page, no curated field may contain a model name, and the
item count must be sane. A run that fails the check publishes nothing, so the last
good feed stays live.

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
