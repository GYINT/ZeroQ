#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 治理守卫执行层（S8 · 归一化治理闭环）

承接 guardian.yaml 中 g023~g028 治理自愈守卫族的定义层登记，提供真实检查函数。

设计：
  - 纯新增执行层，零改动现有引擎；由 core/guardian.py run() 在 --check / --nightrun 时
    自动调用并合并结果（S8 接入已有守卫机制，详见治理成熟度评估）。
  - check_all() 返回 (issues, warnings)，每条消息前缀 [守卫中文别名] 以便 guardian
    按 alias 归类（与 config_sync / guardian_reverse 输出格式对齐）。
  - 全部检查为只读扫描（report-only，符合 M0.4 守卫约束），不改动任何文件。

用法：
  python3 core/governance_check.py --all          # 单独跑全部治理守卫
  python3 core/governance_check.py --guard g026    # 单守卫
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GUARDIAN_CFG = ROOT / "references" / "config" / "guardian.yaml"
GAPS_YAML = ROOT / "references" / "config" / "governance_gaps.yaml"
COMPONENTS_YAML = ROOT / "references" / "config" / "components.yaml"
COMPONENTS_DIR = ROOT / "components"
SKILL_MD = ROOT / "SKILL.md"
MANIFEST = ROOT / "manifest.yaml"
SKILL_META = ROOT / "skill_meta.json"
ACTION_ORDERS = ROOT / "references" / "protocol" / "action-orders.md"
NAMING = ROOT / "references" / "governance" / "naming-convention.md"
DEPLOY = ROOT / "deploy"
ARCHIVE = ROOT / "archive"


def _read(p: Path) -> str:
    try:
        return Path(p).read_text(encoding="utf-8")
    except Exception:
        return ""


def _registry_ids():
    try:
        import yaml
        d = yaml.safe_load(_read(GUARDIAN_CFG)) or {}
        return {g.get("id") for g in d.get("guardians", []) if isinstance(g, dict)}
    except Exception:
        return set()


def check_g023_selfcheck():
    """治理缺口注册表全部进入管理态（开放缺口清零）+ target_guard 引用不变量。

    M1.3 增强：新增『target_guard ∈ registry』不变量校验——
      治理缺口登记表的 target_guard 必须指向 guardian.yaml 中真实注册的守卫 ID。
      若守卫落地时改名（规划名→实现名），此处直接告警列出失效引用，
      杜绝 GAP-RG1/g024_deploy_consistency 式静默漂移（2026-08-26 已对齐 4 处）。
    """
    issues, warns = [], []
    try:
        import yaml
        g = yaml.safe_load(_read(GAPS_YAML)) or {}
        gaps = g.get("gaps", [])
        open_ids = [x.get("id") for x in gaps
                    if x.get("status") not in ("resolved", "retired", "normalized", "watched")]
        if open_ids:
            warns.append("[治理自检] 仍有 %d 个未归一化开放缺口：%s" % (len(open_ids), open_ids))
        # M1.3 不变量：target_guard 必须 ∈ registry（防引用漂移）
        reg_ids = _registry_ids()
        bad_ref = [(x.get("id"), x.get("target_guard")) for x in gaps
                   if x.get("target_guard") and x.get("target_guard") not in reg_ids]
        if bad_ref:
            issues.append("[治理自检] target_guard 引用失效（不在 guardian.yaml 注册中心）：%s"
                          % bad_ref)
    except Exception as e:
        warns.append("[治理自检] 注册表校验跳过：%s" % e)
    return issues, warns


def check_g024_deploy_health():
    """deploy/ 产物健康：无死文件、关键产物存在（孤儿由 corpus 多根扫描覆盖）。"""
    issues, warns = [], []
    if not DEPLOY.exists():
        warns.append("[部署产物健康] deploy/ 不存在")
        return issues, warns
    files = [p for p in DEPLOY.rglob("*") if p.is_file()]
    dead = [str(p.relative_to(ROOT)) for p in files
            if p.suffix in (".tmp", ".bak", ".orig", ".swp", ".DS_Store")]
    if dead:
        issues.append("[部署产物健康] deploy/ 含死文件：%s" % dead)
    for crit in ("deploy/api/openapi.yaml", "deploy/docker/Dockerfile",
                 "deploy/k8s/helm/qcm-mcp/Chart.yaml"):
        if not (ROOT / crit).exists():
            warns.append("[部署产物健康] 关键部署产物缺失：%s" % crit)
    return issues, warns


