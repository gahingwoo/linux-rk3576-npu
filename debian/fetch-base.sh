#!/usr/bin/env bash
# Fetch a Debian arm64 base rootfs, without root and without debootstrap.
#
# debootstrap needs to chown files to uids other than its own, so it needs
# either real root or a subuid range wired up through newuidmap. Neither is
# available here. The official debian images on Docker Hub are debootstrap
# output built by debuerreotype, published as one plain tar.gz, and served
# over ordinary https. Pull that instead: same rootfs, no privileges.
#
#   fetch-base.sh [suite] [outfile]
set -euo pipefail
SUITE="${1:-bookworm-slim}"
OUT="${2:-$(cd "$(dirname "$0")" && pwd)/../.cache/debian-${SUITE}-arm64.tar.gz}"
mkdir -p "$(dirname "$OUT")"

REG=https://registry-1.docker.io/v2/library/debian
tok() { curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/debian:pull" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])'; }

T=$(tok)
echo "==> resolving $SUITE for linux/arm64"
DIGEST=$(curl -fsS -H "Authorization: Bearer $T" \
    -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
    "$REG/manifests/$SUITE" | python3 -c '
import json,sys
for m in json.load(sys.stdin)["manifests"]:
    p = m.get("platform", {})
    if p.get("architecture") == "arm64" and p.get("os") == "linux":
        print(m["digest"]); break
else:
    sys.exit("no arm64 manifest")')
echo "    manifest $DIGEST"

read -r LAYER SIZE < <(curl -fsS -H "Authorization: Bearer $T" \
    -H "Accept: application/vnd.oci.image.manifest.v1+json" \
    "$REG/manifests/$DIGEST" | python3 -c '
import json,sys
ls = json.load(sys.stdin)["layers"]
assert len(ls) == 1, "expected a single layer, got %d" % len(ls)
print(ls[0]["digest"], ls[0]["size"])')
echo "    layer    $LAYER  ($((SIZE/1024/1024)) MiB)"

curl -fsSL -H "Authorization: Bearer $T" "$REG/blobs/$LAYER" -o "$OUT.part"

# The digest IS the checksum, so verifying costs one hash and turns a corrupt
# download into an error here rather than a strange failure much later.
GOT=$(sha256sum "$OUT.part" | cut -d' ' -f1)
[ "sha256:$GOT" = "$LAYER" ] || { rm -f "$OUT.part"; echo "checksum mismatch" >&2; exit 1; }
mv "$OUT.part" "$OUT"
echo "==> $OUT  ($(du -h "$OUT" | cut -f1), sha256 verified)"
