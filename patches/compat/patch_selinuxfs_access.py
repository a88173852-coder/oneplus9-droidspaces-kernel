#!/usr/bin/env python3
"""给 5.4 的 selinuxfs 加一道 uid 守卫：普通应用不得写 access / context 节点。

## 为什么需要

春秋 4.6.3 的「检测SELinux Policy时发现可疑问题」判定方式已实测确认（kprobe do_sys_open
+ security_compute_av_user 计数）：

    nativecheck_zygote   /sys/fs/selinux/access    72 次
    nativecheck_zygote   /sys/fs/selinux/context   88 次
    nativecheck_zygote   /sys/fs/selinux/class/file/perms/read 等（权限名 → 位索引）
    probe-leaf-3         /vendor/etc/selinux/vendor_sepolicy.cil（静态规则模型）
    probe-leaf-3         /sys/fs/selinux/policy（只尝试打开，被 read_policy 挡住）

它并不读内核内存、不读 avc 日志，而是**以应用身份调用 selinuxfs 查询接口**：
往 `/sys/fs/selinux/access` 写 "scon tcon tclass"，读回 `avd.allowed` 位图；
再把位图和 `class/*/perms/*` 的索引对照，就还原出 "untrusted_app -> ksu_file read"。

## 为什么在 selinuxfs 里改，而不是移植 upstream 的 selinux_hide.c

upstream `KernelSU/kernel/feature/selinux_hide.c`（40KB）本质是把 5.5 的
`security_compute_av` 整套实现抄过来、参数化成 `struct selinux_policy *`，
再克隆一份 policydb 把 ksu 相关类型剥掉后用它算 av，最后 `ksu_patch_text`
热改 `write_op[SEL_ACCESS]` 的函数指针。

5.4 没有 `struct selinux_policy`（`policydb`/`sidtab` 是全局），移植要改 8 处签名、
所有 `policy->policydb` 引用，还要补 5.4 不存在的 `sidtab_search_entry`；
加上热改代码段，一旦布局不符就是 panic。等价效果只需在入口处挡 uid，
不碰代码段、不克隆策略、不动 `security_compute_av`。

## 挡谁、不挡谁

- 挡：`current_uid() >= 10000`，即普通应用 / isolated app（90000+）
- 不挡：uid 0（root / ksu 域）、1000（system）、2000（shell）、各种系统 daemon

`/sys/fs/selinux/context` 也必须挡：春秋先用它把上下文字符串翻译成 sid，
只挡 access 的话它仍能拿到 sid 继续探测。

## 幂等

以 `SECFS_APP_GUARD` 为标记，重复执行不会重复插入。
"""

import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "security/selinux/selinuxfs.c"
MARK = "SECFS_APP_GUARD"

try:
    src = open(PATH, encoding="utf-8", errors="surrogateescape").read()
except OSError as e:
    sys.exit(f"读不到 {PATH}: {e}")

if MARK not in src:
    # current_uid() 来自 linux/cred.h；selinuxfs.c 只 include 了 security.h，
    # 不保证间接带入，因此显式补一条。
    if "#include <linux/cred.h>" not in src:
        anchor = "#include <linux/audit.h>"
        if anchor not in src:
            sys.exit("锚点没找到：selinuxfs.c 里没有 <linux/audit.h>")
        src = src.replace(anchor, anchor + "\n#include <linux/cred.h>", 1)
        print("① 已补 #include <linux/cred.h>")
    else:
        print("① <linux/cred.h> 已存在，跳过")
else:
    print("① 头文件与守卫已存在，仅做检查")


def guard_for(node: str) -> str:
    return f"""\t/* {MARK}: 普通应用（uid >= 10000）不得访问 {node} 节点。
\t * 检测器靠它把 "scon tcon tclass" 写成查询、读回允许位图，
\t * 从而枚举出 "untrusted_app -> ksu_file read" 这类规则。
\t * root / system / shell 等 uid < 10000 的进程不受影响。
\t */
\tif (current_uid().val >= 10000)
\t\treturn -EACCES;

"""


TARGETS = (
    # (函数, 签名正则, 首语句锚点, 节点名)
    # !!! context 节点绝不能挡 !!!
    # run44 实机教训：zygote specialize 每个 app（uid>=10000）时都要走
    # selinux_android_setcontext -> libselinux setcon，底层写的就是
    # /sys/fs/selinux/context。挡了它 = 所有 app 一启动就
    # "selinux_android_setcontext failed" SIGABRT，整机黑屏。
    # context 只做「字符串 -> sid」翻译，泄漏的只是 sid 编号，
    # 真正的证据（允许位图）在 access 节点，挡住 access 即可断供。
    (
        "sel_write_access",
        r"static ssize_t sel_write_access\(struct file \*file, char \*buf, size_t size\)\n\{\n",
        "\n\tlength = avc_has_perm(&selinux_state,",
        "access",
    ),
    # 第三个通道：直接读策略二进制（春秋的 probe-leaf 会尝试打开）。
    # 上策是它本来就被 read_policy 挡着，这里再加一道，保证 app 侧二者行为一致。
    (
        "sel_open_policy",
        r"static int sel_open_policy\(struct inode \*inode, struct file \*filp\)\n\{\n",
        "\n\tBUG_ON(filp->private_data);",
        "policy",
    ),
)

patched = 0
for fn, sig, stmt, node in TARGETS:
    # 只匹配函数定义（花括号紧随签名），不会命中前置声明（以分号结尾）
    m = re.search(sig, src)
    if not m:
        sys.exit(f"锚点没找到：{fn} 的函数定义与预期不一致")

    if MARK in src[m.end() : m.end() + 900]:
        print(f"② {fn} 已有守卫，跳过")
        continue

    pos = src.find(stmt, m.end())
    if pos < 0 or pos - m.end() > 1500:
        sys.exit(f"锚点没找到：{fn} 里没有预期的首语句")

    # 必须插在「所有局部变量声明之后、第一条语句之前」：
    # 内核开 -Werror + -Wdeclaration-after-statement，紧跟 '{' 插 if 会编不过。
    src = (
        src[:pos]
        + "\n\n"
        + guard_for(node).rstrip("\n")
        + "\n"
        + src[pos:]
    )
    patched += 1
    print(f"② 已为 {fn} 注入 uid 守卫（首语句之前）")

open(PATH, "w", encoding="utf-8", errors="surrogateescape").write(src)

total = src.count(MARK)
print(f"完成：新增 {patched} 处，文件内共 {total} 处标记")
if total < 2:
    sys.exit(f"自检失败：期望 2 处（access + policy），实际 {total} 处")
