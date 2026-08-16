/*
 * Copyright (c) 2026 Jiaxing Hu <gahing@gahingwoo.com>
 * SPDX-License-Identifier: GPL-2.0
 *
 * Run one .rknn on the vendor stack and REPORT ITS OUTPUT, which runner.c never
 * did because it existed to be LD_PRELOADed rather than read.
 *
 * The question it exists for. On the open driver every convolution whose output
 * range is symmetric loses its whole negative half: the surface equals
 * max(cpu, out_zp) to within one, exactly, and nothing below the zero point is
 * ever produced. The register stream has been excluded as the cause, being the
 * same register set as the vendor's in all four units and the same values for
 * the same model apart from addresses, the model's own requant, and its own
 * padding. The coefficient records were excluded too, a_relu and a_lin sharing
 * a seed and having identical A, B and C.
 *
 * So the remaining question is whether this hardware can put a value below its
 * output zero point AT ALL. geom/a_lin is the vendor's own compile of a linear
 * convolution whose out_zp is 145, and its quantiser chose that zero point from
 * calibration, which it would not have done for a non negative range. If the
 * vendor's own runtime produces values below 145 here, the hardware can and the
 * open driver is missing something. If its minimum sits exactly at 145, the
 * clamp is the hardware and the open driver is not at fault.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rknn_api.h"

static void *read_file(const char *path, int *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror("fopen"); return NULL; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    void *buf = malloc(n);
    if (fread(buf, 1, n, f) != (size_t)n) { free(buf); fclose(f); return NULL; }
    fclose(f); *size = (int)n; return buf;
}

int main(int argc, char **argv)
{
    const char *model = argc > 1 ? argv[1] : "a_lin_rk3576.rknn";
    int msize = 0;
    void *mdata = read_file(model, &msize);
    if (!mdata) { fprintf(stderr, "read model failed\n"); return 1; }

    rknn_context ctx = 0;
    int ret = rknn_init(&ctx, mdata, msize, 0, NULL);
    printf("%s rknn_init = %d\n", model, ret);
    if (ret != 0) return 1;

    rknn_input_output_num ion;
    rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &ion, sizeof(ion));

    rknn_tensor_attr ia; memset(&ia, 0, sizeof(ia)); ia.index = 0;
    rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &ia, sizeof(ia));
    rknn_tensor_attr oa; memset(&oa, 0, sizeof(oa)); oa.index = 0;
    rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &oa, sizeof(oa));

    printf("  in size=%u   out size=%u  out_zp=%d  out_scale=%.8f  out_type=%d\n",
           ia.size, oa.size, oa.zp, oa.scale, (int)oa.type);

    /* The same ramp every other tool here feeds, so two stacks are comparable. */
    unsigned char *inbuf = malloc(ia.size);
    for (unsigned i = 0; i < ia.size; i++)
        inbuf[i] = (unsigned char)(i % 251);

    rknn_input in; memset(&in, 0, sizeof(in));
    in.index = 0; in.type = RKNN_TENSOR_UINT8; in.size = ia.size;
    in.fmt = ia.fmt; in.buf = inbuf; in.pass_through = 0;
    ret = rknn_inputs_set(ctx, 1, &in);
    printf("  inputs_set = %d\n", ret);

    ret = rknn_run(ctx, NULL);
    printf("  rknn_run = %d\n", ret);

    rknn_output out; memset(&out, 0, sizeof(out));
    out.index = 0; out.want_float = 0; out.is_prealloc = 0;
    ret = rknn_outputs_get(ctx, 1, &out, NULL);
    printf("  outputs_get = %d  bytes=%u\n", ret, out.size);
    if (ret != 0) return 1;

    const unsigned char *o = out.buf;
    unsigned n = out.size;
    unsigned hist[256]; memset(hist, 0, sizeof(hist));
    for (unsigned i = 0; i < n; i++)
        hist[o[i]]++;

    int lo = -1, hi = -1, distinct = 0;
    for (int v = 0; v < 256; v++) {
        if (!hist[v]) continue;
        distinct++;
        if (lo < 0) lo = v;
        hi = v;
    }
    unsigned below = 0, at = 0;
    for (int v = 0; v < oa.zp && v < 256; v++)
        below += hist[v];
    if (oa.zp >= 0 && oa.zp < 256)
        at = hist[oa.zp];

    printf("  OUT min=%d max=%d distinct=%d of %u values\n", lo, hi, distinct, n);
    printf("  BELOW out_zp(%d): %u values (%.2f%%)   AT out_zp exactly: %u\n",
           oa.zp, below, n ? 100.0 * below / n : 0.0, at);
    printf("  VERDICT %s\n", below > 0
           ? "the hardware CAN produce a value below its output zero point"
           : "NOTHING below the output zero point, the minimum is the clamp");
    printf("  first 24: ");
    for (unsigned i = 0; i < 24 && i < n; i++) printf("%d ", o[i]);
    printf("\n");

    rknn_outputs_release(ctx, 1, &out);
    rknn_destroy(ctx);
    free(inbuf); free(mdata);
    printf("  DONE\n\n");
    return 0;
}
