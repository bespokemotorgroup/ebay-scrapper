#!/usr/bin/env python3
"""
eBay Store Scraper
Scrapes all listed products from two eBay stores, visits each item page for
full details and compatibility data, then saves to CSV.

Output (4 files total, same folder as script):
    porschepartsdirect_products.csv      — one row per product, all item specifics
    porschepartsdirect_compatibility.csv — one row per compatible vehicle (linked by item_id)
    5150motorsport_products.csv
    5150motorsport_compatibility.csv

Usage:
    py -3 scraper.py                              # full scrape, both stores (visible Chrome)
    py -3 scraper.py --headless                   # headless Chrome
    py -3 scraper.py --test                       # first page of listings only + item pages
    py -3 scraper.py --store porschepartsdirect   # one store only
    py -3 scraper.py --store 5150motorsport --test
"""

import argparse
import re
import sys
import time
import random
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORES = {
    "porschepartsdirect": {"products": "porschepartsdirect_products.csv"},
    "5150motorsport":     {"products": "5150motorsport_products.csv"},
}

LISTINGS_PER_PAGE = 120
OUTPUT_DIR        = Path(__file__).parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ebay_scraper")

# ---------------------------------------------------------------------------
# Chrome driver factory
# ---------------------------------------------------------------------------

def make_driver(headless: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as exc:
        log.error("Cannot start Chrome: %s", exc)
        sys.exit(1)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
    )
    return driver


def warm_up(driver) -> None:
    log.info("Warming up: visiting eBay homepage to pick up cookies...")
    driver.get("https://www.ebay.com/")
    time.sleep(random.uniform(3, 5))

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def seller_search_url(seller: str, page: int, per_page: int) -> str:
    return (
        "https://www.ebay.com/sch/i.html"
        f"?_ssn={seller}&_sop=12&_pgn={page}&_ipg={per_page}&rt=nc"
    )

def _clean_url(href: str) -> str:
    """Strip eBay tracking params — keep just the /itm/XXXXX part."""
    return re.sub(r"\?.*", "", href) if href else ""

# ---------------------------------------------------------------------------
# LISTING PAGE parser  (new li.s-card layout, confirmed from live HTML)
# ---------------------------------------------------------------------------

def _parse_listing_card(card) -> dict | None:
    """
    Parse one li.s-card from the seller search results page.
    Returns None for eBay ghost/sponsored placeholder cards.

    Layout (confirmed from live HTML):
      li.s-card[data-listingid]
        img.s-card__image                    → ghost if alt="Shop on eBay"
        div.su-card-container__header
          a.s-card__link                     → item URL
            div.s-card__title
              span (first, not .clipped)     → title
              span.clipped                   → "Opens in a new window…" (skip)
          div.s-card__subtitle-row (×N)
            div.s-card__subtitle span        → condition labels
        div.su-card-container__attributes__primary
          div.s-card__attribute-row (×N)     → price, listing type, shipping, location, watchers
            span[class*='s-card__price']     → price
    """
    # Ghost detection
    img = card.select_one("img.s-card__image")
    if img and img.get("alt", "") == "Shop on eBay":
        return None

    item_id = card.get("data-listingid", "")

    # Title
    title = ""
    title_div = card.select_one("div.s-card__title")
    if title_div:
        for span in title_div.select("span"):
            if "clipped" not in (span.get("class") or []):
                title = span.get_text(strip=True)
                break
    if not title or title.lower() == "shop on ebay":
        return None

    # URL
    item_url = ""
    header_link = card.select_one("div.su-card-container__header a.s-card__link")
    if header_link:
        href = header_link.get("href", "")
        item_url = _clean_url(href)
        if not item_id:
            m = re.search(r"/itm/(\d+)", href)
            item_id = m.group(1) if m else ""

    # Condition (join all subtitle labels)
    subtitle_spans = card.select(
        "div.su-card-container__header "
        "div.s-card__subtitle-row div.s-card__subtitle span"
    )
    condition_short = " | ".join(
        s.get_text(strip=True) for s in subtitle_spans if s.get_text(strip=True)
    )

    # Price
    price = ""
    price_el = card.select_one("span[class*='s-card__price']")
    if price_el:
        price = price_el.get_text(strip=True)

    # Attribute rows: classify by content keywords
    listing_type = shipping = location = watchers = ""
    for row in card.select(
        "div.su-card-container__attributes__primary div.s-card__attribute-row"
    ):
        rt = row.get_text(strip=True)
        rl = rt.lower()
        if any(k in rl for k in ("buy it now", "best offer", "place bid", "auction")):
            listing_type = rt
        elif any(k in rl for k in ("delivery", "shipping", "free postage", "free shipping")):
            shipping = rt
        elif "located in" in rl or rl.startswith("from "):
            location = rt
        elif "watcher" in rl or "sold" in rl:
            watchers = rt

    # Thumbnail
    image_url = ""
    if img:
        src = img.get("src", "") or img.get("data-defer-load", "")
        if src and "fxxj3ttftm5ltcqnto1o4baovyl" not in src:
            image_url = src

    return {
        "item_id":      item_id,
        "title":        title,
        "price":        price,
        "listing_type": listing_type,
        "condition":    condition_short,
        "shipping":     shipping,
        "location":     location,
        "watchers":     watchers,
        "image_url":    image_url,
        "url":          item_url,
    }

