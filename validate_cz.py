"""
validate_cz.py — pre-publish gate for the Czech feeds.

Run by .github/workflows/feeds.yml after generation and before the commit, the
same way the Google feeds are gated. A failure here publishes nothing, so the
last good feeds stay live on GitHub Pages.

It exists because of a specific incident: heureka.xml and zbozi.xml were once
byte-for-byte identical (zbozi.xml was missing the mandatory Zbozi namespace and
would have been rejected element by element), and the Heureka availability field
was pointed at a product feed, whose completely different schema made Heureka
reject every element starting with SHOP on line 2. Both are now hard failures.

  python validate_cz.py [docs/feeds]
"""

import re
import sys
import os
import hashlib
from datetime import datetime
import xml.etree.ElementTree as ET

ZBOZI_NS = "http://www.zbozi.cz/ns/offer/1.0"
STORE_DOMAIN = "gel-gun.cz"
MIN_ITEMS = 20

# https://sluzby.heureka.cz/napoveda/xml-feed/ — an unknown code is silently
# dropped by Heureka, so a typo here would cost the shipping data without ever
# showing up as an error.
DELIVERY_IDS = {
    "CESKA_POSTA", "CESKA_POSTA_DOPORUCENA_ZASILKA", "CSAD_LOGISTIK_OSTRAVA",
    "DPD", "DHL", "DSV", "FOFR", "GEBRUDER_WEISS", "GEIS", "GLS", "PPL",
    "SEEGMULLER", "TOPTRANS", "UPS", "FEDEX", "RABEN_LOGISTICS",
    "ZASILKOVNA_NA_ADRESU", "ONE_COURIER", "RHENUS_LOGISTICS", "MESSENGER",
    "BALIKOVNA_NA_ADRESU", "QDL", "DB_SCHENKER", "EMONS",
    "ZASILKOVNA", "DPD_PICKUP", "BALIKOVNA_DEPOTAPI", "ONE_POINT",
    "PPL_PARCELSHOP", "GLS_PARCELSHOP", "ALZAPOINT", "UPS_ACCESS_POINT",
    "DPD_BOX", "Z_BOX", "ONE_BOX", "PPL_PARCELBOX", "BALIKOVNA_BOX",
    "ALZABOX", "GLS_PARCELBOX", "ONLINE", "VLASTNI_PREPRAVA",
}

TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def _text(el, tag):
    child = el.find(tag)
    return (child.text or "").strip() if child is not None else ""


def check_heureka(path, problems):
    root = ET.parse(path).getroot()
    if root.tag != "SHOP":
        problems.append(f"{path}: root is <{root.tag}>, Heureka feed 2.0 needs <SHOP>")
        return set()

    items = root.findall("SHOPITEM")
    if len(items) < MIN_ITEMS:
        problems.append(f"{path}: only {len(items)} SHOPITEMs, expected at least {MIN_ITEMS}")

    ids, group_names = set(), {}
    for it in items:
        iid = _text(it, "ITEM_ID")
        name = _text(it, "PRODUCTNAME")
        if not iid:
            problems.append(f"{path}: SHOPITEM with no ITEM_ID")
            continue
        if iid in ids:
            problems.append(f"{path}: duplicate ITEM_ID {iid}")
        ids.add(iid)

        for tag in ("PRODUCTNAME", "PRICE_VAT", "URL"):
            if not _text(it, tag):
                problems.append(f"{path}: {iid} missing mandatory <{tag}>")

        if len(name) > 200:
            problems.append(f"{path}: {iid} PRODUCTNAME over 200 chars")
        url = _text(it, "URL")
        if len(url) > 300:
            problems.append(f"{path}: {iid} URL over 300 chars")
        if url and not url.startswith(f"https://{STORE_DOMAIN}/"):
            problems.append(f"{path}: {iid} URL outside https://{STORE_DOMAIN}/: {url}")

        try:
            if float(_text(it, "PRICE_VAT") or 0) <= 0:
                problems.append(f"{path}: {iid} PRICE_VAT is not a positive number")
        except ValueError:
            problems.append(f"{path}: {iid} PRICE_VAT is not a number: {_text(it, 'PRICE_VAT')}")

        cat = _text(it, "CATEGORYTEXT")
        if not cat.startswith("Heureka.cz | "):
            problems.append(f"{path}: {iid} CATEGORYTEXT is not a Heureka path: {cat!r}")

        deliveries = it.findall("DELIVERY")
        if not deliveries:
            problems.append(f"{path}: {iid} has no <DELIVERY>")
        for d in deliveries:
            did = _text(d, "DELIVERY_ID")
            if did not in DELIVERY_IDS:
                problems.append(f"{path}: {iid} unknown DELIVERY_ID {did!r}")
            if not _text(d, "DELIVERY_PRICE"):
                problems.append(f"{path}: {iid} DELIVERY {did} has no DELIVERY_PRICE")

        # Heureka splits variants onto separate cards and blocks offers it cannot
        # tell apart, so two variants of one product must not share a name.
        gid = _text(it, "ITEMGROUP_ID")
        if gid:
            if name in group_names.get(gid, set()):
                problems.append(f"{path}: ITEMGROUP_ID {gid} has two variants named {name!r}")
            group_names.setdefault(gid, set()).add(name)

    print(f"{path}: {len(items)} offers, "
          f"{sum(1 for i in items if i.find('EAN') is not None)} with EAN, "
          f"{sum(1 for i in items if i.find('PARAM') is not None)} with PARAM")
    return ids


