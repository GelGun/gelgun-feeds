"""
run_feeds.py — entry point for feed generation (called by GitHub Actions cron).

Writes tiktok.xml / heureka.xml / zbozi.xml into ./docs/feeds/, which are then
published to the public 'gelgun-feeds' repo (GitHub Pages) at:

  https://gelgun.github.io/gelgun-feeds/tiktok.xml
  https://gelgun.github.io/gelgun-feeds/heureka.xml
  https://gelgun.github.io/gelgun-feeds/zbozi.xml
"""

import feeds

if __name__ == "__main__":
    _, stats, excluded = feeds.generate(write=True)
    print("Feed generation complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  excluded_from_tiktok: {len(excluded)} products")
