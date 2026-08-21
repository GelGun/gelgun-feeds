"""
run_feeds.py — entry point for feed generation (called by GitHub Actions cron).

Writes google.xml / tiktok.xml / heureka.xml / zbozi.xml into ./docs/feeds/,
published via GitHub Pages at:

  https://gelgun.github.io/gelgun-feeds/feeds/google.xml
  https://gelgun.github.io/gelgun-feeds/feeds/tiktok.xml
  https://gelgun.github.io/gelgun-feeds/feeds/heureka.xml
  https://gelgun.github.io/gelgun-feeds/feeds/zbozi.xml
"""

import feeds

if __name__ == "__main__":
    _, stats, excluded, google_dropped = feeds.generate(write=True)
    print("Feed generation complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  excluded_from_tiktok: {len(excluded)} products")
    print(f"  not_in_google_feed:   {len(google_dropped)} products")
