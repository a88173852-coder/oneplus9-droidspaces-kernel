/* SPDX-License-Identifier: GPL-2.0 */
/*
 * SUSFS 2.3.0 的 5.4 回移补丁里，fs 目录下那些 .c 文件的 hook 点是按某个 KSU 分支的
 * 「manual hook」写的：补丁自带一份 include/linux/odin_ksu_hooks.h，声明
 * ksu_handle_execveat / faccessat / stat / setresuid / sys_read / sys_reboot …
 * 并在 fs、kernel 里直接调用。
 *
 * SukiSU-Ultra 走 tracepoint hook（syscall_event_bridge.c，函数名带 _sucompat），
 * 而且它自己已经定义了 ksu_handle_setresuid(2 参数)、ksu_handle_input_handle_event
 * —— 如果这里再用同名 extern 声明或 static inline 实现，必然撞签名。
 *
 * 所以下面这些 su 兼容 hook 统一改成「函数式宏」把调用整体抹掉：
 *   - 不引入任何新符号，不会和 SukiSU 的同名函数打架；
 *   - 不产生 (0); 这种空表达式语句（会被 -Wunused-value 抓，本树把 warning 当 error）；
 *   - 语句位置用 do{}while(0)。
 *
 * 这些 hook 只承担 KSU 的 su 兼容判定，跟 SUSFS 的隐藏能力（sus_path / sus_mount /
 * uname / cmdline / kstat / open_redirect / sus_map）无关。
 *
 * ── ksu_handle_sys_reboot 是例外：它是 SuSFS 的「控制面」，不能抹掉 ──
 *
 * ksud 下发每条 susfs 命令走 reboot(2)：
 *
 *     reboot(0xDEADBEEF, 0xFAFAFAFA, cmd_id, &payload)
 *
 * 补丁在 kernel/reboot.c 的 SYSCALL_DEFINE4(reboot) 开头插了一句
 * `if (magic1 == 0xDEADBEEF) return ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);`
 * 而 ksu_handle_sys_reboot 在原 fork 里由 KSU 侧实现，SukiSU 没有这个函数。
 *
 * 之前这里把它退化成 `(-EINVAL)`，后果是**每一条 susfs 命令都在门口被吞掉**：
 * syscall 直接返回，payload.err 保留用户态初值 0，ksud 于是认为「成功」。
 * 于是 `ksud susfs set-uname` 返回 RC=0 但 uname 不变、`susfs status` 恒 false、
 * `implementation` 报 unsupported —— 内核里明明有全套 SUSFS 代码却没有控制面。
 *
 * 现在改成真实分发：magic2 命中 0xFAFAFAFA 就按 cmd 调 fs/susfs.c 导出的处理函数。
 * SukiSU 自己的安装通道是 KSU_INSTALL_MAGIC1(0xDEADBEEF)+KSU_INSTALL_MAGIC2(0xCAFEBABE)，
 * 它由 supercall.c 的 reboot kprobe 在函数入口处理（只 add task_work，不消费返回），
 * 到我们这里 magic2 不匹配 → 仍然返回 -EINVAL，与原生行为完全一致，不受影响。
 */
#ifndef _LINUX_ODIN_KSU_HOOKS_H
#define _LINUX_ODIN_KSU_HOOKS_H

#include <linux/errno.h>

#define ksu_handle_execveat(fd, filename, argv, envp, flags)		do { } while (0)
#define ksu_handle_post_execve(fd, filename, argv, envp, flags, retval)	do { } while (0)
#define ksu_handle_sys_read(fd)						do { } while (0)
#define ksu_handle_vfs_fstat(fd, size)					do { } while (0)
#define ksu_handle_faccessat(dfd, filename, mode, flags)		do { } while (0)
#define ksu_handle_stat(dfd, filename, flags)				do { } while (0)
#define ksu_handle_setresuid(ruid, euid, suid)				do { } while (0)
#define ksu_handle_input_handle_event(type, code, value)		do { } while (0)

/* fs/exec.c 里 clear_thread_flag() 用；SukiSU 没占这个位 */
#define TIF_PROC_IN_KSU_EXECVE 61

#ifdef CONFIG_KSU_SUSFS
/*
 * fs/susfs.c 导出的处理函数（原型见补丁的 include/linux/susfs.h）。
 * 这里写 void ** 而不是 void __user **：本头文件被插在各 .c 的第一行，
 * 那时 compiler_types.h 还没进来，__user 尚未定义；GCC 下两者本就等价。
 */
