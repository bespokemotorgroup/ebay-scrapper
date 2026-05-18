#!/usr/bin/env python3
"""
Generate an eBay US draft listing upload CSV from a scraped products CSV.

Usage:
    py -3 generate_draft.py porschepartsdirect_products.csv
    py -3 generate_draft.py 5150motorsport_products.csv --qty 1
    py -3 generate_draft.py porschepartsdirect_products.csv --out my_draft.csv

The output file can be uploaded via:
    eBay Seller Hub → Reports → Upload a file → File type: Listing
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ACTION_HEADER = "Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)"

# Matches the exact structure of the eBay-downloaded template.
# Rows 2-3 embed the "#INFO " prefix inside the first field (no comma after #INFO).
# Padding to the full column count is applied in _write_draft_csv.
INFO_ROWS = [
    ["#INFO", "Version=0.0.2", "Template= eBay-draft-listings-template_US"],
    [
        "#INFO Action and Category ID are required fields. "
        "1) Set Action to Draft "
        "2) Please find the category ID for your listings here: "
        "https://pages.ebay.com/sellerinformation/news/categorychanges.html"
    ],
    [
        "#INFO After you've successfully uploaded your draft from the Seller Hub "
        "Reports tab, complete your drafts to active listings here: "
        "https://www.ebay.com/sh/lst/drafts"
    ],
    ["#INFO"],
]

DRAFT_COLUMNS = [
    ACTION_HEADER,
    "Custom label (SKU)",
    "Category ID",
    "Title",
    "UPC",
    "Price",
    "Quantity",
    "Item photo URL",
    "Condition ID",
    "Description",
    "Format",
    # Item Specifics — C: prefix tells eBay these are custom item specific fields
    "C:Brand",
    "C:Manufacturer Part Number",
    "C:Placement on Vehicle",
    "C:Fitment Type",
    "C:Make",
    "C:Model",
    "C:Year",
    "C:Color",
    "C:Material",
    "C:Surface Finish",
    "C:Country/Region of Manufacture",
    "C:Warranty",
    "C:Genuine OEM",
    "C:Type",
]

_FORMAT_MAP = {
    "buy it now": "FixedPrice",
    "fixedprice":  "FixedPrice",
    "fixed price": "FixedPrice",
    "auction":     "Auction",
}

_CONDITION_MAP = {
    "brand new":        "New",
    "new":              "New",
    "new with tags":    "New",
    "new without tags": "New",
    "new with defects": "New with defects",
    "used":             "Used",
    "very good":        "Used",
    "good":             "Used",
    "acceptable":       "Used",
    "for parts":        "For parts or not working",
    "not working":      "For parts or not working",
    "seller refurbished": "Seller refurbished",
    "certified refurbished": "Certified refurbished",
}


def _map_condition(raw: str) -> str:
    key = raw.strip().lower()
    for k, v in _CONDITION_MAP.items():
        if k in key:
            return v
    return raw.strip() or "New"


def _map_format(raw: str) -> str:
    key = raw.strip().lower()
    return _FORMAT_MAP.get(key, "FixedPrice")


def _clean_price(raw: str) -> str:
    """Strip currency symbols and commas; return bare number string."""
    cleaned = re.sub(r"[^\d.]", "", raw)
    return cleaned if cleaned else ""


def _first(value) -> str:
    """Return the first value when a field contains multiple comma-separated entries."""
    s = str(value or "").strip()
    return s.split(",")[0].strip() if "," in s else s


def _resolve_sku(row: pd.Series) -> str:
    """Return a single clean SKU token: sku → manufacturer_part_number → item_id.
    Takes the first value if multiple are present, strips dashes."""
    raw = (
        _first(row.get("sku"))
        or _first(row.get("manufacturer_part_number"))
        or str(row.get("item_id") or "").strip()
    )
    return raw.replace("-", "").replace(" ", "")


def _compat_to_html_table(compat_str: str) -> str:
    """
    Convert the scraped compatibility string into an HTML table to append to
    the listing description.  eBay renders this as a formatted compatibility
    chart visible to buyers.

    Input format (from scraper):
        YEAR|MAKE|MODEL|TRIM|ENGINE|NOTES, YEAR|MAKE|MODEL|TRIM|ENGINE, ...
    """
    if not compat_str or not str(compat_str).strip():
        return ""

    entries = [e.strip() for e in str(compat_str).split(",") if e.strip()]
    if not entries:
        return ""

    rows_html = []
    for entry in entries:
        parts = [p.strip() for p in entry.split("|")]
        year   = parts[0] if len(parts) > 0 else ""
        make   = parts[1] if len(parts) > 1 else ""
        model  = parts[2] if len(parts) > 2 else ""
        trim   = parts[3] if len(parts) > 3 else ""
        engine = parts[4] if len(parts) > 4 else ""
        notes  = parts[5] if len(parts) > 5 else ""
        rows_html.append(
            f"<tr><td>{year}</td><td>{make}</td><td>{model}</td>"
            f"<td>{trim}</td><td>{engine}</td><td>{notes}</td></tr>"
        )

    if not rows_html:
        return ""

    return (
        "<br><h2>Compatibility</h2>"
        "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse:collapse;width:100%'>"
        "<thead style='background:#f5f5f5'>"
        "<tr><th>Year</th><th>Make</th><th>Model</th>"
        "<th>Trim</th><th>Engine</th><th>Notes</th></tr>"
        "</thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )


def build_draft_row(row: pd.Series, default_qty: int) -> list:
    description = str(row.get("description", ""))
    compat_html = _compat_to_html_table(str(row.get("compatibility", "")))
    if compat_html:
        description = description + compat_html

    return [
        # ── Core listing fields ───────────────────────────────────────────
        "Draft",
        _resolve_sku(row),
        row.get("category_id", ""),
        str(row.get("title", ""))[:80],
        row.get("upc", ""),
        _clean_price(str(row.get("price", ""))),
        default_qty,
        row.get("image_url", ""),
        _map_condition(str(row.get("condition", ""))),
        description,
        _map_format(str(row.get("listing_type", ""))),
        # ── Item Specifics (C: columns) ───────────────────────────────────
        _first(row.get("brand")),
        _first(row.get("manufacturer_part_number")),
        _first(row.get("placement")),
        _first(row.get("fitment_type")),
        _first(row.get("make")),
        _first(row.get("model")),
        _first(row.get("year")),
        _first(row.get("color")),
        _first(row.get("material")),
        _first(row.get("surface_finish")),
        _first(row.get("country_of_origin")),
        _first(row.get("warranty")),
        _first(row.get("genuine_oem")),
        _first(row.get("type")),
    ]


def _write_draft_csv(draft_rows: list, out_path: Path) -> None:
    """Write the #INFO headers, column row, and data rows to out_path.
    Comma-delimited to match the format of eBay's downloaded template exactly."""
    import csv
    n = len(DRAFT_COLUMNS)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for info in INFO_ROWS:
            padded = (list(info) + [""] * n)[:n]
            writer.writerow(padded)
        writer.writerow(DRAFT_COLUMNS)
        writer.writerows(draft_rows)

    print(f"Draft CSV written → {out_path}  ({len(draft_rows)} listings)")
    missing_cat = sum(1 for r in draft_rows if not r[2])
    if missing_cat:
        print(
            f"  Warning: {missing_cat} row(s) have no Category ID — "
            "eBay requires this field. Fill them in before uploading."
        )


