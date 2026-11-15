#!/usr/bin/env python3
"""厂商内核模块 CRC 基线 / 新内核兼容性检查

用法:
  # 1) 从手机导出的模块生成基线（原厂内核要求的符号 -> CRC）
  python check_vendor_crc.py baseline vendor-modules -o vendor-crc-baseline.json

  # 2) 用新编译内核的 Module.symvers 对比，判断能否安全刷入
  python check_vendor_crc.py verify vendor-crc-baseline.json path/to/Module.symvers

原理:
  Android GKI/QGKI 内核开了 CONFIG_MODVERSIONS，每个厂商 .ko 的 __versions 段
  记录了它编译时依赖的 导出符号 -> CRC。加载时必须与内核 __kcrctab 完全一致，
  否则拒绝加载（insmod 报 "disagrees about version of symbol"）。
  厂商模块是预编译的、没有源码，所以只能让内核去迁就它们。
  因此在刷机前就能算出来会不会加载失败，不必拿手机冒险。
"""

import json
import os
import struct
import sys

SHT_SYMTAB = 2
MODULE_NAME_LEN = 56          # 5.4 的 include/linux/module.h
ENTRY_SIZE = 8 + MODULE_NAME_LEN   # ulong crc + char name[56]


def elf_sections(path):
    """返回 [(name, type, offset, size, link, entsize)], 以及 shstrtab 数据"""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'\x7fELF' or data[4] != 2:
        raise ValueError('%s: 不是 ELF64 文件' % path)
    e_shoff, = struct.unpack_from('<Q', data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', data, 0x3A)
    raw = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name, stype = struct.unpack_from('<II', data, off)
        offset, size = struct.unpack_from('<QQ', data, off + 0x18)
        link, = struct.unpack_from('<I', data, off + 0x28)
        entsize, = struct.unpack_from('<Q', data, off + 0x38)
        raw.append((name, stype, offset, size, link, entsize))
    strtab_off, strtab_size = raw[e_shstrndx][2], raw[e_shstrndx][3]
    shstr = data[strtab_off:strtab_off + strtab_size]

    def name_of(idx):
        end = shstr.find(b'\0', idx)
        return shstr[idx:end].decode('utf-8', 'replace')

    return data, [(name_of(n), t, o, s, l, e) for (n, t, o, s, l, e) in raw]


def parse_versions(path):
    """提取 .ko 里的 __versions: {符号名: crc}"""
    data, secs = elf_sections(path)
    out = {}
    for name, stype, off, size, _link, _entsize in secs:
        if name not in ('__versions', '.__versions'):
            continue
        for pos in range(off, off + size - ENTRY_SIZE + 1, ENTRY_SIZE):
            crc, = struct.unpack_from('<Q', data, pos)
            raw = data[pos + 8:pos + 8 + MODULE_NAME_LEN]
            sym = raw.split(b'\0', 1)[0].decode('utf-8', 'replace')
            if sym:
                out[sym] = crc
    return out


def cmd_baseline(moddir, out_path):
    baseline = {}
    vermagic = set()
    for fn in sorted(os.listdir(moddir)):
        if not fn.endswith('.ko'):
            continue
        p = os.path.join(moddir, fn)
        try:
            vers = parse_versions(p)
        except Exception as exc:
            print('  跳过 %s: %s' % (fn, exc))
            continue
        if not vers:
            continue
        baseline[fn] = {k: '%08x' % v for k, v in vers.items()}
        # vermagic 从 .modinfo 粗读
        with open(p, 'rb') as f:
            blob = f.read()
        i = blob.find(b'vermagic=')
        if i >= 0:
            vermagic.add(blob[i + 9:blob.find(b'\0', i)].decode('utf-8', 'replace'))
        print('  %-38s %4d 个符号' % (fn, len(vers)))

    json.dump({'modules': baseline, 'vermagic': sorted(vermagic)},
              open(out_path, 'w', encoding='utf-8'), indent=1, sort_keys=True)
    print('\n基线已写入 %s' % out_path)
    print('覆盖模块 %d 个，vermagic: %s' % (len(baseline), ' / '.join(sorted(vermagic)) or '未知'))


def parse_symvers(path):
    """Module.symvers: 0x<crc>\t<symbol>\t<module>\tEXPORT_SYMBOL..."""
    out = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2:
                continue
            crc = parts[0].strip().lower()
            if crc.startswith('0x'):
                crc = crc[2:]
            out[parts[1].strip()] = crc
    return out


def cmd_verify(baseline_path, symvers_path):
    base = json.load(open(baseline_path, encoding='utf-8'))
    kernel = parse_symvers(symvers_path)
    bad, missing = {}, {}
    total = 0
    for mod, syms in base['modules'].items():
        for sym, crc in syms.items():
            total += 1
            got = kernel.get(sym)
            if got is None:
                missing.setdefault(sym, []).append(mod)
            elif got != crc:
                bad.setdefault(sym, {'need': crc, 'got': got, 'mods': []})['mods'].append(mod)

    print('检查 %d 个模块 / %d 条符号依赖' % (len(base['modules']), total))
    print('新内核导出符号总数: %d' % len(kernel))
    print()
    if not bad and not missing:
        print('结果: 全部匹配，可以刷。')
        return 0
    if bad:
        print('!! CRC 不一致 %d 个（这些模块会拒绝加载）:' % len(bad))
        for sym, info in sorted(bad.items())[:40]:
            print('   %-40s 需要 %s / 新内核 %s  <- %s' %
                  (sym, info['need'], info['got'], ', '.join(info['mods'][:3])))
    if missing:
        print('!! 新内核未导出 %d 个（同样会加载失败）:' % len(missing))
        for sym, mods in sorted(missing.items())[:40]:
            print('   %-40s <- %s' % (sym, ', '.join(mods[:3])))
    print()
    print('结论: 不要刷。先回到 .config 减少改动，或把配置项关掉重编。')
    return 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if sys.argv[1] == 'baseline':
        return cmd_baseline(sys.argv[2], sys.argv[4] if len(sys.argv) > 4 else 'vendor-crc-baseline.json')
    if sys.argv[1] == 'verify':
        return cmd_verify(sys.argv[2], sys.argv[3])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