def parse_listing_page(html: str) -> list[dict]:
    soup  = BeautifulSoup(html, "lxml")
    cards = soup.select("li.s-card") or soup.select("li.s-item")
    items = []
    for card in cards:
        parsed = _parse_listing_card(card)
        if parsed:
            items.append(parsed)
    return items

def has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return bool(soup.select_one(
        "a.pagination__next, li.pagination__next a, "
        "a[rel='next'], a[aria-label='Go to next search page']"
    ))

# ---------------------------------------------------------------------------
# ITEM PAGE parser  (confirmed selectors from live HTML inspection)
# ---------------------------------------------------------------------------

# All item-specific keys we want as dedicated columns (others stored in 'extra_specifics')
KNOWN_SPECIFICS = {
    "Condition":               "condition_full",
    "Brand":                   "brand",
    "SKU":                     "sku",
    "Manufacturer Part Number":"manufacturer_part_number",
    "Product Name":            "product_name",
    "Genuine OEM":             "genuine_oem",
    "Manufacturer Warranty":   "warranty",
    "Fitment Type":            "fitment_type",
    "Make":                    "make",
    "Model":                   "model",
    "Year":                    "year",
    "Category":                "category",
    "Country of Origin":       "country_of_origin",
    "Type":                    "type",
    "Placement on Vehicle":    "placement",
    "Surface Finish":          "surface_finish",
    "Color":                   "color",
    "Material":                "material",
    "Warranty":                "warranty",
    "Part Number":             "manufacturer_part_number",
    "UPC":                     "upc",
    "ISBN":                    "isbn",
    "EAN":                     "ean",
}

