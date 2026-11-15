/* SPDX-License-Identifier: GPL-2.0 */
/*
 * SUSFS 2.3.0 的 5.4 回移补丁里，fs/*.c 的 hook 点是按 ReSukiSU
 * 「manual hook」那一套写的：补丁会自带一份 include/linux/odin_ksu_hooks.h，
 * 里面声明 ksu_handle_execveat/faccessat/stat/sys_read 等函数，并在 fs 里调用。
 *
 * SukiSU-Ultra 走的是 tracepoint hook（syscall_event_bridge.c），函数名是
 * ksu_handle_*_sucompat，签名完全不同 —— 直接编会 undefined reference。
 *
 * 这些 hook 属于 KSU 自己的 su 兼容逻辑，跟 SUSFS 本体无关：SUSFS 的隐藏能力
 * 由 fs/susfs.c + 各 fs 文件里的 susfs_* 分支提供。SukiSU 已经在 tracepoint
 * 层做完 su 兼容，所以这里给空实现，编译通过且不改变 SUSFS 行为。
 *
 * 用法：打完 susfs 补丁后，用本文件覆盖补丁生成的那份同名头。
 */
#ifndef _LINUX_ODIN_KSU_HOOKS_H
#define _LINUX_ODIN_KSU_HOOKS_H

#include <linux/types.h>
#include <linux/compiler_types.h>
#include <linux/version.h>

struct filename;

#ifdef CONFIG_KSU

#if defined(CONFIG_KSU_MANUAL_HOOK) && defined(CONFIG_KSU_SUSFS)
#error "KSU manual hook 与 SUSFS inline hook 互斥，SukiSU 不应同时开启"
#endif

/*
 * 只有当 KSU 没有提供同名符号时才补空实现。
 * SukiSU 用的是 xxx_sucompat 命名，这里不会撞名。
 */
#ifndef KSU_ODIN_SHIM_NO_EXECVEAT
static inline int ksu_handle_execveat(int *fd, struct filename **filename,
				      void *argv, void *envp, int *flags)
{
	return 0;
}

static inline int ksu_handle_post_execve(int *fd, const char *filename,
					 void *argv, void *envp,
					 int *flags, int *retval)
{
	return 0;
}
#endif

static inline void ksu_handle_sys_read(unsigned int fd)
{
}

static inline void ksu_handle_vfs_fstat(int fd, loff_t *size)
{
}

#ifdef CONFIG_KSU_SUSFS
#define TIF_PROC_IN_KSU_EXECVE 61
#endif

static inline int ksu_handle_faccessat(int *dfd, struct filename **filename,
				       int *mode, int *flags)
{
	return 0;
}

static inline int ksu_handle_stat(int *dfd, struct filename **filename,
				  int *flags)
{
	return 0;
}

static inline int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid)
{
	return 0;
}

static inline int ksu_handle_input_handle_event(unsigned int *type,
						unsigned int *code, int *value)
{
	return 0;
}

static inline int ksu_handle_sys_reboot(int magic1, int magic2,
					unsigned int cmd, void __user **arg)
{
	return 0;
}

#endif /* CONFIG_KSU */

#endif /* _LINUX_ODIN_KSU_HOOKS_H */
