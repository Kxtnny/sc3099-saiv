"""
Regenerate app/data/sg_ip_ranges.txt from the DB-IP "IP to Country Lite" CSV.

The backend only needs to answer "is this public IP in Singapore?", so this
keeps the Singapore rows, merges adjacent ranges, and writes one
"first,last" pair per line. Refresh it every few months:

    curl -O https://download.db-ip.com/free/dbip-country-lite-YYYY-MM.csv.gz
    python backend/scripts/build_sg_ip_ranges.py dbip-country-lite-YYYY-MM.csv.gz

IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0.
"""

import gzip
import ipaddress
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[1] / "app" / "data" / "sg_ip_ranges.txt"


def main(source: str) -> None:
    opener = gzip.open if source.endswith(".gz") else open
    ranges = []
    with opener(source, "rt", encoding="utf-8") as handle:
        for line in handle:
            first, last, country = line.strip().split(",")
            if country == "SG":
                ranges.append(
                    (ipaddress.ip_address(first), ipaddress.ip_address(last))
                )

    merged = []
    for version in (4, 6):
        block = sorted(r for r in ranges if r[0].version == version)
        for first, last in block:
            if merged and merged[-1][0].version == version and int(first) <= int(merged[-1][1]) + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            else:
                merged.append((first, last))

    header = (
        f"# Singapore IP ranges ({len(merged)} merged from {len(ranges)}), "
        f"generated from {Path(source).name}\n"
        "# IP geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0.\n"
        "# Regenerate with backend/scripts/build_sg_ip_ranges.py\n"
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        header + "".join(f"{a},{b}\n" for a, b in merged), encoding="utf-8"
    )
    print(f"Wrote {len(merged)} ranges to {OUTPUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
