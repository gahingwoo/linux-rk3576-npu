#!/usr/bin/env bash
# Enter an unprivileged Debian chroot, on an aarch64 host, with no root at all.
#
# unshare -Urm makes us uid 0 in a user namespace, which is enough for
# CAP_SYS_CHROOT and for bind mounts. Two things it is NOT enough for:
#
#   * chown to any uid or gid other than 0. Only our own id is mapped, so
#     every other one fails with EINVAL. apt has to be told to stop dropping
#     privileges to _apt, and a package whose postinst chowns to a real group
#     (fontconfig-config is the one that bites) fails to configure. Installing
#     with --no-install-recommends avoids that whole branch.
#   * /sys as a plain bind. It carries locked submounts, so it needs --rbind.
#
#   enter.sh <rootfs-dir> [command ...]
set -euo pipefail
ROOT="${1:?usage: enter.sh <rootfs> [cmd...]}"; shift || true
ROOT="$(cd "$ROOT" && pwd)"

install -d "$ROOT/etc/apt/apt.conf.d"
cat > "$ROOT/etc/apt/apt.conf.d/00-unshare" <<'EOF'
APT::Sandbox::User "root";
Acquire::Retries "3";
# The archives are the only record of which files a package wants owned by
# somebody other than root, and apt deletes them after installing by default.
Binary::apt::APT::Keep-Downloaded-Packages "true";
EOF

exec unshare -Urm --fork --pid --mount-proc=/proc bash -c '
set -e
ROOT="$1"; shift
mount --bind  /proc "$ROOT/proc"
mount --rbind /sys  "$ROOT/sys"
mount --rbind /dev  "$ROOT/dev"
mount -t tmpfs tmpfs "$ROOT/tmp"
mount -t tmpfs tmpfs "$ROOT/run"
# ⚠ Once the image points /etc/resolv.conf at systemd-resolved stub, a plain
# copy writes THROUGH the symlink into a directory that does not exist in a
# chroot, and every name lookup then fails with nothing to show for it. Put the
# host resolver where the link actually points.
if [ -L "$ROOT/etc/resolv.conf" ]; then
	_t=$(readlink "$ROOT/etc/resolv.conf")
	case "$_t" in
	/*) mkdir -p "$ROOT$(dirname "$_t")" && cp -f /etc/resolv.conf "$ROOT$_t" ;;
	esac
else
	cp -f /etc/resolv.conf "$ROOT/etc/resolv.conf"
fi 2>/dev/null || true
if [ "$#" -eq 0 ]; then set -- /bin/bash -l; fi
exec chroot "$ROOT" env -i \
    HOME=/root TERM="${TERM:-xterm}" \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive \
    "$@"
' -- "$ROOT" "$@"
