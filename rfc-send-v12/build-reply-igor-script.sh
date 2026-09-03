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
the table, with one change: its default directory was a path on my
machine and is now the current one, so

    python3 reserved0-build.py DIR > out.md

over any directory of .rknn files prints the same page for that corpus.
It needs only numpy. Everything it knows about the words is in its
docstring, and the meaning of the bits was arrived at by trial and error
against the files and the board, so where a corpus disagrees with mine
the numbers will simply disagree; the "What it does follow" block prints
the 0x4044 lockstep with its own count, so a file from another toolkit
build that lands on the other side of it will show up there rather than
be averaged away.

Thank you for checking 01/14 in v11.

Regards,
Jiaxing

---8<---
COVER
cat reserved0-build.py
} > reply-igor-script.eml
