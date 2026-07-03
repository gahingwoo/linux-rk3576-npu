// SPDX-License-Identifier: MIT
/*
 * replay.c — faithfully replay librknnrt's captured submission for the simplest
 * conv through the rknn UABI (Tomeu #55). The conv is 3 tiled tasks over 5 BOs
 * (task-array, weights+bias+3-regcmds, 300KB scratch, input, output), captured
 * by capture.so into a dir of bo00..bo04.bin + meta.txt. This re-creates those
 * BOs, fills them, remaps every captured IOVA reference (regcmd address regs +
 * the task-array regcmd_addr) to the new BOs, and submits task_number=3.
 *
 * Run on the vendor stack first (must reproduce the conv); the rocket port of
 * this is the decisive test. NOT yet board-validated.
 *
 *   replay <dir>   (dir holds meta.txt + bo00.bin ..)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>

#define DRM_COMMAND_BASE 0x40
struct rknpu_mem_create { uint32_t handle, flags; uint64_t size, obj_addr,
	dma_addr, sram_size; int32_t iommu_domain_id; uint32_t core_mask; };
struct rknpu_mem_map { uint32_t handle, reserved; uint64_t offset; };
struct rknpu_mem_sync { uint32_t flags, reserved; uint64_t obj_addr, offset, size; };
struct rknpu_subcore_task { uint32_t task_start, task_number; };
struct rknpu_submit { uint32_t flags, timeout, task_start, task_number, task_counter;
	int32_t priority; uint64_t task_obj_addr; uint32_t iommu_domain_id, reserved;
	uint64_t task_base_addr; int64_t hw_elapse_time; uint32_t core_mask; int32_t fence_fd;
	struct rknpu_subcore_task subcore_task[5]; };
#define IOCTL_RKNPU_SUBMIT      _IOWR('d', DRM_COMMAND_BASE + 0x01, struct rknpu_submit)
#define IOCTL_RKNPU_MEM_CREATE  _IOWR('d', DRM_COMMAND_BASE + 0x02, struct rknpu_mem_create)
#define IOCTL_RKNPU_MEM_MAP     _IOWR('d', DRM_COMMAND_BASE + 0x03, struct rknpu_mem_map)
#define IOCTL_RKNPU_MEM_SYNC    _IOWR('d', DRM_COMMAND_BASE + 0x05, struct rknpu_mem_sync)
struct rknpu_action { uint32_t flags, value; };
#define IOCTL_RKNPU_ACTION      _IOWR('d', DRM_COMMAND_BASE + 0x00, struct rknpu_action)
#define RKNPU_ACT_RESET 6   /* librknnrt's rknn_init issues this; the kernel only
			     * soft-resets after a timeout, so a raw replay that
			     * skips it runs the PC un-reset: task 0 runs but the
			     * task-iteration state machine never advances. */
struct drm_version { int v_major, v_minor, v_patch;
	size_t name_len; char *name; size_t date_len; char *date; size_t desc_len; char *desc; };
#define DRM_IOCTL_VERSION _IOWR('d', 0x00, struct drm_version)

/* librknnrt BO flags (ioctl trace): data 0x403, task-array 0x40b (KERNEL_MAPPING). */
#define BO_FLAGS_DATA 0x403u
#define BO_FLAGS_TASK 0x40bu
#define MEM_SYNC_TO_DEVICE   1u
#define MEM_SYNC_FROM_DEVICE 2u

/* rknpu_task is __packed: 8 u32 then a u64 regcmd_addr (regcmd_addr at +32). */
#define TASK_STRUCT_SIZE 40
#define TASK_REGFG_OFF   24   /* regcfg_amount */
#define TASK_REGCMD_OFF  32   /* regcmd_addr (u64) */

/* regcmd address registers to remap (NOT 0x1084 — that's the -128 pad const). */
static int is_addr_reg(uint32_t reg)
{
	return reg == 0x1088 || reg == 0x1110 || reg == 0x4018 ||
	       reg == 0x5020 || reg == 0x5024;
}

#define MAXBO 8
struct bo { uint64_t vdma, vsize; uint32_t flags;     /* captured (vendor) */
	    uint32_t handle; uint64_t mdma, mobj; void *va; }; /* mine */
static struct bo bo[MAXBO];
static int nbo, task_bo = -1;

static uint64_t remap(uint64_t v)
{
	for (int i = 0; i < nbo; i++)
		if (v >= bo[i].vdma && v < bo[i].vdma + bo[i].vsize)
			return bo[i].mdma + (v - bo[i].vdma);
	return v;   /* not a BO ref (e.g. a constant) — leave it */
}

