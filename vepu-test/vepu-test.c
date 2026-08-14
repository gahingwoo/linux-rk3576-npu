// SPDX-License-Identifier: MIT
/*
 * vepu-test.c — minimal V4L2 mem2mem smoke test for the VEPU510 H.264 encoder
 * driver (rockchip-vepu510.ko). No v4l2-ctl/ffmpeg/gstreamer on this rootfs,
 * so this talks to /dev/videoN directly via ioctl(), mirroring the same
 * "small standalone cross-compiled probe tool" style as replay/replay_rocket.c.
 *
 * Encodes N synthetic NV12 frames (default 10, a horizontal luma gradient
 * that shifts a little each frame, flat 128 chroma) and dumps the resulting
 * Annex-B bitstream as one playable file. With the default GOP size (30),
 * frame 0 is the IDR/SPS-PPS path and frames 1..N-1 exercise the P-frame /
 * FBC reference-buffer read path -- the least-verified part of the driver
 * until this multi-frame mode existed (see the driver README's bring-up
 * checklist).
 *
 * Usage: vepu-test [/dev/video0] [width] [height] [out.h264] [num_frames]
 */

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <linux/videodev2.h>

#define CHECK(cond, msg) do { if (!(cond)) { perror(msg); exit(1); } } while (0)

static int xioctl(int fd, unsigned long req, void *arg)
{
	int ret;

	do {
		ret = ioctl(fd, req, arg);
	} while (ret == -1 && errno == EINTR);

	return ret;
}

static void fill_nv12_gradient(unsigned char *buf, unsigned int width,
			       unsigned int height, unsigned int shift)
{
	unsigned int x, y;
	unsigned char *y_plane = buf;
	unsigned char *uv_plane = buf + (size_t)width * height;

	for (y = 0; y < height; y++)
		for (x = 0; x < width; x++)
			y_plane[y * width + x] =
				(unsigned char)(((x + shift) % width) * 255 / (width - 1));

	memset(uv_plane, 128, (size_t)width * height / 2);
}

