# gelgun-feeds

Self-hosted product feeds for **gel-gun.cz**, generated from Shopify.

| Feed | URL | Platform |
|------|-----|----------|
| TikTok | `/feeds/tiktok.xml` | TikTok Catalog — **policy-safe products only** (realistic/dark blasters excluded) |
| Heureka | `/feeds/heureka.xml` | Heureka.cz |
| Zbozi | `/feeds/zbozi.xml` | Zbozi.cz / Seznam |

Served via GitHub Pages: `https://gelgun.github.io/gelgun-feeds/feeds/<name>.xml`

## Auto-update
`.github/workflows/feeds.yml` regenerates every 6h. **One manual step:** add three
repository secrets (Settings → Secrets and variables → Actions):
`SHOPIFY_SHOP`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` (same values as the
Olda-connector `.env`). Until then, the committed feeds are static.

## TikTok exclusions
Edit `TIKTOK_EXCLUDE_TITLES` / keyword guard in `feeds.py` to change which SKUs
TikTok sees. `content_id` = Shopify variant id, matching the purchase pixel.