static int which_bo(uint64_t v)
{
	for (int i = 0; i < nbo; i++)
		if (v >= bo[i].vdma && v < bo[i].vdma + bo[i].vsize)
			return i;
	return -1;
}

static int open_rknpu(void)
{
	for (int i = 128; i < 136; i++) {
		char path[64], name[32] = { 0 };
		snprintf(path, sizeof(path), "/dev/dri/renderD%d", i);
		int fd = open(path, O_RDWR);
		if (fd < 0)
			continue;
		struct drm_version v = { 0 };
		v.name = name; v.name_len = sizeof(name) - 1;
		if (!ioctl(fd, DRM_IOCTL_VERSION, &v) && !strcmp(name, "rknpu")) {
			printf("== %s (rknpu DRM render) ==\n", path);
			return fd;
		}
		close(fd);
	}
	return -1;
}

static int mk_bo(int fd, int i)
{
	struct rknpu_mem_create c = { 0 };
	c.size = bo[i].vsize; c.flags = bo[i].flags;
	if (ioctl(fd, IOCTL_RKNPU_MEM_CREATE, &c)) { perror("MEM_CREATE"); return -1; }
	struct rknpu_mem_map m = { .handle = c.handle };
	if (ioctl(fd, IOCTL_RKNPU_MEM_MAP, &m)) { perror("MEM_MAP"); return -1; }
	void *v = mmap(0, bo[i].vsize, PROT_READ | PROT_WRITE, MAP_SHARED, fd, m.offset);
	if (v == MAP_FAILED) { perror("mmap"); return -1; }
	bo[i].handle = c.handle; bo[i].mdma = c.dma_addr; bo[i].mobj = c.obj_addr; bo[i].va = v;
	return 0;
}

static void sync_bo(int fd, int i, uint32_t flags)
{
	struct rknpu_mem_sync s = { .flags = flags, .obj_addr = bo[i].mobj, .size = bo[i].vsize };
	ioctl(fd, IOCTL_RKNPU_MEM_SYNC, &s);
}

static void load(const char *dir, int i)
{
	char p[256]; snprintf(p, sizeof(p), "%s/bo%02d.bin", dir, i);
	FILE *f = fopen(p, "rb");
	if (!f) { fprintf(stderr, "open %s: %s\n", p, strerror(errno)); return; }
	size_t n = fread(bo[i].va, 1, bo[i].vsize, f);
	(void)n; fclose(f);
}

