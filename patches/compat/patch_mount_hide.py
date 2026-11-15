#!/usr/bin/env python3
"""修 SukiSU mount_hide 在「一加9 / 5.4 非 GKI + CONFIG_CFI_CLANG」上的两道门。

## 门一：p->show != expected 恒真（这就是「layout mismatch」的真因）

本内核 `CONFIG_CFI_CLANG=y` + `CONFIG_LTO_CLANG_THIN=y`，kallsyms 里静态函数是这样的：

    t show_mountinfo$55b24370bfac44f0022045815b5292f1
    t show_mountinfo$55b24370bfac44f0022045815b5292f1.cfi_jt

C 源码里 `p->show = show_mountinfo;` 存进去的是 **`.cfi_jt` 跳板地址**（CFI 要求所有
间接调用目标都过跳板，跳板前 4 字节是 typeid）；而 `ksu_lookup_kernel_symbols()`
剥掉 `.llvm.<hash>` 后缀后拿到的是 **函数本体地址**。两者一个是 .rodata/.text 的跳板、
一个是函数入口，永远不相等。

实测 dmesg（run34）：

    mount_hide: show slot not found (p->show=ffffffe5c9196120 expected=ffffffe5c8019dd4)

于是上游那句 `if (p->show != expected) 放弃` 恒成立 → 三个 .open 钩子装上了，
但一次过滤都没做 → app 侧 `/proc/self/mountinfo` 与 root 完全一致（实测都是 211 条）。

所以本补丁把「比对 expected」换成「健全性检查 + 直接替换」：
  - `p->show == filter` → 已经换过了，幂等返回
  - `p->show` 不像内核指针（高 16 位不是 0xffff）→ 说明布局假设不成立，放弃并打印
  - 否则直接替换

## 门二：wrapper 上的 __nocfi 会让 CFI 检查失败

`p->show(m, "")` 是在 fs/proc_namespace.c 的 `m_show()` 里做的间接调用，调用点由
kCFI 插桩：读 `*(u32 *)(target - 4)` 当 typeid 和目标比。上游给三个 wrapper 打了
`__nocfi`，就是让它们「没有 typeid」→ 一旦真的被 p->show 间接调到，检查必失败
（`__cfi_check_fail` → BUG/panic）。上游在 GKI 上没炸，是因为那边 p->show 从来没被
成功替换过（门一一直拦着），这条路径压根没走到。

本补丁只保留 `ksu_filter_show` 的 `__nocfi`（它确实要拿裸函数指针调 orig），
把三个 wrapper 的 `__nocfi` 去掉 —— 它们的签名与 `show_vfsmnt` 完全一致
（`int (struct seq_file *, struct vfsmount *)`），编译器会给它们生成与原生 show
相同的 kCFI typeid，间接调用即可通过检查。

用法: python3 patches/compat/patch_mount_hide.py <path/to/KernelSU/kernel/feature/mount_hide.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

MARK_SWAP = "mount_hide: swap show"
MARK_NOCFI = "ksu_show_vfsmnt CFI-safe"

OLD = """    if (p->show != expected) {
        pr_warn_once("mount_hide: proc_mounts layout mismatch, not filtering\\n");
        return 0;
    }
    p->show = filter;
    return 0;"""

NEW = """    /*
     * 本内核 CONFIG_CFI_CLANG=y + ThinLTO：p->show 里存的是 show_xxx 的 .cfi_jt
     * 跳板地址，而 expected 是 kallsyms 解析出来的函数本体地址，两者永远不等
     * （实测 p->show=ffffffe5c9196120 / expected=ffffffe5c8019dd4）。
     * 上游那句 if (p->show != expected) 因此恒真，一次都没过滤过。
     * 改成：幂等判重 + 内核指针健全性检查，然后直接替换。
     */
    if (p->show == filter)
        return 0;
    if ((((unsigned long)p->show) >> 48) != 0xffffUL) {
        pr_warn_once("mount_hide: p->show 不像内核指针 (%px)，放弃\\n", (void *)p->show);
        return 0;
    }
    /*
     * 换之前先自证能过 kCFI：m_show() 里的间接调用会读 *(u32 *)(target - 4)
     * 当 typeid 去比对。这里照做一遍 —— 原生 show 的 typeid vs 我们 wrapper 的
     * typeid，相等才换。不相等则不做任何事（只是没隐藏，不会 panic）。
     */
    {
        u32 want = *(u32 *)((unsigned long)p->show - 4);
        u32 have = *(u32 *)((unsigned long)filter - 4);

        if (want != have) {
            pr_warn_once("mount_hide: kCFI typeid 不匹配 (native=%08x ours=%08x)，放弃\\n",
                         want, have);
            return 0;
        }
    }
    pr_info_once("mount_hide: swap show %px -> %px (kallsyms orig=%px)\\n",
                 (void *)p->show, (void *)filter, (void *)expected);
    p->show = filter;
    return 0;"""

ok = True
if MARK_SWAP not in src:
    if OLD not in src:
        sys.exit("锚点没找到：ksu_install_filter 与预期不一致")
    src = src.replace(OLD, NEW, 1)
    print("① show 槽位置换逻辑已替换（不再比对 expected）")
else:
    print("① 已打过，跳过")

# ---- 门二：去掉三个 wrapper 的 __nocfi，让它们拿到 kCFI typeid ----
for fn in ("ksu_show_vfsmnt", "ksu_show_mountinfo", "ksu_show_vfsstat"):
    old_sig = "static int __nocfi %s(struct seq_file *m, struct vfsmount *mnt)" % fn
    new_sig = ("static int %s(struct seq_file *m, struct vfsmount *mnt) /* %s */"
               % (fn, MARK_NOCFI))
    if new_sig in src:
        print("② %s 已改过，跳过" % fn)
        continue
    if old_sig not in src:
        sys.exit("锚点没找到：%s 的定义与预期不一致" % fn)
    src = src.replace(old_sig, new_sig, 1)
    print("② %s 去掉 __nocfi（补 typeid）" % fn)

# ---- ③ 诊断期临时插桩（定位完把 DBG 改成 False 即可全撤）----
DBG = True
if DBG:
    MARK_DBG = "MH_DBG"
    if MARK_DBG in src:
        print("③ 诊断插桩已存在，跳过")
    else:
        # 三个 .open shim 的入口：证明钩子到底有没有被调用
        for tag, orig in (("mounts", "ksu_orig_mounts_open"),
                          ("mountinfo", "ksu_orig_mountinfo_open"),
                          ("mountstats", "ksu_orig_mountstats_open")):
            old = "    int ret = %s(inode, file);" % orig
            new = ('    pr_info("MH_DBG %s_open uid=%%d hide=%%d\\n", current_uid().val,\n'
                   '            ksu_should_hide_mount_for_current());\n'
                   '    int ret = %s(inode, file);' % (tag, orig))
            if old not in src:
                sys.exit("锚点没找到：%s 的 open shim 与预期不一致" % tag)
            src = src.replace(old, new, 1)

        # install_filter 的四个出口：证明它走到了哪一步
        old = "    if (!m || !m->private)\n        return 0;"
        new = ('    pr_info("MH_DBG install_filter file=%px m=%px priv=%px\\n",\n'
               '            (void *)file, (void *)m, m ? (void *)m->private : NULL);\n'
               '    if (!m || !m->private)\n        return 0;')
        if old not in src:
            sys.exit("锚点没找到：install_filter 的 !m 判空与预期不一致")
        src = src.replace(old, new, 1)
        print("③ 诊断插桩已注入")

open(PATH, "w").write(src)
print("mount_hide 补丁注入完成")