def check_g025_terminology():
    """设计原则语境禁止『5 大范式』残留；『工具』三义须受控定义（GAP-T2）。

    A+B 扩展（V8.7 · B-3）：意图表一致性不变量——
      naming-convention.md 意图表 == core/ambiguity_resolver.py INTENTS（6 类）
      （复用 scripts/gen_intent_table.py --check 断言 · 文档由代码派生，杜绝二次定义漂移）
    """
    issues, warns = [], []
    for f in (SKILL_MD, MANIFEST):
        t = _read(f)
        for bad in ("5 大范式", "5大范式", "5 范式"):
            if bad in t:
                issues.append("[术语一致] %s 仍残留设计原则旧称『%s』" % (f.name, bad))
    nm = _read(NAMING)
    if "工具" in nm and "三义" not in nm and "受控术语" not in nm:
        warns.append("[术语一致] naming-convention.md 未受控定义『工具』三义（GAP-T2）")
    # B-3 意图表一致性不变量（真源派生 · 复用生成器断言）
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import gen_intent_table as git
        # 仅做纯命中计数无害：调用其 check() 会 import core.router（可能触发 sys.path 副作用）
        # 因此直接内联比对块文本（轻量 · 无副作用）
        intents = git._load_intents()
        expect = "\n".join([git.BEG, " / ".join(intents), git.END])
        import re
        m = re.search(re.escape(git.BEG) + r"(.*?)" + re.escape(git.END), nm, re.S)
        cur = m.group(0) if m else ""
        if cur != expect:
            issues.append("[术语一致] 意图表漂移：naming-convention.md 意图表 != router INTENTS（真源 6 类）· 请运行 scripts/gen_intent_table.py")
    except Exception as e:
        warns.append("[术语一致] 意图表一致性校验跳过：%s" % e)
    return issues, warns


def check_g026_component_dualpath():
    """components.yaml 键集合 == 磁盘 components/*.md（无重复键/孤儿/缺漏）。"""
    issues, warns = [], []
    try:
        import yaml
        cfg = yaml.safe_load(_read(COMPONENTS_YAML)) or {}
        yk = set(cfg.get("components", {}).keys()) if isinstance(cfg, dict) else set()
        dk = {f[:-3] for f in os.listdir(COMPONENTS_DIR) if f.endswith(".md")}
        if yk - dk:
            issues.append("[组件双路一致] yaml 有但磁盘缺 .md：%s" % sorted(yk - dk))
        if dk - yk:
            issues.append("[组件双路一致] 磁盘 .md 但 yaml 未登记：%s" % sorted(dk - yk))
        # 依赖闭合（GAP-L2）：dep 字段引用的母模板须存在（references/outputs/components 多根）
        roots = [ROOT / "outputs", ROOT / "references", ROOT / "components"]
        for comp, meta in (cfg.get("components", {}) or {}).items():
            if not isinstance(meta, dict):
                continue
            for d in (meta.get("dep") or []):
                if d and not any((r / d).exists() for r in roots):
                    warns.append("[组件双路一致] 组件 %s 依赖 %s 不存在（dep 闭合失败）" % (comp, d))
    except Exception as e:
        issues.append("[组件双路一致] 检查异常：%s" % e)
    return issues, warns


def check_g027_bind_consistency():
    """SKILL/manifest/skill_meta 三件套双绑一致（守卫数/协议章数/版本号）。"""
    issues, warns = [], []
    reg = _registry_ids()
    n_reg = len(reg)
    smd = _read(SKILL_MD)
    m = re.search(r"\*\*合计\*\*\s*\|\s*\*\*(\d+)\s*项\*\*", smd)
    n_skill = int(m.group(1)) if m else None
    if n_skill is not None and n_skill != n_reg:
        issues.append("[双绑一致] 守卫数不一致：SKILL.md 声明 %d 项 vs 注册中心 %d 项" % (n_skill, n_reg))
    try:
        import json
        meta = json.loads(_read(SKILL_META)) if SKILL_META.exists() else {}
        mv = meta.get("version")
        mm = re.search(r"version:\s*([0-9.]+)", smd)
        sv = mm.group(1) if mm else None
        if mv and sv and mv != sv:
            issues.append("[双绑一致] 版本不一致：SKILL.md %s vs skill_meta.json %s" % (sv, mv))
    except Exception:
        pass
    return issues, warns


