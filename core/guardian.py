#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 守卫统一引擎（S3 · 归一化全生命周期动态自适应分发调用前身）

功能：把 config_sync.py 的同步全量检查结果 + S4 反向守卫族（guardian_reverse），
      按 guardian.yaml 注册中心的守卫元数据归类（guard→msgs）、裁剪（--phase /
      --guard）、摘要报告——守卫从"整体快照"升级为"注册可查 · 分类可看 · 单点可跑"。

设计：
  - 归一化定义：references/config/guardian.yaml（id/severity/phase/trigger/data/level/exempt）
  - 归类规则：config_sync 输出 messages 带前缀（[文件健康①] [字典注册] [Key 健康⑬]
              [四件套⑭] [契约⑮] [行业包⑯] [行业包⑯-KW] [T1.6 标签一致性]），
              反向守卫族带 [反向R1]~[反向R5]，按 alias 前缀匹配归属守卫
              （未匹配 → g_unclassified）
  - 裁剪：--phase <register|inject|run|decision> 只展示该阶段守卫；--guard <id> 只跑单守卫
          （g_capacity 由核心容器消费方覆盖；g017 反向族由 guardian_reverse 提供，
           phase=decision 即决策校准环）
  - 输出：与 config_sync --check 文本完全兼容（严重问题/警告计数 + 过滤后明细）

用法：
  python3 core/guardian.py --check              # 全量（CI 入口 · 替换 config_sync --check）
  python3 core/guardian.py --phase decision     # 决策校准环（含 g017 反向族）
  python3 core/guardian.py --level kw           # S7a 分级响应（kw 及以上守卫）
  python3 core/guardian.py --nightrun           # S7c 夜巡（决策环 + 校准器跨周期推进）
  python3 core/guardian.py --guard g017_r3_usage_cal  # 单反向守卫（R3 使用事实校准）
  python3 core/guardian.py --registry           # 守卫注册摘要
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARDIAN_CFG = ROOT / "references" / "config" / "guardian.yaml"

# 兜底注册表（guardian.yaml 缺失时 · 与 config_sync 输出前缀对齐）
FALLBACK = [
    {"id": "g000_core", "alias": ["T1.6 标签一致性"], "severity": "error"},
    {"id": "g001_dangling_ref", "alias": ["文件健康①"], "severity": "error"},
    {"id": "g002_deprecated", "alias": ["文件健康②"], "severity": "error"},
    {"id": "g003_ownership", "alias": ["文件健康③"], "severity": "error"},
    {"id": "g004_test_archive", "alias": ["文件健康④"], "severity": "warn"},
    {"id": "g005_nested_link", "alias": ["文件健康⑤"], "severity": "error"},
    {"id": "g006_capacity_files", "alias": ["文件健康⑥"], "severity": "warn"},
    {"id": "g007_qcm_hardcode", "alias": ["文件健康⑦"], "severity": "error"},
    {"id": "g008_plugins", "alias": ["文件健康⑧"], "severity": "warn"},
    {"id": "g009_cross_skill_hardcode", "alias": ["文件健康⑨"], "severity": "error"},
    {"id": "g010_ref_exists", "alias": ["文件健康⑩"], "severity": "error"},
    {"id": "g011_dict_registry", "alias": ["字典注册"], "severity": "error"},
    {"id": "g012_rglob_scan", "alias": ["文件健康⑫"], "severity": "error"},
    {"id": "g013_key_health", "alias": ["Key 健康⑬"], "severity": "warn"},
    {"id": "g014_four_aspect", "alias": ["四件套⑭"], "severity": "warn"},
    {"id": "g015_contract", "alias": ["契约⑮"], "severity": "warn"},
    {"id": "g016_pack_registry", "alias": ["行业包⑯"], "severity": "error"},
    {"id": "g016_kw_injected", "alias": ["行业包⑯-KW"], "severity": "warn"},
]

_registry = None
_loaders = None