int main(int argc, char **argv)
{
	const char *dir = argc > 1 ? argv[1] : ".";
	char path[256], line[256];
	uint32_t sub_flags = 0x5, sub_tnum = 0, sub_timeout = 6000;

	snprintf(path, sizeof(path), "%s/meta.txt", dir);
	FILE *m = fopen(path, "r");
	if (!m) { perror("meta.txt"); return 1; }
	while (fgets(line, sizeof(line), m)) {
		unsigned idx; unsigned long long vdma, vsize;
		char *p;
		if ((p = strstr(line, "task_number=")))
			sub_tnum = atoi(p + 12);
		if ((p = strstr(line, "flags=")) && line[0] == 'f')
			sub_flags = strtoul(p + 6, NULL, 0);
		if (sscanf(line, "bo idx=%u handle=%*u dma=0x%llx obj=0x%*x size=%llu",
			   &idx, &vdma, &vsize) == 3 && idx < MAXBO) {
			bo[idx].vdma = vdma; bo[idx].vsize = vsize;
			if (idx + 1 > (unsigned)nbo) nbo = idx + 1;
		}
		if ((p = strstr(line, "task_array_bo=")))
			task_bo = atoi(p + 14);
	}
	fclose(m);
	if (nbo < 2 || task_bo < 0) { fprintf(stderr, "bad meta (nbo=%d task_bo=%d)\n", nbo, task_bo); return 1; }
	for (int i = 0; i < nbo; i++)
		bo[i].flags = (i == task_bo) ? BO_FLAGS_TASK : BO_FLAGS_DATA;
	printf("meta: nbo=%d task_bo=%d task_number=%u flags=0x%x\n", nbo, task_bo, sub_tnum, sub_flags);

	int fd = open_rknpu();
	if (fd < 0) { fprintf(stderr, "no rknpu render node\n"); return 1; }

	for (int i = 0; i < nbo; i++) {
		if (mk_bo(fd, i)) return 1;
		load(dir, i);
		printf("  bo%d size=%llu vdma=0x%llx -> mdma=0x%llx\n", i,
		       (unsigned long long)bo[i].vsize, (unsigned long long)bo[i].vdma,
		       (unsigned long long)bo[i].mdma);
	}

	/* Patch: task array regcmd_addr (3x) + each regcmd's address registers. */
	uint8_t *ta = bo[task_bo].va;
	int out_bo = -1;
	for (uint32_t t = 0; t < sub_tnum; t++) {
		uint8_t *te = ta + t * TASK_STRUCT_SIZE;
		uint32_t regfg; uint64_t rc_v;
		memcpy(&regfg, te + TASK_REGFG_OFF, 4);
		memcpy(&rc_v, te + TASK_REGCMD_OFF, 8);
		int wb = which_bo(rc_v);             /* regcmds live in the weights BO */
		if (wb < 0) { fprintf(stderr, "task%u regcmd 0x%llx not in a BO\n", t,
				      (unsigned long long)rc_v); return 1; }
		uint64_t off = rc_v - bo[wb].vdma;
		uint64_t rc_m = bo[wb].mdma + off;
		memcpy(te + TASK_REGCMD_OFF, &rc_m, 8);   /* remap regcmd_addr */

		uint64_t *rc = (uint64_t *)(bo[wb].va + off);   /* the regcmd entries */
		for (uint32_t e = 0; e < regfg; e++) {
			uint32_t reg = rc[e] & 0xffff;
			uint32_t val = (rc[e] >> 16) & 0xffffffff;
			if (is_addr_reg(reg)) {
				uint32_t nv = (uint32_t)remap(val);
				rc[e] = (rc[e] & 0xffff00000000ffffULL) | ((uint64_t)nv << 16);
				if (reg == 0x4018) out_bo = which_bo(val);
			}
		}
	}
	if (out_bo < 0) out_bo = nbo - 1;
	printf("  patched %u tasks; output=bo%d\n", sub_tnum, out_bo);

	for (int i = 0; i < nbo; i++)
		sync_bo(fd, i, MEM_SYNC_TO_DEVICE);

	/* Use librknnrt's EXACT submit verbatim if captured (submit.bin) — the only
	 * BO reference in it is task_obj_addr (a kernel pointer), re-pointed at our
	 * task BO. This carries the fields trace.so can't see (priority, task_counter,
	 * subcore_task[]) that a hand-built submit was only guessing. */
	struct rknpu_submit s = { 0 };
	snprintf(path, sizeof(path), "%s/submit.bin", dir);
	FILE *sf = fopen(path, "rb");
	if (sf && fread(&s, 1, sizeof(s), sf) == sizeof(s)) {
		printf("  submit: verbatim from submit.bin (task_counter=%u priority=%d "
		       "subcore0={%u,%u} core_mask=%u)\n", s.task_counter, s.priority,
		       s.subcore_task[0].task_start, s.subcore_task[0].task_number, s.core_mask);
	} else {
		printf("  submit: hand-built (no submit.bin)\n");
		s.flags = sub_flags; s.timeout = sub_timeout;
		s.task_start = 0; s.task_number = sub_tnum; s.task_counter = sub_tnum;
		s.core_mask = 0; s.subcore_task[0].task_start = 0;
		s.subcore_task[0].task_number = sub_tnum;
	}
	if (sf) fclose(sf);
	s.fence_fd = -1;
	s.task_obj_addr = bo[task_bo].mobj;   /* re-point at our task BO */
	if (ioctl(fd, IOCTL_RKNPU_SUBMIT, &s)) { perror("SUBMIT"); return 1; }

	sync_bo(fd, out_bo, MEM_SYNC_FROM_DEVICE);
	uint8_t *o = bo[out_bo].va;
	int seen[256] = { 0 }, distinct = 0, nz = 0;
	for (uint64_t i = 0; i < bo[out_bo].vsize; i++) {
		if (o[i]) nz++;
		if (!seen[o[i]]) { seen[o[i]] = 1; distinct++; }
	}
	/* Persist the vendor(rknn)-computed output as the ground truth: this is the
	 * one true reference for the SAME payload's rocket replay. Pull both files
	 * and byte-compare -- non-degenerate is NOT correct; only cmp is. */
	FILE *of = fopen("/tmp/rknn_out.bin", "wb");
	if (of) { fwrite(o, 1, bo[out_bo].vsize, of); fclose(of); }
	printf("OUT bo%d: distinct=%d nonzero=%d/%llu head=%02x %02x %02x %02x -> %s\n",
	       out_bo, distinct, nz, (unsigned long long)bo[out_bo].vsize,
	       o[0], o[1], o[2], o[3],
	       distinct > 2 ? "COMPUTED (non-degenerate)" : "DEGENERATE");
	return 0;
}