def check_g029_archive_drift():
    """archive/ 编目漂移：实际文件 vs INDEX.md 编目（孤儿/悬空 → 动态自适应闭环 GAP-L1）。"""
    issues, warns = [], []
    try:
        sys.path.insert(0, str(ARCHIVE))
        from inventory import scan_archive_drift
        orphan, stale = scan_archive_drift()
        for p in orphan:
            warns.append("[archive 编目漂移] 退役文件未编目：%s（须补登 archive/INDEX.md）" % p)
        for p in stale:
            warns.append("[archive 编目漂移] 编目悬空（文件不存在）：%s" % p)
    except Exception as e:
        warns.append("[archive 编目漂移] 扫描异常：%s" % e)
    return issues, warns


def check_g028_protocol_version():
    """action-orders 声明章数 == 实际章数；naming 对齐 15/§1-§15；无陈旧章数引用。"""
    issues, warns = [], []
    ao = _read(ACTION_ORDERS)
    dm = re.search(r"(\d+)\s*章", ao)
    actual = len(re.findall(r"^#{1,3}\s*§\d+", ao, re.M))
    if dm:
        dnum = int(dm.group(1))
        if actual != dnum:
            issues.append("[协议版本一致] action-orders 声明 %d 章 vs 实际 %d 章" % (dnum, actual))
    nm = _read(NAMING)
    if re.search(r"13\s*协议术语|§1-§13", nm):
        issues.append("[协议版本一致] naming-convention.md 仍写 13 协议术语/§1-§13（应 15/§1-§15）")
    elif "15 协议术语" not in nm or "§1-§15" not in nm:
        warns.append("[协议版本一致] naming-convention.md 未对齐 15 协议术语/§1-§15")
    # 陈旧章数引用扫描（权威双绑/协议集 · 排除 archive/CHANGELOG/.bak 史实；
    # 负向 (?<!§) 避免误伤合法单章引用『§13』）
    stale_files = [SKILL_MD, MANIFEST, NAMING,
                   ROOT / "docs" / "eval.md",
                   ROOT / "references" / "planning" / "quarterly_update.md"]
    for f in stale_files:
        t = _read(f)
        if re.search(r"(?<!§)13\s*协议|(?<!§)13\s*章|§1-§13|14\s*章|§1-§14", t):
            issues.append("[协议版本一致] %s 含陈旧章数引用（应 15/§1-§15）" % f.name)
    return issues, warns


def check_g031_clarify_drift():
    """澄清率漂移（L3 · 前缀 [澄清率漂移] · core/usage_drift.py::scan_clarify_drift）：
    逐意图澄清率超阈值(>20%)→ 提示阈值/提示词需复盘（report-only · 供 R3 校准器消费）。

    复刻 g029_archive_drift 模板：将"澄清率"登记为治理资产，接入 nightrun 夜巡，
    实现"采样即校验"的动态自适应闭环；仅观测、不写回（写回由 confidence_calibrator --apply 门控）。
    """
    issues, warns = [], []
    try:
        sys.path.insert(0, str(ROOT / "core"))
        from usage_drift import scan_clarify_drift
        drift, _stats = scan_clarify_drift()
        for d in drift:
            warns.append("[澄清率漂移] 意图 %s 澄清率 %.0f%%（澄清 %d / 路由 %d）超阈值 → 建议复盘 clarify_matrix.intent_overrides 或提示词"
                         % (d["intent"], d["rate"] * 100, d["clarified"], d["routed"]))
    except Exception as e:
        warns.append("[澄清率漂移] 扫描异常：%s" % e)
    return issues, warns