def _parse_item_listing_details(soup: BeautifulSoup) -> dict:
    """
    Extract listing-level fields directly from an item page.
    Used to fill in price, condition, shipping, location, watchers, image_url,
    and listing_type when they weren't populated from a search-results card
    (e.g. --url single-item mode).
    """
    result = {}

    # ── Price ────────────────────────────────────────────────────────────────
    _price_re = re.compile(r'^(US\s*)?\$[\d,]+\.?\d*$')
    price_el = (
        soup.select_one("div[data-testid='x-price-section'] span.ux-textspans--BOLD") or
        soup.select_one("div.x-price-primary span.ux-textspans--BOLD") or
        soup.select_one("div.x-bin-price span.ux-textspans--BOLD") or
        soup.select_one("span.x-price-primary span.ux-textspans") or
        soup.select_one("span[itemprop='price']")
    )
    if price_el:
        result["price"] = price_el.get_text(strip=True)
    else:
        # Text scan: first bold span whose text looks like a price
        for span in soup.select("span.ux-textspans--BOLD"):
            t = span.get_text(strip=True)
            if _price_re.match(t):
                result["price"] = t
                break

    # ── Listing type ─────────────────────────────────────────────────────────
    # Reliable: just check page text for canonical eBay phrases
    _page_text = soup.get_text(" ", strip=True)
    if "Buy It Now" in _page_text:
        result["listing_type"] = "Buy It Now"
    elif "Place bid" in _page_text or "Place Bid" in _page_text:
        result["listing_type"] = "Auction"

    # ── Condition ────────────────────────────────────────────────────────────
    cond_el = (
        soup.select_one("div.x-item-condition-text span.ux-textspans") or
        soup.select_one("span[data-testid='x-item-condition'] span.ux-textspans") or
        soup.select_one("div[data-testid='x-item-condition-text'] span.ux-textspans")
    )
    if cond_el:
        result["condition"] = cond_el.get_text(strip=True)

    # ── Shipping ─────────────────────────────────────────────────────────────
    ship_el = (
        soup.select_one("div[data-testid='x-shipping-section'] span.ux-textspans--BOLD") or
        soup.select_one("div.ux-labels-values--shipping span.ux-textspans--BOLD") or
        soup.select_one("span[data-testid='x-shipping-cost'] span.ux-textspans")
    )
    if ship_el:
        result["shipping"] = ship_el.get_text(strip=True)
    else:
        # Text scan: first span that starts with "Free shipping" / "Free postage"
        # or is a short shipping-cost string
        for span in soup.select("span.ux-textspans"):
            t = span.get_text(strip=True)
            tl = t.lower()
            if tl.startswith("free shipping") or tl.startswith("free postage"):
                result["shipping"] = t
                break
            if "shipping" in tl and len(t) < 60 and _price_re.search(t):
                result["shipping"] = t
                break

    # ── Location ─────────────────────────────────────────────────────────────
    loc_el = soup.select_one("span[data-testid='x-shipping-location'] span.ux-textspans")
    if loc_el:
        result["location"] = loc_el.get_text(strip=True)
    else:
        for span in soup.select("span.ux-textspans"):
            txt = span.get_text(strip=True)
            if txt.lower().startswith("located in"):
                result["location"] = txt
                break

    # ── Watchers ─────────────────────────────────────────────────────────────
    _watch_re = re.compile(r'\d+\s+watcher', re.IGNORECASE)
    watch_el = (
        soup.select_one("span[data-testid='x-watchcount'] span.ux-textspans") or
        soup.select_one("span.vi-notify-new span.ux-textspans") or
        soup.select_one("div[data-testid='x-watch-count'] span.ux-textspans")
    )
    if watch_el:
        result["watchers"] = watch_el.get_text(strip=True)
    else:
        # Text scan: find "N watchers" or "N people are watching"
        for span in soup.select("span.ux-textspans"):
            t = span.get_text(strip=True)
            if _watch_re.search(t):
                result["watchers"] = t
                break

    # ── Image ────────────────────────────────────────────────────────────────
    img_el = (
        soup.select_one("div.ux-image-carousel-item.active img") or
        soup.select_one("div.ux-image-carousel-item img") or
        soup.select_one("img.ux-image-carousel-image") or
        soup.select_one("div[data-testid='ux-image-carousel-item'] img")
    )
    if img_el:
        src = (
            img_el.get("src") or
            img_el.get("data-src") or
            img_el.get("data-defer-load") or
            ""
        )
        if src:
            result["image_url"] = src

    return result