def generate_draft_from_df(df: pd.DataFrame, output_csv: str, default_qty: int = 1) -> None:
    """Generate an eBay draft CSV from an in-memory DataFrame."""
    draft_rows = [build_draft_row(row, default_qty) for _, row in df.iterrows()]
    _write_draft_csv(draft_rows, Path(output_csv))


def generate_draft(input_csv: str, output_csv: str, default_qty: int) -> None:
    src = Path(input_csv)
    if not src.exists():
        print(f"Error: file not found — {src}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(src, encoding="utf-8-sig", low_memory=False)
    print(f"Loaded {len(df)} rows from {src.name}")
    draft_rows = [build_draft_row(row, default_qty) for _, row in df.iterrows()]
    _write_draft_csv(draft_rows, Path(output_csv))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert scraped products CSV → eBay AU draft upload CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", help="Scraped products CSV (e.g. porschepartsdirect_products.csv)")
    parser.add_argument(
        "--out",
        default="",
        help="Output filename (default: <input_stem>_draft.csv)",
    )
    parser.add_argument(
        "--qty",
        type=int,
        default=1,
        help="Default quantity for all listings (default: 1)",
    )
    args = parser.parse_args()

    out = args.out or Path(args.input).stem + "_draft.csv"
    generate_draft(args.input, out, args.qty)


if __name__ == "__main__":
    main()
