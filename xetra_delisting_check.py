import csv
import http.cookiejar
import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path


XETRA_HOLIDAYS: set[date] = {
    # 2026
    date(2026, 1, 1),   # Нова година
    date(2026, 4, 3),   # Великден
    date(2026, 4, 6),   # Великден
    date(2026, 5, 1),   # Ден на труда
    date(2026, 12, 24), # Коледа
    date(2026, 12, 25), # Коледа
    date(2026, 12, 31), # Нова година
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in XETRA_HOLIDAYS


def prev_trading_day(d: date) -> date:
    """Step back one calendar day at a time until we land on a trading day."""
    candidate = d - timedelta(days=1)
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


#Main configg 

PAGE_URL = (
    "https://www.cashmarket.deutsche-boerse.com"
    "/cash-en/trading/Tradable-Instruments-Xetra/xetra"
)
BASE_URL = "https://www.cashmarket.deutsche-boerse.com"
CSV_BLOB_RE = re.compile(
    r"blob/\d+/[a-f0-9]+/data/t7-xetr-allTradableInstruments\.csv"
)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

SNAPSHOT_DIR = Path("snapshots")
REPORT_DIR   = Path("reports")
SNAPSHOT_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

#http request 

def make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def fetch_csv_url(opener):
    req = urllib.request.Request(PAGE_URL, headers={"User-Agent": UA})
    with opener.open(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    match = CSV_BLOB_RE.search(html)
    if not match:
        raise RuntimeError("Could not find CSV URL in page HTML.")
    return f"{BASE_URL}/resource/{match.group(0)}"


def fetch_instruments(opener):
    csv_url = fetch_csv_url(opener)
    req = urllib.request.Request(csv_url, headers={"User-Agent": UA})
    with opener.open(req, timeout=60) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    lines = content.splitlines()
    
    reader = csv.DictReader(lines[2:], delimiter=";")
    return list(reader)

# Sp assist

def snapshot_path(d):
    return SNAPSHOT_DIR / f"{d.isoformat()}_xetr_isins.json"

def save_snapshot(d, isin_map):
    with open(snapshot_path(d), "w") as f:
        json.dump(isin_map, f, indent=2)

def load_snapshot(d):
    p = snapshot_path(d)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)

def build_isin_map(rows):
    result = {}
    for r in rows:
        isin = r.get("ISIN", "").strip()
        if not isin:
            continue
        result[isin] = {
            "name":              r.get("Instrument", "").strip(),
            "type":              r.get("Instrument Type", "").strip(),
            "product_status":    r.get("Product Status", "").strip(),
            "instrument_status": r.get("Instrument Status", "").strip(),
            "last_trading_date": r.get("Last Trading Date", "").strip(),
            "mnemonic":          r.get("Mnemonic", "").strip(),
            "wkn":               r.get("WKN", "").strip(),
        }
    return result

# Check

def detect_pending_deletions(isin_map):
    """Instruments flagged PendingDeletion — removal is imminent."""
    return [
        {"isin": isin, **meta}
        for isin, meta in isin_map.items()
        if meta["instrument_status"] == "PendingDeletion"
    ]

def detect_removed_isins(today_map, yesterday_map):
    """ISINs that were in yesterday's file but are completely gone today."""
    removed = set(yesterday_map.keys()) - set(today_map.keys())
    return [{"isin": isin, **yesterday_map[isin]} for isin in removed]

#Output

def print_section(title, items):
    print(f"\n{'='*62}")
    print(f"  {title} ({len(items)})")
    print(f"{'='*62}")
    if not items:
        print("  None.")
        return
    for item in items:
        print(
            f"  {item['isin']:<14} | {item['name']:<30} | "
            f"{item['type']:<4} | Last traded: {item.get('last_trading_date') or 'N/A'}"
        )

def save_report(today, pending, removed):
    path = REPORT_DIR / f"{today.isoformat()}_xetr_delistings.json"
    with open(path, "w") as f:
        json.dump(
            {"date": today.isoformat(), "pending_deletion": pending, "confirmed_removals": removed},
            f, indent=2,
        )
    print(f"\n  Report saved -> {path}")

# Main

def main():
    today = date.today()

    if not is_trading_day(today):
        print(f"\n{today.isoformat()} is not a Xetra trading day. Nothing to do.")
        sys.exit(0)

    prev = prev_trading_day(today)
    gap  = (today - prev).days

    print(f"\nXetra Delisting Check — {today.isoformat()}")
    print(f"Previous trading day:  {prev.isoformat()}", end="")
    if gap > 1:
        print(f"  ({gap - 1} non-trading day(s) skipped)", end="")
    print()

    opener = make_opener()

    print("\n  Fetching instrument file (visiting page first for session)...")
    try:
        rows = fetch_instruments(opener)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    today_map = build_isin_map(rows)
    print(f"  Instruments in today's file: {len(today_map)}")

    save_snapshot(today, today_map)
    print(f"  Snapshot saved for {today.isoformat()}")

    pending = detect_pending_deletions(today_map)

    prev_map = load_snapshot(prev)
    if prev_map:
        removed = detect_removed_isins(today_map, prev_map)
        print(f"  Instruments in previous snapshot ({prev.isoformat()}): {len(prev_map)}")
        if gap > 1:
            print(f"  Note: diff spans {gap} calendar days — any removal in that window is captured.")
    else:
        removed = []
        print(f"  No snapshot for {prev.isoformat()} — diff unavailable today.")
        print("  Tomorrow's run will produce confirmed removals.")

    print_section("PENDING DELETION  (flagged in today's file, removal imminent)", pending)
    print_section("CONFIRMED REMOVALS  (in previous snapshot, gone today)", removed)

    save_report(today, pending, removed)
    print(f"\nDone.  Pending: {len(pending)}  |  Confirmed removed: {len(removed)}\n")


if __name__ == "__main__":
    main()
