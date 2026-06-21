/*
 * Minimal rknn runner: load a .rknn, set a zero input, run once. The point is
 * to make librknnrt submit ONE inference through the vendor rknpu driver so the
 * (patched) kernel dumps the working PC submit + regcmd sequence to dmesg.
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
    const char *model = argc > 1 ? argv[1] : "conv0_rk3576.rknn";
    int msize = 0;
    void *mdata = read_file(model, &msize);
    if (!mdata) { fprintf(stderr, "read model failed\n"); return 1; }

    rknn_context ctx = 0;
    int ret = rknn_init(&ctx, mdata, msize, 0, NULL);
    printf("rknn_init = %d\n", ret);
    if (ret < 0) return 1;

    rknn_input_output_num ion;
    rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &ion, sizeof(ion));
    printf("n_input=%u n_output=%u\n", ion.n_input, ion.n_output);

    rknn_tensor_attr ia; memset(&ia, 0, sizeof(ia)); ia.index = 0;
    rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &ia, sizeof(ia));
    printf("input size=%u\n", ia.size);

    void *inbuf = calloc(1, ia.size ? ia.size : (3 * 224 * 224));
    /*
     * Optional position-encoded input ("posenc" 2nd arg): fill NHWC input so
     * every (h,w,c) is identifiable in the staged feature BO -- value(h,w,c) =
     * 32 + c*64 + (w%16)*2 + (h%2). Channels land in clear 64-wide bands
     * (R~32 / G~96 / B~160), w steps by 2 within a band, h parity in the LSB.
     * Dumping the CNA feature BO (0x1088) then reveals the first-conv input
     * layout (channel interleave / pixel stride / padding) the same way the
     * weight capture reveals the weight layout.
     */
    /*
     * "ramp" input: fill the NHWC buffer with a flat byte ramp value(i) = i %
     * 251, byte-for-byte identical to Mesa's test_conv.py (np.arange(n) % 251),
     * so the staged input BO is directly comparable between the two stacks.
     * (posenc is for the 3-channel firstconv; with 16 channels c*64 overflows.)
     */
    if (argc > 2 && !strcmp(argv[2], "ramp")) {
        unsigned char *p = inbuf;
        unsigned sz = ia.size ? ia.size : (3 * 224 * 224);
        for (unsigned i = 0; i < sz; i++)
            p[i] = (unsigned char)(i % 251);
        printf("ramp input filled %u bytes (i %% 251)\n", sz);
    }
    if (argc > 2 && !strcmp(argv[2], "posenc") && ia.n_dims == 4) {
        unsigned H = ia.dims[1], W = ia.dims[2], C = ia.dims[3];
        unsigned char *p = inbuf;
        for (unsigned h = 0; h < H; h++)
            for (unsigned w = 0; w < W; w++)
                for (unsigned c = 0; c < C; c++)
                    p[(h * W + w) * C + c] =
                        (unsigned char)(32 + c * 64 + (w % 16) * 2 + (h % 2));
        printf("posenc input filled %ux%ux%u\n", H, W, C);
    }
    rknn_input in; memset(&in, 0, sizeof(in));
    in.index = 0;
    in.type = RKNN_TENSOR_UINT8;
    in.size = ia.size ? ia.size : (3 * 224 * 224);
    in.fmt = RKNN_TENSOR_NHWC;
    in.buf = inbuf;
    ret = rknn_inputs_set(ctx, 1, &in);
    printf("inputs_set = %d\n", ret);

    ret = rknn_run(ctx, NULL);
    printf("rknn_run = %d\n", ret);

    rknn_destroy(ctx);
    free(inbuf); free(mdata);
    printf("DONE\n");
    return 0;
}
