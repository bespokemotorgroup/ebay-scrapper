# eBay Store Scraper

Scrapes all listed products from eBay seller stores, visits each item page for full details and compatibility data, then saves everything to CSV.

## Features

- Scrapes all listings from one or both configured stores
- Visits each item page to extract full **Item Specifics** (brand, SKU, part number, warranty, fitment, etc.)
- Parses the full **compatibility table** (year/make/model/trim/engine), paginating through all pages
- Single-URL mode to scrape one item directly
- Test mode (first page only) for quick verification
- Anti-bot measures: cookie warm-up, randomised delays, custom user-agent, webdriver flag suppression

## Output

| File | Contents |
|------|----------|
| `porschepartsdirect_products.csv` | One row per product, all fields |
| `5150motorsport_products.csv` | One row per product, all fields |
| `single_product.csv` | Output when using `--url` mode |

### Columns

`item_id`, `title`, `price`, `listing_type`, `condition`, `shipping`, `location`, `watchers`, `brand`, `sku`, `manufacturer_part_number`, `genuine_oem`, `warranty`, `fitment_type`, `make`, `model`, `year`, `country_of_origin`, `color`, `material`, `upc`, `extra_specifics`, `compatibility_count`, `compatibility`, `image_url`, `url`

The `compatibility` column stores all compatible vehicles in one cell, each entry formatted as `YEAR|MAKE|MODEL|TRIM|ENGINE`, separated by `, `.

## Requirements

- Python 3.10+
- Google Chrome (latest)
- ChromeDriver (must match your Chrome version, on PATH or auto-managed)

Install Python dependencies:

```bash
pip install selenium beautifulsoup4 lxml pandas
```

## Usage

```bash
# Scrape both stores (visible Chrome window)
py -3 scraper.py

# Headless Chrome
py -3 scraper.py --headless

# One store only
py -3 scraper.py --store porschepartsdirect
py -3 scraper.py --store 5150motorsport

# Test mode: first page of listings only (quick check)
py -3 scraper.py --test
py -3 scraper.py --store porschepartsdirect --test

# Scrape a single item URL
py -3 scraper.py --url "https://www.ebay.com/itm/326301736942"
```

## Configuration

Stores are defined in the `STORES` dict near the top of `scraper.py`:

```python
STORES = {
    "porschepartsdirect": {"products": "porschepartsdirect_products.csv"},
    "5150motorsport":     {"products": "5150motorsport_products.csv"},
}
```

Add or remove entries to change which stores are scraped.

## Notes

- If eBay presents a bot challenge, the scraper pauses 30 seconds and retries automatically. If running in visible mode, you can solve the challenge manually in the browser window.
- Output CSV files are saved in the same directory as `scraper.py`.
- Encoding is `utf-8-sig` (Excel-compatible UTF-8).
