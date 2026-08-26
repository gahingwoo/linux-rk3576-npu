# A serial line has no way to tell anyone how big it is, so the kernel keeps
# the default 24x80 and readline redraws long lines in the wrong column. The
# board log shows what that looks like: curl's error printed on top of the
# command that was still echoed on that row.
#
#   curl: (6) Could not resolve host: raw.githubusercontent.comm/gahingwoo/...
#
# Ask the terminal instead. Park the cursor far past the bottom right, where
# it stops at the real corner, and read the position back. This is what
# xterm's resize(1) does, without pulling in the xterm package.
#
# ⚠ ONLY ON A SERIAL TTY, and only when the size still looks like the default,
# so a real terminal that already reported its size is left alone.
case "${TERM:-}" in dumb|"") return 2>/dev/null || exit 0 ;; esac

_ss_tty=$(tty 2>/dev/null) || _ss_tty=""
case "$_ss_tty" in
/dev/ttyS*|/dev/ttyAMA*|/dev/ttyFIQ*|/dev/ttyGS*) ;;
*) unset _ss_tty; return 2>/dev/null || exit 0 ;;
esac

_ss_size=$(stty size 2>/dev/null) || _ss_size=""
case "$_ss_size" in
"24 80"|"0 0"|"")
	_ss_saved=$(stty -g 2>/dev/null) || _ss_saved=""
	if [ -n "$_ss_saved" ]; then
		# ⚠ `min 0 time 10` is the whole safety of this: a terminal that
		# does not answer costs one second, not a hung login.
		stty raw -echo min 0 time 10 2>/dev/null
		# ⚠ STDIN AND STDOUT, NOT THE TTY BY PATH. Reopening /dev/ttySn
		# gets a different file description, and the reply never arrives
		# on it -- measured: the escape went out and nothing came back.
		printf '\0337\033[999;999H\033[6n\0338'
		_ss_reply=$(dd bs=32 count=1 2>/dev/null)
		stty "$_ss_saved" 2>/dev/null
		_ss_r=$(printf '%s' "$_ss_reply" | tr -dc '0-9;' | cut -d';' -f1)
		_ss_c=$(printf '%s' "$_ss_reply" | tr -dc '0-9;' | cut -d';' -f2)
		case "$_ss_r$_ss_c" in
		*[!0-9]*|"") ;;
		*)
			if [ "$_ss_r" -ge 10 ] && [ "$_ss_c" -ge 40 ]; then
				stty rows "$_ss_r" cols "$_ss_c" 2>/dev/null
			fi ;;
		esac
	fi ;;
esac
unset _ss_tty _ss_size _ss_saved _ss_reply _ss_r _ss_c
