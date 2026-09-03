#!/bin/sh
# assemble reply-igor-script.eml = cover + reserved0-build.py, so the script in
# the mail is the file and cannot drift from it
cd "$(dirname "$0")"
{
cat <<'COVER'
From: Jiaxing Hu <gahing@gahingwoo.com>
Subject: Re: [PATCH v9 05/13] dt-bindings: npu: rockchip: add rockchip,rk3576-rknn-core
In-Reply-To: <20260902100147.16191-1-royalnet026@gmail.com>
References: <CAEWPSH5_PmfUCEm5O53=32NQjPKMd4vm--Y2R=4ErMoehtt=tA@mail.gmail.com> <20260831040751.24030-1-gahing@gahingwoo.com> <20260902100147.16191-1-royalnet026@gmail.com>

Hi Igor,

Here it is, below the line. It is the file that printed every number in
the table, changed only where it had to be before it could run on a
machine that is not mine. The reader for the container is inlined, so
it needs numpy and nothing else. The directory is an argument:

    python3 reserved0-build.py DIR > out.md

And the parts of the page that only hold for my files print only when
those files are present. That covers the named same-geometry pairs,
g_pw24, and the note on my earlier mail.

The meaning of the bits came from trial and error against the files and
the board, so where your corpus disagrees with mine the numbers will
disagree. The "What it does follow" block tests the 0x4044 pairing on
whatever it is given and reports one-to-one or not, with the counts.

Thank you for checking 01/14 in v11.

Regards,
Jiaxing

---8<---
COVER
cat reserved0-build.py
} > reply-igor-script.eml