def _parse_item_specifics(soup: BeautifulSoup) -> dict:
    """
    Extract Item Specifics from the item page.
    Selectors confirmed from live HTML:
      dl.ux-labels-values
        dt .ux-textspans  → label
        dd .ux-textspans  → value(s)
    Returns a flat dict with known keys mapped to column names,
    plus 'extra_specifics' for any remaining key=value pairs.
    """
    result = {}
    extra  = []

    for dl in soup.select("dl.ux-labels-values"):
        label_el = dl.select_one("dt .ux-textspans")
        if not label_el:
            continue
        label = label_el.get_text(strip=True)
        # Join multiple value spans (e.g. multi-line condition text)
        value_spans = dl.select("dd .ux-textspans")
        value = " ".join(s.get_text(strip=True) for s in value_spans).strip()
        # Collapse internal whitespace
        value = re.sub(r"\s+", " ", value)

        col = KNOWN_SPECIFICS.get(label)
        if col:
            result[col] = value
        else:
            extra.append(f"{label}: {value}")

    result["extra_specifics"] = " | ".join(extra) if extra else ""
    return result


def _parse_compatibility_page(soup: BeautifulSoup) -> list[dict]:
    """
    Parse one page of the compatibility table.
    Table: table.ux-table-section
      thead: Year | Make | Model | Trim | Engine | Notes
      tbody: one tr per vehicle
    """
    rows = []
    table = soup.select_one("table.ux-table-section")
    if not table:
        return rows

    headers = [
        th.get_text(strip=True).lower()
        for th in table.select("thead th")
    ]
    if not headers:
        return rows

    for tr in table.select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        rows.append(row)
    return rows