int main(int argc, char **argv)
{
	const char *dev = argc > 1 ? argv[1] : "/dev/video0";
	unsigned int width = argc > 2 ? (unsigned int)atoi(argv[2]) : 176;
	unsigned int height = argc > 3 ? (unsigned int)atoi(argv[3]) : 144;
	const char *outpath = argc > 4 ? argv[4] : "/opt/npu-test/vepu-out.h264";
	unsigned int num_frames = argc > 5 ? (unsigned int)atoi(argv[5]) : 10;

	struct v4l2_capability cap = {0};
	struct v4l2_format fmt = {0};
	struct v4l2_requestbuffers reqbuf = {0};
	struct v4l2_buffer buf = {0};
	int fd, i;
	void *out_map, *cap_map;
	size_t out_len, cap_len;
	FILE *out;
	unsigned int frame, errors = 0;

	fd = open(dev, O_RDWR);
	CHECK(fd >= 0, "open");

	CHECK(xioctl(fd, VIDIOC_QUERYCAP, &cap) == 0, "VIDIOC_QUERYCAP");
	printf("driver=%s card=%s\n", cap.driver, cap.card);

	/* OUTPUT: raw NV12 source frame */
	fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12;
	fmt.fmt.pix.width = width;
	fmt.fmt.pix.height = height;
	CHECK(xioctl(fd, VIDIOC_S_FMT, &fmt) == 0, "VIDIOC_S_FMT(OUTPUT)");
	width = fmt.fmt.pix.width;
	height = fmt.fmt.pix.height;
	printf("OUTPUT: %ux%u sizeimage=%u\n", width, height, fmt.fmt.pix.sizeimage);
	out_len = fmt.fmt.pix.sizeimage;

	/* CAPTURE: H.264 Annex-B bitstream */
	memset(&fmt, 0, sizeof(fmt));
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_H264;
	fmt.fmt.pix.width = width;
	fmt.fmt.pix.height = height;
	CHECK(xioctl(fd, VIDIOC_S_FMT, &fmt) == 0, "VIDIOC_S_FMT(CAPTURE)");
	printf("CAPTURE: %ux%u sizeimage=%u\n", fmt.fmt.pix.width, fmt.fmt.pix.height,
	       fmt.fmt.pix.sizeimage);
	cap_len = fmt.fmt.pix.sizeimage;

	/* OUTPUT queue: one buffer, reused/re-queued every frame */
	reqbuf.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	reqbuf.memory = V4L2_MEMORY_MMAP;
	reqbuf.count = 1;
	CHECK(xioctl(fd, VIDIOC_REQBUFS, &reqbuf) == 0, "VIDIOC_REQBUFS(OUTPUT)");

	memset(&buf, 0, sizeof(buf));
	buf.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	buf.memory = V4L2_MEMORY_MMAP;
	buf.index = 0;
	CHECK(xioctl(fd, VIDIOC_QUERYBUF, &buf) == 0, "VIDIOC_QUERYBUF(OUTPUT)");
	out_map = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
		      buf.m.offset);
	CHECK(out_map != MAP_FAILED, "mmap(OUTPUT)");

	/* CAPTURE queue: one buffer, reused/re-queued every frame */
	memset(&reqbuf, 0, sizeof(reqbuf));
	reqbuf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	reqbuf.memory = V4L2_MEMORY_MMAP;
	reqbuf.count = 1;
	CHECK(xioctl(fd, VIDIOC_REQBUFS, &reqbuf) == 0, "VIDIOC_REQBUFS(CAPTURE)");

	memset(&buf, 0, sizeof(buf));
	buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	buf.memory = V4L2_MEMORY_MMAP;
	buf.index = 0;
	CHECK(xioctl(fd, VIDIOC_QUERYBUF, &buf) == 0, "VIDIOC_QUERYBUF(CAPTURE)");
	cap_map = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
		      buf.m.offset);
	CHECK(cap_map != MAP_FAILED, "mmap(CAPTURE)");

	out = fopen(outpath, "wb");
	CHECK(out != NULL, "fopen(outpath)");

	i = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	CHECK(xioctl(fd, VIDIOC_STREAMON, &i) == 0, "VIDIOC_STREAMON(OUTPUT)");
	i = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	CHECK(xioctl(fd, VIDIOC_STREAMON, &i) == 0, "VIDIOC_STREAMON(CAPTURE)");

	for (frame = 0; frame < num_frames; frame++) {
		bool is_error, is_key;

		fill_nv12_gradient(out_map, width, height, frame * 8);

		memset(&buf, 0, sizeof(buf));
		buf.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
		buf.memory = V4L2_MEMORY_MMAP;
		buf.index = 0;
		buf.bytesused = out_len;
		CHECK(xioctl(fd, VIDIOC_QBUF, &buf) == 0, "VIDIOC_QBUF(OUTPUT)");

		memset(&buf, 0, sizeof(buf));
		buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		buf.memory = V4L2_MEMORY_MMAP;
		buf.index = 0;
		CHECK(xioctl(fd, VIDIOC_QBUF, &buf) == 0, "VIDIOC_QBUF(CAPTURE)");

		/* Blocks until the hardware (or the watchdog, on error) finishes. */
		memset(&buf, 0, sizeof(buf));
		buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
		buf.memory = V4L2_MEMORY_MMAP;
		CHECK(xioctl(fd, VIDIOC_DQBUF, &buf) == 0, "VIDIOC_DQBUF(CAPTURE)");

		is_error = !!(buf.flags & V4L2_BUF_FLAG_ERROR);
		is_key = !!(buf.flags & V4L2_BUF_FLAG_KEYFRAME);
		printf("frame %2u: bytesused=%u flags=0x%x%s%s\n", frame, buf.bytesused,
		       buf.flags, is_key ? " KEY" : " P", is_error ? " *** ERROR ***" : "");
		if (is_error || buf.bytesused == 0)
			errors++;

		fwrite(cap_map, 1, buf.bytesused, out);

		memset(&buf, 0, sizeof(buf));
		buf.type = V4L2_BUF_TYPE_VIDEO_OUTPUT;
		buf.memory = V4L2_MEMORY_MMAP;
		CHECK(xioctl(fd, VIDIOC_DQBUF, &buf) == 0, "VIDIOC_DQBUF(OUTPUT)");
	}

	fclose(out);
	printf("wrote %u frame(s) to %s (%u error%s)\n", num_frames, outpath,
	       errors, errors == 1 ? "" : "s");

	i = V4L2_BUF_TYPE_VIDEO_OUTPUT;
	xioctl(fd, VIDIOC_STREAMOFF, &i);
	i = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	xioctl(fd, VIDIOC_STREAMOFF, &i);

	munmap(out_map, out_len);
	munmap(cap_map, cap_len);
	close(fd);

	return errors ? 1 : 0;
}
