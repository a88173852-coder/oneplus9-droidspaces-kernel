/* SPDX-License-Identifier: GPL-2.0 */
/*
 * SUSFS 2.3.0 的 5.4 回移补丁假定 KSU 一侧会提供两个符号：
 *
 *   u32  susfs_ksu_sid;                     // ksu domain 的 SELinux sid
 *   bool susfs_is_current_ksu_domain(void); // 当前进程是否跑在 ksu domain
 *
 * 原仓库里这两个符号由它自己那份 KernelSU（odin/manual-hook 分支）在装载
 * 策略时写入。SukiSU-Ultra 没有这套东西，补丁打上去 fs/ 与 avc.c 就会
 * 引用到未定义符号，链接期直接失败（ld.lld: undefined symbol）。
 *
 * 这里用 SukiSU 已有的 ksu_cred 做等价判断：su 进程在拿到超级用户之后，
 * current_cred() 就是 ksu_cred 这个对象，SUSFS 的 sus_mount 正是靠这个
 * 判定「这个挂载是不是 ksu 进程干的」，从而给它分配伪造的 mnt_id。
 *
 * susfs_ksu_sid 只被 avc 的日志伪装（CONFIG_KSU_SUSFS_AVC_LOG_SPOOFING）用到，
 * 那项没开时静态键恒假、分支不会执行；保持 0 即可，不影响任何已开启的能力。
 *
 * 由工作流追加到 fs/susfs.c 末尾（该文件已经 include 了 cred.h 与 sched.h，
 * 也已经有 ksu_cred 的 extern 声明），不额外改 Makefile。
 */

u32 susfs_ksu_sid;

bool susfs_is_current_ksu_domain(void)
{
#ifdef CONFIG_KSU
	return current_cred() == ksu_cred;
#else
	return false;
#endif
}

/*
 * susfs_init() 在原 fork 里由 KSU 初始化流程显式调用，只做两件事：
 *   INIT_WORK(&susfs_extra_works, …) / INIT_DELAYED_WORK(&sdcard_cleanup_dwork, …)
 *
 * SukiSU 没有这个调用点。不补的话这两个结构是 .bss 里的全零对象，
 * 一旦有 sus_path_loop / sdcard monitor 相关路径 schedule 到它们，
 * 就是「把 NULL 当函数指针调」的 oops——而且是随机时间点炸，最难查。
 *
 * late_initcall 比任何用户态 susfs 命令都早，安全。
 */
#include <linux/init.h>

/*
 * 故意不叫 susfs_*：initcall 会以 __initcall_<n>_<uniq>_<名字><级别> 的形式
 * 留在 kallsyms 里，CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS 只过滤 susfs_ 前缀，
 * 名字里带 susfs 就会漏一个符号出去（实测 __initcall_255_1653_susfs_compat_init7）。
 */
static int __init fs_compat_late_init(void)
{
	susfs_init();
	return 0;
}
late_initcall(fs_compat_late_init);
