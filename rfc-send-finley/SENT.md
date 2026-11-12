# Sent 2026-11-12

Two replies, both accepted by the SMTP server (250):

- `reply-finley.eml`, Message-ID `<20261112072131.41144-1-gahing@gahingwoo.com>`,
  on v16 10/16, answering Finley Xiao's review of 9/16, 10/16 and 14/16.
  Agrees with all three: the domain reset is a leftover of June's IOMMU
  debugging (dropped in a debug patch that never reached the exported
  series), the commit message's hang and vendor claims are not accurate,
  and the current code runs clean without the reset, with two domain clocks
  and with no delay on NPU0/NPU1 (board-logs/r425, r426). VOP gets the delay.
- `reply-ulf.eml`, Message-ID `<20261112072146.41218-1-gahing@gahingwoo.com>`,
  on v15 00/15, asking Ulf to drop patch 7 (binding) and patch 10 (reset)
  from ulfh/linux-pm.git next; patch 9 stays and a separate patch will fix
  the delay table (npu0/npu1 15 -> 0, vop 0 -> 15).

Owed: that delay-table patch, against Ulf's next.
