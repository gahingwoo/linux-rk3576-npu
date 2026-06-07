# U-Boot boot script for Radxa ROCK 4D (RK3576)
# Loaded by U-Boot from FAT partition 1; ${devtype}/${devnum} set automatically.
# CONFIRMED from existing SD boot.scr: console=ttyS0,1500000, mmc 0:1
# Uses initramfs (no separate rootfs partition); rdinit=/init
setenv kernel_addr_r  0x50000000
setenv fdt_addr_r     0x5f000000
setenv ramdisk_addr_r 0x60000000
setenv bootargs "console=ttyS0,1500000n8 earlycon=uart8250,mmio32,0x2ad40000 nokaslr rdinit=/init clk_ignore_unused"
load mmc ${devnum}:1 ${kernel_addr_r}  Image
load mmc ${devnum}:1 ${fdt_addr_r}     rk3576-rock-4d.dtb
load mmc ${devnum}:1 ${ramdisk_addr_r} initramfs.cpio.gz
setenv initrd_size ${filesize}
booti ${kernel_addr_r} ${ramdisk_addr_r}:${initrd_size} ${fdt_addr_r}
