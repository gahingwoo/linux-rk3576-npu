#!/usr/bin/env bash
# Build a bootable Debian arm64 SD card image for the ROCK 4D (RK3576),
# carrying the NPU kernel, entirely without root.
#
# This replaces buildroot. Almost every bug of the last month was a buildroot
# bug and not a real one: no stat(1), no udev so a =m driver never loaded, no
# ntp, and a busybox date(1) that rejects the format every guide prints. A
# user runs Debian and hits none of them, while hitting things we never saw.
#
# HOW IT AVOIDS NEEDING ROOT
#   * the base rootfs comes from debuerreotype's published tar (fetch-base.sh)
#     rather than from debootstrap, which cannot run without a uid range
#   * packages are installed in a user namespace, where we are uid 0
#   * mke2fs -d run INSIDE that namespace sees our files as uid 0 and writes
#     uid 0 into the filesystem, which is right for all but a few dozen files
#   * those few get fixed afterwards with debugfs, which edits an image file
#     and so needs no privileges either
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
WORK="${WORK:-$REPO/.debian-build}"
CACHE="${CACHE:-$REPO/.cache}"
PREBUILT="${PREBUILT:-$REPO/prebuilt}"
UBOOT="${UBOOT:-$HOME/Desktop/rock4d_package/binaries/rock4d-sd-uboot.img}"
SUITE="${SUITE:-bookworm-slim}"
BASE="${BASE:-$CACHE/debian-${SUITE}-arm64.tar.gz}"
OUT="${OUT:-$REPO/debian-rock4d.img}"

# Partition layout, matching what U-Boot on this board already expects.
UBOOT_MB=16
BOOT_MB=128
ROOTFS_MB="${ROOTFS_MB:-4096}"

HOSTNAME_="${HOSTNAME_:-charsiu}"
BOARD_USER="${BOARD_USER:-rock}"
PASSWORD="${PASSWORD:-rock}"

# A normal Debian install has whiptail (priority: important) and no compiler.
# Match that: the point of this image is to meet charsiu's installer with the
# machine a user actually has, so leave build-essential for it to offer.
PKGS="systemd-sysv udev dbus systemd-timesyncd systemd-resolved
      iproute2 iputils-ping openssh-server ca-certificates curl
      whiptail sudo less nano e2fsprogs kmod fdisk"

msg() { printf '\n==> %s\n' "$*"; }

for c in curl python3 mke2fs debugfs sfdisk mkfs.fat mcopy dpkg-deb unshare; do
	command -v "$c" >/dev/null || { echo "missing: $c" >&2; exit 1; }
done
[ -f "$UBOOT" ]                    || { echo "no u-boot at $UBOOT" >&2; exit 1; }
[ -f "$PREBUILT/boot/Image" ]      || { echo "no kernel at $PREBUILT/boot/Image" >&2; exit 1; }
[ -f "$BASE" ] || "$HERE/fetch-base.sh" "$SUITE" "$BASE"

MODTAR=$(echo "$PREBUILT"/modules-*.tar.gz)
[ -f "$MODTAR" ] || { echo "no modules tarball in $PREBUILT" >&2; exit 1; }
# ⚠ NOT `| head -1`. head closes the pipe, tar takes SIGPIPE, and with
# pipefail that kills the whole script before it has printed a single line.
# Let sed stop reading instead.
KVER=$(tar tzf "$MODTAR" | awk -F/ '/^lib\/modules\//{print $3; exit}')
[ -n "$KVER" ] || { echo "cannot read the kernel version from $MODTAR" >&2; exit 1; }

STAGE="$WORK/stage"
msg "staging $SUITE into $STAGE  (kernel $KVER)"
rm -rf "$WORK"; mkdir -p "$STAGE"
# ⚠ EXTRACT INSIDE THE NAMESPACE, NOT OUTSIDE IT. tar clears setuid and setgid
# when it is not root, so a host-side extraction silently produced an image
# where su, passwd, mount and umount were all plain 0755 and no user could
# become root. Inside the namespace we are uid 0 and the bits survive. The few
# non-root chowns still fail here; those are repaired at the end.
unshare -Urm tar -C "$STAGE" -xpzf "$BASE" 2>/dev/null || true

