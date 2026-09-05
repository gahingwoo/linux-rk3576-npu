# Driving the ROCK 4D over its UART from this machine

The VM cannot reach the board over IP (Parallels NAT against the board's own
network), so everything that is not a GitHub release goes through the serial
console: a Raspberry Pi Debug Probe on `/dev/ttyACM*`, 1500000 baud, root/root.

`uart.py` is the whole driver, termios only, no pyserial. Three things in it
were each paid for once:

- **One long-lived opener.** The probe's UART bridge stalls after a close and
  re-open; `usb_reset()` (USBDEVFS_RESET on the parent USB device) brings it
  back, and `expect(..., quiet_reset=N)` does that after N seconds of silence.
  Never run two scripts against the port at once.
- **Follow the device node, not the number.** A reset can re-enumerate the
  adapter as `ttyACM1`; `find_dev()` resolves the by-id link every time.
- **A crash takes the shell with it.** An Oops drops the console back to
  `login:` and every later command then returns the empty string, which looks
  exactly like a command that printed nothing. `run()` watches for the login
  prompt, logs in again, retries once, and counts it in `.relogins`.

Typical use: a small script that logs in, runs a few things with generous
timeouts, and writes its own status file that a monitor tails.
