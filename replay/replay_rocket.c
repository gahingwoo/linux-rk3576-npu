// SPDX-License-Identifier: MIT
/*
 * replay_rocket.c — the decisive half of Tomeu #55. Replay librknnrt's captured
 * conv payload (the SAME bytes that compute correctly through the vendor rknn
 * UABI — see replay.c) through the mainline *rocket* UABI (/dev/accel/accel0).
 *
 *   vendor rknn replay COMPUTES  (control: captured bytes + vendor kernel = good)
 *   rocket replay COMPUTES   -> rocket kernel sound; the bug is Mesa's packing
 *   rocket replay DEGENERATE -> bug isolated to the rocket kernel driver
 *
 * The capture (vendor-capture/capture.c) gives 5 BOs over 3 tiled tasks + a task
 * array (bo00) of rknpu_task{ ... regcfg_amount@24, regcmd_addr@32 } structs.
 * Rocket doesn't take a task-array BO; each drm_rocket_task carries the regcmd's
 * DMA address + count directly. So we:
 *   - CREATE_BO the 4 data BOs (weights+regcmds / scratch / input / output); the
 *     kernel returns each one's NPU IOVA (dma_address), assigned by rocket (NOT
 *     the vendor's captured IOVAs), valid for the fd's lifetime.
 *   - parse bo00 to find each task's regcmd (offset into the weights BO) + count.
 *   - REMAP every captured IOVA the regcmd references (any 32-bit word that lands
 *     in a captured BO range) to the rocket-assigned dma_address. This is the
 *     cross-UABI step the same-IOVA vendor replay didn't need.
 *   - submit, spread one-task-per-job (matching the vendor's per-subcore split)
 *     or, with ROCKET_REPLAY_ONEJOB=1, as one job of 3 tasks.
 *
 * Build: aarch64-linux-gnu-gcc -O2 -Wall -o replay_rocket replay_rocket.c
 * Run:   replay_rocket <dir>      (dir = meta.txt + bo00.bin ..)
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
struct drm_rocket_create_bo { uint32_t size, handle; uint64_t dma_address, offset; };
struct drm_rocket_prep_bo { uint32_t handle, reserved; int64_t timeout_ns; };
struct drm_rocket_fini_bo { uint32_t handle, reserved; };
struct drm_rocket_task { uint32_t regcmd, regcmd_count; };
struct drm_rocket_job { uint64_t tasks, in_bo_handles, out_bo_handles;
	uint32_t task_count, task_struct_size, in_bo_handle_count, out_bo_handle_count; };
struct drm_rocket_submit { uint64_t jobs; uint32_t job_count, job_struct_size; uint64_t reserved; };
#define IOCTL_ROCKET_CREATE_BO _IOWR('d', DRM_COMMAND_BASE + 0x00, struct drm_rocket_create_bo)
#define IOCTL_ROCKET_SUBMIT    _IOW('d', DRM_COMMAND_BASE + 0x01, struct drm_rocket_submit)
#define IOCTL_ROCKET_PREP_BO   _IOW('d', DRM_COMMAND_BASE + 0x02, struct drm_rocket_prep_bo)
#define IOCTL_ROCKET_FINI_BO   _IOW('d', DRM_COMMAND_BASE + 0x03, struct drm_rocket_fini_bo)
struct drm_version { int v_major, v_minor, v_patch;
	size_t name_len; char *name; size_t date_len; char *date; size_t desc_len; char *desc; };
#define DRM_IOCTL_VERSION _IOWR('d', 0x00, struct drm_version)

/* rknpu_task is __packed: regcfg_amount@24, regcmd_addr (u64)@32, stride 40. */
#define TASK_STRUCT_SIZE 40
#define TASK_REGFG_OFF   24
#define TASK_REGCMD_OFF  32

#define MAXBO 8
struct bo { uint64_t vdma, vsize;             /* captured (vendor IOVA) */
	    uint32_t handle; uint64_t mdma, off; void *va; int created; }; /* mine */
static struct bo bo[MAXBO];
static int nbo, task_bo = -1;

/* Remap a captured 32-bit IOVA into the rocket-assigned address. Value-in-range
 * over every created BO — robust to address registers the whitelist might miss,
 * and safe because the captured BO IOVAs sit at the very top of the 32-bit space
 * where ordinary config words never land. */