def load_registry(force: bool = False) -> list:
    """加载守卫注册中心（guardian.yaml · 缺失用兜底表）"""
    global _registry
    if _registry is not None and not force:
        return _registry
    regs = list(FALLBACK)
    try:
        if GUARDIAN_CFG.exists():
            import yaml
            data = yaml.safe_load(GUARDIAN_CFG.read_text(encoding="utf-8")) or {}
            y_regs = data.get("guardians") if isinstance(data, dict) else None
            if isinstance(y_regs, list) and y_regs:
                regs = y_regs
    except Exception:
        pass
    _registry = regs
    return _registry


def load_loaders(force: bool = False) -> list:
    """加载懒加载语料对象元数据（guardian.yaml loaders 段 · R18 P3）

    返回 [{object, level, group, freq, note, source?}] · 缺失时返回 [] 空表
    （消费方：--registry 摘要、load_plan 分发、anchors 登记门 g011）

    V8.6 overlay：在 guardian.yaml 既有 loaders 之上，叠加 corpus_manifest.yaml
    派生条目（自动检入新增的语料/excluded 自动进入 loaders，无需改写 guardian.yaml，
    避免 R18 yaml.safe_dump 破坏注释）。按 object(stem) 去重，已登记不重复添加。
    """
    global _loaders
    if _loaders is not None and not force:
        return _loaders
    _loaders = []
    try:
        if GUARDIAN_CFG.exists():
            import yaml
            data = yaml.safe_load(GUARDIAN_CFG.read_text(encoding="utf-8")) or {}
            lds = data.get("loaders") if isinstance(data, dict) else None
            if isinstance(lds, list):
                _loaders = list(lds)
    except Exception:
        pass
    # overlay：manifest 派生 loaders（自动检入 · 不重写 guardian.yaml）
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from corpus_manifest import load_manifest
        m = load_manifest()
        existing = {l.get("object") for l in _loaders if isinstance(l, dict)}
        for sec in ("corpus", "excluded"):
            for e in m.get(sec, []):
                rel = e.get("rel", "")
                stem = rel.split("/")[-1].rsplit(".", 1)[0]
                if not stem or stem in existing:
                    continue
                if sec == "corpus":
                    _loaders.append({"object": stem, "level": e.get("level", "chapter"),
                                     "group": e.get("group", "?"), "freq": e.get("freq", "low"),
                                     "note": e.get("note", ""), "source": "manifest"})
                else:
                    _loaders.append({"object": stem, "level": "index",
                                     "group": e.get("group", "测试族"), "freq": "low",
                                     "note": e.get("note", ""), "source": "manifest"})
                existing.add(stem)
    except Exception:
        pass
    return _loaders


def registry_summary() -> str:
    """守卫注册摘要（--registry）"""
    regs = load_registry()
    lds = load_loaders()
    lines = [f"QCM 守卫注册中心（{GUARDIAN_CFG.name} · {len(regs)} 守卫 · {len(lds)} 懒加载对象）", ""]
    for r in regs:
        if not isinstance(r, dict):
            continue
        rid = r.get("id", "?")
        sev = r.get("severity", "?")
        phase = r.get("phase", "?")
        trig = ",".join(r.get("trigger", []) or [])
        desc = r.get("desc", "") or ""
        lines.append(f"  {rid} [{sev}] phase={phase} trigger=[{trig}] — {desc}")
    if lds:
        lines.append("")
        lines.append(f"-- 懒加载对象（{len(lds)} · P3 loader 元数据）--")
        for l in lds:
            if not isinstance(l, dict):
                continue
            obj = l.get("object", "?")
            lv = l.get("level", "?")
            grp = l.get("group", "?")
            fq = l.get("freq", "?")
            nt = l.get("note", "") or ""
            lines.append(f"  loader[{obj}] level={lv} group={grp} freq={fq} — {nt}")
    return "\n".join(lines)


