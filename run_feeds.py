"""
run_feeds.py — entry point for feed generation (called by GitHub Actions cron).

Writes google.xml / google-sk.xml / tiktok.xml / heureka.xml /
heureka-availability.xml / zbozi.xml into ./docs/feeds/, published via GitHub
Pages at:

  https://gelgun.github.io/gelgun-feeds/feeds/google.xml
  https://gelgun.github.io/gelgun-feeds/feeds/google-sk.xml
  https://gelgun.github.io/gelgun-feeds/feeds/tiktok.xml
  https://gelgun.github.io/gelgun-feeds/feeds/heureka.xml
  https://gelgun.github.io/gelgun-feeds/feeds/heureka-availability.xml
  https://gelgun.github.io/gelgun-feeds/feeds/zbozi.xml

The two Heureka files are different schemas and go into different fields of the
Heureka admin — heureka.xml into Nastavení → Profil obchodu → URL XML obchodu,
heureka-availability.xml into Nastavení → Dostupnostní XML soubor. Swapping them
makes the validator reject every element, starting with SHOP on line 2.

feeds_cz runs last on purpose: feeds.generate() still emits its own older
heureka.xml / zbozi.xml, and feeds_cz overwrites both with the versions that
carry CATEGORYTEXT from Heureka's own tree, DELIVERY, PARAM and the mandatory
Zbozi namespace. The two builders left in feeds.py are superseded and can be
deleted.
"""

import feeds
import feeds_sk
import feeds_cz

if __name__ == "__main__":
    _, stats, excluded, google_dropped = feeds.generate(write=True)
    print("Feed generation complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  excluded_from_tiktok: {len(excluded)} products")
    print(f"  not_in_google_feed:   {len(google_dropped)} products")

    print("\nSlovak Google feed:")
    _, sk_count, sk_skipped = feeds_sk.generate(write=True)
    print(f"  google_sk_items: {sk_count}")
    print(f"  google_sk_skipped: {len(sk_skipped)}")

    print("\nCzech comparison feeds (Heureka, Zbozi):")
    _, cz_stats = feeds_cz.generate(write=True)
    for k, v in cz_stats.items():
        print(f"  {k}: {v}")
