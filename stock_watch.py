#!/usr/bin/env python3
"""Watch a BigCommerce product's variants and notify when any come back in stock.

Uses the same endpoint the product page calls when you pick an option
(/remote/v1/product-attributes/<id>), so it sees per-variant stock.

Notifications:
  - NTFY_TOPIC env var set  -> push to phone via $NTFY_SERVER/<topic> (default https://ntfy.sh)
  - running on macOS        -> also shows a desktop notification

Only alerts on transitions (out -> in), tracked in STATE_FILE, so you aren't
spammed every run while something stays in stock.

Stdlib only. Run: python3 stock_watch.py   (add --test to send a test alert)
"""
import itertools
import json
import os
import platform
import subprocess
import sys
import urllib.parse
import urllib.request

STORE = "https://extarusa.com"
PRODUCT_ID = 322
PRODUCT_NAME = 'Extar EP9 MDB 6.5" 9mm'
PRODUCT_URL = f"{STORE}/ep9-mdb/"

# attribute id -> {value id: label}. Trim these to only the combos you'd buy.
OPTIONS = {
    199: {  # Brace Selection
        250: "Extar Stabilizer w/ Strap",
        251: "SBA3 Brace",
        257: "SBA6 Brace",
    },
    200: {  # Magazine Selection
        252: "Extar 18rd",
        253: "10rd",
        267: "Extar 18rd x4 (+$30)",
    },
}

STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
)
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def check_variant(attrs: dict) -> bool:
    form = [("action", "add"), ("product_id", str(PRODUCT_ID)), ("qty[]", "1")]
    form += [(f"attribute[{a}]", str(v)) for a, v in attrs.items()]
    req = urllib.request.Request(
        f"{STORE}/remote/v1/product-attributes/{PRODUCT_ID}",
        data=urllib.parse.urlencode(form).encode(),
        headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)["data"]
    return bool(data.get("instock")) and bool(data.get("purchasable"))


def notify(title: str, message: str) -> None:
    print(f"NOTIFY: {title} — {message}")
    if NTFY_TOPIC:
        req = urllib.request.Request(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode(),
            headers={"Title": title, "Priority": "urgent", "Tags": "rotating_light",
                     "Click": PRODUCT_URL},
        )
        urllib.request.urlopen(req, timeout=20).read()
    if platform.system() == "Darwin":
        safe = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e",
                        f'display notification "{safe(message)}" with title "{safe(title)}" sound name "Glass"'],
                       check=False)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    if "--test" in sys.argv:
        notify("Stock watch test", f"Notifications work. Watching {PRODUCT_NAME}.")
        return 0

    prev = load_state()
    now, newly_in = {}, []
    attr_ids = list(OPTIONS)
    for combo in itertools.product(*(OPTIONS[a].items() for a in attr_ids)):
        key = " / ".join(label for _, label in combo)
        try:
            now[key] = check_variant({a: vid for a, (vid, _) in zip(attr_ids, combo)})
        except Exception as e:  # keep previous state on transient errors
            print(f"ERROR checking {key}: {e}", file=sys.stderr)
            now[key] = prev.get(key, False)
            continue
        print(f"{'IN STOCK ' if now[key] else 'out      '} {key}")
        if now[key] and not prev.get(key, False):
            newly_in.append(key)

    if newly_in:
        notify(f"IN STOCK: {PRODUCT_NAME}", "; ".join(newly_in) + f"\n{PRODUCT_URL}")

    with open(STATE_FILE, "w") as f:
        json.dump(now, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
