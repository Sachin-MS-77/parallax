#!/usr/bin/env bash
set -euo pipefail

# MaxMind requires a free account and license key for GeoLite2 downloads.
# Credentials are read from the environment and never written to the repo.
: "${MAXMIND_ACCOUNT_ID:?Set MAXMIND_ACCOUNT_ID from your MaxMind account}"
: "${MAXMIND_LICENSE_KEY:?Set MAXMIND_LICENSE_KEY from your MaxMind account}"
out="${1:-data/geolite2}"
mkdir -p "$out"
base="https://${MAXMIND_ACCOUNT_ID}:${MAXMIND_LICENSE_KEY}@download.maxmind.com/geoip/databases"
for edition in GeoLite2-Country GeoLite2-ASN; do
  archive="$out/${edition}.tar.gz"
  curl --fail --location --retry 3 --output "$archive" "$base/${edition}-tar.gz/download?edition_id=${edition}&suffix=tar.gz"
  tar -xzf "$archive" -C "$out"
  found=$(find "$out" -type f -name "${edition}.mmdb" -print -quit)
  test -n "$found"
  cp "$found" "$out/${edition}.mmdb"
done
echo "GeoLite2 databases written under $out; retain the MaxMind license notice with them."