static uint32_t remap(uint32_t v, int *hit)
{
	for (int i = 0; i < nbo; i++)
		if (bo[i].created && v >= bo[i].vdma && v < bo[i].vdma + bo[i].vsize) {
			*hit = 1;
			return (uint32_t)(bo[i].mdma + (v - bo[i].vdma));
		}
	*hit = 0;
	return v;
}

static int which_bo(uint64_t v)
{
	for (int i = 0; i < nbo; i++)
		if (v >= bo[i].vdma && v < bo[i].vdma + bo[i].vsize)
			return i;
	return -1;
}

static int open_rocket(void)
{
	for (int i = 0; i < 8; i++) {
		char path[64], name[32] = { 0 };
		snprintf(path, sizeof(path), "/dev/accel/accel%d", i);
		int fd = open(path, O_RDWR);
		if (fd < 0)
			continue;
		struct drm_version ver = { 0 };
		ver.name = name; ver.name_len = sizeof(name) - 1;
		if (!ioctl(fd, DRM_IOCTL_VERSION, &ver) && !strcmp(name, "rocket")) {
			printf("== %s (rocket accel) ==\n", path);
			return fd;
		}
		close(fd);
	}
	return -1;
}

static int mk_bo(int fd, int i)
{
	struct drm_rocket_create_bo c = { .size = (uint32_t)bo[i].vsize };
	if (ioctl(fd, IOCTL_ROCKET_CREATE_BO, &c)) { perror("CREATE_BO"); return -1; }
	void *v = mmap(0, bo[i].vsize, PROT_READ | PROT_WRITE, MAP_SHARED, fd, c.offset);
	if (v == MAP_FAILED) { perror("mmap"); return -1; }
	bo[i].handle = c.handle; bo[i].mdma = c.dma_address; bo[i].off = c.offset;
	bo[i].va = v; bo[i].created = 1;
	if (c.dma_address >> 32)
		fprintf(stderr, "WARN bo%d dma_address 0x%llx > 32 bits — regcmd field truncates\n",
			i, (unsigned long long)c.dma_address);
	return 0;
}

static void prep_bo(int fd, int i)
{
	struct drm_rocket_prep_bo p = { .handle = bo[i].handle, .timeout_ns = 2000000000LL };
	if (ioctl(fd, IOCTL_ROCKET_PREP_BO, &p)) perror("PREP_BO");
}
static void fini_bo(int fd, int i)
{
	struct drm_rocket_fini_bo f = { .handle = bo[i].handle };
	if (ioctl(fd, IOCTL_ROCKET_FINI_BO, &f)) perror("FINI_BO");
}

static void load(const char *dir, int i, void *dst)
{
	char p[256]; snprintf(p, sizeof(p), "%s/bo%02d.bin", dir, i);
	FILE *f = fopen(p, "rb");
	if (!f) { fprintf(stderr, "open %s: %s\n", p, strerror(errno)); return; }
	size_t n = fread(dst, 1, bo[i].vsize, f);
	(void)n; fclose(f);
}

