#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
隐藏非原厂 loop 设备的 backing_file。

背景
----
一加9 这棵 5.4 树里 loop 的 sysfs 属性没有拆到 loop_sysfs.c，全部在
drivers/block/loop.c：

    static ssize_t loop_attr_backing_file_show(struct loop_device *lo, char *buf)
    {
        ...
        spin_lock_irq(&lo->lo_lock);
        if (lo->lo_backing_file)
            p = file_path(lo->lo_backing_file, buf, PAGE_SIZE - 1);
        spin_unlock_irq(&lo->lo_lock);

        if (IS_ERR_OR_NULL(p))
            ret = PTR_ERR(p);
        else {
            ret = strlen(p);
            ...
        }
    }

容器与模块镜像的真实路径会原样泄露：

    /sys/block/loop41/loop/backing_file = /data/adb/modules/meta-overlayfs/modules.img
    /sys/block/loop42/loop/backing_file = /data/local/Droidspaces/Containers/ubuntu/rootfs.img

SUSFS 的 sus_path 对 kernfs(sysfs) inode 不可靠 —— inode 会被重建，标记半分钟内
失效，所以只能在 show 输出这一层直接过滤。

策略
----
命中隐藏词的 loop 一律返回 0 字节（等同“该 loop 未绑定后备文件”）。只改只读
show 路径，不触碰 loop 的 ioctl / 挂载逻辑，容器功能不受影响。

注意：root 也看不到（losetup -a 会显示空）。系统里没有任何服务依赖这个 sysfs
文件做决策（vold 走 LOOP_GET_STATUS ioctl），故不做 uid 例外 —— 少一个可以被
“root 与 app 结果不一致”比对出来的破绽。排查容器请用 `losetup -a` 的 ioctl 路径
或直接看 /proc/mounts。

幂等：文件里已有 loop_path_should_hide 就直接退出。
"""

import re
import sys


HELPER = '''/*
 * osd: 隐藏非原厂 loop 的后备文件路径。
 * 检测软件读 /sys/block/loopN/loop/backing_file，靠路径定位
 * /data/local/Droidspaces（容器 rootfs）与 /data/adb/modules（模块镜像）。
 * sus_path 对 kernfs inode 无效（inode 会重建），只能在这里过滤 show 输出。
 */
static bool loop_path_should_hide(const char *path)
{
\tif (!path || !*path)
\t\treturn false;
\tif (strstr(path, "Droidspaces") || strstr(path, "daidai") ||
\t    strstr(path, "/data/adb/modules") || strstr(path, "/data/local/tmp") ||
\t    strstr(path, "susfs"))
\t\treturn true;
\treturn false;
}

'''

DEF_RE = re.compile(
    r'static ssize_t loop_attr_backing_file_show\(struct loop_device \*lo, char \*buf\)\n\{'
)

# 宽松匹配 "else { ... ret = strlen(p);" 这一段，兼容 tab/空格差异
ELSE_RE = re.compile(
    r'(?P<indent>[ \t]*)else\s*\{\s*\n(?P<body>[ \t]*)ret = strlen\(p\);'
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_loop_hide.py <path/to/drivers/block/loop.c>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        src = f.read()

    if "loop_path_should_hide" in src:
        print("already patched, skip")
        return 0

    m = DEF_RE.search(src)
    if not m:
        print("ERROR: 找不到 loop_attr_backing_file_show 定义，源码结构可能不对", file=sys.stderr)
        return 1

    src = src[: m.start()] + HELPER + src[m.start():]

    m2 = ELSE_RE.search(src, m.start() + len(HELPER))
    if not m2:
        print("ERROR: 找不到 backing_file show 里的 else{ret=strlen(p);} 分支", file=sys.stderr)
        return 1

    indent = m2.group("indent")
    body = m2.group("body")
    repl = (
        f"{indent}else if (loop_path_should_hide(p)) {{\n"
        f"{body}/* osd: 非原厂 loop 不暴露路径，等同未绑定 */\n"
        f"{body}ret = 0;\n"
        f"{indent}}} else {{\n"
        f"{body}ret = strlen(p);"
    )
    src = src[: m2.start()] + repl + src[m2.end():]

    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(src)

    if "loop_path_should_hide(p)" not in src:
        print("ERROR: 替换后自检失败", file=sys.stderr)
        return 1

    print("patched: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
