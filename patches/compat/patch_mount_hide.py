#!/usr/bin/env python3
"""修 SukiSU mount_hide 在「一加9 / 5.4 非 GKI」上的 proc_mounts 布局不匹配。

现象（dmesg）：
    KernelSU: mount_hide: enabled (3/3 files hooked)
    KernelSU: mount_hide: proc_mounts layout mismatch, not filtering

后果：三个 proc 挂载视图的 .open 钩子装上了，但真正决定是否过滤的那一步
（把 proc_mounts->show 换成我们的 filter）被放弃，于是 app 侧 /proc/self/mountinfo
仍然是原始内容 —— 春秋检测的「挂载间隙 / 挂载异常 / Mount loophole / Magic Mount /
KernelSU loop device」全部命中。

上游代码假设 proc_mounts 的 show 槽位在固定偏移：
    struct ksu_proc_mounts {
        struct mnt_namespace *ns;     // +0
        struct path root;             // +8
        int (*show)(...);             // +24
    };
本树（OPPO/一加 5.4）里 p->show 读出来和解析到的 show 函数对不上，可能是布局差异，
也可能是 file_operations 里 show 的解析落点不同。既然无法在编译期确定，就改成运行期
自定位：在前 0x80 字节里找「值恰好等于任一已知 show 函数指针」的 8 字节槽位，
命中即替换。只写回一个精确等于已知函数地址的槽位，不会误伤别的字段。

替换成功后 dmesg 会打印实际偏移，便于下一轮把偏移写死。

用法: python3 patches/compat/patch_mount_hide.py <path/to/KernelSU/kernel/feature/mount_hide.c>
"""
import sys

PATH = sys.argv[1]
src = open(PATH).read()

OLD = """    if (p->show != expected) {
        pr_warn_once("mount_hide: proc_mounts layout mismatch, not filtering\\n");
        return 0;
    }
    p->show = filter;
    return 0;"""

NEW = """    if (p->show != expected) {
        /*
         * 本树（一加9 / 5.4 非 GKI）上 p->show 与解析到的 show 函数对不上。
         * 直接放弃过滤 = 检测软件能看到全部模块挂载，所以这里改成运行期自定位：
         * 在前 0x80 字节里找值恰好等于任一已知 show 函数的 8 字节槽位。
         * 只写回一个精确等于已知函数地址的槽位，不会误伤其它字段。
         */
        unsigned long *slot;
        int i, found = -1;

        for (i = 0; i < 0x10; i++) {
            slot = (unsigned long *)p + i;
            if (*slot == (unsigned long)expected ||
                *slot == (unsigned long)ksu_orig_show_vfsmnt ||
                *slot == (unsigned long)ksu_orig_show_mountinfo ||
                *slot == (unsigned long)ksu_orig_show_vfsstat) {
                found = i;
                break;
            }
        }
        if (found < 0) {
            pr_warn_once("mount_hide: show slot not found (p->show=%px expected=%px)\\n",
                         (void *)p->show, (void *)expected);
            return 0;
        }
        pr_info("mount_hide: show slot at +%d bytes (p->show=%px expected=%px)\\n",
                found * 8, (void *)p->show, (void *)expected);
        ((unsigned long *)p)[found] = (unsigned long)filter;
        return 0;
    }
    p->show = filter;
    return 0;"""

if "show slot at +%d bytes" in src:
    print("mount_hide 补丁已存在，跳过")
    sys.exit(0)

if OLD not in src:
    sys.exit("锚点没找到：mount_hide.c 的 ksu_install_filter 与预期不一致")

open(PATH, "w").write(src.replace(OLD, NEW, 1))
print("mount_hide 补丁注入成功")