def scrape_item_page(driver, item: dict) -> tuple[dict, list[dict]]:
    """
    Visit an item page, extract:
    - item specifics (all fields)
    - full compatibility list (paginating through all compat pages)

    Returns:
        enriched_item  — original item dict + all item specifics fields
        compat_rows    — list of {year, make, model, trim, engine, notes}
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException

    wait = WebDriverWait(driver, 20)
    url  = item.get("url", "")

    if not url:
        return item, []

    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "h1.x-item-title__mainTitle, div#viTabs_0_is")
        ))
        time.sleep(random.uniform(1.5, 2.5))
    except TimeoutException:
        log.warning("    Timeout loading item page: %s", url)
        return item, []

    soup      = BeautifulSoup(driver.page_source, "lxml")
    specifics = _parse_item_specifics(soup)

    # Fill listing-level fields (price, condition, etc.) from the item page
    # for any fields that were not populated from a search-results card.
    listing_details = _parse_item_listing_details(soup)
    listing_fill = {k: v for k, v in listing_details.items() if not item.get(k) and v}

    enriched = {**item, **listing_fill, **specifics}

    # ── Compatibility table — scroll to it, then paginate ─────────────────
    compat_rows: list[dict] = []

    has_compat = bool(soup.select_one("div[class*='compat']"))
    if not has_compat:
        return enriched, compat_rows

    # Scroll compatibility section into view
    try:
        driver.execute_script(
            "document.querySelector('table.ux-table-section') "
            "&& document.querySelector('table.ux-table-section').scrollIntoView();"
        )
        time.sleep(1.5)
    except Exception:
        pass

    page_num = 1
    while True:
        soup_page = BeautifulSoup(driver.page_source, "lxml")
        page_rows = _parse_compatibility_page(soup_page)

        if not page_rows:
            break

        compat_rows.extend(page_rows)

        # Look for a next-page button inside the compat pagination
        # Selector confirmed: nav.pagination button.pagination__item
        # The active page has aria-current="page"; next is the following enabled button.
        try:
            compat_nav = driver.find_element(
                By.CSS_SELECTOR, "div.motors-pagination nav.pagination"
            )
            buttons = compat_nav.find_elements(
                By.CSS_SELECTOR, "button.pagination__item"
            )
            next_btn = None
            found_active = False
            for btn in buttons:
                aria = btn.get_attribute("aria-current")
                if aria == "page":
                    found_active = True
                    continue
                if found_active and btn.is_enabled():
                    next_btn = btn
                    break

            if next_btn is None:
                break

            driver.execute_script("arguments[0].click();", next_btn)
            page_num += 1
            time.sleep(random.uniform(1.2, 2.0))
        except (NoSuchElementException, Exception):
            break

    if compat_rows:
        log.info(
            "    Item %s: %d compat vehicles (across %d page(s))",
            item["item_id"], len(compat_rows), page_num,
        )

    return enriched, compat_rows

# ---------------------------------------------------------------------------
# Listing page scraper
# ---------------------------------------------------------------------------

def scrape_listings(driver, seller: str, test_mode: bool) -> list[dict]:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    wait     = WebDriverWait(driver, 20)
    all_items: list[dict] = []
    page      = 1
    per_page  = 10 if test_mode else LISTINGS_PER_PAGE

    while True:
        url = seller_search_url(seller, page, per_page)
        log.info("  Listings page %d: %s", page, url)
        driver.get(url)

        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "li.s-card, li.s-item, ul.srp-results")
            ))
        except TimeoutException:
            log.warning("  Timeout on listings page %d.", page)
            break

        time.sleep(random.uniform(2.0, 3.5))
        html  = driver.page_source

        # CAPTCHA / challenge check — only flag if redirected to a challenge URL
        # (avoid false positives from "captcha" strings in eBay's embedded JS)
        if "splashui/challenge" in driver.current_url or "robot" in driver.current_url:
            log.error(
                "  eBay bot challenge detected at: %s\n"
                "  Waiting 30 s — solve it in the browser window if visible, "
                "then the scraper will retry automatically.",
                driver.current_url,
            )
            time.sleep(30)
            continue

        items = parse_listing_page(html)

        if not items:
            log.info("  Page %d: no items found — end of listings.", page)
            break

        all_items.extend(items)
        log.info("  Page %d: +%d listings  (total: %d)", page, len(items), len(all_items))

        if test_mode:
            log.info("  Test mode: stopping after first page.")
            break

        if not has_next_page(html):
            log.info("  No next page — done.")
            break

        page += 1
        time.sleep(random.uniform(2.5, 5.0))

    return all_items

# ---------------------------------------------------------------------------
# Full store scrape: listings + item pages
# ---------------------------------------------------------------------------

def _compat_to_cell(compat_rows: list[dict]) -> str:
    """
    One entry per compatibility row, values within a row separated by |,
    rows separated by comma.

    Format:  YEAR|MAKE|MODEL|TRIM|ENGINE, YEAR|MAKE|MODEL|TRIM|ENGINE, ...

    Example:
        2023|Porsche|Cayenne|S Coupe Sport Utility 4-Door|2.9L V6 Turbo,
        2023|Porsche|Cayenne|Turbo Sport Utility 4-Door|4.0L V8 Turbo, ...
    """
    entries = []
    for row in compat_rows:
        values = [
            row.get("year",   "").strip(),
            row.get("make",   "").strip(),
            row.get("model",  "").strip(),
            row.get("trim",   "").strip(),
            row.get("engine", "").strip(),
        ]
        notes = row.get("notes", "").strip()
        if notes:
            values.append(notes)
        entry = "|".join(values)
        if entry.strip("|"):
            entries.append(entry)
    return ", ".join(entries)


def scrape_store(driver, seller: str, test_mode: bool) -> list[dict]:
    """
    Returns a list of fully enriched product dicts.
    Compatibility data is flattened into a single 'compatibility' column cell.
    """
    log.info("  Collecting listings...")
    listings = scrape_listings(driver, seller, test_mode)

    if not listings:
        return []

    log.info("  Visiting %d individual item pages for full details...", len(listings))
    products: list[dict] = []

    for i, item in enumerate(listings, 1):
        log.info(
            "  [%d/%d] %s — %s",
            i, len(listings), item["item_id"], item["title"][:60],
        )
        enriched, compat = scrape_item_page(driver, item)
        enriched["compatibility"] = _compat_to_cell(compat)
        if compat:
            enriched["compatibility_count"] = len(compat)
        else:
            enriched["compatibility_count"] = 0
        products.append(enriched)

        time.sleep(random.uniform(1.5, 3.0))

    return products

# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

PRODUCT_COLUMNS = [
    # ── Listing info ───────────────────────────────────────────────────────
    "item_id",
    "title",
    "price",
    "listing_type",
    "condition",
    "shipping",
    "location",
    "watchers",
    # ── Item specifics ─────────────────────────────────────────────────────
    "brand",
    "sku",
    "manufacturer_part_number",
    "genuine_oem",
    "warranty",
    "fitment_type",
    "make",
    "model",
    "year",
    "country_of_origin",
    "color",
    "material",
    "upc",
    "extra_specifics",
    # ── Compatibility ──────────────────────────────────────────────────────
    "compatibility_count",
    "compatibility",       # all vehicles in one cell, separated by " | "
    # ── Media & link ───────────────────────────────────────────────────────
    "image_url",
    "url",
]


def save_products(products: list[dict], filename: str) -> None:
    if not products:
        log.warning("No products to save.")
        return
    path = OUTPUT_DIR / filename
    df   = pd.DataFrame(products)
    for col in PRODUCT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df.reindex(columns=PRODUCT_COLUMNS, fill_value="")
    df.index += 1
    df.to_csv(path, index_label="row", encoding="utf-8-sig")
    log.info("Saved %d products  ->  %s", len(df), path)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def scrape_single_url(driver, url: str) -> None:
    """Scrape one item URL and save to single_product.csv / single_compatibility.csv."""
    # Extract item_id from URL for a minimal listing stub
    m = re.search(r"/itm/(\d+)", url)
    item_id = m.group(1) if m else "unknown"
    clean = _clean_url(url)

    log.info("Scraping single item: %s", clean)
    stub = {
        "item_id":      item_id,
        "title":        "",
        "price":        "",
        "listing_type": "",
        "condition":    "",
        "shipping":     "",
        "location":     "",
        "watchers":     "",
        "image_url":    "",
        "url":          clean,
    }
    enriched, compat = scrape_item_page(driver, stub)

    # Fill title from item specifics if listing stub was empty
    if not enriched.get("title") and enriched.get("product_name"):
        enriched["title"] = enriched["product_name"]

    enriched["compatibility_count"] = len(compat)
    enriched["compatibility"] = _compat_to_cell(compat)

    save_products([enriched], "single_product.csv")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape eBay store listings + item details to CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run Chrome without a visible window.",
    )
    parser.add_argument(
        "--store", choices=list(STORES.keys()),
        help="Scrape only one store (default: all).",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test mode: first page of listings only (10 items) to verify output.",
    )
    parser.add_argument(
        "--url",
        help="Scrape a single eBay item URL instead of a full store. "
             "Outputs: single_product.csv + single_compatibility.csv",
    )
    args = parser.parse_args()

    log.info("=" * 65)
    log.info("eBay Store Scraper")
    log.info("Mode    : Chrome/Selenium%s", " [headless]" if args.headless else " [visible]")
    if args.url:
        log.info("Target  : single URL")
    else:
        stores = {args.store: STORES[args.store]} if args.store else dict(STORES)
        log.info("Stores  : %s%s", ", ".join(stores), "  [TEST]" if args.test else "")
    log.info("Started : %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 65)

    driver = make_driver(headless=args.headless)
    try:
        warm_up(driver)

        if args.url:
            scrape_single_url(driver, args.url)
        else:
            for idx, (seller, files) in enumerate(stores.items()):
                log.info("")
                log.info(">>> Store: %s", seller)

                products = scrape_store(driver, seller, test_mode=args.test)
                save_products(products, files["products"])

                if idx < len(stores) - 1:
                    pause = random.uniform(8, 15)
                    log.info("Pausing %.1f s before next store...", pause)
                    time.sleep(pause)
    finally:
        driver.quit()

    log.info("")
    log.info("All done: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


if __name__ == "__main__":
    main()
