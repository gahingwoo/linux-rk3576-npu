// SPDX-License-Identifier: MIT
/*
 * LD_PRELOAD ioctl tracer for librknnrt: log the full sequence of rknpu DRM
 * ioctls (ACTION / MEM_CREATE / MEM_MAP / MEM_SYNC / SUBMIT) the vendor runtime
 * issues, so the replay can replicate any init-time setup (e.g. a RESET action)
 * that a raw payload submit alone misses.
 *
 * Build: aarch64-linux-gnu-gcc -shared -fPIC -o trace.so trace.c -ldl
 * Use:   LD_PRELOAD=/opt/npu-cap/trace.so runner model.rknn ramp
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <dlfcn.h>
#include <sys/ioctl.h>

static int (*real_ioctl)(int, unsigned long, void *);

struct act { uint32_t flags, value; };
struct sub { uint32_t flags, timeout, task_start, task_number, task_counter;
	int32_t priority; uint64_t task_obj_addr; uint32_t iommu_domain_id, rsvd;
	uint64_t task_base_addr; int64_t hw_elapse; uint32_t core_mask; int32_t fence_fd; };
struct mc { uint32_t handle, flags; uint64_t size, obj_addr, dma_addr; };

int ioctl(int fd, unsigned long req, ...)
{
	va_list ap; va_start(ap, req);
	void *arg = va_arg(ap, void *); va_end(ap);
	if (!real_ioctl)
		real_ioctl = dlsym(RTLD_NEXT, "ioctl");

	unsigned nr = _IOC_NR(req), type = _IOC_TYPE(req);
	if (type == 'd' && nr >= 0x40 && nr <= 0x4f) {
		int op = nr - 0x40;
		if (op == 0 && arg) {
			struct act *a = arg;
			fprintf(stderr, "TRACE ACTION flags=%u value=%u\n",
				a->flags, a->value);
		} else if (op == 1 && arg) {
			struct sub *s = arg;
			fprintf(stderr,
				"TRACE SUBMIT flags=0x%x timeout=%u t_start=%u t_num=%u core=%u obj=0x%llx base=0x%llx dom=%u fence=%d\n",
				s->flags, s->timeout, s->task_start, s->task_number,
				s->core_mask, (unsigned long long)s->task_obj_addr,
				(unsigned long long)s->task_base_addr,
				s->iommu_domain_id, s->fence_fd);
		} else if (op == 2 && arg) {
			struct mc *c = arg;
			int r = real_ioctl(fd, req, arg);
			fprintf(stderr,
				"TRACE MEM_CREATE size=%llu flags=0x%x -> handle=%u dma=0x%llx\n",
				(unsigned long long)c->size, c->flags, c->handle,
				(unsigned long long)c->dma_addr);
			return r;
		} else {
			static const char *n[] = { "ACTION", "SUBMIT", "MEM_CREATE",
				"MEM_MAP", "MEM_DESTROY", "MEM_SYNC" };
			fprintf(stderr, "TRACE %s\n",
				op < 6 ? n[op] : "DRM?");
		}
	}
	return real_ioctl(fd, req, arg);
}