int main(int argc, char **argv)
{
	const char *dir = argc > 1 ? argv[1] : ".";
	int onejob = getenv("ROCKET_REPLAY_ONEJOB") && atoi(getenv("ROCKET_REPLAY_ONEJOB"));
	char path[256], line[256];
	uint32_t sub_tnum = 0;

	snprintf(path, sizeof(path), "%s/meta.txt", dir);
	FILE *m = fopen(path, "r");
	if (!m) { perror("meta.txt"); return 1; }
	while (fgets(line, sizeof(line), m)) {
		unsigned idx; unsigned long long vdma, vsize; char *p;
		if ((p = strstr(line, "task_number=")))
			sub_tnum = atoi(p + 12);
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
	printf("meta: nbo=%d task_bo=%d task_number=%u mode=%s\n", nbo, task_bo, sub_tnum,
	       onejob ? "ONEJOB (1 job x N tasks)" : "SPREAD (N jobs x 1 task)");

	int fd = open_rocket();
	if (fd < 0) { fprintf(stderr, "no rocket accel node\n"); return 1; }

	/* The task-array BO (bo00) is parsed host-side only; rocket carries regcmd
	 * addresses in the task struct. Create every other BO on the NPU. */
	uint8_t *ta = malloc(bo[task_bo].vsize);
	load(dir, task_bo, ta);
	for (int i = 0; i < nbo; i++) {
		if (i == task_bo) continue;
		if (mk_bo(fd, i)) return 1;
		load(dir, i, bo[i].va);
		printf("  bo%d size=%llu vdma=0x%llx -> rocket dma=0x%llx\n", i,
		       (unsigned long long)bo[i].vsize, (unsigned long long)bo[i].vdma,
		       (unsigned long long)bo[i].mdma);
	}

	/* Per task: locate its regcmd in the weights BO, remap the addresses it
	 * references to rocket's IOVAs, and record the rocket task descriptor. */
	struct drm_rocket_task tasks[32] = { 0 };
	int out_bo = -1, miss = 0;
	for (uint32_t t = 0; t < sub_tnum && t < 32; t++) {
		uint8_t *te = ta + t * TASK_STRUCT_SIZE;
		uint32_t regfg; uint64_t rc_v;
		memcpy(&regfg, te + TASK_REGFG_OFF, 4);
		memcpy(&rc_v, te + TASK_REGCMD_OFF, 8);
		int wb = which_bo(rc_v);
		if (wb < 0 || !bo[wb].created) {
			fprintf(stderr, "task%u regcmd 0x%llx not in a created BO\n", t,
				(unsigned long long)rc_v); return 1; }
		uint64_t off = rc_v - bo[wb].vdma;
		uint64_t *rc = (uint64_t *)((uint8_t *)bo[wb].va + off);
		for (uint32_t e = 0; e < regfg; e++) {
			uint32_t reg = rc[e] & 0xffff;
			uint32_t val = (rc[e] >> 16) & 0xffffffff;
			int hit; uint32_t nv = remap(val, &hit);
			if (hit) {
				rc[e] = (rc[e] & 0xffff00000000ffffULL) | ((uint64_t)nv << 16);
				if (reg == 0x4018) out_bo = which_bo(val);
			} else if (val >= 0xfff00000) {
				miss++;   /* a top-of-space word we didn't remap — suspect */
				fprintf(stderr, "  task%u e%u reg=0x%04x val=0x%08x not remapped\n",
					t, e, reg, val);
			}
		}
		tasks[t].regcmd = (uint32_t)(bo[wb].mdma + off);
		tasks[t].regcmd_count = regfg;
		printf("  task%u regcmd=0x%08x count=%u (in bo%d +0x%llx)\n",
		       t, tasks[t].regcmd, tasks[t].regcmd_count, wb, (unsigned long long)off);
	}
	if (out_bo < 0) out_bo = nbo - 1;
	if (miss) fprintf(stderr, "  WARNING: %d unremapped top-of-space words\n", miss);

	/* flush every filled BO to the device */
	for (int i = 0; i < nbo; i++)
		if (bo[i].created) fini_bo(fd, i);

	/* in = every data BO EXCEPT the write targets (read/mapped); out = the write
	 * targets (bo2 intermediate pool + final output) with write-fences. A BO must
	 * not appear in both lists (that stalled the jobs -> none completed). Mapping
	 * all read BOs covers a chain's intermediates without the in==out deadlock. */
	uint32_t in_h[32]; uint32_t in_n = 0;
	for (int i = 0; i < nbo; i++)
		if (i != task_bo && i != 2 && i != out_bo && bo[i].created)
			in_h[in_n++] = bo[i].handle;
	uint32_t out_h[2] = { bo[2].handle, bo[out_bo].handle };
	uint32_t out_n = (out_bo == 2) ? 1 : 2;

	struct drm_rocket_job jobs[32] = { 0 };
	uint32_t njob;
	if (onejob) {
		jobs[0].tasks = (uint64_t)(uintptr_t)tasks;
		jobs[0].task_count = sub_tnum;
		jobs[0].task_struct_size = sizeof(struct drm_rocket_task);
		jobs[0].in_bo_handles = (uint64_t)(uintptr_t)in_h;
		jobs[0].in_bo_handle_count = in_n;
		jobs[0].out_bo_handles = (uint64_t)(uintptr_t)out_h;
		jobs[0].out_bo_handle_count = out_n;
		njob = 1;
	} else {
		for (uint32_t t = 0; t < sub_tnum; t++) {
			jobs[t].tasks = (uint64_t)(uintptr_t)&tasks[t];
			jobs[t].task_count = 1;
			jobs[t].task_struct_size = sizeof(struct drm_rocket_task);
			jobs[t].in_bo_handles = (uint64_t)(uintptr_t)in_h;
			jobs[t].in_bo_handle_count = in_n;
			jobs[t].out_bo_handles = (uint64_t)(uintptr_t)out_h;
			jobs[t].out_bo_handle_count = out_n;
		}
		njob = sub_tnum;
	}

	struct drm_rocket_submit s = { 0 };
	s.jobs = (uint64_t)(uintptr_t)jobs;
	s.job_count = njob;
	s.job_struct_size = sizeof(struct drm_rocket_job);
	printf("  submit: %u job(s), output=bo%d\n", njob, out_bo);
	if (ioctl(fd, IOCTL_ROCKET_SUBMIT, &s)) { perror("SUBMIT"); return 1; }

	/* PREP_BO waits on the output's fences + syncs cache for CPU read. The
	 * rocket submit is async, so PREP can race ahead of the scheduler and return
	 * before the job's fence exists — poll until the NPU has written something. */
	uint8_t *o = bo[out_bo].va;
	int seen[256], distinct = 0, nz = 0, tries;
	for (tries = 0; tries < 40; tries++) {
		prep_bo(fd, out_bo);
		nz = 0;
		for (uint64_t i = 0; i < bo[out_bo].vsize; i++)
			if (o[i]) { nz++; if (nz > 4) break; }
		if (nz) break;
		usleep(50000);
	}
	memset(seen, 0, sizeof(seen));
	nz = 0;
	for (uint64_t i = 0; i < bo[out_bo].vsize; i++) {
		if (o[i]) nz++;
		if (!seen[o[i]]) { seen[o[i]] = 1; distinct++; }
	}
	/* keep the bytes for an offline byte-compare against the rknn replay output */
	FILE *of = fopen("/tmp/rocket_out.bin", "wb");
	if (of) { fwrite(o, 1, bo[out_bo].vsize, of); fclose(of); }
	printf("OUT bo%d: distinct=%d nonzero=%d/%llu head=%02x %02x %02x %02x (settled in %d tries) -> %s\n",
	       out_bo, distinct, nz, (unsigned long long)bo[out_bo].vsize,
	       o[0], o[1], o[2], o[3], tries,
	       distinct > 2 ? "COMPUTED (non-degenerate)" : "DEGENERATE");

	/* CHAIN diagnostic: dump EVERY created BO's stats, so a multi-layer replay
	 * (conv0->dw1->pw1->dw2) shows each layer's output BO -- pinpointing WHERE the
	 * chain dies (esp. dw1, the layer after conv0). The intermediate BOs are the
	 * layer boundaries; a non-degenerate dw1-output BO = conv0->dw1 computed. */
	for (int i = 0; i < nbo; i++) {
		if (!bo[i].created || !bo[i].va) continue;
		prep_bo(fd, i);
		int bseen[256] = {0}, bd = 0, bnz = 0;
		uint8_t *bv = bo[i].va;
		for (uint64_t k = 0; k < bo[i].vsize; k++) {
			if (bv[k]) bnz++;
			if (!bseen[bv[k]]) { bseen[bv[k]] = 1; bd++; }
		}
		printf("  BO%d size=%-8llu distinct=%-3d nonzero=%-8d head=%02x %02x %02x %02x\n",
		       i, (unsigned long long)bo[i].vsize, bd, bnz,
		       bv[0], bv[1], bv[2], bv[3]);
	}

	/* The real verdict: byte-compare against the rknn(vendor)-computed ground
	 * truth for the SAME payload (REPLAY_REF=/path/to/rknn_out.bin). "COMPUTED"
	 * above only means non-zero -- a wrong tile offset also prints that. Only
	 * this cmp proves the rocket path (SPREAD or ONEJOB) is byte-exact. */
	const char *ref = getenv("REPLAY_REF");
	if (ref) {
		FILE *rf = fopen(ref, "rb");
		if (!rf) { printf("VERDICT: no ref (%s)\n", ref); return 0; }
		uint64_t i, diffs = 0, first = ~0ULL;
		int rb;
		for (i = 0; i < bo[out_bo].vsize && (rb = fgetc(rf)) != EOF; i++)
			if ((uint8_t)rb != o[i]) { if (first == ~0ULL) first = i; diffs++; }
		fclose(rf);
		printf("VERDICT vs %s: %s (diffs=%llu/%llu)\n",
		       ref, diffs ? "MISMATCH" : "BYTE-EXACT",
		       (unsigned long long)diffs, (unsigned long long)bo[out_bo].vsize);
		if (diffs)
			printf("  first diff @%llu: rocket=%02x\n",
			       (unsigned long long)first, o[first]);
	}
	return 0;
}
