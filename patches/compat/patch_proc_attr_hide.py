#!/usr/bin/env python3
"""给 app uid 隐藏 /proc/<pid>/attr/* 里的 ksu SELinux 上下文字符串。

## 为什么需要（春秋 4.6.3 实证）

「设备取得ROOT权限/异常模块」项的详细说明写死：
    检测到 SELinux 上下文关键词：u:r:ksu:s0, u:object_r:ksu_file:s0

春秋 app 自己跑在 u:r:untrusted_app:s0，它读自己的 attr 不会是 ksu。
它是**遍历 /proc/<pid>/attr/current** 读所有进程的 context，
命中 ksud / zn-daemon / droidspaces 容器里一堆 u:r:ksu:s0 进程，
于是断定设备已 root。

## 为什么在 proc_pid_attr_read 里改

这是内核读 /proc/<pid>/attr/* 的唯一入口（5.4 fs/proc/base.c）。
在 security_getprocattr 返回后、simple_read_from_buffer 之前，
若调用者 uid >= 10000（普通 app）且字符串含 ksu 关键词，
就地替换成 u:r:untrusted_app:s0（长度不足则用空格补齐，保持 length 不变，
避免动 simple_read_from_buffer 的偏移逻辑）。

## 边界

- 只挡 uid >= 10000，root/shell/system 完全不受影响
- 只改返回给 app 的字符串副本 p（内核态 kmalloc 的 buffer），不改真实 context
- 用 memcmp/strstr 匹配，避免误伤普通进程
- MARK = PROC_ATTR_HIDE，幂等
"""

import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "fs/proc/base.c"
MARK = "PROC_ATTR_HIDE"

try:
    src = open(PATH, encoding="utf-8", errors="surrogateescape").read()
except OSError as e:
    sys.exit(f"读不到 {PATH}: {e}")

if MARK in src:
    print("已有 PROC_ATTR_HIDE 标记，跳过")
    sys.exit(0)

SIG = """static ssize_t proc_pid_attr_read(struct file * file, char __user * buf,
				  size_t count, loff_t *ppos)
{
	struct inode * inode = file_inode(file);
	char *p = NULL;
	ssize_t length;
	struct task_struct *task = get_proc_task(inode);
"""
if SIG not in src:
    sys.exit("锚点没找到：proc_pid_attr_read 函数签名与预期不一致")

# 替换点：security_getprocattr 调用之后紧跟的 put_task_struct(task);
ANCHOR = """				      &p);
	put_task_struct(task);
	if (length > 0)
"""
if ANCHOR not in src:
    sys.exit("锚点没找到：security_getprocattr 之后的 put_task_struct")

GUARD = """				      &p);
	put_task_struct(task);
	/* PROC_ATTR_HIDE: 对普通 app 隐藏 ksu/ksu_file 上下文字符串。
	 * 春秋靠遍历 /proc/<pid>/attr/current 命中 u:r:ksu:s0 判定 root。
	 * 只替换返回给 app 的临时 buffer，不改进程真实 context。
	 */
	if (length > 0 && current_uid().val >= 10000 && p) {
		if (strstr(p, "u:r:ksu:s0") || strstr(p, "u:object_r:ksu_file:s0")) {
			/* p 的容量就是 length，绝不能写入超过 length 字节。
			 * 全填 ' ' 后再写截断的假 context，春秋只做字符串包含匹配，
			 * 看到 u:r:untrusted_app 就不会命中 ksu 关键词。 */
			memset(p, ' ', length);
			memcpy(p, "u:r:untrusted_app:s0",
			       min_t(size_t, length, sizeof("u:r:untrusted_app:s0") - 1));
		}
	}
	if (length > 0)
"""

src = src.replace(ANCHOR, GUARD, 1)

# 确保 string.h 的 strstr/memset/memcpy 可用（base.c 通常已间接带入，
# 但显式补一条更保险）
if "#include <linux/string.h>" not in src:
    inc = "#include <linux/string.h>\n"
    # 插在第一个 #include 之后
    pos = src.find("#include")
    if pos >= 0:
        end = src.find("\n", pos) + 1
        src = src[:end] + inc + src[end:]

open(PATH, "w", encoding="utf-8", errors="surrogateescape").write(src)
print(f"完成：已注入 {MARK} 守卫到 {PATH}")
