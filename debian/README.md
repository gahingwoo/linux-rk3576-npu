# Debian for the ROCK 4D, built without root

This replaces `buildroot/`. Almost every bug of the last month was a buildroot
bug rather than a real one: no `stat(1)`, no udev so a `=m` driver never
loaded, no ntp, and a busybox `date` that rejects the format every guide
prints. A user runs Debian and hits none of them, while hitting things we
never saw. The first hour on real Debian found five bugs in charsiu's
installer that months on the board could not have shown.

    ./fetch-base.sh          # cache a Debian arm64 rootfs (once)
    ./build-image.sh         # -> debian-rock4d.img

Nothing here needs `sudo`.

## Why not debootstrap

debootstrap has to chown files to ids other than its own, so it needs either
real root or a subuid range wired up through `newuidmap`, and `uidmap` is not
installed here. The official Debian images are debuerreotype's debootstrap
output, published as one plain tar.gz over ordinary https, so `fetch-base.sh`
pulls that: the same rootfs, no privileges, and a sha256 that is checked
because the digest already is one.

## How the rest avoids root

| | |
|---|---|
| packages | installed in a `unshare -Urm` namespace, where we are uid 0 |
| the filesystem | `mke2fs -d` run **inside** that namespace sees our files as uid 0 and writes uid 0, which is right for all but a few dozen |
| the exceptions | `debugfs -w` afterwards, which edits an image file and so needs nothing |

### The one hard edge

A namespace with a single mapped id cannot chown to any *other* id. Two
postinst scripts do exactly that (openssh-client chgrps `ssh-agent` to the
`ssh` group; dbus statoverrides its launch helper to `messagebus`), and dpkg
then leaves five packages half-configured, taking systemd-resolved and the ssh
server down with it.

fakeroot does not help. Inside the namespace we already **are** uid 0, so
libfakeroot decides no faking is needed and passes the chown straight to the
kernel, which refuses it just the same.

The build instead shims `chown`, `chgrp` and `dpkg-statoverride`, lets the
scripts believe it worked, writes down what they asked for, and applies it to
the finished image with debugfs.

⚠ The shims go in `/usr/sbin`, not `/usr/local/sbin`: dpkg sets
`PATH=/usr/sbin:/usr/bin:/sbin:/bin` for maintainer scripts, so a shim in
`/usr/local/sbin` is invisible to exactly the scripts it exists for.

⚠ The ownership table is read out of the `.deb` archives, so apt must be told
to keep them (`Binary::apt::APT::Keep-Downloaded-Packages`). It deletes them
after installing by default.

## What ships, and what deliberately does not

whiptail is there, because a normal Debian install has it (priority:
important). **build-essential is not**, because a normal Debian install does
not have it either, and charsiu's installer has to meet the machine a user
actually has. Neither is charsiu: the point of this image is to run

    curl -fsSL .../charsiu-install.sh -o install.sh && sh install.sh

on real Debian and find out what hurts.

## The card

    0 - 16 MiB    u-boot (idbloader + U-Boot, from rock4d_package)
   16 - 144 MiB   FAT32 /boot: Image, dtb, extlinux/extlinux.conf
  144 - end       ext4 rootfs

`rk-growroot` takes the rest of the card on the first boot, so the image stays
small and the card does not.

Login `rock` / `rock` (also root), serial `ttyS0` at 1500000.