# ---------------------------------------------------------------------------
# OWNERSHIP SHIMS
# ---------------------------------------------------------------------------
# One mapped id means chown to any other id fails with EINVAL, and a handful of
# postinst scripts do exactly that: openssh-client chgrps ssh-agent to the ssh
# group, dbus statoverrides its launch helper to messagebus. dpkg then leaves
# five packages half-configured, which takes systemd-resolved and the ssh server
# down with it.
#
# fakeroot cannot help: inside the namespace we already ARE uid 0, so
# libfakeroot decides no faking is needed and passes the chown straight to the
# kernel, which refuses it just the same.
#
# So let the scripts believe it worked, write down what they asked for, and put
# it into the filesystem at the end with debugfs, which edits an image file and
# needs no privileges at all.
OWNREQ="var/lib/charsiu-ownership"
: > "$STAGE/$OWNREQ"
SHIMDIR="$STAGE/usr/sbin"

cat > "$SHIMDIR/chgrp" <<'EOF'
#!/bin/sh
# build-time shim, removed before the image is made
real=/usr/bin/chgrp
"$real" "$@" 2>/dev/null && exit 0
grp=""; for a in "$@"; do
	case "$a" in -*) continue ;; esac
	if [ -z "$grp" ]; then grp="$a"; else echo ":$grp $a" >> /var/lib/charsiu-ownership; fi
done
exit 0
EOF

cat > "$SHIMDIR/chown" <<'EOF'
#!/bin/sh
real=/usr/bin/chown
"$real" "$@" 2>/dev/null && exit 0
spec=""; for a in "$@"; do
	case "$a" in -*) continue ;; esac
	if [ -z "$spec" ]; then spec="$a"; else echo "$spec $a" >> /var/lib/charsiu-ownership; fi
done
exit 0
EOF

cat > "$SHIMDIR/dpkg-statoverride" <<'EOF'
#!/bin/sh
# Only --add needs intercepting; everything else is the real thing. The mode
# is applied for real (chmod works, we own the file); the owner is recorded.
real=/usr/bin/dpkg-statoverride
case " $* " in *" --add "*) ;; *) exec "$real" "$@" ;; esac
u=""; g=""; m=""; path=""
for a in "$@"; do
	case "$a" in --*) continue ;; esac
	if   [ -z "$u" ]; then u="$a"
	elif [ -z "$g" ]; then g="$a"
	elif [ -z "$m" ]; then m="$a"
	else path="$a"; fi
done
[ -n "$path" ] || exec "$real" "$@"
grep -q "[[:space:]]$path\$" /var/lib/dpkg/statoverride 2>/dev/null \
	|| echo "$u $g $m $path" >> /var/lib/dpkg/statoverride
chmod "$m" "$path" 2>/dev/null || true
echo "$u:$g $path" >> /var/lib/charsiu-ownership
exit 0
EOF
chmod 0755 "$SHIMDIR/chgrp" "$SHIMDIR/chown" "$SHIMDIR/dpkg-statoverride"

msg "installing packages"
"$HERE/lib/enter.sh" "$STAGE" sh -c "
	apt-get update -qq
	apt-get install -y --no-install-recommends $(echo $PKGS) >/dev/null
	dpkg-query -f '\${Package}\n' -W | wc -l
" | tail -1 | sed 's/^/    packages installed: /'

msg "kernel modules"
tar -C "$STAGE" -xzf "$MODTAR"
"$HERE/lib/enter.sh" "$STAGE" depmod -a "$KVER"

msg "configuring"
install -d "$STAGE/etc/systemd/network" "$STAGE/usr/local/sbin" "$STAGE/boot"

