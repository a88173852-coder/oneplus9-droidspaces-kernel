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

## 门二（已撤销）：wrapper 的 __nocfi 与 kCFI typeid

曾经把三个 wrapper 的 `__nocfi` 去掉，理由是「m_show 调用 p->show 时会读
*(u32 *)(target-4) 比 typeid，wrapper 需要正确 typeid」。反汇编核实后这个前提是错的：

    m_show 调用点：blr x8，前面没有 ldr [x8,#-4]
    wrapper（36 字节）：0 处 kCFI 检查，0 处间接调用（只 tail-call）
    ksu_filter_show（__nocfi）：0 处 kCFI 检查，2 处 blr x2（回调 orig）

即调用点根本不校验。因此 wrapper 有没有 `__nocfi` 都不影响安全性。
本补丁仍去掉 `__nocfi`，只为让 wrapper 不再依赖 `__nocfi` 属性传播，
行为上等价；真正决定成败的是门一。

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
     * 跳板地址，而 expected 是 kallsyms 解析出来的函数本体地址（符号还带 $hash
     * 后缀），两者永远不等 —— 上游那句 if (p->show != expected) 恒成立，
     * 于是三个钩子全装上了、却一次都没过滤过。
     *
     * 关于 kCFI（2026-11-16 反汇编实测，run38 镜像 System.map + Image）：
     *   - m_show 里调用 p->show 的地方是 blr x8，前面没有 ldr [x8,#-4]，
     *     即调用点根本不读 typeid；
     *   - 三个 wrapper 各 36 字节，只做 tail-call 到 ksu_filter_show；
     *   - ksu_filter_show 是 __nocfi，拿裸指针回调 orig。
     *   整条链上没有任何 typeid 比对，所以直接替换是安全的，
     *   不需要（也不可能）自证 typeid。
     */
    if (p->show == filter)
        return 0;          /* 已经换过，幂等 */
    if ((((unsigned long)p->show) >> 48) != 0xffffUL) {
        pr_warn_once("mount_hide: p->show 不像内核指针 (%px)，放弃\\n", (void *)p->show);
        return 0;
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

# ---- ③ 扩充 marker：把容器类挂载也纳入过滤 ----
# 上游 markers 只有 /adb/、/data/adb、kernelsu、magisk、zygisk、/debug_ramdisk。
# 本机跑着 Droidspaces 和 daidai 两个容器，它们在 /data/local/<name>/ 下各挂了一堆
# dev/proc/sys/pts/shm。这些路径不含上面任何一个 marker，于是：
#   - 目录被 sus_path 隐藏（app 看不见 /data/local/daidai）
#   - 挂载记录却照常输出 → 挂载点路径不可达 → 春秋的「挂载间隙」
# 实测：去掉 daidai 的 sus_path 后 13 个挂载点恢复可达、间隙消失，
# 但容器痕迹暴露，异常项从 14 涨到 16。所以必须两边一起隐藏。
OLD_MARKERS = """static const char *const ksu_mount_markers[] = {
    "/adb/", "/data/adb", "kernelsu", "magisk", "zygisk", "/debug_ramdisk",
};"""
NEW_MARKERS = """static const char *const ksu_mount_markers[] = {
    "/adb/", "/data/adb", "kernelsu", "magisk", "zygisk", "/debug_ramdisk",
    /* 容器挂载：本机 Droidspaces / daidai / nandswap，目录被 sus_path 隐藏后
     * 这些挂载点若不一起隐藏，就会在 app 视角变成「路径不可达的孤儿挂载」。 */
    "daidai", "Droidspaces", "nandswap",
};"""

MARK_MARKERS = "daidai"
if MARK_MARKERS in src:
    print("③ markers 已扩充，跳过")
else:
    if OLD_MARKERS not in src:
        sys.exit("锚点没找到：ksu_mount_markers 与预期不一致")
    src = src.replace(OLD_MARKERS, NEW_MARKERS, 1)
    print("③ markers 已扩充（daidai / Droidspaces / nandswap）")

# ---- ④ 诊断插桩：定位已完成（钩子确实被调用、卡点已查明），撤掉 ----
DBG = False
MARK_DBG = "MH_DBG"
if MARK_DBG in src:
    import re
    src = re.sub(r'[ \t]*pr_info\("MH_DBG[\s\S]*?\);[ \t]*\n', '', src)
    print("③ 已移除历史诊断插桩（MH_DBG）")
else:
    print("③ 无诊断插桩，跳过")

open(PATH, "w").write(src)
print("mount_hide 补丁注入完成")
