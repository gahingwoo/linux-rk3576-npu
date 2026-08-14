RK3576 NPU RFC v2 — send kit
============================
Board test PASSED (ROCK 4D): no raw-reset error, no stall timeout, NPU runs
to completion. The clear-fault approach (patch 5) is validated. Ready to send.

Two steps, each asks you [y/N] once, then git send-email prompts for your
fastmail SMTP password. From/Bcc are already in git config
(gahing@gahingwoo.com). Nothing is sent until you confirm.

  1) ./send-v2.sh
       Sends [RFC PATCH v2 0/8] (cover + 8 patches) to the maintainers +
       lists, Cc Chaoyi. Prints the v2 cover lore link and saves its
       Message-Id for step 2.

  2) ./send-reply-chaoyi.sh
       Replies to Chaoyi's patch-4 question, threaded under his comment,
       with the v2 lore link filled in automatically from step 1.

Files:
  v2-0000-cover-letter.patch .. v2-0008-*.patch   the series
  reply-chaoyi.eml                                 the reply (auto-filled)
  reply-chaoyi-patch4.txt                          plain-text copy of the reply

If patch 5 had FAILED on HW we would have fallen back to option A (keep the
two skip patches); it passed, so this kit sends the clear-fault version.
