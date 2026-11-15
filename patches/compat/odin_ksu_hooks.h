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
 * 所以这里统一改成「函数式宏」把调用整体抹掉：
 *   - 不引入任何新符号，不会和 SukiSU 的同名函数打架；
 *   - 不产生 (0); 这种空表达式语句（会被 -Wunused-value 抓，本树把 warning 当 error）；
 *   - 语句位置用 do{}while(0)，取返回值的位置（kernel/reboot.c）给 -EINVAL —— 
 *     这条路径只处理 magic 0xDEADBEEF，正常重启走 LINUX_REBOOT_MAGIC1，不受影响。
 *
 * 这些 hook 只承担 KSU 的 su 兼容判定，跟 SUSFS 的隐藏能力（sus_path / sus_mount /
 * uname / cmdline / kstat / open_redirect / sus_map）无关：后者由 fs/susfs.c 与各
 * fs 文件里的 susfs_* 分支实现，不受这里影响。
 */
#ifndef _LINUX_ODIN_KSU_HOOKS_H
#define _LINUX_ODIN_KSU_HOOKS_H

#define ksu_handle_execveat(fd, filename, argv, envp, flags)		do { } while (0)
#define ksu_handle_post_execve(fd, filename, argv, envp, flags, retval)	do { } while (0)
#define ksu_handle_sys_read(fd)						do { } while (0)
#define ksu_handle_vfs_fstat(fd, size)					do { } while (0)
#define ksu_handle_faccessat(dfd, filename, mode, flags)		do { } while (0)
#define ksu_handle_stat(dfd, filename, flags)				do { } while (0)
#define ksu_handle_setresuid(ruid, euid, suid)				do { } while (0)
#define ksu_handle_input_handle_event(type, code, value)		do { } while (0)
#define ksu_handle_sys_reboot(magic1, magic2, cmd, arg)			(-EINVAL)

/* fs/exec.c 里 clear_thread_flag() 用；SukiSU 没占这个位 */
#define TIF_PROC_IN_KSU_EXECVE 61

#endif /* _LINUX_ODIN_KSU_HOOKS_H */
