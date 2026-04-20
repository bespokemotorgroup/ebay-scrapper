# eBay Store Scraper

Scrapes all listed products from eBay seller stores, collects full item details and compatibility data, and saves everything to CSV.

## Requirements

- Python 3.10+
- Google Chrome (latest)

```bash
pip install selenium beautifulsoup4 lxml pandas
```

ChromeDriver is auto-managed by Selenium. If it isn't, download the matching version from https://chromedriver.chromium.org and put it on your PATH.

## Usage

```bash
# Scrape both stores
py -3 scraper.py

# Headless (no Chrome window)
py -3 scraper.py --headless

# One store only
py -3 scraper.py --store porschepartsdirect
py -3 scraper.py --store 5150motorsport

# Test mode — first 10 listings only, fast
py -3 scraper.py --test

# Single item
py -3 scraper.py --url "https://www.ebay.com/itm/326301736942"
```

## Output

Each run produces two files per store — a fixed-name file (always up to date) and a timestamped archive:

```
porschepartsdirect_products.csv
porschepartsdirect_products_20260420_143022.csv

5150motorsport_products.csv
5150motorsport_products_20260420_143022.csv
```

Single-item mode writes `single_product.csv` (+ timestamped copy).

**Columns:** `item_id`, `title`, `price`, `listing_type`, `condition`, `shipping`, `location`, `watchers`, `brand`, `sku`, `manufacturer_part_number`, `genuine_oem`, `warranty`, `fitment_type`, `make`, `model`, `year`, `country_of_origin`, `color`, `material`, `upc`, `extra_specifics`, `compatibility_count`, `compatibility`, `image_url`, `url`

## Resume / Checkpoints

If the scraper is interrupted, just re-run the same command — it picks up where it left off:

```
08:14:03  INFO  Checkpoint found (created 2026-04-20T08:00:00): 147/312 items already done.
08:14:03  INFO  Resuming: 165 items left out of 312 total.
```

- Checkpoint saved after every item (`checkpoints/{store}_checkpoint.json`)
- Listing pages are not re-scraped on resume
- Checkpoint is deleted automatically when the run completes
- To force a fresh start: delete the file in `checkpoints/` before running

## Terminal output

Progress, rate, and ETA are shown after each item:

```
[47/312  15%]  326301736942 — Porsche Cayenne Brake Caliper Front Left OEM
    Done in 3s  |  2.3 items/min  |  265 remaining  |  ETA 1h 55m
```

## Notes

- If eBay shows a bot challenge, the scraper pauses 30 seconds and retries. In visible mode you can solve it manually in the browser window.
- To add or remove stores, edit the `STORES` dict near the top of `scraper.py`.
