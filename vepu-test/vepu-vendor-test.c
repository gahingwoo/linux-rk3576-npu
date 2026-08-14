// SPDX-License-Identifier: MIT
/*
 * vepu-vendor-test.c — minimal standalone client for the Rockchip downstream
 * vendor kernel's raw MPP ioctl UAPI (/dev/mpp_service), talking directly to
 * the VEPU510 (rkvenc2) codec with NO vendor userspace library (no
 * librockchip_mpp) available on this rootfs.
 *
 * Purpose: this drives the encoder through the VENDOR kernel's own
 * VEPU510-specific control/quirk sequencing (the 0x74/0x308/0x300 dance,
 * exact write ordering, ENC_WDG threshold calc, all handled internally by
 * mpp_rkvenc2.c) while supplying the SAME picture/buffer register content
 * the from-scratch mainline "rockchip-vepu510" driver
 * (drivers/media/platform/rockchip/rkvenc/ in a separate linux-next tree)
 * already uses. If this ALSO stalls (hardware watchdog, zero output), that
 * implicates the picture/buffer-class register content itself (shared by
 * both attempts) rather than the control-register quirk sequence (which
 * only the mainline driver had to reverse-engineer). If this SUCCEEDS, the
 * fix is about control-class register timing/values on the mainline driver
 * side specifically.
 *
 * Protocol summary (see comments inline; derived by reading
 * drivers/video/rockchip/mpp/mpp_common.c and mpp_rkvenc2.c directly, no
 * in-tree example existed to crib from):
 *   - open("/dev/mpp_service")
 *   - ioctl(fd, MPP_IOC_CFG_V1, &array_of_struct_mpp_request)
 *     Array is NOT preceded by a count; the kernel walks it 24 bytes
 *     (sizeof(struct mpp_request) on a 64-bit ABI) at a time, terminated by
 *     flag: MPP_FLAGS_MULTI_MSG on all but the last, MPP_FLAGS_LAST_MSG on
 *     the last. The whole batch (INIT_CLIENT_TYPE + all SET_REG_WRITE +
 *     SET_REG_READ + POLL_HW_FINISH) goes in ONE ioctl call, which BLOCKS
 *     until hardware completion (or error) before returning.
 *   - MPP_CMD_INIT_CLIENT_TYPE: data -> a single u32 = MPP_DEVICE_RKVENC (16)
 *   - MPP_CMD_SET_REG_WRITE: data -> raw register words for one class range
 *     [offset, offset+size); may issue several, one per class, in one batch
 *   - Buffer pointer registers (fixed word-indices 4-23,28-30 relative to
 *     the PIC class base 0x270, i.e. absolute 0x280-0x2ec8/0x2e0-0x2e8) are
 *     NOT raw dma addresses -- each word holds (fd & 0x3ff) | (byte_offset
 *     << 10); the kernel imports the dma-buf fd and rewrites that exact
 *     word to iova+offset before hardware ever sees it.
 *   - MPP_CMD_SET_REG_READ: data -> buffer to receive a class range after
 *     completion (used here for the STATUS class, to read back bs_lgth /
 *     slice_num / int_sta).
 *   - MPP_CMD_POLL_HW_FINISH: last in the batch, flags |= MPP_FLAGS_LAST_MSG.
 *
 * Buffers are allocated via the standard DMA-BUF heaps UAPI
 * (/dev/dma_heap/*, DMA_HEAP_IOCTL_ALLOC) -- this vendor kernel has
 * CONFIG_DMABUF_HEAPS_SYSTEM/CMA=y, no ION, no udmabuf.
 */

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

/* ---- subset of include/uapi/linux/rk-mpp.h ---- */
#define MPP_IOC_MAGIC 'v'
#define MPP_IOC_CFG_V1 _IOW(MPP_IOC_MAGIC, 1, unsigned int)

#define MPP_CMD_INIT_CLIENT_TYPE 0x100
#define MPP_CMD_SET_REG_WRITE    0x200
#define MPP_CMD_SET_REG_READ     0x201
#define MPP_CMD_POLL_HW_FINISH   0x300

#define MPP_FLAGS_MULTI_MSG 0x00000001u
#define MPP_FLAGS_LAST_MSG  0x00000002u

#define MPP_DEVICE_RKVENC 16

