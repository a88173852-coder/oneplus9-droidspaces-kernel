#!/usr/bin/env python3
"""把 /proc/version 里的编译器串钉成原厂那一串。

## 为什么

`/proc/version` 由 linux_banner 拼出来：

    "Linux version " UTS_RELEASE " (" LINUX_COMPILE_BY "@" LINUX_COMPILE_HOST
    ") (" LINUX_COMPILER ") " UTS_VERSION

- UTS_RELEASE / UTS_VERSION / LINUX_COMPILE_BY / HOST 都能用 KBUILD_BUILD_*
  和 CONFIG_LOCALVERSION 控制（workflow 里已经这么干了）；
- **LINUX_COMPILER 不受任何 KBUILD_* 影响**，它由 scripts/mkcompile_h 现场跑
  `$CC -v` 取出来，里面还带着 LLD 的临时目录 /buildbot/tmp/tmpXXXXXX。

实测差异（同一台机器，原厂 vs 我们编的）：

  原厂: Android (6877366 based on r383902b1) clang version 11.0.2 (https://...b397f810...), LLD 11.0.2 (https://...b397f810...)
  我们: Android (6573524 based on r383902b)  clang version 11.0.2 (https://...b397f810...), LLD 11.0.2 (/buildbot/tmp/tmpF3FjA8 ...)

括号里那串 buildbot 临时目录每次编译都不一样 —— 就算用同一个 clang 快照也对不上，
所以只能写死成原厂串。写死的是**纯字符串**，不影响任何代码生成。

原厂串取自 boot_a 分区（LE2110_14.0.0.1901 原厂 boot.img）:
    grep -a -o 'Linux version 5.4.254[^"]*' /dev/block/sde16

用法: python3 patches/compat/patch_mkcompile_h.py <path/to/scripts/mkcompile_h>
"""
import sys

PATH = sys.argv[1]
STOCK = (
    "Android (6877366 based on r383902b1) clang version 11.0.2 "
    "(https://android.googlesource.com/toolchain/llvm-project "
    "b397f81060ce6d701042b782172ed13bee898b79), LLD 11.0.2 "
    "(https://android.googlesource.com/toolchain/llvm-project "
    "b397f81060ce6d701042b782172ed13bee898b79)"
)

OLD = ("  echo \\#define LINUX_COMPILER \\\"`$CC -v 2>&1 | grep ' version ' | "
       "sed 's/[[:space:]]*$//'`\\\"")
# 单引号整体包住，避免括号/斜杠被 shell 当成语法
NEW = "  echo \\#define LINUX_COMPILER '\"%s\"'" % STOCK

src = open(PATH).read()

if "6877366 based on r383902b1" in src:
    print("LINUX_COMPILER 已是原厂串，跳过")
    sys.exit(0)

if OLD not in src:
    sys.exit("锚点没找到：mkcompile_h 的 LINUX_COMPILER 行与预期不一致")

body = src.replace(OLD, NEW, 1)
# 顺手在最前面加一句说明，便于以后在树里看出这行是被人改过的
body = body.replace(
    "#!/bin/sh",
    "#!/bin/sh\n"
    "# 注意：LINUX_COMPILER 已被钉成原厂串（见 patches/compat/patch_mkcompile_h.py）。\n"
    "# /proc/version 会暴露 CI 构建机的 clang buildbot 临时目录，属可识别特征。",
    1,
)
open(PATH, "w").write(body)
print("mkcompile_h 已改：LINUX_COMPILER 钉成原厂串")