extern void susfs_add_sus_path(void **user_info);
extern void susfs_add_sus_path_loop(void **user_info);
extern void susfs_set_hide_sus_mnts_for_non_su_procs(void **user_info);
extern void susfs_add_sus_kstat(void **user_info);
extern void susfs_update_sus_kstat(void **user_info);
extern void susfs_set_uname(void **user_info);
extern void susfs_enable_log(void **user_info);
extern void susfs_set_cmdline_or_bootconfig(void **user_info);
extern void susfs_add_open_redirect(void **user_info);
extern void susfs_add_sus_map(void **user_info);
extern void susfs_set_avc_log_spoofing(void **user_info);
extern void susfs_get_enabled_features(void **user_info);
extern void susfs_show_variant(void **user_info);
extern void susfs_show_version(void **user_info);

/* 命令字与补丁 include/linux/susfs_def.h、ksud 侧 susfs/abi/consts.rs 一致 */
#define SUSFS_RB_ADD_SUS_PATH			0x55550u
#define SUSFS_RB_ADD_SUS_PATH_LOOP		0x55553u
#define SUSFS_RB_HIDE_SUS_MNTS_FOR_NON_SU_PROCS	0x55561u
#define SUSFS_RB_ADD_SUS_KSTAT			0x55570u
#define SUSFS_RB_UPDATE_SUS_KSTAT		0x55571u
#define SUSFS_RB_ADD_SUS_KSTAT_STATICALLY	0x55572u
#define SUSFS_RB_SET_UNAME			0x55590u
#define SUSFS_RB_ENABLE_LOG			0x555a0u
#define SUSFS_RB_SET_CMDLINE_OR_BOOTCONFIG	0x555b0u
#define SUSFS_RB_ADD_OPEN_REDIRECT		0x555c0u
#define SUSFS_RB_SHOW_VERSION			0x555e1u
#define SUSFS_RB_SHOW_ENABLED_FEATURES		0x555e2u
#define SUSFS_RB_SHOW_VARIANT			0x555e3u
#define SUSFS_RB_ENABLE_AVC_LOG_SPOOFING	0x60010u
#define SUSFS_RB_ADD_SUS_MAP			0x60020u

static inline int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void **arg)
{
	if ((unsigned int)magic1 != 0xDEADBEEFu || (unsigned int)magic2 != 0xFAFAFAFAu)
		return -EINVAL;

	switch (cmd) {
	case SUSFS_RB_ADD_SUS_PATH:
		susfs_add_sus_path(arg);
		break;
	case SUSFS_RB_ADD_SUS_PATH_LOOP:
		susfs_add_sus_path_loop(arg);
		break;
	case SUSFS_RB_HIDE_SUS_MNTS_FOR_NON_SU_PROCS:
		susfs_set_hide_sus_mnts_for_non_su_procs(arg);
		break;
	case SUSFS_RB_ADD_SUS_KSTAT:
	case SUSFS_RB_ADD_SUS_KSTAT_STATICALLY:
		/* 两者共用一套结构，is_statically 在 payload 里区分 */
		susfs_add_sus_kstat(arg);
		break;
	case SUSFS_RB_UPDATE_SUS_KSTAT:
		susfs_update_sus_kstat(arg);
		break;
	case SUSFS_RB_SET_UNAME:
		susfs_set_uname(arg);
		break;
	case SUSFS_RB_ENABLE_LOG:
		susfs_enable_log(arg);
		break;
	case SUSFS_RB_SET_CMDLINE_OR_BOOTCONFIG:
		susfs_set_cmdline_or_bootconfig(arg);
		break;
	case SUSFS_RB_ADD_OPEN_REDIRECT:
		susfs_add_open_redirect(arg);
		break;
	case SUSFS_RB_ADD_SUS_MAP:
		susfs_add_sus_map(arg);
		break;
	case SUSFS_RB_ENABLE_AVC_LOG_SPOOFING:
		susfs_set_avc_log_spoofing(arg);
		break;
	case SUSFS_RB_SHOW_VERSION:
		susfs_show_version(arg);
		break;
	case SUSFS_RB_SHOW_ENABLED_FEATURES:
		susfs_get_enabled_features(arg);
		break;
	case SUSFS_RB_SHOW_VARIANT:
		susfs_show_variant(arg);
		break;
	default:
		/* set-priority-uid-filter(0x60030) 等本回移版没有实现 */
		return -ENOSYS;
	}

	return 0;
}
#else /* !CONFIG_KSU_SUSFS */
#define ksu_handle_sys_reboot(magic1, magic2, cmd, arg)			(-EINVAL)
#endif /* CONFIG_KSU_SUSFS */

#endif /* _LINUX_ODIN_KSU_HOOKS_H */
