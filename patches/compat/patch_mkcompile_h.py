#!/usr/bin/env python3
"""把 /proc/version 里的编译器串钉成原厂那一串。

## 为什么

`/proc/version` 由 linux_banner 拼出来：

    "Linux version " UTS_RELEASE " (" LINUX_COMPILE_BY "@" LINUX_COMPILE_HOST
    ") (" LINUX_COMPILER ") " UTS_VERSION

- UTS_RELEASE / UTS_VERSION / LINUX_COMPILE_BY / HOST 都能用 KBUILD_BUILD_*
  和 CONFIG_LOCALVERSION 控制（workflow 里已经这么干了）；
- **LINUX_COMPILER 不受任何 KBUILD_* 影响**，由 scripts/mkcompile_h 现场拼出来。

实测差异（同一台机器，原厂 vs 我们编的）：

  原厂: Android (6877366 based on r383902b1) clang version 11.0.2 (https://…b397f810…), LLD 11.0.2 (https://…b397f810…)
  我们: Android (6573524 based on r383902b) clang version 11.0.2 (https://…b397f810…), LLD 11.0.2 (/buildbot/tmp/tmpF3FjA8 b397f810…)

括号里那串 buildbot 临时目录每次编译都不一样 —— 就算用同一个 clang 快照也对不上，
所以只能写死成原厂串。写死的是**纯字符串**，不影响任何代码生成。

## 注意：这棵树（OPPO sm8350）的 mkcompile_h 和 mainline 5.4 不一样

mainline 5.4 是 `echo \\#define LINUX_COMPILER \\"`$CC -v ...`\\"`；
这棵树是：

    LD_VERSION=$($LD -v | head -n1 | sed ...)
    printf '#define LINUX_COMPILER "%s"\\n' "$CC_VERSION, $LD_VERSION"

所以锚点按后者的 printf 行来，同时兼容前者。

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

# OPPO 树的锚点
OLD_OPPO = """  printf '#define LINUX_COMPILER "%s"\\n' "$CC_VERSION, $LD_VERSION\""""
NEW_OPPO = "  printf '#define LINUX_COMPILER \"%%s\"\\n' '%s'" % STOCK

# mainline 5.4 的锚点（留着兜底，万一哪天换树）
OLD_MAIN = ("  echo \\#define LINUX_COMPILER \\\"`$CC -v 2>&1 | grep ' version ' | "
            "sed 's/[[:space:]]*$//'`\\\"")
NEW_MAIN = "  echo \\#define LINUX_COMPILER '\"%s\"'" % STOCK

src = open(PATH).read()

if "6877366 based on r383902b1" in src:
    print("LINUX_COMPILER 已是原厂串，跳过")
    sys.exit(0)

if OLD_OPPO in src:
    src = src.replace(OLD_OPPO, NEW_OPPO, 1)
    which = "OPPO 版 printf"
elif OLD_MAIN in src:
    src = src.replace(OLD_MAIN, NEW_MAIN, 1)
    which = "mainline 版 echo"
else:
    sys.exit("锚点没找到：mkcompile_h 的 LINUX_COMPILER 生成行两种写法都不匹配")

# 顺手在最前面加一句说明，便于以后在树里看出这行是被人改过的
src = src.replace(
    "#!/bin/sh",
    "#!/bin/sh\n"
    "# 注意：LINUX_COMPILER 已被钉成原厂串（见 patches/compat/patch_mkcompile_h.py）。\n"
    "# /proc/version 会暴露 CI 构建机的 clang 快照号与 LLD 的 buildbot 临时目录。",
    1,
)
open(PATH, "w").write(src)
print("mkcompile_h 已改（%s）：LINUX_COMPILER 钉成原厂串" % which)