echo "$HOSTNAME_" > "$STAGE/etc/hostname"
cat > "$STAGE/etc/hosts" <<EOF
127.0.0.1	localhost
127.0.1.1	$HOSTNAME_
::1		localhost ip6-localhost ip6-loopback
EOF

# ⚠ NLS_ASCII is not in this kernel, so do not let anything mount the boot
# partition with the utf8 default. iso8859-1 and cp437 are both built in.
cat > "$STAGE/etc/fstab" <<'EOF'
/dev/mmcblk0p2  /      ext4  defaults,noatime                        0 1
/dev/mmcblk0p1  /boot  vfat  defaults,iocharset=iso8859-1,codepage=437,nofail  0 2
EOF

# The board's ethernet is stmmac; the interface name depends on udev's
# policy, so match on type rather than guessing between eth0 and end0.
cat > "$STAGE/etc/systemd/network/10-dhcp.network" <<'EOF'
[Match]
Type=ether

[Network]
DHCP=yes

[DHCPv4]
UseDomains=yes
EOF

# ⚠ THE BOARD HAD NO WORKING CLOCK AND SO NO TLS, WHICH LOOKED LIKE A NETWORK
# FAULT FOR MOST OF A DAY. There is a hym8563 RTC on i2c and the kernel now
# has its driver built in; timesyncd corrects it from the network and writes
# it back, so the next cold boot starts with a plausible date.
cat > "$STAGE/etc/systemd/timesyncd.conf" <<'EOF'
[Time]
NTP=
FallbackNTP=pool.ntp.org time.cloudflare.com
EOF

cat > "$STAGE/usr/local/sbin/rk-growroot" <<'EOF'
#!/bin/sh
# The image is deliberately smaller than any card it will be written to.
# Take the rest of the card on the first boot, once, and never think about it.
set -e
DISK=/dev/mmcblk0
PART=2
[ -b "$DISK" ] || exit 0
echo ', +' | sfdisk --no-reread --force -N "$PART" "$DISK" >/dev/null 2>&1 || true
partx -u "$DISK" >/dev/null 2>&1 || true
resize2fs "${DISK}p${PART}" >/dev/null 2>&1 || true
mkdir -p /var/lib/misc && touch /var/lib/misc/rk-growroot.done
EOF
chmod 0755 "$STAGE/usr/local/sbin/rk-growroot"

cat > "$STAGE/etc/systemd/system/rk-growroot.service" <<'EOF'
[Unit]
Description=Grow the root filesystem to fill the card
DefaultDependencies=no
After=systemd-remount-fs.service
Before=sysinit.target
ConditionPathExists=!/var/lib/misc/rk-growroot.done

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rk-growroot
RemainAfterExit=yes

[Install]
WantedBy=sysinit.target
EOF

cat > "$STAGE/etc/motd" <<EOF

  Debian $(echo "$SUITE" | cut -d- -f1) on ROCK 4D (RK3576), kernel $KVER
  The NPU driver is 'rocket'; /dev/accel/accel0 appears when it binds.

  Install the LLM runtime:
    curl -fsSL https://raw.githubusercontent.com/gahingwoo/charsiu/main/scripts/charsiu-install.sh -o install.sh && sh install.sh

EOF

# ⚠ machine-id must be EMPTY, not absent and not copied: systemd generates one
# on first boot, and an image that ships the same id on every card gives every
# board the same DHCP identity.
rm -f "$STAGE/etc/machine-id"; : > "$STAGE/etc/machine-id"
chmod 0644 "$STAGE/etc/machine-id"

msg "users and services"
"$HERE/lib/enter.sh" "$STAGE" sh -c "
	set -e
	echo 'root:$PASSWORD' | chpasswd
	id $BOARD_USER >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo $BOARD_USER
	echo '$BOARD_USER:$PASSWORD' | chpasswd
	ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
	for u in systemd-networkd systemd-resolved systemd-timesyncd \
	         serial-getty@ttyS0.service ssh rk-growroot; do
		systemctl enable \$u >/dev/null 2>&1 || echo \"    could not enable \$u\"
	done