def check_g030_meta():
    """元层完备性（M1.4 · g030_meta_completeness · [元守卫] 前缀）：守卫体系自身的归一化闭环。

    A. 实现态↔注册态差集（显式映射表 = guardian.yaml 每项 impl 字段）：
       - 幽灵注册：registry 有 impl 但指向的文件/符号不存在 → warn
       - 缺 impl：registry 项无 impl 字段（新增守卫必须登记实现位置）→ warn
       - 漏登：core/*.py 存在 check_* 守卫函数但无任何注册 impl 指向 → warn
    B. 元数据漂移：guardian_reverse fn_map 支持范围 vs 提示文案（如 r1-r8）→ warn
    C. 治理文件冗余：gap_tracker 重复 query / 行数超健康基线 → warn

    全部发现统一走 warn 通道（与注册 severity: warn 一致 · 确保 --nightrun 警告流可见）。
    fail-open：registry 解析失败 → 显式「元守卫自身失明」warn，绝不静默全绿。
    纯读：无写路径（report-only）。
    """
    issues, warns = [], []

    # ── A1 幽灵注册 / 缺 impl（fail-open 解析） ──
    gs = None
    err = None
    try:
        import yaml
        d = yaml.safe_load(_read(GUARDIAN_CFG)) or {}
        gs = [g for g in d.get("guardians", []) if isinstance(g, dict)]
    except Exception as e:
        err = str(e)
    if gs is None:
        warns.append("[元守卫] registry 解析失败：%s → 元守卫自身失明（fail-open）" % err)
        return issues, warns
    ghost = []
    for g in gs:
        impl_raw = (g.get("impl") or "").strip()
        gid = g.get("id", "?")
        if not impl_raw:
            ghost.append((gid, "缺 impl 字段（新增守卫必须登记实现位置）"))
            continue
        # 多值支持：逗号分隔（如 g026 附加 validator 实现）
        for impl in [x.strip() for x in impl_raw.split(",") if x.strip()]:
            if ":" not in impl:
                ghost.append((gid, "impl 格式错误（应为 文件:符号）：%s" % impl))
                continue
            fname, sym = impl.split(":", 1)
            # 候选路径：裸名 / core/ / scripts/
            cands = [ROOT / fname, ROOT / "core" / fname, ROOT / "scripts" / fname]
            src = ""
            for c in cands:
                if c.exists():
                    src = _read(c)
                    break
            if not src:
                ghost.append((gid, "impl 文件不存在：%s" % impl))
                continue
            if sym.strip() and sym.strip() not in src:
                ghost.append((gid, "impl 符号缺失：%s" % impl))
    for gid, why in ghost:
        warns.append("[元守卫] 幽灵注册/缺登记 %s：%s" % (gid, why))

    # ── A2 漏登：实现 check_* 函数无注册 impl 指向（豁免汇总/工具函数） ──
    EXEMPT = {"check_all", "check_form"}  # 汇总入口 / validator 通用校验
    reg_impls = set()
    for g in gs:
        impl_raw = (g.get("impl") or "").strip()
        for impl in [x.strip() for x in impl_raw.split(",") if x.strip()]:
            reg_impls.add(impl)
    for core_py in sorted((ROOT / "core").glob("*.py")):
        if "test" in core_py.name:
            continue
        src = _read(core_py)
        for fn in re.findall(r"^def (check_[a-z0-9_]+)\(", src, re.M):
            if fn in EXEMPT:
                continue
            impl_ref = "%s:%s" % (core_py.name, fn)
            if impl_ref not in reg_impls:
                warns.append("[元守卫] 漏登候选 %s：实现函数无注册 impl 指向（工具函数请豁免/登记映射）" % impl_ref)

    # ── B 元数据漂移：guardian_reverse fn_map keys vs 提示文案 ──
    rev_src = _read(ROOT / "core" / "guardian_reverse.py")
    m = re.search(r"可选 r1-r(\d+)", rev_src)
    if m:
        fm = re.search(r"fn_map\s*=\s*\{(.*?)\}", rev_src, re.S)
        if fm:
            n_keys = len(re.findall(r'"r\d+"\s*:', fm.group(1)))
            if int(m.group(1)) != n_keys:
                warns.append("[元守卫] 元数据漂移：guardian_reverse fn_map 文案 r1-r%s 与实际支持 %d 个守卫不符" % (m.group(1), n_keys))

    # ── C 治理文件冗余：gap_tracker 重复 query / 行数基线 ──
    tracker = ROOT / "references" / "gap_tracker.md"
    if tracker.exists():
        rows = [ln for ln in _read(tracker).splitlines() if ln.strip().startswith("|")]
        queries = []
        for r in rows[2:]:  # 跳过表头/分隔行
            cells = [c.strip() for c in r.strip("|").split("|")]
            if len(cells) >= 3:
                queries.append(cells[1][:40])
        seen, dups = set(), set()
        for q in queries:
            if q in seen:
                dups.add(q)
            seen.add(q)
        if dups:
            warns.append("[元守卫] gap_tracker 重复登记 %d 组（%s…）→ 建议去重" % (len(dups), " / ".join(sorted(dups)[:3])))
        if len(queries) > 50:
            warns.append("[元守卫] gap_tracker 数据行 %d 超健康基线（>50）→ 建议清理归档" % len(queries))
    return issues, warns


