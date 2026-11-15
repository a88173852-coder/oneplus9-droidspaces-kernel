#!/usr/bin/env python3
"""抹掉 /proc/sys/kernel/tainted 里的「自编译痕迹」三位。

## 为什么

原厂机器 `/proc/sys/kernel/tainted` 是 0。我们这棵树编出来的内核实测是 **4612**：

    4612 = 0x1204 = bit12(TAINT_OOT_MODULE) | bit9(TAINT_WARN) | bit2(TAINT_UNSAFE_SMP)

- **O (bit12)**：厂商 dlkm（wlan/camera/…）是相对「本次构建」的 out-of-tree 模块，
  每次 modprobe 都会打上，dmesg 里能看到 `rmnet_ctl: loading out-of-tree module taints kernel`；
- **W (bit9)**：开机过程中某个驱动 WARN 过一次（WARN 本身抹不掉，但 taint 位可以不打）；
- **S (bit2)**：本树 SMP 相关的一次 taint。

这三位都不影响任何功能，只是诊断标记；检测软件（春秋的 Tampered kernel 项）直接读
`/proc/sys/kernel/tainted`，非 0 就等于「你自己编的内核」。所以在 `add_taint()` 入口
把这三位吃掉 —— 其余 taint 位（真正的 panic/oops/lockdep）照常打，不影响排障。

用法: python3 patches/compat/patch_taint.py <path/to/kernel/panic.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

MARK = "伪装原厂"

ANCHOR = "void add_taint(unsigned flag, enum lockdep_ok lockdep_ok)\n{\n"

BODY = """	/*
	 * 伪装原厂：本树编出来的内核加载的是厂商 dlkm（相对本次构建属 out-of-tree），
	 * 开机必打 O；再叠加某个驱动 WARN 的 W 和 SMP 的 S，/proc/sys/kernel/tainted
	 * 就成了 4612，而原厂是 0 —— 检测软件（春秋 Tampered kernel）直接读这个值。
	 * 这三位的语义纯粹是诊断标记，吃掉不影响任何功能；其余 taint 位照常。
	 */
	if (flag == TAINT_OOT_MODULE || flag == TAINT_WARN || flag == TAINT_UNSAFE_SMP)
		return;
"""

if MARK in src:
    print("taint 补丁已存在，跳过")
    sys.exit(0)

if ANCHOR not in src:
    sys.exit("锚点没找到：panic.c 里没有 add_taint(unsigned flag, enum lockdep_ok) 的定义")

src = src.replace(ANCHOR, ANCHOR + BODY, 1)
open(PATH, "w").write(src)
print("taint 补丁注入成功（TAINT_OOT_MODULE / TAINT_WARN / TAINT_UNSAFE_SMP 不再置位）")