"

# ---------------------------------------------------------------------------
# OWNERSHIP
# ---------------------------------------------------------------------------
# Everything staged is owned by us, which reads as uid 0 inside the namespace
# and is correct for all but a few dozen files. Those are exactly the entries
# whose archives declare a non-root owner, so ask the archives rather than
# keeping a hand-written list that will rot.
msg "collecting the ownership table"
OWNTAB="$WORK/ownership.txt"
{
	tar tvzf "$BASE"
	# ⚠ `[ -f "$d" ] && ...` RETURNS 1 when the glob matched nothing, and as
	# the last command in the group that is enough for set -e to kill the
	# build with no message at all.
	for d in "$STAGE"/var/cache/apt/archives/*.deb; do
		[ -f "$d" ] || continue
		dpkg-deb -c "$d"
	done
	true
} 2>/dev/null | awk '
	$2 != "0/0" {
		path = $6
		for (i = 7; i <= NF; i++) { if ($i == "->") break; path = path " " $i }
		sub(/^\.?\//, "", path)
		sub(/\/$/, "", path)
		if (path != "") print $2, path
	}' | sort -u > "$OWNTAB"
# and whatever the shims caught, which is by name rather than by number
if [ -s "$STAGE/$OWNREQ" ]; then
	python3 - "$STAGE" "$STAGE/$OWNREQ" >> "$OWNTAB" <<'PYEOF'
import sys, os

stage, req = sys.argv[1], sys.argv[2]

def table(path, col):
    out = {}
    try:
        with open(os.path.join(stage, path)) as fh:
            for line in fh:
                f = line.split(':')
                if len(f) > col:
                    out[f[0]] = f[col]
    except OSError:
        pass
    return out

users, groups = table('etc/passwd', 2), table('etc/group', 2)
seen = set()
for line in open(req):
    line = line.strip()
    if not line or ' ' not in line:
        continue
    spec, path = line.split(' ', 1)
    u, _, g = spec.partition(':')
    # A name the chroot knows resolves; a number is already what we want.
    uid = u if u.isdigit() else users.get(u, '')
    gid = g if g.isdigit() else groups.get(g, '')
    if not uid and not gid:
        continue
    path = path.lstrip('/')
    if (uid, gid, path) in seen:
        continue
    seen.add((uid, gid, path))
    print('%s/%s %s' % (uid or '0', gid or '0', path))
PYEOF
	sort -u -o "$OWNTAB" "$OWNTAB"
fi
printf '    %d entries need a non-root owner\n' "$(wc -l < "$OWNTAB")"

msg "cleaning the build's own leavings"
"$HERE/lib/enter.sh" "$STAGE" sh -c 'apt-get clean; rm -rf /var/lib/apt/lists/*'
rm -f "$STAGE/etc/apt/apt.conf.d/00-unshare"   # a build artifact, not policy
rm -f "$STAGE"/usr/sbin/chown "$STAGE"/usr/sbin/chgrp \
      "$STAGE"/usr/sbin/dpkg-statoverride "$STAGE/$OWNREQ"
rm -f "$STAGE/etc/resolv.conf.bak"
rm -f "$STAGE/etc/resolv.conf"
ln -sf /run/systemd/resolve/stub-resolv.conf "$STAGE/etc/resolv.conf"

# ---------------------------------------------------------------------------
# THE FILESYSTEM
# ---------------------------------------------------------------------------
ROOTIMG="$WORK/rootfs.ext4"
msg "building ${ROOTFS_MB} MiB ext4"
rm -f "$ROOTIMG"
unshare -Urm sh -c "mke2fs -q -t ext4 -b 4096 -L rootfs -d '$STAGE' -F '$ROOTIMG' $((ROOTFS_MB * 256))"

msg "repairing ownership"
CMDS="$WORK/debugfs.cmds"
: > "$CMDS"
while read -r own path; do
	uid=${own%%/*}; gid=${own##*/}
	printf 'sif "/%s" uid %s\nsif "/%s" gid %s\n' "$path" "$uid" "$path" "$gid"
