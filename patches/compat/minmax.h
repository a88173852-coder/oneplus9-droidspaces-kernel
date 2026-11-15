/* SPDX-License-Identifier: GPL-2.0 */
/*
 * 5.4 兼容层：linux/minmax.h 在 5.10 才从 linux/kernel.h 拆出来，
 * 上游 KernelSU / SukiSU 只针对 GKI 2.0(>=5.10)，所以直接 include 会找不到。
 * min/max/clamp/clamp_val 5.4 的 kernel.h 里已有，这里只补 5.10 新增的 min3/max3。
 */
#ifndef _LINUX_MINMAX_H
#define _LINUX_MINMAX_H

#include <linux/kernel.h>
#include <linux/limits.h>

#ifndef min3
#define min3(x, y, z) min((typeof(x))min(x, y), z)
#endif

#ifndef max3
#define max3(x, y, z) max((typeof(x))max(x, y), z)
#endif

#ifndef min_not_zero
#define min_not_zero(x, y) ({			\
	typeof(x) __x = (x);			\
	typeof(y) __y = (y);			\
	__x == 0 ? __y : ((__y == 0) ? __x : min(__x, __y)); })
#endif

#ifndef umin
#define umin(x, y) min((x), (y))
#endif

#ifndef umax
#define umax(x, y) max((x), (y))
#endif

#endif /* _LINUX_MINMAX_H */