struct mpp_request {
	uint32_t cmd;
	uint32_t flags;
	uint32_t size;
	uint32_t offset;
	void *data;
};

/* ---- subset of include/uapi/linux/dma-heap.h ---- */
#define DMA_HEAP_IOC_MAGIC 'H'
#define DMA_HEAP_IOCTL_ALLOC _IOWR(DMA_HEAP_IOC_MAGIC, 0x0, struct dma_heap_allocation_data)

struct dma_heap_allocation_data {
	uint64_t len;
	uint32_t fd;
	uint32_t fd_flags;
	uint64_t heap_flags;
};

#define CHECK(cond, msg) do { if (!(cond)) { fprintf(stderr, msg ": %s\n", strerror(errno)); exit(1); } } while (0)
#define ALIGN(x, a) (((x) + (a) - 1) & ~((size_t)(a) - 1))

static int dmabuf_alloc(size_t len, void **out_map)
{
	static const char *heaps[] = {
		"/dev/dma_heap/system", "/dev/dma_heap/reserved",
		"/dev/dma_heap/linux,cma", "/dev/dma_heap/cma-reserved", NULL,
	};
	int i;

	for (i = 0; heaps[i]; i++) {
		int hfd = open(heaps[i], O_RDWR);
		struct dma_heap_allocation_data data;
		int ret;

		if (hfd < 0)
			continue;

		memset(&data, 0, sizeof(data));
		data.len = len;
		data.fd_flags = O_RDWR | O_CLOEXEC;
		ret = ioctl(hfd, DMA_HEAP_IOCTL_ALLOC, &data);
		close(hfd);
		if (ret == 0) {
			void *map = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, data.fd, 0);

			fprintf(stderr, "alloc %zu bytes from %s -> fd=%u\n", len, heaps[i], data.fd);
			if (map == MAP_FAILED) {
				fprintf(stderr, "mmap fd=%u failed: %s\n", data.fd, strerror(errno));
				exit(1);
			}
			memset(map, 0, len);
			if (out_map)
				*out_map = map;
			return (int)data.fd;
		}
	}
	fprintf(stderr, "no /dev/dma_heap/* worked for len=%zu\n", len);
	exit(1);
}

/* fd-slot register word: low 10 bits = fd, bits[31:10] = byte offset. */
static uint32_t fdw(int fd, uint32_t byte_offset)
{
	return ((uint32_t)fd & 0x3ff) | (byte_offset << 10);
}

/* ---- register class layout (absolute byte offsets, whole mpp reg space) ---- */
#define CLASS_BASE_OFF 0x0000
#define CLASS_BASE_SZ  0x0124
#define CLASS_PIC_OFF  0x0270
#define CLASS_PIC_SZ   0x0214
#define CLASS_RC_OFF   0x1000
#define CLASS_RC_SZ    0x0110
#define CLASS_PAR_OFF  0x1700
#define CLASS_PAR_SZ   0x02d0
#define CLASS_SQI_OFF  0x2000
#define CLASS_SQI_SZ   0x00bc
#define CLASS_SCL_OFF  0x2200
#define CLASS_SCL_SZ   0x0388
#define CLASS_ST_OFF   0x4000

/* mpp always writes these classes unconditionally (RDO lambda tables,
 * "subjective adjust" quant tuning, scaling-list) regardless of format or
 * RC mode -- this tool never touched them at all until a real wtrace
 * capture of a genuinely successful mpi_enc_test encode on this exact
 * board showed it does. Values below are copied verbatim from that real,
 * successful capture (same 176x144/NV12/H264 config) -- SCL happens to be
 * all-zero for a same-size passthrough encode (no scaling), included
 * anyway for completeness/safety. */
#include "extra-classes.h"
#define CLASS_ST_SZ    0x0250

#define REG_ENC_START 0x0010
#define REG_INT_EN    0x0020

