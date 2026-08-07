/*
 * VENDOR two-submit control. Originally 2026-07-16, CORRECTED 2026-08-06.
 *
 * The 2026-07-16 version staged the input ONCE, before the loop, and then fired
 * rknn_run() N times over it. All five runs came back byte-identical and that
 * was read as "the vendor recomputes correctly on every submit". It does not
 * show that. A buffer nothing has written since run 0 is byte-identical too,
 * and on 2026-08-06 the open stack was measured doing exactly that: with one
 * configuration and a DIFFERENT input, the second submit left the output buffer
 * untouched (crc32 unchanged) and only a reset restored computation.
 *
 * So the control has to change the input per run. Same test, one line moved,
 * and now it can fail:
 *
 *   outputs DIFFER per run  -> the vendor really does recompute warm, the
 *                              asymmetry with rocket is real
 *   outputs IDENTICAL       -> the vendor only computes once per reset as well,
 *                              the wall is normal behaviour for this block and
 *                              the question becomes what the vendor runtime
 *                              does between inferences
 *
 * The missing symmetric half of the
 * rocket SPREAD-CONFIRM test: does the VENDOR stack re-arm on the SECOND (and
 * later) INDEPENDENT submit within ONE power session (no genpd power-cycle)?
 *
 * Runs one rknn context and fires rknn_run() N times back-to-back. Each run is
 * an independent PC submit through the vendor rknpu driver. Because the context
 * stays alive across all N runs (and rknpu power_put_delay = 3000ms), all N
 * submits share ONE powered session -- exactly rocket's op0/op1/op2 situation.
 *
 * For each run we fetch the float output and print distinct/min/max + save the
 * raw bytes to <outdir>/out_runN.bin. Verdict:
 *   run0 rich  AND run1.. rich, byte-identical to run0 => vendor RE-ARMS per
 *        independent submit within a session (rocket's gap is ordering/timing).
 *   run0 rich  AND run1.. collapse to a constant (empty MAC / output zero-point)
 *        => the wall is NORMAL vendor HW behaviour too; only op0 MACs per
 *        session (hypothesis confirmed; per-op dispatch is a dead end, chain it).
 *
 * Input is the flat byte ramp value(i)=i%251 (identical to test_conv.py and the
 * original runner "ramp" mode) so the staged input is comparable across stacks.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
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

static double now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

int main(int argc, char **argv)
{
	const char *model  = argc > 1 ? argv[1] : "exp2_rk3576.rknn";
	int         nruns  = argc > 2 ? atoi(argv[2]) : 4;
	const char *outdir = argc > 3 ? argv[3] : "/tmp";
	if (nruns < 1) nruns = 1;

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
	unsigned insz = ia.size ? ia.size : (16 * 80 * 80);
	printf("input size=%u\n", insz);

	unsigned char *inbuf = malloc(insz);

	unsigned int sum0 = 0;
	int differed = 0;

	double t_prev = now_ms();
	for (int run = 0; run < nruns; run++) {
		/*
		 * A different input every run. Offsetting the ramp by run*37 keeps
		 * the data in the same range and the model out of saturation, so a
		 * correct recomputation has to produce different output bytes.
		 */
		for (unsigned i = 0; i < insz; i++)
			inbuf[i] = (unsigned char)((i + run * 37) % 251);

		rknn_input in; memset(&in, 0, sizeof(in));
		in.index = 0;
		in.type  = RKNN_TENSOR_UINT8;
		in.size  = insz;
		in.fmt   = RKNN_TENSOR_NHWC;
		in.buf   = inbuf;
		ret = rknn_inputs_set(ctx, 1, &in);

		double t0 = now_ms();
		ret = rknn_run(ctx, NULL);
		double t1 = now_ms();

		rknn_output out; memset(&out, 0, sizeof(out));
		out.index = 0; out.want_float = 1; out.is_prealloc = 0;
		int gret = rknn_outputs_get(ctx, 1, &out, NULL);

		if (gret == 0 && out.buf && out.size >= sizeof(float)) {
			const float *f = (const float *)out.buf;
			unsigned n = out.size / sizeof(float);
			float mn = f[0], mx = f[0];
			int constant = 1;
			for (unsigned i = 1; i < n; i++) {
				if (f[i] < mn) mn = f[i];
				if (f[i] > mx) mx = f[i];
				if (f[i] != f[0]) constant = 0;
			}
			unsigned int sum = 2166136261u;
			for (unsigned i = 0; i < out.size; i++)
				sum = (sum ^ ((const unsigned char *)out.buf)[i]) * 16777619u;
			if (run == 0)
				sum0 = sum;

			char path[512];
			snprintf(path, sizeof(path), "%s/out_run%d.bin", outdir, run);
			FILE *of = fopen(path, "wb");
			if (of) { fwrite(out.buf, 1, out.size, of); fclose(of); }

			printf("RUN %d rknn_run=%d run_ms=%.1f gap_since_prev_ms=%.1f "
			       "out_bytes=%u nfloat=%u min=%.4g max=%.4g fnv=%08x %s %s\n",
			       run, ret, t1 - t0, t0 - t_prev, out.size, n, mn, mx, sum,
			       constant ? "CONSTANT" : "RICH",
			       run == 0 ? "(baseline)" :
			       (sum == sum0 ? "SAME-AS-RUN0(did not recompute)"
					    : "DIFFERS(recomputed)"));
			if (run > 0 && sum != sum0)
				differed++;
		} else {
			printf("RUN %d rknn_run=%d outputs_get=%d (no output)\n",
			       run, ret, gret);
		}
		rknn_outputs_release(ctx, 1, &out);
		t_prev = t0;
	}

	rknn_destroy(ctx);
	free(inbuf); free(mdata);
	printf("DONE nruns=%d runs_that_differed_from_run0=%d\n", nruns, differed);
	if (nruns > 1) {
		if (differed == nruns - 1)
			printf("VERDICT: vendor RECOMPUTES on every warm submit. The "
			       "asymmetry with rocket is real.\n");
		else if (differed == 0)
			printf("VERDICT: vendor output never changed despite a different "
			       "input every run. It does NOT recompute warm either, so the "
			       "wall is normal behaviour for this block.\n");
		else
			printf("VERDICT: mixed (%d of %d differed). Read the per-run lines.\n",
			       differed, nruns - 1);
	}
	return 0;
}