done < "$OWNTAB" >> "$CMDS"
# debugfs says "File not found" for anything a package listed but did not end
# up installing. That is expected, so count the real repairs instead.
debugfs -w -f "$CMDS" "$ROOTIMG" >"$WORK/debugfs.log" 2>&1 || true
BAD=$(grep -c "File not found" "$WORK/debugfs.log" || true)
printf '    %d applied, %d not present\n' "$(( $(wc -l < "$CMDS") - BAD ))" "$BAD"
debugfs -R 'stat /etc/shadow' "$ROOTIMG" 2>/dev/null | sed -n 's/.*Group: *\([0-9]*\).*/    check: \/etc\/shadow gid \1 (want 42)/p'

# ---------------------------------------------------------------------------
# THE CARD
# ---------------------------------------------------------------------------
TOTAL_MB=$(( UBOOT_MB + BOOT_MB + ROOTFS_MB ))
msg "assembling ${OUT}  (${TOTAL_MB} MiB)"
rm -f "$OUT"; truncate -s "${TOTAL_MB}M" "$OUT"
dd if="$UBOOT" of="$OUT" bs=1M conv=notrunc status=none

sfdisk --quiet "$OUT" <<EOF
label: dos
unit: sectors

start=32768,  size=262144, type=c
start=294912, size=$(( ROOTFS_MB * 2048 )), type=83
EOF

BOOTFAT="$WORK/boot.fat"
truncate -s "$(( BOOT_MB * 1024 * 1024 ))" "$BOOTFAT"
export MTOOLS_SKIP_CHECK=1
mkfs.fat -F32 -n BOOT "$BOOTFAT" >/dev/null
mcopy -i "$BOOTFAT" "$PREBUILT/boot/Image"               ::Image
mcopy -i "$BOOTFAT" "$PREBUILT/boot/rk3576-rock-4d.dtb"  ::rk3576-rock-4d.dtb

# ⚠ loglevel=4 KEEPS THE CONSOLE FOR USERSPACE. This board's only screen is the
# serial line, and a driver that prints at info level halfway through a whiptail
# dialog scribbles straight over it. Warnings and worse still come through and
# dmesg still has everything, so nothing is lost for debugging.
#
# ⚠ TWO ENTRIES, ALWAYS. charsiu's installer adds a kernel by prepending a
# label here and leaving the previous one selectable, so a kernel that does
# not boot costs a menu choice rather than a card rewrite. The menu is shown
# for three seconds; the default is the entry at the top.
EXTL="$WORK/extlinux.conf"
cat > "$EXTL" <<EOF
default charsiu
prompt 1
timeout 30

label charsiu
    menu label Debian, NPU kernel $KVER
    kernel /Image
    fdt /rk3576-rock-4d.dtb
    append console=ttyS0,1500000n8 earlycon=uart8250,mmio32,0x2ad40000 root=/dev/mmcblk0p2 rootfstype=ext4 rootwait rw log_buf_len=8M loglevel=4
EOF
mmd  -i "$BOOTFAT" ::extlinux
mcopy -i "$BOOTFAT" "$EXTL" ::extlinux/extlinux.conf

dd if="$BOOTFAT" of="$OUT" bs=1M seek="$UBOOT_MB" conv=notrunc status=none
dd if="$ROOTIMG" of="$OUT" bs=1M seek=$(( UBOOT_MB + BOOT_MB )) conv=notrunc status=none

msg "done"
printf '    %s  (%s)\n' "$OUT" "$(du -h "$OUT" | cut -f1)"
printf '    login %s / %s, or root / %s, on ttyS0 at 1500000\n' "$BOARD_USER" "$PASSWORD" "$PASSWORD"
printf '\n    dd if=%s of=/dev/sdX bs=4M conv=fsync oflag=direct status=progress\n\n' "$OUT"