#define REG_ADR_SRC0  0x0280
#define REG_ADR_SRC1  0x0284
#define REG_ADR_SRC2  0x0288
#define REG_RFPW_H    0x028c
#define REG_RFPW_B    0x0290
#define REG_RFPR_H    0x0294
#define REG_RFPR_B    0x0298
#define REG_MEIW      0x02ac
#define REG_DSPW      0x02a4
#define REG_DSPR      0x02a8
#define REG_RFPT_H    0x02d0
#define REG_RFPB_H    0x02d4
#define REG_RFPT_B    0x02d8
#define REG_ADR_RFPB_B 0x02dc
#define REG_BSBT      0x02b0
#define REG_BSBB      0x02b4
#define REG_ADR_BSBS  0x02b8
#define REG_BSBR      0x02bc
#define REG_SMEAR_RD  0x02e0
#define REG_SMEAR_WR  0x02e4
#define REG_ENC_PIC   0x0300
#define REG_ENC_RSL   0x0310
#define REG_SRC_FILL  0x0314
#define REG_SRC_FMT   0x0318
#define REG_SRC_STRD0 0x0334
#define REG_SRC_STRD1 0x0338
#define REG_RC_QP     0x0354
#define REG_SLI_SPLT  0x0360
#define REG_ME_RNGE   0x0370
#define REG_ME_CFG    0x0374
#define REG_ME_CACH   0x0378
#define REG_SYNT_NAL  0x03b0
#define REG_SYNT_SPS  0x03b4
#define REG_SYNT_PPS  0x03b8
#define REG_SYNT_SLI0 0x03bc

#define REG_ROI_QTHD0 0x1030
#define REG_ROI_QTHD1 0x1034
#define REG_ROI_QTHD2 0x1038
#define REG_ROI_QTHD3 0x103c

#define REG_ST_BS_LENGTH 0x4000
#define REG_ST_SLICE_NUM 0x4034
#define REG_ST_INT_STA_SHADOW 0x0000 /* rkvenc_finish() patches int_sta into the ST shadow; offset TBD, read whole class instead */

static void setw(uint8_t *class_buf, uint32_t class_off, uint32_t reg_off, uint32_t val)
{
	memcpy(class_buf + (reg_off - class_off), &val, 4);
}