def check_availability(path, product_ids, problems, now=None):
    now = now or datetime.now()
    root = ET.parse(path).getroot()
    if root.tag != "item_list":
        problems.append(
            f"{path}: root is <{root.tag}>, the availability feed needs <item_list>. "
            "A <SHOP> root here means the product feed was written to this path.")
        return

    items = root.findall("item")
    ids = set()
    for it in items:
        iid = (it.get("id") or "").strip()
        if not iid:
            problems.append(f"{path}: <item> with no id attribute")
            continue
        ids.add(iid)
        qty = it.find("stock_quantity")
        eta = it.find("delivery_time")
        if qty is None and eta is None:
            problems.append(f"{path}: {iid} has neither stock_quantity nor delivery_time "
                            "— Heureka reads that as 'cannot be delivered'")
        # Heureka's schema rejects an item carrying both:
        #   Extra element delivery_time in interleave / item failed to validate
        if qty is not None and eta is not None:
            problems.append(f"{path}: {iid} has both stock_quantity and delivery_time "
                            "— Heureka's schema accepts only one of them per item")
        if qty is not None and not (qty.text or "").strip().isdigit():
            problems.append(f"{path}: {iid} stock_quantity is not a whole number")
        if eta is not None:
            val = (eta.text or "").strip()
            if not TIME_RE.match(val):
                problems.append(f"{path}: {iid} delivery_time {val!r} is not YYYY-MM-DD HH:MM")
            else:
                if datetime.strptime(val, "%Y-%m-%d %H:%M") < now:
                    problems.append(f"{path}: {iid} delivery_time {val} is in the past")
                deadline = (eta.get("orderDeadline") or "").strip()
                if deadline:
                    if not TIME_RE.match(deadline):
                        problems.append(f"{path}: {iid} orderDeadline {deadline!r} "
                                        "is not YYYY-MM-DD HH:MM")
                    elif datetime.strptime(deadline, "%Y-%m-%d %H:%M") < now:
                        problems.append(f"{path}: {iid} orderDeadline {deadline} is in the past")

    # Offers left out of the availability feed show as "info v obchode" on Heureka
    # even when the product feed says they are in stock.
    missing = product_ids - ids
    if missing:
        problems.append(f"{path}: {len(missing)} offers from heureka.xml are missing here "
                        f"(e.g. {sorted(missing)[:3]})")
    extra = ids - product_ids
    if extra:
        problems.append(f"{path}: {len(extra)} ids are not in heureka.xml "
                        f"(e.g. {sorted(extra)[:3]})")
    print(f"{path}: {len(items)} items, "
          f"{sum(1 for i in items if i.find('stock_quantity') is not None)} with a stock count")


def check_zbozi(path, heureka_path, problems):
    root = ET.parse(path).getroot()
    if root.tag != f"{{{ZBOZI_NS}}}SHOP":
        problems.append(f"{path}: root is <{root.tag}>, Zbozi.cz requires "
                        f'<SHOP xmlns="{ZBOZI_NS}">')
        return
    items = root.findall(f"{{{ZBOZI_NS}}}SHOPITEM")
    if len(items) < MIN_ITEMS:
        problems.append(f"{path}: only {len(items)} SHOPITEMs, expected at least {MIN_ITEMS}")

    def digest(p):
        return hashlib.md5(open(p, "rb").read()).hexdigest()

    if os.path.exists(heureka_path) and digest(path) == digest(heureka_path):
        problems.append(f"{path}: byte-identical to {heureka_path} — the Zbozi dialect "
                        "is not being applied")
    print(f"{path}: {len(items)} offers, namespace OK")


def main(feed_dir):
    problems = []
    heureka = os.path.join(feed_dir, "heureka.xml")
    availability = os.path.join(feed_dir, "heureka-availability.xml")
    zbozi = os.path.join(feed_dir, "zbozi.xml")

    for path in (heureka, availability, zbozi):
        if not os.path.exists(path):
            problems.append(f"{path}: missing")
    if problems:
        print("\n".join(problems))
        sys.exit("REFUSING TO PUBLISH")

    product_ids = check_heureka(heureka, problems)
    check_availability(availability, product_ids, problems)
    check_zbozi(zbozi, heureka, problems)

    if problems:
        print()
        print("\n".join(problems[:25]))
        if len(problems) > 25:
            print(f"... and {len(problems) - 25} more")
        sys.exit("REFUSING TO PUBLISH")
    print("Czech feeds OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/feeds")
