#!/usr/bin/env python3
"""A serial console driver with nothing but termios: one open for the whole session, and a USB
reset of the adapter when it goes quiet (the Raspberry Pi Debug Probe's UART bridge stalls after
a re-open / line-coding change; a USBDEVFS_RESET brings it back)."""
import os, sys, time, termios, select, re, fcntl, glob

def find_dev():
    """the adapter's current node: the by-id link survives re-enumeration, the ttyACM number does not"""
    e = os.environ.get("UART_DEV")
    if e: return e
    for p in sorted(glob.glob("/dev/serial/by-id/*Debug_Probe*-if01")) + sorted(glob.glob("/dev/ttyACM*")):
        if os.path.exists(p): return os.path.realpath(p)
    return "/dev/ttyACM0"
DEV = find_dev()
BAUD = getattr(termios, "B%s" % os.environ.get("UART_BAUD", "1500000"))
PROMPT = "@@PROMPT@@"
LOG = open(os.environ.get("UART_LOG", "/dev/null"), "ab", buffering=0)

def usb_reset():
    global DEV
    DEV = find_dev()
    dev = os.path.realpath("/sys/class/tty/%s/device" % os.path.basename(DEV))
    usb = dev
    while usb and not os.path.exists(os.path.join(usb, "busnum")):
        usb = os.path.dirname(usb)
    node = "/dev/bus/usb/%03d/%03d" % (int(open(usb + "/busnum").read()), int(open(usb + "/devnum").read()))
    fd = os.open(node, os.O_WRONLY); fcntl.ioctl(fd, 0x5514, 0); os.close(fd)
    time.sleep(2)
    for _ in range(60):
        time.sleep(0.5)
        links = glob.glob("/dev/serial/by-id/*Debug_Probe*-if01")
        if links and os.path.exists(os.path.realpath(links[0])):
            time.sleep(1.5); DEV = find_dev(); return True
    DEV = find_dev(); return os.path.exists(DEV)

class Uart:
    def __init__(self):
        self.relogins = 0
        self.open()
    def open(self):
        global DEV
        DEV = find_dev()
        self.fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = 0; a[1] = 0
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[3] = 0; a[4] = BAUD; a[5] = BAUD
        a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
    def reopen(self):
        try: os.close(self.fd)
        except OSError: pass
        usb_reset(); self.open()
        LOG.write(b"\n[[USB RESET]]\n")
    def send(self, s):
        os.write(self.fd, s.encode() if isinstance(s, str) else s)
    def read_for(self, t):
        end = time.time() + t; out = b""
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if r:
                try: d = os.read(self.fd, 65536)
                except BlockingIOError: d = b""
                if d: out += d; LOG.write(d)
        return out
    def expect(self, pats, timeout, quiet_reset=None):
        """wait for one of pats (bytes regex) in the accumulated stream; (index, acc).
        quiet_reset: seconds of total silence after which the adapter is USB-reset once."""
        end = time.time() + timeout; acc = b""; last = time.time(); resets = 0
        while time.time() < end:
            d = self.read_for(0.5)
            if d: acc += d; last = time.time()
            elif quiet_reset and time.time() - last > quiet_reset and resets < 3:
                self.reopen(); resets += 1; last = time.time()
                self.send("\n")
            for i, p in enumerate(pats):
                if re.search(p, acc, re.S): return i, acc
        return -1, acc
    def login(self, timeout=30):
        for attempt in range(4):
            self.send("\n")
            i, acc = self.expect([rb"login: *$", rb"[Pp]assword: *$", PROMPT.encode() + rb" *$", rb"[#$] *$"], 8)
            if i == 0:
                self.send("root\n"); j, _ = self.expect([rb"[Pp]assword: *$", rb"[#$] *$"], 12)
                if j == 0: self.send("root\n"); self.expect([rb"[#$] *$"], 20)
            elif i == 1:
                self.send("root\n"); self.expect([rb"[#$] *$"], 20)
            elif i < 0:
                if attempt == 2: self.reopen()
                continue
            self.send("export PS1='%s '; stty -echo; stty cols 400\n" % PROMPT)
            k, _ = self.expect([PROMPT.encode() + rb" *$"], 8)
            if k == 0:
                self.read_for(0.5); return True
        return False
    def run(self, cmd, timeout=600, quiet_reset=None, relogin=True):
        """Run one command. ⚠ A CRASH TAKES THE SHELL WITH IT: an Oops on the
        board drops the console back to `login:`, and every later command then
        matches nothing and returns the empty string -- which reads exactly
        like a command that printed nothing. That cost a whole round of unbind
        data on 2026-09-05. So the login prompt is watched for as well, and a
        session that has fallen back to it is logged into again and the command
        retried once, with the fact recorded in .relogins."""
        self.read_for(0.2)
        self.send(cmd + "\n")
        i, acc = self.expect([PROMPT.encode() + rb" *$", rb"login: *$"], timeout, quiet_reset)
        text = acc.decode("utf-8", "replace")
        if i == 1 and relogin:
            LOG.write(b"\n[[LOST THE SHELL, LOGGING IN AGAIN]]\n")
            self.relogins += 1
            time.sleep(1)
            if self.login():
                ok, again = self.run(cmd, timeout, quiet_reset, relogin=False)
                return ok, text.rsplit("login:", 1)[0] + "\n[[shell was lost and retaken]]\n" + again
            return False, text
        return (i == 0), text.rsplit(PROMPT, 1)[0]
    def reboot_and_login(self, timeout=300):
        self.send("reboot\n"); t0 = time.time()
        i, _ = self.expect([rb"login: *$"], timeout, quiet_reset=90)
        if i < 0: return False, time.time() - t0
        time.sleep(1)
        return self.login(), time.time() - t0
