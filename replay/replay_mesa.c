// SPDX-License-Identifier: MIT
/*
 * replay_mesa.c — reproduce Mesa's DEGENERATE conv2d in a fully controllable
 * harness, so the vendor↔mesa difference can be BISECTED instead of guessed.
 *
 * Feeds Mesa's own dumped conv2d payload (mesa-regcmd/weights/biases-000-000.bin,
 * 1 self-contained task) back through the rocket UABI: create BOs, fill them,
 * re-point the regcmd's address registers, submit one task. Expected: distinct=2
 * (Mesa's degeneracy reproduced). Then bisect with env knobs that swap one
 * component for the vendor's (which computes via replay_rocket):
 *   MESA_WT=<file>     override weights with vendor's 51200-byte blob
 *   MESA_REQUANT=1     patch the regcmd's OUT_CVT (0x40ac/40b0/40b4) to vendor's
 *   MESA_CBUF=1        patch the regcmd's CBUF 0x1040 to the vendor's 0x10000000
 * Whichever swap flips distinct=2 -> non-degenerate is the cause.
 *
 * Build: aarch64-linux-gnu-gcc -O2 -Wall -static -o replay_mesa replay_mesa.c
 * Run:   replay_mesa <dir-with-mesa-*.bin>
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

/* conv2d.tflite sizes: in 1x80x80x16, out 1x40x40x128, weights 16->128 5x5 */
#define IN_SZ   (80*80*16)
#define OUT_SZ  (40*40*128)
#define WT_SZ   204800   /* mesa over-allocates; regcmd reads 51200 */
#define BIAS_SZ 20800    /* spans the vendor requant region bo1[51200:72000]:
                          * 0x5020 buf @+0 (A/B/C), 0x5024 buf @+0x400 (float wt) */

enum { B_RC, B_WT, B_BIAS, B_IN, B_OUT, NBO };
static const unsigned bo_sz[NBO] = { 0, WT_SZ, BIAS_SZ, IN_SZ, OUT_SZ };
struct bo { uint32_t handle, size; uint64_t mdma; void *va; } bo[NBO];
static int fd;

static int open_rocket(void)
{
	for (int i = 0; i < 8; i++) {
		char p[64], n[32] = { 0 };
		snprintf(p, sizeof(p), "/dev/accel/accel%d", i);
		int f = open(p, O_RDWR);
		if (f < 0) continue;
		struct drm_version v = { 0 }; v.name = n; v.name_len = 31;
		if (!ioctl(f, DRM_IOCTL_VERSION, &v) && !strcmp(n, "rocket")) {
			printf("== %s ==\n", p); return f;
		}
		close(f);
	}
	return -1;
}
static int mk(int i, uint32_t size)
{
	struct drm_rocket_create_bo c = { .size = size };
	if (ioctl(fd, IOCTL_ROCKET_CREATE_BO, &c)) { perror("CREATE_BO"); return -1; }
	void *v = mmap(0, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, c.offset);
	if (v == MAP_FAILED) { perror("mmap"); return -1; }
	bo[i].handle = c.handle; bo[i].size = size; bo[i].mdma = c.dma_address; bo[i].va = v;
	return 0;
}
static void fini(int i){ struct drm_rocket_fini_bo f={.handle=bo[i].handle}; ioctl(fd,IOCTL_ROCKET_FINI_BO,&f); }
static void prep(int i){ struct drm_rocket_prep_bo p={.handle=bo[i].handle,.timeout_ns=2000000000LL}; ioctl(fd,IOCTL_ROCKET_PREP_BO,&p); }
static long rdfile(const char *p, void *dst, long max)
{
	FILE *f = fopen(p, "rb"); if (!f) { fprintf(stderr, "open %s: %s\n", p, strerror(errno)); return -1; }
	long n = fread(dst, 1, max, f); fclose(f); return n;
}

