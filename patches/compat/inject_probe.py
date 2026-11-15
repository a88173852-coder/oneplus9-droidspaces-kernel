#!/usr/bin/env python3
"""在 fs/susfs.c 的 susfs_is_inode_sus_path() 入口插入一行探点。

背景：sus_path 隐藏完全不生效——add-sus-path 返回 0、dmesg 里 AS_FLAGS_SUS_PATH
确实置位、kallsyms 里函数也在、termux(uid 10318) 访问已标记路径仍看得见。
三个判断条件哪个 false 只能让内核自己说：

    susfs_is_inode_sus_path(inode):
        if (!susfs_is_current_proc_umounted_app()) return false;   ← ① uid >= 10000
        if (!inode->i_mapping) return false;                       ← ② mapping 存在
        test_bit(AS_FLAGS_SUS_PATH, ...) && is_i_uid_not_allowed()  ← ③ 位 + inode uid

探点只在 current_uid >= 10000（app 进程）时打印，root/system/shell 不刷屏。
定位完把 workflow 里调用本脚本的那两行删掉即可。

用法: python3 patches/compat/inject_probe.py <path/to/fs/susfs.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

# 函数定义（不是 extern 声明）的唯一形态：签名 + #endif + { + 第一句
ANCHOR = (
    "bool susfs_is_inode_sus_path(struct inode *inode)\n"
    "#endif\n"
    "{\n"
    "\tstruct fuse_inode *fi = NULL;\n"
)

PROBE = (
    '\tif (current_uid().val >= 10000) {\n'
    '\t\tint __p_app  = susfs_is_current_proc_umounted_app() ? 1 : 0;\n'
    '\t\tint __p_map  = inode->i_mapping ? 1 : 0;\n'
    '\t\tint __p_bit  = (inode->i_mapping &&\n'
    '\t\t\ttest_bit(AS_FLAGS_SUS_PATH, &inode->i_mapping->flags)) ? 1 : 0;\n'
    '\t\tSUSFS_LOGE("PROBE uid=%u app=%d map=%d bit=%d iuid=%u ino=%lu\\n",\n'
    '\t\t\tcurrent_uid().val, __p_app, __p_map, __p_bit,\n'
    '\t\t\tinode->i_uid.val, inode->i_ino);\n'
    '\t}\n'
)

if "PROBE uid=" in src:
    print("probe 已存在，跳过")
    sys.exit(0)

if ANCHOR not in src:
    sys.exit("锚点没找到：susfs_is_inode_sus_path 的结构和预期不一致")

open(PATH, "w").write(src.replace(ANCHOR, ANCHOR + PROBE, 1))
print("probe 注入成功")
