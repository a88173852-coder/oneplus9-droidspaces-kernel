#!/usr/bin/env python3
"""在 fs/namei.c 的两个关键点插入探点，判定 sus_path 钩子是否真的跑起来。

背景：susfs_is_inode_sus_path() 体内已有 PROBE（inject_probe.py 注入），
但 app 访问已标记路径时 dmesg 里 PROBE 计数恒为 0 → 函数从未被调用。
两种可能：①patch 的 namei.c 钩子没落盘；②钩子落盘但执行路径没走到。

本脚本在 namei.c 里插两个计数探点，直接把这两种情况分开：
  A) link_path_walk_inode() 主循环开头（patch 无条件调 susfs_is_inode_sus_path 的地方）
     → 打印说明循环在跑。若 PROBE 仍不出现，说明钩子代码被剔掉了。
  B) lookup_fast() 的 __d_lookup_rcu() 之后
     → 打印 nd->flags 实测值，验证 ND_STATE_LOOKUP_LAST(0x04000000) 有没有被置上。

限流：每个点最多 80 条，避免 uid>=10000 的进程把 dmesg 刷爆。

用法: python3 patches/compat/inject_namei_probe.py <path/to/fs/namei.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

# ---- A) link_path_walk_inode 的 for(;;) 循环开头 ----
# patch 在这行之后插入 #ifdef CONFIG_KSU_SUSFS_SUS_PATH 的无条件检查。
# 这行只出现一次（namei.c 里只有 link_path_walk_inode 有 nd->path.dentry 转局部变量）。
ANCHOR_A = "\t\tstruct dentry *dentry = nd->path.dentry;\n"

PROBE_A = (
    '\t\tif (current_uid().val != 0) {\n'
    '\t\t\tstatic int __nprobe_w = 0;\n'
    '\t\t\tif (__nprobe_w < 200) {\n'
    '\t\t\t\t__nprobe_w++;\n'
    '\t\t\t\tpr_info("NPROBE walk uid=%u ge10k=%d ino=%lu\\n",\n'
    '\t\t\t\t\tcurrent_uid().val,\n'
    '\t\t\t\t\tcurrent_uid().val >= 10000 ? 1 : 0,\n'
    '\t\t\t\t\tdentry->d_inode ? dentry->d_inode->i_ino : 0UL);\n'
    '\t\t\t}\n'
    '\t\t}\n'
)

# ---- B) lookup_fast 的 RCU 查表 ----
ANCHOR_B = "\t\tdentry = __d_lookup_rcu(parent, &nd->last, &seq);\n"

PROBE_B = (
    '\t\tif (current_uid().val >= 10000) {\n'
    '\t\t\tstatic int __nprobe_f = 0;\n'
    '\t\t\tif (__nprobe_f < 80) {\n'
    '\t\t\t\t__nprobe_f++;\n'
    '\t\t\t\tpr_info("NPROBE fast uid=%u hit=%d f=0x%x\\n",\n'
    '\t\t\t\t\tcurrent_uid().val,\n'
    '\t\t\t\t\t(dentry && !IS_ERR(dentry) && dentry->d_inode) ? 1 : 0,\n'
    '\t\t\t\t\tnd->flags);\n'
    '\t\t\t}\n'
    '\t\t}\n'
)

if "NPROBE walk" in src:
    print("namei 探点已存在，跳过")
    sys.exit(0)

missing = []
if ANCHOR_A not in src:
    missing.append("A(link_path_walk_inode 循环开头)")
if ANCHOR_B not in src:
    missing.append("B(lookup_fast 的 __d_lookup_rcu 之后)")

src = src.replace(ANCHOR_A, ANCHOR_A + PROBE_A, 1)
src = src.replace(ANCHOR_B, ANCHOR_B + PROBE_B, 1)
open(PATH, "w").write(src)

if missing:
    # 锚点缺失本身就是结论：说明 SUSFS patch 的 namei.c 钩子没打进来。
    # 不硬失败，让审计日志把结论带出来，同时尽量留住可刷的镜象。
    print("!! 锚点缺失: %s —— patch 的 namei.c 部分没落盘" % "、".join(missing))
else:
    print("namei 探点注入成功（A + B）")
