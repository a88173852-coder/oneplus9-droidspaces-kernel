#!/usr/bin/env python3
"""sel_write_context 里拒绝翻译 ksu/ksu_file 等 root 特征上下文字符串。

## 为什么需要（run45+keybox 实证）

春秋「设备取得ROOT权限/异常模块」详情：
    检测到 SELinux 上下文关键词：u:r:ksu:s0, u:object_r:ksu_file:s0
    SELinux status: version=1 sequence=0 enforcing=1 ...

之前的 proc attr 补丁无效 —— app 读 /proc/<pid>/attr/current 直接 PERM_DENIED，
根本走不到我们的代码。kprobe 实证 nativecheck_zygote 写 /sys/fs/selinux/context
88 次：它把 u:r:ksu:s0 这类字符串写进 context 接口翻译成 sid，
若翻译成功（说明 KSU 策略加载了）就判定 root。

## 为什么不能像上一版那样直接挡整个 context 节点

run44 教训：zygote specialize 每个 app 都要用 context 接口 setcon，
整个挡掉 = 所有 app SIGABRT 黑屏。所以必须**按内容过滤**：
- 正常 context（u:r:untrusted_app:s0 等）→ 放行
- 含 ksu/ksu_file/magisk 等 root 特征的 → 返回 -EINVAL（假装不存在）

## 挡法

在 sel_write_context 里 avc_has_perm 之后、security_context_to_sid 之前：
    if (strstr(buf, "ksu") || strstr(buf, "magisk") || strstr(buf, "su:s0"))
        return -EINVAL;

只挡查询，不改策略、不改任何进程 context，zygote 正常流程零影响。
MARK = SEL_CONTEXT_FILTER，幂等。
"""

import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "security/selinux/selinuxfs.c"
MARK = "SEL_CONTEXT_FILTER"

try:
    src = open(PATH, encoding="utf-8", errors="surrogateescape").read()
except OSError as e:
    sys.exit(f"读不到 {PATH}: {e}")

if MARK in src:
    print("已有 SEL_CONTEXT_FILTER 标记，跳过")
    sys.exit(0)

# 锚点：sel_write_context 里 avc_has_perm 之后、security_context_to_sid 之前
ANCHOR = """	length = security_context_to_sid(state, buf, size, &sid, GFP_KERNEL);
	if (length)
		goto out;
"""
if ANCHOR not in src:
    sys.exit("锚点没找到：sel_write_context 里的 security_context_to_sid 调用")

GUARD = """	/* SEL_CONTEXT_FILTER: 拒绝把 root 特征上下文翻译成 sid。
	 * 春秋把 u:r:ksu:s0 / u:object_r:ksu_file:s0 写进 context 节点探测，
	 * 翻译成功就认定 KSU 策略存在 → 判定 root。正常 app context 不含这些词。
	 */
	if (size && (strstr(buf, ":ksu:") || strstr(buf, "ksu_file"))) {
		length = -EINVAL;
		goto out;
	}

	length = security_context_to_sid(state, buf, size, &sid, GFP_KERNEL);
	if (length)
		goto out;
"""
src = src.replace(ANCHOR, GUARD, 1)

open(PATH, "w", encoding="utf-8", errors="surrogateescape").write(src)
print(f"完成：已注入 {MARK} 到 {PATH}")