def _match_guard(msg: str, regs: list):
    """按 alias 前缀匹配守卫（最长 alias 优先 · 避免 ⑯ 匹配 ⑯-KW 短路）"""
    best, best_len = None, -1
    for r in regs:
        if not isinstance(r, dict):
            continue
        for a in (r.get("alias") or []):
            if a and a in msg and len(a) > best_len:
                best, best_len = r, len(a)
    return best


def classify(issues: list, warnings: list, regs: list = None) -> dict:
    """把 config_sync 输出按守卫归类

    Returns:
        {"guard_id": {"issues": [...], "warnings": [...]}, ..., "g_unclassified": {...}}
    """
    regs = regs if regs is not None else load_registry()
    out = {}
    for msg in issues:
        g = _match_guard(msg, regs)
        gid = g.get("id", "g_unclassified") if g else "g_unclassified"
        out.setdefault(gid, {"issues": [], "warnings": []})["issues"].append(msg)
    for msg in warnings:
        g = _match_guard(msg, regs)
        gid = g.get("id", "g_unclassified") if g else "g_unclassified"
        out.setdefault(gid, {"issues": [], "warnings": []})["warnings"].append(msg)
    return out


def _is_in_phase(guard: dict, phase: str) -> bool:
    ph = guard.get("phase", "register")
    if isinstance(ph, list):
        return phase in ph
    return str(ph) == phase


def _is_in_trigger(guard: dict, trigger: str) -> bool:
    """触发闭环（S8 · 让 trigger 元数据真正驱动选择，而非仅 registry_summary 展示）"""
    tr = guard.get("trigger", [])
    if isinstance(tr, str):
        tr = [tr]
    return trigger in (tr or [])


def _level_rank(level: str) -> int:
    """分级响应等级顺序（S7a）：l0 最轻 · full 最全"""
    order = {"l0": 0, "kw": 1, "adaptive": 2, "l2": 3, "full": 4}
    return order.get(level, 4)  # 未知级默认 full


def _is_in_level(guard: dict, level: str) -> bool:
    """守卫 level 是否满足裁剪（level 要求 ≥ 裁剪级 · S7a 分级响应）
    --level full → 全部；--level kw → 只要 kw 及以上（kw/adaptive/l2/full）"""
    gl = guard.get("level", "full")
    if isinstance(gl, list):
        gl = gl[-1]  # 多级取最高
    return _level_rank(str(gl)) >= _level_rank(level)


