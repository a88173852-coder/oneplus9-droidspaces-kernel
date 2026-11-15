trap 'rc=$?; echo "::error::Configure 第 $LINENO 行失败 rc=$rc: $BASH_COMMAND"' ERR
export PATH="$HOME/clang/bin:$PATH"
cp config/device-stock.config "$KDIR/.config"

# vermagic 逐字对齐原厂（值以 "-" 开头，交给 sed 处理更稳）
sed -i 's|^CONFIG_LOCALVERSION=.*|CONFIG_LOCALVERSION="'"$TARGET_VERMAGIC"'"|' "$KDIR/.config"
sed -i 's|^CONFIG_LOCALVERSION_AUTO=.*|# CONFIG_LOCALVERSION_AUTO is not set|' "$KDIR/.config"
grep -E '^CONFIG_LOCALVERSION' "$KDIR/.config" | tee /dev/stderr | grep -q 'gd2a1055adeb0' \
  || { echo "::error::LOCALVERSION 没写对"; exit 1; }

# 叠加 Droidspaces 配置
cat config/droidspaces.config >> "$KDIR/.config"
# 叠加 SukiSU 配置（CONFIG_KSU）
cat config/sukisu.config >> "$KDIR/.config"

make -C "$KDIR" ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu- \
  KCFLAGS="-D__ANDROID_COMMON_KERNEL__" olddefconfig 2>&1 | tee olddefconfig.log
echo "=== kconfig 告警/错误 ==="
grep -iE "warning|error|recursive" olddefconfig.log | head -30 || echo "  (none)"

echo "=== 关键配置复查（依据 Droidspaces 官方 GKI 清单）==="
# 缺任意一项：容器直接起不来 / 硬件不可用 —— 硬失败
# olddefconfig 会静默丢弃依赖不满足的项，所以必须逐条 grep 验证
fatal="CFI_CLANG NAMESPACES PID_NS UTS_NS IPC_NS SYSVIPC POSIX_MQUEUE DEVTMPFS SECCOMP SECCOMP_FILTER CGROUPS MEMCG"
for sym in $fatal; do
  if grep -q "^CONFIG_${sym}=y" "$KDIR/.config"; then
    printf "  ok    CONFIG_%s=y\n" "$sym"
  else
    echo "::error::CONFIG_${sym} 没开，容器会起不来"; exit 1
  fi
done

# 这两项开了会破坏 kABI，原厂模块全部拒载 —— 必须确认是关的
for sym in CFS_BANDWIDTH CGROUP_PIDS; do
  if grep -q "^CONFIG_${sym}=y" "$KDIR/.config"; then
    echo "::error::CONFIG_${sym} 被打开了，会破坏 kABI"; exit 1
  fi
done

# 推荐项：缺了功能打折，但不影响启动
for sym in USER_NS NETFILTER_XT_MATCH_ADDRTYPE IP6_NF_NAT MACVLAN TMPFS_XATTR \
           BLK_DEV_LOOP EXT4_FS OVERLAY_FS FUSE_FS TUN VETH BRIDGE NET_NS; do
  grep -q "^CONFIG_${sym}=y" "$KDIR/.config" || echo "::warning::CONFIG_${sym} 未开启（功能受限）"
done

grep -E '^CONFIG_LOCALVERSION' "$KDIR/.config"
grep -q '^# CONFIG_LOCALVERSION_AUTO is not set' "$KDIR/.config" \
  || { echo "::error::LOCALVERSION_AUTO 没关掉，vermagic 会带脏尾"; exit 1; }

# 原厂功能对齐：源码把 OPPO_* 改名成 OPLUS_*，不显式开就会静默丢掉
# 指纹是硬失败项：COMMON 不开 -> 链接期 opticalfp_irq_handler_register
# 未定义；GOODIX/QCOM 不开 -> /dev/goodix_fp 不存在，HAL 起来就退出 255
for sym in OPLUS_FINGERPRINT OPLUS_FINGERPRINT_COMMON OPLUS_FINGERPRINT_QCOM \
           OPLUS_FINGERPRINT_GOODIX_OPTICAL OPLUS_FINGERPRINT_JIIOV_OPTICAL; do
  if grep -q "^CONFIG_${sym}=y" "$KDIR/.config"; then
    printf "  ok    CONFIG_%s=y\n" "$sym"
  else
    echo "::error::CONFIG_${sym} 被 olddefconfig 丢掉了，指纹会失效"
    echo "::warning::diag SPI: $(grep -E '^CONFIG_SPI(_MASTER)?=' "$KDIR/.config" | tr '\n' ' ')"
    echo "::warning::diag OPLUS: $(grep -c '^CONFIG_OPLUS' "$KDIR/.config") 项, 指纹 Kconfig 引用: $(grep -c 'oplus_fp_drivers' "$KDIR/drivers/input/Kconfig" 2>/dev/null || echo NA)"
    echo "::warning::diag Kconfig尾: $(tail -3 "$KDIR/drivers/Kconfig" | tr '\n' '|')"
    echo "::warning::diag FINGERPRINT行: $(grep -n 'FINGERPRINT' "$KDIR/.config" | head -4 | tr '\n' '|' | cut -c1-260)"
    echo "::warning::diag inputKconfig: $(grep -n 'oplus_fp_drivers' "$KDIR/drivers/input/Kconfig" | head -2 | tr '\n' '|') / INPUT=$(grep -E '^CONFIG_INPUT=' "$KDIR/.config")"
    echo "::warning::diag olddefconfig: $(grep -iE 'warning|error' olddefconfig.log | head -3 | tr '\n' '|' | cut -c1-260)"
  fi
done
for sym in OPLUS_FEATURE_SCHED_ASSIST DEVTMPFS_MOUNT; do
  grep -q "^CONFIG_${sym}=y" "$KDIR/.config" \
    && printf "  ok    CONFIG_%s=y\n" "$sym" \
    || echo "::warning::CONFIG_${sym} 没开（原厂是开的，功能会缺失）"
done
echo "OPLUS 私有项数量: $(grep -c OPLUS "$KDIR/.config")"

# KSU 是硬失败项：KSU 依赖 KPROBES + EXT4_FS，任一不满足 olddefconfig 会把它悄悄丢掉，
# 编出来的内核看着正常、刷进去没有 root，最难排查。
if grep -q '^CONFIG_KSU=y' "$KDIR/.config"; then
  printf "  ok    CONFIG_KSU=y\n"
else
  echo "::error::CONFIG_KSU 被 olddefconfig 丢掉了（检查 KPROBES / EXT4_FS）"; exit 1
fi
for sym in KSU_MANUAL_SU; do
  grep -q "^CONFIG_${sym}=y" "$KDIR/.config" \
    && printf "  ok    CONFIG_%s=y\n" "$sym" \
    || echo "::warning::CONFIG_${sym} 没开，授权链会依赖管理器常驻"
done
grep -q '^# CONFIG_KPM is not set' "$KDIR/.config" \
  || echo "::warning::CONFIG_KPM 状态不是预期的关闭"
