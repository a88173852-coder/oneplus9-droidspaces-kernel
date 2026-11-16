#!/usr/bin/env python3
"""对 app uid 隐藏 loop 设备 ioctl 返回的 lo_file_name（backing 文件路径）。

## 为什么需要（run45 实证）

现有 patch_loop_hide.py 只挡了 sysfs 的 backing_file show（返回空），
但春秋的「KernelSU loop device: Device: loop42」判据根本不走 sysfs：

    losetup -a  # 走 LOOP_GET_STATUS64 ioctl
    /dev/block/loop42: ... (/data/local/Droidspaces/Containers/ubuntu/rootfs.img)

lo_file_name 由 loop_get_status() 填进 loop_info64，再 copy_to_user 给调用者。
sysfs 挡了、ioctl 没挡 —— 这就是 loop42 一直消不掉的原因。

## 挡法

在 loop_get_status64 / loop_get_status_old 里，loop_get_status() 返回后、
copy_to_user 之前，若 current_uid() >= 10000（普通 app），把
info64.lo_file_name / info.lo_name 清空（填 0）。
这样 app 用 ioctl 看到的 loop 是「未设置文件名」状态，等同 AOSP 空闲 loop。

## 边界

- 只清名字，不动 lo_device/lo_inode/offset/sizelimit 等真实字段：
  vold / apex / 容器自己的 losetup（uid 0）照常工作，不受影响。
- 不做 uid 例外的「root 与 app 结果不一致」比对：sysfs 已经 root 也看不到，
  这里 ioctl 对 app 隐藏、root 可见，属于正常权限差异（app 本来就不该能 losetup）。
- MARK = LOOP_IOCTL_HIDE，幂等。
"""

import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "drivers/block/loop.c"
MARK = "LOOP_IOCTL_HIDE"

try:
    src = open(PATH, encoding="utf-8", errors="surrogateescape").read()
except OSError as e:
    sys.exit(f"读不到 {PATH}: {e}")

if MARK in src:
    print("已有 LOOP_IOCTL_HIDE 标记，跳过")
    sys.exit(0)

# 补 current_uid 需要的头文件
if "#include <linux/cred.h>" not in src:
    inc = "#include <linux/cred.h>\n"
    pos = src.find("#include")
    if pos >= 0:
        end = src.find("\n", pos) + 1
        src = src[:end] + inc + src[end:]
        print("① 已补 #include <linux/cred.h>")

# ---- 1. loop_get_status64 ----
SIG64 = """static int
loop_get_status64(struct loop_device *lo, struct loop_info64 __user *arg) {
	struct loop_info64 info64;
	int err;

	if (!arg)
		return -EINVAL;
	err = loop_get_status(lo, &info64);
	if (!err && copy_to_user(arg, &info64, sizeof(info64)))
		err = -EFAULT;

	return err;
}
"""
if SIG64 not in src:
    sys.exit("锚点没找到：loop_get_status64 函数签名与预期不一致")

NEW64 = """static int
loop_get_status64(struct loop_device *lo, struct loop_info64 __user *arg) {
	struct loop_info64 info64;
	int err;

	if (!arg)
		return -EINVAL;
	err = loop_get_status(lo, &info64);
	/* LOOP_IOCTL_HIDE: 对普通 app 清空 backing 文件名。
	 * 春秋靠 LOOP_GET_STATUS64 读 lo_file_name 发现 loop42 绑了容器镜像。
	 */
	if (!err && current_uid().val >= 10000)
		memset(info64.lo_file_name, 0, sizeof(info64.lo_file_name));
	if (!err && copy_to_user(arg, &info64, sizeof(info64)))
		err = -EFAULT;

	return err;
}
"""
src = src.replace(SIG64, NEW64, 1)
print("② 已注入 loop_get_status64 守卫")

# ---- 2. loop_get_status_old ----
SIGOLD = """	err = loop_get_status(lo, &info64);
	if (!err)
		err = loop_info64_to_old(&info64, &info);
	if (!err && copy_to_user(arg, &info, sizeof(info)))
		err = -EFAULT;

	return err;
}

static int
loop_get_status64"""
if SIGOLD not in src:
    sys.exit("锚点没找到：loop_get_status_old 函数体与预期不一致")

NEWOLD = """	err = loop_get_status(lo, &info64);
	if (!err)
		err = loop_info64_to_old(&info64, &info);
	/* LOOP_IOCTL_HIDE: 旧版 LOOP_GET_STATUS 同样清空文件名 */
	if (!err && current_uid().val >= 10000)
		memset(info.lo_name, 0, sizeof(info.lo_name));
	if (!err && copy_to_user(arg, &info, sizeof(info)))
		err = -EFAULT;

	return err;
}

static int
loop_get_status64"""
src = src.replace(SIGOLD, NEWOLD, 1)
print("③ 已注入 loop_get_status_old 守卫")

open(PATH, "w", encoding="utf-8", errors="surrogateescape").write(src)
print(f"完成：{MARK} 已注入到 {PATH}")