def check_g032_zero_event_obs():
    """M1 归零事件观测守卫：扫描 zero_events.yaml，报告闭环门禁未过 / AO-4 未触发 / 复用待补（report-only）。"""
    issues, warns = [], []
    try:
        import yaml
        p = ROOT / "references" / "data" / "zero_events.yaml"
        if not p.exists():
            return issues, warns
        reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for e in reg.get("events", []):
            eid = e.get("event_id", "?")
            d5 = e.get("dimensions", {}).get("D5_闭环门禁", {})
            if e.get("status") == "registered" and not d5.get("effectiveness_verified", {}).get("ok"):
                warns.append("[归零事件观测] %s 闭环门禁未过（effectiveness_verified.ok=false）→ 须补有效性验证+责任层签名" % eid)
            d8 = e.get("dimensions", {}).get("D8_复发", {})
            if d8.get("recurrence_count", 0) >= 2 and e.get("intent_route") != "②流程优化":
                warns.append("[归零事件观测] %s 复发≥2 但 intent_route=%s（AO-4 复发预防未触发）" % (eid, e.get("intent_route")))
            d7 = e.get("dimensions", {}).get("D7_复用", {})
            if d8.get("recurrence_count", 0) > 0 and d7.get("reuse_rate", 0) == 0:
                warns.append("[归零事件观测] %s 有复发但复用率=0（D7 待补 match_reuse）" % eid)
            # #61-③ G4：水平展开确认缺失（仅对已进入沉淀/复用/收口态的事件观测）
            if e.get("status") in ("deposited", "reused", "resolved"):
                spread = d5.get("h6_spread") or d5.get("horizontal_deployed") or {}
                if not spread.get("ok"):
                    warns.append("[归零事件观测] %s 已沉淀但水平展开未确认（h6_spread.ok=false）→ 审核/水平展开引用前须补水平展开" % eid)
            # #61-③ G5：责任层签名不完整（定义 review_layers 但未全签）
            layers = d5.get("review_layers") or []
            signed = set(d5.get("review_layers_signed") or [])
            if layers and not signed.issuperset(set(layers)):
                warns.append("[归零事件观测] %s 责任层签名不完整（定义 %d 层·已签 %d 层）→ 分层审核未闭环" % (eid, len(layers), len(signed)))
            # #61-③ G6：已沉淀事件未挂 cases.md 锚点（审核/水平展开引用零事件可达性代理观测）
            if e.get("status") in ("deposited", "reused", "resolved"):
                try:
                    from zero_event import resolve_case_ref
                    if resolve_case_ref(eid) is None:
                        warns.append("[归零事件观测] %s 已沉淀但 cases.md 无锚点（审核/水平展开不可引用为案例）→ 须补 §锚点" % eid)
                except Exception:
                    pass
    except Exception as ex:
        warns.append("[归零事件观测] 扫描异常：%s" % ex)
    return issues, warns


CHECKERS = {
    "g023_governance_selfcheck": check_g023_selfcheck,
    "g032_zero_event_obs": check_g032_zero_event_obs,
    "g024_deploy_health": check_g024_deploy_health,
    "g025_terminology_consistency": check_g025_terminology,
    "g026_component_dualpath": check_g026_component_dualpath,
    "g027_bind_consistency": check_g027_bind_consistency,
    "g028_protocol_version": check_g028_protocol_version,
    "g029_archive_drift": check_g029_archive_drift,
    "g030_meta_completeness": check_g030_meta,
    "g031_clarify_drift": check_g031_clarify_drift,
}


def check_all():
    issues, warnings = [], []
    for fn in CHECKERS.values():
        try:
            i, w = fn()
            issues += i
            warnings += w
        except Exception as e:
            warnings.append("[治理自检] %s 异常：%s" % (fn.__name__, e))
    return issues, warnings


def main():
    args = sys.argv[1:]
    if "--guard" in args:
        gid = args[args.index("--guard") + 1]
        fn = CHECKERS.get(gid)
        if not fn:
            print("未知治理守卫：%s" % gid)
            return 2
        i, w = fn()
    else:
        i, w = check_all()
    print("=" * 70)
    print("QCM 治理守卫检查（governance_check.py · S8 执行层）")
    print("=" * 70)
    print("严重问题：%d 项" % len(i))
    print("警告：%d 项" % len(w))
    for x in i:
        print("  ❌ " + x)
    for x in w:
        print("  ⚠️ " + x)
    if not i and not w:
        print("  ✅ 治理守卫全绿")
    print()
    return 1 if i else 0


if __name__ == "__main__":
    sys.exit(main())
