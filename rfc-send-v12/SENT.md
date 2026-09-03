# Sent

## reply-igor-script.eml -- SENT

The script behind the RESERVED_0 table, which Igor asked for on 2026-09-02
10:02 in the v9 05/13 thread. Sent 2026-09-03 23:22 +1200, SMTP result 250.

    Message-ID:   <20260903112208.952061-1-gahing@gahingwoo.com>
    In-Reply-To:  <20260902100147.16191-1-royalnet026@gmail.com>
    To:           royalnet026@gmail.com
    Cc:           linux-rockchip@lists.infradead.org, dri-devel@lists.freedesktop.org

What it commits us to:

- the script in it "needs numpy and nothing else": true, the container
  reader is inlined and the rest is the standard library;
- "the parts of the page that only hold for my files print only when those
  files are present": true, gated on MINE, exercised on a six-file subset
  that has none of them;
- "the What it does follow block tests the 0x4044 pairing ... and reports
  one-to-one or not, with the counts": true, it computes both directions
  and prints the verdict it computed.

What it does NOT commit us to: nothing about v12, nothing about a date.

The cover was passed through the no-dashes, no-filler edit before it went;
the script's own prose keeps its double hyphens, it is a file.

## v12 -- NOT SENT, on purpose

v12 is prepared (README.md here). It waits for a reply on v11.