def run(phase: str = None, guard: str = None, level: str = None, trigger: str = None) -> tuple:
    """运行（裁剪）守卫检查 · 懒加载式（S7.5 评估落地）

    - 正向前置守卫（g001~g016）：config_sync.check_consistency 全量结果
    - 反向守卫族（g017_R1~R6）：guardian_reverse.check_all（S4 · 落库词源←使用事实）
    - 两路消息合并后统一归类/裁剪（--phase decision 会包含 g017 族）
    - S7a 分级响应：--level <full|l2|adaptive|kw|l0> 按守卫 level 元数据裁剪
    - S7.5 懒加载：--level l0/kw/adaptive（轻量模式）跳过 config_sync 全量文件扫描
      （file_health_check ~800ms · 轻量模式仅跑 role 校验 + 反向守卫 + 轻量段）
      → 目标：节省 token / 提高运行效率（夜巡/高频调用走轻量路径）

    Returns:
        (filtered_issues, filtered_warnings, summary_dict)
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "core"))

    # S7.5 懒加载：轻量级（l0/kw/adaptive）→ 跳过 config_sync 全量扫描
    is_light = level in ("l0", "kw", "adaptive")
    if is_light:
        # 轻量路径：仅 role 配置一致性（check_consistency 的轻量子集 · 不跑 file_health）
        try:
            import config_sync as _cs
            # 复用 check_consistency 但跳过文件层（将 file_health 结果置空）
            _orig_fh = _cs.file_health_check
            _cs.file_health_check = lambda: ([], [])
            all_issues, all_warnings = _cs.check_consistency()
            _cs.file_health_check = _orig_fh
        except Exception:
            all_issues, all_warnings = [], []
    else:
        from config_sync import check_consistency
        all_issues, all_warnings = check_consistency()

    # S4 反向守卫族（g017_r1~r6 · 全为 warn 级别）
    from guardian_reverse import check_all
    r_issues, r_warnings = check_all()
    all_issues += r_issues
    all_warnings += r_warnings

    # S8 治理守卫族（g023~g028 · governance_check 执行层 · 接入已有守卫机制）
    try:
        sys.path.insert(0, str(ROOT / "core"))
        from governance_check import check_all as _gov_check
        g_issues, g_warnings = _gov_check()
        all_issues += g_issues
        all_warnings += g_warnings
    except Exception:
        pass

    regs = load_registry()

    # S7a 分级响应：按 level 裁剪守卫集合（l0 预留 · 当前无 l0 守卫则退化为 kw）
    if level and level != "full":
        regs = [r for r in regs if isinstance(r, dict) and _is_in_level(r, level)]

    # S8 触发闭环：按 trigger 裁剪守卫集合（让 guardian.yaml 的 trigger 元数据真正驱动选择）
    if trigger:
        regs = [r for r in regs if isinstance(r, dict) and _is_in_trigger(r, trigger)]

    if guard:
        g = next((r for r in regs if isinstance(r, dict) and r.get("id") == guard), None)
        if not g:
            print(f"❌ 未知守卫: {guard}（--registry 查看全部）")
            return None, None, None
        # 单守卫语义：先按守卫 alias 精确过滤消息（反向守卫族由 guardian_reverse 提供）
        aliases = [a for a in (g.get("alias") or []) if a]
        if aliases:
            f_i = [m for m in all_issues if any(a in m for a in aliases)]
            f_w = [m for m in all_warnings if any(a in m for a in aliases)]
            return f_i, f_w, {guard: {"issues": f_i, "warnings": f_w}}
        cls = classify(all_issues, all_warnings, [g])
        return cls.get(guard, {"issues": [], "warnings": []})["issues"], \
            cls.get(guard, {"issues": [], "warnings": []})["warnings"], cls

    if phase:
        ph_regs = [r for r in regs if isinstance(r, dict) and _is_in_phase(r, phase)]
        cls = classify(all_issues, all_warnings, ph_regs)
        keep = {}
        # 归一化可见性：phase 命中的守卫即使 0 消息也列出（✅ 无异常）
        # （g019/g_capacity 等配置型守卫无消费方消息时仍须在夜巡视图可见）
        seen = {r.get("id") for r in ph_regs}
        for gid in [r.get("id") for r in ph_regs]:
            if gid in cls:
                keep[gid] = cls[gid]
            else:
                keep[gid] = {"issues": [], "warnings": []}
        keep["g_unclassified"] = cls.get("g_unclassified", {"issues": [], "warnings": []})
        f_i = [m for v in keep.values() for m in v["issues"]]
        f_w = [m for v in keep.values() for m in v["warnings"]]
        return f_i, f_w, keep

    cls = classify(all_issues, all_warnings, regs)
    return all_issues, all_warnings, cls


def report(issues: list, warnings: list, cls: dict = None) -> None:
    """输出（对齐 config_sync --check 文本格式 · CI 兼容）"""
    print("=" * 70)
    print("QCM 守卫检查（guardian 引擎）")
    print("=" * 70)
    print(f"严重问题：{len(issues)} 项")
    print(f"警告：{len(warnings)} 项")
    if cls:
        for gid in sorted(cls.keys()):
            v = cls[gid]
            n_issue, n_warn = len(v["issues"]), len(v["warnings"])
            ph = ""
            g = next((r for r in load_registry() if isinstance(r, dict) and r.get("id") == gid), None)
            if g:
                ph = f"phase={g.get('phase', '?')}"
            print(f"  [{gid}] {ph} 严重 {n_issue} · 警告 {n_warn}")
    if issues:
        print("\n❌ 严重问题：")
        for i in issues:
            print(f"   {i}")
    if warnings:
        print("\n⚠️ 警告：")
        for w in warnings:
            print(f"   {w}")
    if not issues and not warnings:
        print("\n✅ 配置完全一致")
    print()


def selfcheck() -> int:
    """S8 治理自检：兜底表⊆注册中心 + 组件双路一致 + 治理注册表归一化。
    返回 0=全绿 1=存在偏差（供 CI/nightrun 判定）。"""
    import yaml
    ok = True
    print("=" * 70)
    print("QCM 治理自检（guardian --selfcheck · S8 归一化闭环）")
    print("=" * 70)

    # ① FALLBACK ⊆ registry
    reg = load_registry()
    reg_ids = {r.get("id") for r in reg if isinstance(r, dict)}
    fb_ids = {r.get("id") for r in FALLBACK if isinstance(r, dict)}
    miss = fb_ids - reg_ids
    if miss:
        ok = False
        print(f"❌ FALLBACK 未进入注册中心：{sorted(miss)}")
    else:
        print(f"✅ FALLBACK({len(fb_ids)}) ⊆ registry({len(reg_ids)})")

    # ② 组件双路一致
    try:
        cfg = yaml.safe_load(open(ROOT / "references" / "config" / "components.yaml", encoding="utf-8"))
        yaml_keys = set(cfg.get("components", {}).keys()) if cfg else set()
        disk = {f[:-3] for f in os.listdir(ROOT / "components") if f.endswith(".md")}
        if yaml_keys == disk:
            print(f"✅ 组件双路一致：yaml {len(yaml_keys)} == 磁盘 {len(disk)}")
        else:
            ok = False
            print(f"❌ 组件双路不一致：yaml-only={sorted(yaml_keys - disk)} disk-only={sorted(disk - yaml_keys)}")
    except Exception as e:
        ok = False
        print(f"❌ 组件双路检查异常：{e}")

    # ③ 治理注册表归一化
    try:
        gp = ROOT / "references" / "config" / "governance_gaps.yaml"
        if not gp.exists():
            ok = False
            print("❌ 治理缺口注册表缺失：governance_gaps.yaml")
        else:
            g = yaml.safe_load(open(gp, encoding="utf-8"))
            gaps = g.get("gaps", [])
            unnorm = [x.get("id") for x in gaps if not x.get("normalized")]
            print(f"✅ 治理注册表存在：{len(gaps)} 缺口 · 未归一化 {len(unnorm)}")
            if unnorm:
                print(f"   ⚠️ 未归一化：{unnorm}")
    except Exception as e:
        ok = False
        print(f"❌ 治理注册表检查异常：{e}")

    print()
    print("✅ 治理自检通过" if ok else "⚠️ 治理自检发现偏差（见上）")
    return 0 if ok else 1


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    if "--registry" in sys.argv:
        print(registry_summary())
        return 0
    if "--trigger" in sys.argv:
        i = sys.argv.index("--trigger")
        trig = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if not trig:
            print("用法: guardian.py --trigger <ci|watch|inject|evolution|nightrun|load>")
            return 2
        fi, fw, cls = run(trigger=trig)
        report(fi, fw, cls)
        return 1 if fi else 0
    if "--nightrun" in sys.argv:
        # S7c 夜巡：决策校准环 + 动态自适应级 + 校准器跨周期推进（遗留1解决）
        # --cron 提示挂载：nightrun 执行一次，可挂 CI cron / 系统定时任务（周频建议）
        print("=" * 70)
        print("QCM 夜巡（S7 · --nightrun · 决策校准环 + 动态自适应）")
        print("=" * 70)
        if "--cron" in sys.argv:
            print("ℹ️  cron 模式：夜巡为一次性执行 · 建议挂周频定时（如 CI schedule 每周五 23:00）")
        # ① 决策环守卫（含反向守卫族 R1-R6 · 动态自适应级 · S7.5 懒加载跳过重扫描）
        fi, fw, cls = run(phase="decision", level="adaptive")
        print(f"夜间守卫复检（decision + adaptive）· 严重 {len(fi)} · 警告 {len(fw)}")
        for w in fw[:20]:
            print(f"   {w}")
        if len(fw) > 20:
            print(f"   ... 等 {len(fw) - 20} 条")
        # ③ 元守卫兜底可见性：g030 发现无论截断必显（registry 漏登/幽灵注册是最致命的静默失效）
        _g030 = cls.get("g030_meta_completeness", {})
        for m in list(_g030.get("issues", [])) + list(_g030.get("warnings", [])):
            print(f"   {m}")
        # ② 校准器跨周期推进（dry-run 两周期 · 夜巡推进周期计数）
        try:
            sys.path.insert(0, str(ROOT / "core"))
            from intent_calibrator import analyze, report as _cal_report
            cands = analyze()  # 在读状态基础上推进 runs
            print("\n-- 意图分布校准器（跨周期推进）--")
            print(_cal_report(cands))
        except Exception as e:
            print(f"ℹ️ 校准器跳转（不可用: {e}）")
        # ③ 实体索引自愈合（源文档演进 → 实体层 auto-checkin · M1.1）
        #    --sync 幂等：源未变更则不触碰 entities.yaml，仅夜巡校验；变更才重生
        sync_rc = 0
        try:
            import subprocess
            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "extract_entities.py"), "--sync"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=120)
            print("\n-- 实体索引自愈合（extract_entities --sync）--")
            for line in (r.stdout or "").strip().splitlines():
                print("   " + line)
            if r.returncode != 0:
                sync_rc = r.returncode
                print(f"   ⚠️ --sync 校验未通过（rc={r.returncode}）")
                for line in (r.stderr or "").strip().splitlines()[:8]:
                    print("   " + line)
        except Exception as e:
            print(f"ℹ️ 实体索引自愈合跳过（不可用: {e}）")
        return 1 if (fi or sync_rc) else 0
    if "--guard" in sys.argv:
        i = sys.argv.index("--guard")
        gid = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        phase = sys.argv[i + 2] if i + 2 < len(sys.argv) and sys.argv[i + 2] in (
            "register", "inject", "run", "decision", "evolution", "load", "watch", "ci", "nightrun") else None
        if not gid:
            print("用法: guardian.py --guard <id> [phase]")
            return 2
        fi, fw, cls = run(guard=gid)
        if fi is None:
            return 2
        if phase:
            # phase 参数附加过滤（不破坏单守卫语义 · 仅当指定）
            pass
        report(fi, fw, cls)
        return 1 if fi else 0
    elif "--phase" in sys.argv:
        i = sys.argv.index("--phase")
        phase = sys.argv[i + 1] if i + 1 < len(sys.argv) else "register"
        level = None
        if "--level" in sys.argv:
            li = sys.argv.index("--level")
            level = sys.argv[li + 1] if li + 1 < len(sys.argv) else None
        fi, fw, cls = run(phase=phase, level=level)
        report(fi, fw, cls)
        return 1 if fi else 0
    elif "--level" in sys.argv:
        # S7a 分级响应：--level <full|l2|adaptive|kw|l0>
        li = sys.argv.index("--level")
        level = sys.argv[li + 1] if li + 1 < len(sys.argv) else "full"
        valid = ("full", "l2", "adaptive", "kw", "l0")
        if level not in valid:
            print(f"❌ 未知级别 {level}（可选: {', '.join(valid)}）")
            return 2
        fi, fw, cls = run(level=level)
        report(fi, fw, cls)
        return 1 if fi else 0
    else:
        # 默认 --check（CI 入口）
        fi, fw, cls = run()
        report(fi, fw, cls)
        return 1 if fi else 0


if __name__ == "__main__":
    sys.exit(main())