# 一加9 (ColorOS 14) Droidspaces 内核 · 云编译

给一加9（LE2110，ColorOS 14，内核 5.4.254-qgki）编译一个支持 Droidspaces 容器的内核，
**其余配置保持原厂不动**，只多出容器需要的命名空间和 IPC 能力。

## 为什么走云编译

本机没法编：WSL 被安全策略禁用、没有 Docker、C 盘只剩 64 GB。
Android 5.4 内核带 LTO 编一次要 60 GB 空间和 20 分钟以上，普通 Windows 环境跑不了。
GitHub Actions 免费，跑完直接下载 Image。

## 三步

### 1. 推到 GitHub

随便建一个仓库（public，免费额度够），然后把本目录推上去：

```bash
cd oneplus9-droidspaces-kernel
git init -b main
git add -A
git commit -m "oneplus9 droidspaces kernel build"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

`.github/` 是隐藏目录，别被漏掉（`git add -A` 会带上）。

### 2. 跑 workflow

仓库页面 → Actions → 左侧 `build-oneplus9-droidspaces` → Run workflow。
大约 30–60 分钟。绿色对勾表示成功。

产物在 Run 页面的 Artifacts 里，关键文件是 `Image`（aarch64 内核）、`crc-report.txt`（兼容性报告）。

**如果最后一步 Gate 变红**，说明厂商模块 CRC 对不上，这个内核刷了起不来，别用。

### 3. 刷入

不要直接刷 Image，要把它塞回原厂 boot 镜像里，保留 Magisk 和 ramdisk：

```bash
# 把新内核和原厂 boot 备份放到手机上
adb push Image /sdcard/Image
adb push backups/boot_2026-11-15/boot_b.img /sdcard/boot_b.img

# 在手机上拆包 → 换内核 → 重新打包
adb shell su -c 'cd /sdcard && mkdir -p bw && cd bw && \
  magiskboot unpack ../boot_b.img && \
  cp ../Image kernel && \
  magiskboot repack ../boot_b.img new-boot.img'

adb pull /sdcard/bw/new-boot.img

