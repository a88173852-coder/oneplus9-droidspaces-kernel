#!/usr/bin/env python3
"""把 susfs_is_inode_sus_path() 的探点换成裸 pr_err（绕过 SUSFS_LOGE 的 static_branch）。

为什么：inject_probe.py 用的是 SUSFS_LOGE，它包在
    if (static_branch_likely(&susfs_is_log_enabled)) pr_err(...)
里。若这个 static key 在 app 进程上下文没有生效，探点会静默不输出，
让人误判「函数没被调用」。改裸 pr_err 后可以彻底排除这个变量。

同时把三个前置条件一次性打全（app 门 / i_mapping / FUSE / sus bit / i_uid），
并把 test_bit 的结果也算出来，肉眼即可判断哪一项不满足。

用法: python3 patches/compat/inject_diag.py <path/to/fs/susfs.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

OLD_MARK = '\tif (current_uid().val >= 10000) {\n'

ANCHOR = (
    "bool susfs_is_inode_sus_path(struct inode *inode)\n"
    "#endif\n"
    "{\n"
    "\tstruct fuse_inode *fi = NULL;\n"
)

DIAG = (
    '\tif (current_uid().val >= 10000) {\n'
    '\t\tunsigned int __u = current_uid().val;\n'
    '\t\tint __app = susfs_is_current_proc_umounted_app() ? 1 : 0;\n'
    '\t\tint __map = inode->i_mapping ? 1 : 0;\n'
    '\t\tint __fus = (inode->i_sb->s_magic == FUSE_SUPER_MAGIC) ? 1 : 0;\n'
    '\t\tint __bit = __map ? (int)test_bit(AS_FLAGS_SUS_PATH,\n'
    '\t\t\t&inode->i_mapping->flags) : -1;\n'
    '\t\tpr_err("SUSDIAG uid=%u app=%d map=%d fus=%d bit=%d iuid=%u ino=%lu\\n",\n'
    '\t\t\t__u, __app, __map, __fus, __bit,\n'
    '\t\t\tinode->i_uid.val, inode->i_ino);\n'
    '\t}\n'
)

if "SUSDIAG" in src:
    print("SUSDIAG 已存在，跳过")
    sys.exit(0)

if ANCHOR not in src:
    sys.exit("锚点没找到：susfs_is_inode_sus_path 的结构和预期不一致")

# 若旧的 SUSFS_LOGE 版探点还在，先整块删掉（从 if 到配对的 } 共 10 行）
if "PROBE uid=" in src:
    start = src.index(ANCHOR) + len(ANCHOR)
    seg_end = src.index('\tif (!susfs_is_current_proc_umounted_app())', start)
    src = src[:start] + src[seg_end:]
    print("已移除旧的 SUSFS_LOGE 探点")

pos = src.index(ANCHOR) + len(ANCHOR)
src = src[:pos] + DIAG + src[pos:]
open(PATH, "w").write(src)
print("SUSDIAG 裸探点注入成功")