int main(int argc, char **argv)
{
	const char *dir = argc > 1 ? argv[1] : ".";
	char p[256];

	fd = open_rocket();
	if (fd < 0) { fprintf(stderr, "no rocket node\n"); return 1; }

	/* read mesa's regcmd to size BO_RC + know the entry count */
	static uint8_t rc[8192];
	snprintf(p, sizeof(p), "%s/mesa-regcmd-000-000.bin", dir);
	long rcn = rdfile(p, rc, sizeof(rc));
	if (rcn <= 0) return 1;
	unsigned n_entries = rcn / 8;

	for (int i = 0; i < NBO; i++) {
		uint32_t sz = i == B_RC ? (uint32_t)rcn : bo_sz[i];
		if (mk(i, sz)) return 1;
		memset(bo[i].va, 0, sz);
	}
	memcpy(bo[B_RC].va, rc, rcn);
	/* weights: vendor override (MESA_WT) or mesa's own */
	const char *wtov = getenv("MESA_WT");
	if (wtov) { printf("  WT override: %s\n", wtov); rdfile(wtov, bo[B_WT].va, WT_SZ); }
	else { snprintf(p, sizeof(p), "%s/mesa-weights-000-000.bin", dir); rdfile(p, bo[B_WT].va, WT_SZ); }
	/* bias/requant: vendor override (MESA_BIAS = bo1[51200:72000]) or mesa's own */
	const char *biov = getenv("MESA_BIAS");
	if (biov) { printf("  BIAS override: %s\n", biov); rdfile(biov, bo[B_BIAS].va, BIAS_SZ); }
	else { snprintf(p, sizeof(p), "%s/mesa-biases-000-000.bin", dir); rdfile(p, bo[B_BIAS].va, BIAS_SZ); }
	/* input ramp (matches the vendor capture: 0x80,0x81,..) */
	for (int i = 0; i < IN_SZ; i++) ((uint8_t *)bo[B_IN].va)[i] = 0x80 + (i & 0x7f);

	/* patch the regcmd: re-point address registers + optional vendor swaps */
	int reqsw = getenv("MESA_REQUANT") && atoi(getenv("MESA_REQUANT"));
	int cbufsw = getenv("MESA_CBUF") && atoi(getenv("MESA_CBUF"));
	uint64_t *e = (uint64_t *)bo[B_RC].va;
	for (unsigned k = 0; k < n_entries; k++) {
		uint32_t reg = e[k] & 0xffff, val = (e[k] >> 16) & 0xffffffff, nv = val;
		switch (reg) {
		case 0x1088: nv = (uint32_t)bo[B_IN].mdma; break;          /* input */
		case 0x1110: nv = (uint32_t)bo[B_WT].mdma; break;          /* weights */
		case 0x4018: nv = (uint32_t)bo[B_OUT].mdma; break;         /* output */
		case 0x5020: nv = (uint32_t)bo[B_BIAS].mdma; break;        /* bias */
		case 0x5024: nv = (uint32_t)(bo[B_BIAS].mdma + 0x400); break;
		case 0x1040: if (cbufsw) { nv = 0x10000000; printf("  CBUF->0x10000000\n"); } break;
		case 0x40ac: if (reqsw) nv = 9; break;                     /* vendor OUT_CVT */
		case 0x40b0: if (reqsw) nv = 23896; break;
		case 0x40b4: if (reqsw) { nv = 26; printf("  REQUANT->vendor (shift26)\n"); } break;
		/* MESA_REGFIX: patch the only non-matching CNA regs to the vendor's,
		 * the suspects for why mesa's geometry doesn't latch (DS0=0). */
		case 0x1018: if (getenv("MESA_REGFIX")) nv = 0x40000404; break;
		case 0x1024: if (getenv("MESA_REGFIX")) nv = 0x0404007f; break;
		/* MESA_DMACON2: the ONE config reg the FULL-REGCMD test never patched.
		 * DMA_CON2 (0x1080) SURF_STRIDE: mesa 0x00000101 vs vendor 0x02020101.
		 * If patching this clears the saturation, the residual is the surface
		 * stride (a real mesa fix); if not, the residual is the submit structure. */
		case 0x1080: if (getenv("MESA_DMACON2")) { nv = 0x02020101; printf("  DMA_CON2->0x02020101\n"); } break;
		}
		if (nv != val) e[k] = (e[k] & 0xffff00000000ffffULL) | ((uint64_t)nv << 16);
	}
	/* MESA_STRIPOPEN: REMOVE the in-stream broadcast op_en (tgt 0x81 reg 0x08) —
	 * compact it out + shrink the count, the way the vendor regcmd has none and
	 * relies on the kernel's PC_OP_EN pulse to engage. (Zeroing it in place makes
	 * a tgt=0/reg=0 entry the PC chokes on → hang; must actually drop it.) */
	if (getenv("MESA_STRIPOPEN") || getenv("MESA_STRIPPAD")) {
		int sop = getenv("MESA_STRIPOPEN") != NULL, spad = getenv("MESA_STRIPPAD") != NULL;
		unsigned w = 0, nop = 0, npad = 0;
		for (unsigned k = 0; k < n_entries; k++) {
			uint32_t reg = e[k] & 0xffff, tgt = (e[k] >> 48) & 0xffff;
			if (sop && reg == 0x0008 && tgt == 0x81) { nop++; continue; }
			if (spad && tgt == 0 && reg == 0) { npad++; continue; }  /* (0,0,0) tail pad */
			e[w++] = e[k];
		}
		n_entries = w;
		printf("  cleaned tail: removed %u op_en + %u pad -> %u entries\n", nop, npad, n_entries);
	}

	for (int i = 0; i < NBO; i++) fini(i);

	struct drm_rocket_task task = { .regcmd = (uint32_t)bo[B_RC].mdma, .regcmd_count = n_entries };
	uint32_t in_h[2] = { bo[B_WT].handle, bo[B_IN].handle };
	uint32_t out_h[2] = { bo[B_OUT].handle, bo[B_BIAS].handle };
	struct drm_rocket_job job = { .tasks = (uint64_t)(uintptr_t)&task, .task_count = 1,
		.task_struct_size = sizeof(task), .in_bo_handles = (uint64_t)(uintptr_t)in_h,
		.in_bo_handle_count = 2, .out_bo_handles = (uint64_t)(uintptr_t)out_h, .out_bo_handle_count = 2 };
	struct drm_rocket_submit s = { .jobs = (uint64_t)(uintptr_t)&job, .job_count = 1,
		.job_struct_size = sizeof(job) };
	printf("  submit: 1 task, %u regcmd entries, wt=%s requant=%s cbuf=%s\n",
	       n_entries, wtov ? "vendor" : "mesa", reqsw ? "vendor" : "mesa", cbufsw ? "vendor" : "mesa");
	if (ioctl(fd, IOCTL_ROCKET_SUBMIT, &s)) { perror("SUBMIT"); return 1; }

	uint8_t *o = bo[B_OUT].va; int seen[256] = { 0 }, distinct = 0, nz = 0, tries;
	for (tries = 0; tries < 40; tries++) {
		prep(B_OUT); nz = 0;
		for (int i = 0; i < OUT_SZ; i++) if (o[i]) { nz++; if (nz > 4) break; }
		if (nz) break; usleep(50000);
	}
	memset(seen, 0, sizeof(seen)); nz = 0;
	for (int i = 0; i < OUT_SZ; i++) { if (o[i]) nz++; if (!seen[o[i]]) { seen[o[i]] = 1; distinct++; } }
	printf("OUT: distinct=%d nonzero=%d/%d head=%02x %02x %02x %02x -> %s\n",
	       distinct, nz, OUT_SZ, o[0], o[1], o[2], o[3],
	       distinct > 2 ? "COMPUTED" : "DEGENERATE (reproduced mesa)");
	return 0;
}