int main(int argc, char **argv)
{
	unsigned width = argc > 1 ? (unsigned)atoi(argv[1]) : 176;
	unsigned height = argc > 2 ? (unsigned)atoi(argv[2]) : 144;
	unsigned aligned_w16 = ALIGN(width, 16), aligned_h16 = ALIGN(height, 16);
	unsigned aligned_w64 = ALIGN(width, 64), aligned_h64 = ALIGN(height, 16) + 16;
	size_t nv12_size = (size_t)aligned_w16 * aligned_h16 * 3 / 2;
	size_t bs_size = 128 * 1024;
	size_t pixel_hdr = ALIGN((size_t)aligned_w64 * aligned_h64 / 64, 8192);
	size_t pixel_bdy = (size_t)aligned_w64 * aligned_h64 * 3 / 2;
	size_t pixel_size = pixel_hdr + pixel_bdy;
	size_t thumb_size = ALIGN((aligned_w64 / 64) * (aligned_h64 / 64) * 256, 8192);
	size_t smear_size = ALIGN(aligned_w64 / 64, 16) * ALIGN(aligned_h64 / 16, 16);
	int qp = 26;

	void *src_map, *bs_map, *reconw_map, *thumbw_map, *smearw_map, *meiw_map;
	int fd_src, fd_bs, fd_reconw, fd_thumbw, fd_smearw, fd_meiw;
	uint8_t base_buf[CLASS_BASE_SZ] = {0};
	uint8_t pic_buf[CLASS_PIC_SZ] = {0};
	uint8_t rc_buf[CLASS_RC_SZ] = {0};
	uint8_t st_buf[CLASS_ST_SZ] = {0};
	uint32_t u32val;
	int mpp_fd;
	struct mpp_request reqs[11];
	int n = 0;

	if (thumb_size < 8192)
		thumb_size = 8192;
	if (smear_size < 4096)
		smear_size = 4096;

	fprintf(stderr, "vepu-vendor-test: %ux%u, pixel=%zu(hdr=%zu) thumb=%zu smear=%zu bs=%zu\n",
		width, height, pixel_size, pixel_hdr, thumb_size, smear_size, bs_size);

	fd_src = dmabuf_alloc(nv12_size, &src_map);
	/* horizontal gradient luma, flat chroma -- matches the mainline vepu-test pattern */
	{
		unsigned x, y;
		uint8_t *y_plane = src_map;
		uint8_t *uv_plane = (uint8_t *)src_map + (size_t)aligned_w16 * aligned_h16;

		for (y = 0; y < aligned_h16; y++)
			for (x = 0; x < aligned_w16; x++)
				y_plane[y * aligned_w16 + x] = (uint8_t)(x * 255 / (aligned_w16 - 1));
		memset(uv_plane, 128, (size_t)aligned_w16 * aligned_h16 / 2);
	}
	fd_bs = dmabuf_alloc(bs_size, &bs_map);
	fd_reconw = dmabuf_alloc(pixel_size, &reconw_map);
	fd_thumbw = dmabuf_alloc(thumb_size, &thumbw_map);
	fd_smearw = dmabuf_alloc(smear_size, &smearw_map);
	fd_meiw = dmabuf_alloc(4096, &meiw_map); /* motion-detection info -- real capture had this non-zero */

	/* ---- CLASS_BASE ----
	 * Copied verbatim (words 0-23, offsets 0x0-0x5c) from a real successful
	 * mpi_enc_test wtrace capture -- includes int_en=0x7ff7, enc_start=0x100
	 * (kernel defers the actual HW write regardless), dtrns_map=0x7000
	 * (0x30) and opt_strg=0x3 (0x54), neither of which this tool ever set
	 * before. enc_wdg/the 0x74+0x308 dvbm-hold quirk are handled
	 * unconditionally by the vendor kernel's rkvenc_run() for
	 * RKVENC_VEPU_510 regardless of what's supplied here.
	 */
	memcpy(base_buf, base_class_words, sizeof(base_class_words));

	/* ---- CLASS_PIC ---- */
	setw(pic_buf, CLASS_PIC_OFF, REG_ADR_SRC0, fdw(fd_src, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_ADR_SRC1, fdw(fd_src, (uint32_t)((size_t)aligned_w16 * aligned_h16)));
	/* mpp sets adr_src2 = adr_src1 unconditionally (hal_h264e_vepu510.c:860,
	 * "reg_frm->common.adr_src2 = fd_in") even for 2-plane NV12 -- confirmed
	 * via real wtrace capture this was NOT zero on a real encode. */
	setw(pic_buf, CLASS_PIC_OFF, REG_ADR_SRC2, fdw(fd_src, (uint32_t)((size_t)aligned_w16 * aligned_h16)));

	/* mpp's setup_vepu510_recn_refr() (hal_h264e_vepu510.c:1403-1444) draws
	 * write pointers (rfpw/dspw/smear_wr) from the "curr" ping-pong slot and
	 * read pointers (rfpr/dspr/smear_rd) from the "refr" slot -- but for the
	 * FIRST frame of a session refr_idx==curr_idx, so real hardware gets the
	 * SAME buffer aliased for both read and write. Confirmed directly from a
	 * real wtrace capture of mpi_enc_test's frame 0 (rfpr_h==rfpw_h,
	 * dspr==dspw, smear_rd==smear_wr, all identical addresses) -- this tool
	 * previously used separate never-written buffers for the read side,
	 * which the real encoder never does on frame 0.
	 */
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPW_H, fdw(fd_reconw, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPW_B, fdw(fd_reconw, (uint32_t)pixel_hdr));
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPR_H, fdw(fd_reconw, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPR_B, fdw(fd_reconw, (uint32_t)pixel_hdr));
	setw(pic_buf, CLASS_PIC_OFF, REG_DSPW, fdw(fd_thumbw, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_DSPR, fdw(fd_thumbw, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_SMEAR_WR, fdw(fd_smearw, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_SMEAR_RD, fdw(fd_smearw, 0));
	/* motion-detection info write pointer -- real capture had this set
	 * (non-zero) even though it's undocumented as required for a plain
	 * encode; allocate a real buffer rather than assume it's inert at 0. */
	setw(pic_buf, CLASS_PIC_OFF, REG_MEIW, fdw(fd_meiw, 0));
	/* rfpt_h/rfpb_h/rfpt_b/adr_rfpb_b: real capture had 0x2d0/0x2d8 set to
	 * the literal sentinel 0xffffffff (not an fd-embedded address -- 0x3ff
	 * as an fd would be invalid on any real system, so this reads as an
	 * explicit "disabled" pattern) with 0x2d4/0x2dc left at 0. Copied
	 * verbatim rather than guessing zero is equivalent. */
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPT_H, 0xffffffff);
	setw(pic_buf, CLASS_PIC_OFF, REG_RFPT_B, 0xffffffff);

	setw(pic_buf, CLASS_PIC_OFF, REG_BSBB, fdw(fd_bs, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_BSBT, fdw(fd_bs, (uint32_t)(bs_size - 1)));
	setw(pic_buf, CLASS_PIC_OFF, REG_ADR_BSBS, fdw(fd_bs, 0));
	setw(pic_buf, CLASS_PIC_OFF, REG_BSBR, fdw(fd_bs, 0));

	/* enc_rsl: pic_wd8_m1[10:0] | pic_hd8_m1[26:16], 16-px aligned per mpp */
	u32val = ((aligned_w16 / 8 - 1) & 0x7ff) | (((aligned_h16 / 8 - 1) & 0x7ff) << 16);
	setw(pic_buf, CLASS_PIC_OFF, REG_ENC_RSL, u32val);
	u32val = ((aligned_w16 - width) & 0x3f) | (((aligned_h16 - height) & 0x3f) << 16);
	setw(pic_buf, CLASS_PIC_OFF, REG_SRC_FILL, u32val);
	/* src_fmt.src_cfmt = YUV420SP(6), bits[5:2] -- real capture had 0x98
	 * (cfmt=6 at bits[5:2] plus an extra bit7 this tool's own bitfield
	 * understanding didn't account for); use the real value verbatim. */
	setw(pic_buf, CLASS_PIC_OFF, REG_SRC_FMT, 0x98);
	setw(pic_buf, CLASS_PIC_OFF, REG_SRC_STRD0, aligned_w16 & 0x1fffff);
	setw(pic_buf, CLASS_PIC_OFF, REG_SRC_STRD1, aligned_w16 & 0xffff);

	/* enc_pic: enc_stnd=0(H264) bits[1:0], cur_frm_ref=1 bit2, pic_qp
	 * bits[13:8], slen_fifo bit30 (vendor kernel ORs this in anyway,
	 * set here too for clarity)
	 */
	u32val = (0) | (1u << 2) | ((uint32_t)qp << 8) | (1u << 30);
	setw(pic_buf, CLASS_PIC_OFF, REG_ENC_PIC, u32val);

	/* rc_qp: rc_max_qp[27:22] rc_min_qp[21:16] (bits[31:16] region per
	 * struct { reserved:16; rc_qp_range:4; rc_max_qp:6; rc_min_qp:6; })
	 * -> rc_min_qp at bits[21:16], rc_max_qp at bits[27:22]
	 */
	u32val = (((uint32_t)qp & 0x3f) << 16) | (((uint32_t)qp & 0x3f) << 22);
	setw(pic_buf, CLASS_PIC_OFF, REG_RC_QP, u32val);

	/* sli_splt = 0 (single slice, no split) */
	setw(pic_buf, CLASS_PIC_OFF, REG_SLI_SPLT, 0);

	/* motion-estimation config -- mpp's own hardcoded constants,
	 * written unconditionally regardless of I/P (see mainline driver's
	 * rkvenc-regs.h banner comment for the derivation).
	 * me_rnge: cime_srch_dwnh[3:0]=15 uph[7:4]=15 rgtw[11:8]=12 lftw[15:12]=12
	 */
	u32val = 15 | (15 << 4) | (12 << 8) | (12 << 12);
	setw(pic_buf, CLASS_PIC_OFF, REG_ME_RNGE, u32val);
	/* me_cfg: srgn_max_num[6:0]=54 cime_dist_thre[19:7]=1024 rme_srch_h[21:20]=3 rme_srch_v[23:22]=3 */
	u32val = 54 | (1024u << 7) | (3u << 20) | (3u << 22);
	setw(pic_buf, CLASS_PIC_OFF, REG_ME_CFG, u32val);
	/* me_cach: cime_zero_thre[12:0]=64 */
	setw(pic_buf, CLASS_PIC_OFF, REG_ME_CACH, 64);

	/* synt_nal: nal_ref_idc[1:0]=1 nal_unit_type[6:2]=5(IDR) */
	setw(pic_buf, CLASS_PIC_OFF, REG_SYNT_NAL, 1 | (5 << 2));
	/* synt_sps: max_fnum[3:0]=4 drct_8x8 bit4=1 mpoc_lm4[8:5]=4 poc_type[10:9]=0 */
	setw(pic_buf, CLASS_PIC_OFF, REG_SYNT_SPS, 4 | (1 << 4) | (4 << 5));
	/* synt_pps: etpy_mode bit0=0(CAVLC) pic_init_qp[13:8] cb/cr_ofst=0 dbf_cp_flg bit22=1 */
	u32val = ((uint32_t)qp << 8) | (1u << 22);
	setw(pic_buf, CLASS_PIC_OFF, REG_SYNT_PPS, u32val);
	/* synt_sli0: sli_type[1:0]=2(I) pps_id=0 frm_num[31:16]=0 */
	setw(pic_buf, CLASS_PIC_OFF, REG_SYNT_SLI0, 2);

	/* ---- CLASS_RC (RC_ROI) ----
	 * Copied verbatim from the real successful capture: rc_adj0/rc_adj1,
	 * rc_dthd_0_8[9] (bit-count deviation thresholds -- real leaves the
	 * outer ones at the 0x7fffffff "never trigger" sentinel, this tool
	 * previously left the whole class near-zero, which for a threshold
	 * register may read as "always triggered" instead of "inert"),
	 * roi_qthd0-3, and the rc_wgt tables -- rather than this tool's own
	 * fixed-QP-derived subset (roi_qthd0-3 only, rest zero). This uses
	 * mpp's default adaptive-RC values, not literal fixed-QP, but the
	 * goal here is reproducing/ruling out the hardware stall, not
	 * matching a specific RC mode.
	 */
	memcpy(rc_buf, rc_class_words, sizeof(rc_class_words));

	/* ---- open device, build the batch ---- */
	mpp_fd = open("/dev/mpp_service", O_RDWR);
	CHECK(mpp_fd >= 0, "open /dev/mpp_service");

	memset(reqs, 0, sizeof(reqs));

	u32val = MPP_DEVICE_RKVENC;
	reqs[n].cmd = MPP_CMD_INIT_CLIENT_TYPE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = 4;
	reqs[n].data = &u32val;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = CLASS_BASE_SZ;
	reqs[n].offset = CLASS_BASE_OFF;
	reqs[n].data = base_buf;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = CLASS_PIC_SZ;
	reqs[n].offset = CLASS_PIC_OFF;
	reqs[n].data = pic_buf;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = CLASS_RC_SZ;
	reqs[n].offset = CLASS_RC_OFF;
	reqs[n].data = rc_buf;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = sizeof(par_class_words);
	reqs[n].offset = CLASS_PAR_OFF;
	reqs[n].data = (void *)par_class_words;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = sizeof(sqi_class_words);
	reqs[n].offset = CLASS_SQI_OFF;
	reqs[n].data = (void *)sqi_class_words;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_WRITE;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = sizeof(scl_class_words);
	reqs[n].offset = CLASS_SCL_OFF;
	reqs[n].data = (void *)scl_class_words;
	n++;

	reqs[n].cmd = MPP_CMD_SET_REG_READ;
	reqs[n].flags = MPP_FLAGS_MULTI_MSG;
	reqs[n].size = CLASS_ST_SZ;
	reqs[n].offset = CLASS_ST_OFF;
	reqs[n].data = st_buf;
	n++;

	reqs[n].cmd = MPP_CMD_POLL_HW_FINISH;
	reqs[n].flags = MPP_FLAGS_LAST_MSG;
	n++;

	fprintf(stderr, "submitting %d-message batch, blocking until hw completion...\n", n);
	if (ioctl(mpp_fd, MPP_IOC_CFG_V1, reqs) < 0) {
		fprintf(stderr, "MPP_IOC_CFG_V1 failed: %s\n", strerror(errno));
		return 1;
	}

	{
		uint32_t bs_lgth, slice_num;

		memcpy(&bs_lgth, st_buf + (REG_ST_BS_LENGTH - CLASS_ST_OFF), 4);
		memcpy(&slice_num, st_buf + (REG_ST_SLICE_NUM - CLASS_ST_OFF), 4);
		printf("ioctl returned OK. bs_lgth=0x%08x slice_num=0x%08x\n", bs_lgth, slice_num);
		if (bs_lgth) {
			FILE *f = fopen("/opt/npu-test/vepu-vendor-out.h264", "wb");

			if (f) {
				fwrite(bs_map, 1, bs_lgth, f);
				fclose(f);
				printf("wrote %u bytes to /opt/npu-test/vepu-vendor-out.h264\n", bs_lgth);
			}
		}
	}

	return 0;
}
