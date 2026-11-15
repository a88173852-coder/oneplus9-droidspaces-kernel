/* SPDX-License-Identifier: GPL-2.0 */
/*
 * 5.4 兼容层：linux/hex.h 在 5.18 才从 linux/kernel.h 拆出来。
 * 5.4 的 kernel.h 已经声明了 hex_to_bin / hex2bin / bin2hex / print_hex_dump，
 * 这里只做转发。KSU 里只有 manager/apk_sign.c 的 bin2hex() 用到。
 */
#ifndef _LINUX_HEX_H
#define _LINUX_HEX_H

#include <linux/kernel.h>
#include <linux/types.h>

#endif /* _LINUX_HEX_H */