# 进 fastboot 刷入（只刷 b 槽）
adb reboot bootloader
fastboot getvar current-slot     # 必须是 b
fastboot flash boot_b new-boot.img
fastboot reboot
```

开机后验证：

```bash
adb shell su -c 'unshare -p true && echo PID_OK'
adb shell su -c 'unshare -i true && echo IPC_OK'
adb shell su -c 'unshare -U true && echo USER_OK'
```

三条都出 OK，就可以装 Droidspaces APK 了。

## 刷进去会不会变砖

分两层看，结论是**不可恢复的砖基本不可能，可恢复的起不来有真实概率**。

| 风险 | 概率 | 后果 | 能否恢复 |
|---|---|---|---|
| 分区表 / bootloader 损坏 | 约等于 0 | 真砖 | 只能 EDL + MSM 工具 |
| 内核起不来（卡开机动画、循环重启） | 中等 | 进不了系统 | 能，fastboot 刷回，5 分钟 |
| 厂商模块拒绝加载（CRC/vermagic 不符） | 低（已加校验门禁） | 无显示、无 WiFi | 能，同上 |
| 数据丢失 | 0 | — | 刷 boot 不碰 userdata |
| 丢指纹 / 丢 IMEI | 0 | — | 只要不碰 persist / modemst |

为什么内核坏了也一定能救：**bootloader 在独立分区**（`abl`/`xbl`），跟 `boot` 里的内核完全无关。
关机后按住音量上+下插 USB 就能进 fastboot，刷回备份即可。

已经准备好的救援材料：

- `backups/boot_2026-11-15/` — boot/vendor_boot/dtbo/vbmeta 双槽，md5 已与手机分区逐字节核对
- `restore_boot_b.bat` — 双击即刷回当前可用状态（含 Magisk）
- **2026-11-15 已实测走通整条救援链路**：进 fastboot → 刷 boot_b → 开机 → 分区 md5 与备份完全一致，全程 5 秒

关于 a 槽：实测 `fastboot getvar slot-successful:a` 返回 **no**，a 槽没有"启动成功"标记，
`--set-active=a` 不一定能开机。**唯一可靠的兜底就是在 b 槽刷回备份**，不要指望切槽。

**真正不可逆的只有三种操作**，编译内核都碰不到：刷错分区（`abl`/`xbl`/`persist`/`modemst`）、
`fastboot flashing lock` 重新上锁、`fastboot erase` 引导分区。

## 这个仓库做了什么

### 补丁（`patches/droidspaces-5.4-kabi.patch`）

改 2 个文件，把 SYSVIPC / POSIX_MQUEUE 需要的字段放进 Android 预留的 ABI padding 槽位：

- `include/linux/sched.h` — `sysvsem` / `sysvshm` 从 `task_struct` 普通位置挪进 `ANDROID_KABI_RESERVE(6..8)`
- `include/linux/sched/user.h` — `mq_bytes` 挪进 `ANDROID_KABI_RESERVE(1)`

这么做是为了**不改 `task_struct` / `user_struct` 的大小和字段偏移**。厂商模块是预编译的，
一旦偏移变了，加载时报 "disagrees about version of symbol module_layout"，直接起不来。

来源：`Gamesmes90/android_kernel_oneplus_sm8350` 提交 `74910bbc3e6a`，
该内核在 Droidspaces 官方社区支持设备列表里，机型就是一加9。

### 配置（`config/droidspaces.config`）

**严格照抄** Droidspaces 官方 `Documentation/Kernel-Configuration.md` 里
"GKI kernels (5.4 and newer)" 章节的 Step 2 配置块，一项不多。

`CONFIG_CFS_BANDWIDTH` 和 `CONFIG_CGROUP_PIDS` 故意不开——官方原文写明
*"These two BREAK the kABI and no patch covers them"*：它们会改调度器和 cgroup 结构体大小，
几千个导出符号 CRC 全变，原厂预编译模块全部拒载。代价是容器用不了 `--cpus` 和 `--pids-limit`，
其它功能不受影响。

> `CONFIG_CGROUP_DEVICE` 不在 GKI 清单里（只出现在 non-GKI 3.18~4.19 那段），
> Requirements 检查表也不查它，所以没开。

### 编译器为什么必须是 clang 11.0.2

手机 `/proc/version` 实机确认：

```
Linux version 5.4.254-qgki-gd2a1055adeb0 (root@kvm-slave-build-s-vendor-04929040)
(Android (6877366 based on r383902b1) clang version 11.0.2, LLD 11.0.2) #1 SMP PREEMPT
Wed Apr 16 13:02:59 CST 2025
```

所以用的是 **`clang-r383902b`**（退回 `clang-r383902`）。
注意 OPPO 源码里 `build.config.common` 写的是 `clang-r416183b`（=12.0.5），
那是 ACK 的默认值，**实际构建没用它**——照它编会让 CFI 类型哈希与厂商模块不一致。
同时 `build.config.common` 里的 `KCFLAGS += -D__ANDROID_COMMON_KERNEL__` 必须保留，原厂就是这么编的。

### 调研过但不需要的东西

| 排查项 | 结论 |
|---|---|
| 模块签名强制（ColorOS 6.6 机型要 `trust_stock_cert`） | **不涉及**：本机 `CONFIG_MODULE_SIG is not set`，`.ko` 也无签名段 |
| `xt_qtaguid` 容器网络 panic 补丁（Droidspaces 官方 non-GKI 补丁） | **不需要**：源码里没有 `net/netfilter/xt_qtaguid.c`，配置也无 QTAGUID |
| cgroup 前缀恢复补丁（同上） | **不需要**：5.4 的 `cgroup_file_name()` 已直接生成带前缀的文件名，4.14 那套 symlink 机制在 5.4 不存在 |
| `droidspaces-lkm` / `lkm4ctr` 免刷内核的 LKM 方案 | **不可用**：最低支持 5.10，没有 5.4 |

参考仓库：
[`Gamesmes90/android_kernel_oneplus_sm8350`](https://github.com/Gamesmes90/android_kernel_oneplus_sm8350)（同芯片同内核，补丁来源）、
[`ssyclr/op13t-droidspaces-oki`](https://github.com/ssyclr/op13t-droidspaces-oki)（ColorOS 17，保持 kABI 一致的完整方法论）、
[`liyunkeee/op7pro-droidspaces-kernel`](https://github.com/liyunkeee/op7pro-droidspaces-kernel)（原厂源码直编）

### 兼容性门禁（`checks/`）

`checks/vendor-crc-baseline.json.gz` 是从这台手机上导出的 99 个厂商模块里提取的：

- 每个模块依赖的导出符号 → 它编译时看到的 CRC（取自 `.ko` 的 `__versions` 段）
- vermagic：`5.4.254-qgki-gd2a1055adeb0 SMP preempt mod_unload modversions aarch64`

编译完成后，CI 会把新内核的 `Module.symvers` 跟这份基线逐条比对（2098 条依赖），
不匹配就让 job 变红。**这是刷机前唯一的客观保险**，比"试试看"强。

手册里核对一遍：

```bash
cd kernel-check
python check_vendor_crc.py baseline vendor-modules -o my-baseline.json   # 重新生成基线
python check_vendor_crc.py verify my-baseline.json path/to/Module.symvers
```

## 还没有验证的部分

- 这套配置只在一加9 + LineageOS 上被别人验证过，**ColorOS 14 上没人跑过**，你是第一个。
- OPPO 的 QGKI 树里有一堆 `CONFIG_OPLUS_*` 私有项，olddefconfig 可能会丢掉个别项，
  workflow 会把实际生效的 `.config` 一起传上来，可以对照 `config/device-stock.config` 看差异。
- 万一编译报错（大概率是 LTO + clang 11 的环境问题），把 `build.log` 发我，改 workflow 再跑。
