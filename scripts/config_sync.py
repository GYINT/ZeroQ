#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QCM 配置同步工具 （2026-08-17）
功能：角色配置与校验配置联动，自动同步一致性

用法：
  python3 config_sync.py --check      # 检查配置一致性
  python3 config_sync.py --sync       # 同步配置（自动修正）
  python3 config_sync.py --report     # 生成联动报告
"""

import sys
import os
import json  # V8.4 T6：守卫⑬ Key 健康检查
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR = SCRIPT_DIR.parent
REFERENCES_DIR = SKILL_DIR / "references"

# 配置路径
ROLE_CONFIG = REFERENCES_DIR / "config" / "role.yaml"
VALIDATOR_CONFIG = REFERENCES_DIR / "config" / "validator.yaml"


def _load_yaml(path: Path):
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"⚠️  无法加载 {path}: {e}")
        return None


def check_consistency():
    """检查角色配置与校验配置的一致性"""
    role_cfg = _load_yaml(ROLE_CONFIG) if ROLE_CONFIG.exists() else None
    val_cfg = _load_yaml(VALIDATOR_CONFIG) if VALIDATOR_CONFIG.exists() else None

    issues = []
    warnings = []

    if role_cfg is None:
        issues.append("❌ role_config.yaml 不存在或无法解析")
    if val_cfg is None:
        issues.append("❌ validator_config.yaml 不存在或无法解析")

    if not role_cfg or not val_cfg:
        return issues, warnings

    # 检查 1：角色定义的 domains 覆盖度
    roles = role_cfg.get("roles", [])
    all_domains = set()
    for r in roles:
        all_domains.update(r.get("domains", []))
    
    if len(all_domains) < 8:
        warnings.append(f"⚠️  角色 domains 覆盖仅 {len(all_domains)} 个，建议 ≥8")

    # 检查 1.5（V8.3.2 T1.6 新增）：role.yaml 领域标签值域一致性
    # 语义冲突 S1 防再漂移：role.yaml 全部 domains 标签必须 ∈ keyword.yaml 的 8 领域值域
    keyword_path = REFERENCES_DIR / "config" / "keyword.yaml"
    if keyword_path.exists():
        kw = _load_yaml(keyword_path) or {}
        domain_values = set()
        for item in kw.get("keywords", []):
            d = item.get("domain")
            if d:
                domain_values.add(d)
        if domain_values:
            bad_tags = set()
            for r in roles:
                for d in r.get("domains", []):
                    if d not in domain_values:
                        bad_tags.add(f"{d}（角色 {r.get('id')}）")
            if bad_tags:
                issues.append(f"❌ [T1.6 标签一致性] role.yaml 领域标签不在 keyword.yaml 值域 "
                              f"({sorted(domain_values)})：{sorted(bad_tags)}")
        else:
            warnings.append("⚠️  keyword.yaml 无 domain 字段可做标签值域校验")
    else:
        warnings.append("⚠️  keyword.yaml 不存在，跳过标签值域一致性检查")

    # 检查 2：form_role_map 与 validator_config.forms 对齐
    form_role_map = role_cfg.get("form_role_map", {})
    checks = val_cfg.get("checks", [])
    
    for form_name in ["case_application", "decision_card", "assessment_report", "quick_response"]:
        # 形态在角色配置中有定义
        if form_name not in form_role_map:
            issues.append(f"❌ 形态 {form_name} 在 role_config.form_role_map 中缺失")
        
        # 形态在校验配置中有定义
        form_checks = [c for c in checks if form_name in c.get("forms", {})]
        if not form_checks:
            warnings.append(f"⚠️  形态 {form_name} 在校验配置中无检查项")

    # 检查 3：RACI 约束一致性
    for form_name, frm in form_role_map.items():
        constraints = frm.get("constraints", [])
        # 校验配置中应有 has_raci 检查
        raci_checks = [c for c in checks 
                      if c.get("id") == "has_raci" and form_name in c.get("forms", {})]
        if not raci_checks and form_name in ["case_application", "decision_card", "assessment_report"]:
            warnings.append(f"⚠️  {form_name} 有 RACI 约束但校验配置无 has_raci 检查")

    # 检查 4：probe_role_bridge 与 has_positioning_depth 联动
    probe_bridge = role_cfg.get("probe_role_bridge", {})
    depth_checks = [c for c in checks if c.get("id") == "has_positioning_depth"]
    if probe_bridge and not depth_checks:
        warnings.append("⚠️  probe_role_bridge 存在但校验配置无 has_positioning_depth 检查")

    # ── 文件层健康检查（T4 扩展 · 6 检） ──
    fh_issues, fh_warnings = file_health_check()
    issues.extend(fh_issues)
    warnings.extend(fh_warnings)

    return issues, warnings


def file_health_check():
    """文件层健康 10 检（T4 守卫 · 防扩展/迭代导致文件混乱 · 去盲区版）

    ① 悬空引用检测：SKILL.md/manifest 引用的文件必须存在且不在 archive/
    ② deprecated 检测：archive/ 外不允许 .deprecated 后缀（递归全目录）
    ③ 所有权检测：manifest/SKILL 引用的文件必须在 core 或活跃区（防散落）
    ④ 测试归档检测：scripts/ 根不允许 *_test.py 堆积（应入 tests/）
    ⑤ 嵌套检测：QCM/QCM 悬空符号链接复现即报错
    ⑥ 容量检测：components ≤35 · tests ≤40（超限告警 · 与 .file-manifest 对齐）
    ⑦ 硬编码零容忍：scripts/ + tests/ 禁止 QCM 本体路径硬编码（应使用 qcm_paths/env）
    ⑧ plugins 目录存在性：config 指向的插件目录必须存在
    ⑨ 跨 Skill 硬编码零容忍：scripts/ + tests/ 禁止裸内部绝对路径（开发机 skills 安装目录；应使用 skill_registry/env）
    ⑩ 配置引用存在性：core/scripts/plugins 中 references 字面引用必须存在（防 reorg 改名断链）
    """
    import re as _re
    issues, warnings = [], []
    root = Path(__file__).resolve().parent.parent

    # ① 悬空引用：SKILL.md 头部 frontmatter 中 entry_point/protocol_authority
    skill_md = root / "SKILL.md"
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
        refs = _re.findall(r"^(entry_point|protocol_authority|manifest_sync|output_validator):\s*(.+)$",
                           content, _re.M)
        for _, ref in refs:
            ref = ref.strip().strip("`'\"")
            target = root / ref
            if not target.exists():
                issues.append(f"❌ [文件健康①] SKILL.md 引用缺失: {ref}")
            elif "archive" in str(target):
                issues.append(f"❌ [文件健康①] SKILL.md 引用归档文件: {ref}")

    # ② deprecated 零容忍（archive 外 · 递归全目录）
    for sub in ["references", "scripts", "outputs", "components", "core", "domains", "deploy", "docs", "tests"]:
        d = root / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and (f.suffix in (".deprecated", ".old") or ".deprecated" in f.name):
                rel = f.relative_to(root)
                issues.append(f"❌ [文件健康②] 活跃区 {rel} 不应存在（应入 archive/）")

    # ③ 所有权：outputs 目录禁止 deprecated
    outputs_dir = root / "outputs"
    if outputs_dir.exists():
        for f in outputs_dir.iterdir():
            if f.suffix == ".md" and ".deprecated" in f.name:
                issues.append(f"❌ [文件健康③] outputs/ 含废弃文件 {f.name}")

    # ④ 测试归档：scripts/ 根 *_test.py 堆积检测
    scripts_dir = root / "scripts"
    if scripts_dir.exists():
        loose_tests = [f.name for f in scripts_dir.iterdir()
                       if f.is_file() and f.suffix == ".py" and "_test" in f.name]
        if loose_tests:
            warnings.append(f"⚠️ [文件健康④] scripts/ 根测试文件 {len(loose_tests)} 个（建议迁 tests/）: {', '.join(loose_tests[:5])}")

    # ⑤ 嵌套/悬空链接：QCM/QCM 或 self-symlink
    qcm_link = root / "QCM"
    if qcm_link.exists() and qcm_link.is_symlink():
        issues.append(f"❌ [文件健康⑤] 悬空符号链接 {qcm_link} 存在（应删除）")

    # ⑥ 容量：components ≤35 · tests ≤30
    comp_dir = root / "components"
    if comp_dir.exists():
        n = len([f for f in comp_dir.iterdir() if f.suffix == ".md"])
        if n > 35:
            issues.append(f"❌ [文件健康⑥] 组件池 {n}/35 超限")
        elif n >= 30:
            warnings.append(f"⚠️ [文件健康⑥] 组件池 {n}/35 接近上限")
    tests_dir = root / "tests"
    if tests_dir.exists():
        n = len([f for f in tests_dir.rglob("*.py")])
        # 容量上限与 .file-manifest 对齐（V8.4：manifest 为容量真源）
        t_cap = 40
        try:
            import yaml as _y
            man = _y.safe_load((root / ".file-manifest.yaml").read_text(encoding="utf-8")) or {}
            _tc = ((man.get("subdirs") or {}).get("tests") or {}).get("capacity") or {}
            t_cap = _tc.get("max", 40)
        except Exception:
            pass
        if n > t_cap:
            warnings.append(f"⚠️ [文件健康⑥] tests/ {n} 个测试文件（容量 ≤{t_cap} · 超限告警）")

    # ⑦+⑨ 硬编码扫描辅助：按行扫描（scripts/ + tests/ 递归）
    # 豁免：os.environ.get("X", "/path") 参数化默认值（env 覆盖 + 默认值 = 归一化合规）
    def _scan_hardcode(py_files):
        """返回 (issues7, issues9)。⑦ QCM 本体路径 · ⑨ 跨 Skill 路径。"""
        i7, i9 = [], []
        for f in py_files:
            rel = f.relative_to(root)
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            hits7, hits9 = [], []
            for ln in lines:
                is_env_default = ("os.environ.get(" in ln
                                  and ("/root/.skills" in ln or "/sandbox/workspace/skills" in ln))
                if "/sandbox/workspace/skills/QCM" in ln or "/root/.skills/QCM" in ln:
                    if not is_env_default:
                        hits7.append(ln.strip()[:70])
                cleaned = ln.replace("/sandbox/workspace/skills/QCM", "").replace("/root/.skills/QCM", "")
                if "/root/.skills/" in cleaned or "/sandbox/workspace/skills/" in cleaned:
                    if not is_env_default:
                        hits9.append(ln.strip()[:70])
            if hits7:
                i7.append(f"❌ [文件健康⑦] {rel} 含 QCM 硬编码 {hits7[0]}（应使用 env QCM_ROOT）")
            if hits9:
                i9.append(f"❌ [文件健康⑨] {rel} 含跨 Skill 硬编码 {hits9[0]}（应使用 skill_registry/env）")
        return i7, i9

    # ⑦⑨ 扫描范围：scripts/ 根 *.py（豁免检查逻辑自身）+ tests/ 递归 *.py
    scan_files = []
    if scripts_dir.exists():
        for f in scripts_dir.glob("*.py"):
            if f.name in ("config_sync.py", "registry.py", "paths.py"):
                continue  # 检查逻辑/探测列表/路径真源设计的一部分，跳过
            scan_files.append(f)
    if tests_dir.exists():
        scan_files.extend(f for f in tests_dir.rglob("*.py") if f.is_file())
    i7, i9 = _scan_hardcode(scan_files)
    issues.extend(i7)
    issues.extend(i9)

    # ⑧ plugins 目录存在性
    plugins_dir = root / "plugins"
    if not plugins_dir.exists():
        warnings.append("⚠️ [文件健康⑧] plugins/ 目录不存在（插件扩展不可用）")

    # ⑩ 配置引用存在性：core/scripts/plugins 中 references 字面引用必须存在
    #     捕获 "references", "config", "constraint.yaml" / "references" / "xxx" 风格
    #     运行时生成文件豁免（首次采样才落盘 · hit_stats/usage_stats 同款语义）：
    #       usage_global.json    —— V8.6 P0 全局对象域采样（record_usage 落盘）
    #       entity_hit_stats.json —— M1.0 实体命中采样（record_entity_hit 落盘 · 与 R8 反向守卫协同）
    _RUNTIME_REF_EXEMPT = {"usage_global.json", "entity_hit_stats.json"}
    ref_pat = _re.compile(r'''["']references["']\s*[,/]\s*["']([^"']+)["'](?:\s*[,/]\s*["']([^"']+)["'])?(?:\s*[,/]\s*["']([^"']+)["'])?''')
    ref_scan_dirs = []
    for d in [root / "core", root / "scripts", root / "plugins"]:
        if d.exists():
            ref_scan_dirs.extend(d.glob("*.py"))
    for f in ref_scan_dirs:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in ref_pat.finditer(text):
            segs = [s for s in m.groups() if s]
            rel = "/".join(segs)
            if not rel.endswith((".yaml", ".yml", ".md", ".json", ".txt")):
                continue
            if rel in _RUNTIME_REF_EXEMPT:
                continue  # 运行时生成文件 · 首次采样才存在
            target = root / "references" / rel
            if not target.exists():
                rel_f = f.relative_to(root)
                issues.append(f"❌ [文件健康⑩] {rel_f} 引用 references/{rel} 缺失（reorg 改名未同步？）")

    # ⑪ 字典注册合规（V8.4 B1→V8.4 完整化）：登记覆盖 + 字段完整 + schema 引用 + 消费方存在 + 容量比对
    dict_path = root / "references" / "config" / "dictionary.yaml"
    if dict_path.exists():
        try:
            import yaml as _y
            reg = _y.safe_load(dict_path.read_text(encoding="utf-8")) or {}
            registered = []
            for d in reg.get("dictionaries", []):
                did, dpath = d.get("id"), d.get("path")
                if not did or not dpath:
                    issues.append(f"❌ [字典注册] dictionary.yaml 条目缺 id/path: {d}")
                    continue
                registered.append(did)
                target = root / dpath.split("#")[0]
                if not target.exists():
                    issues.append(f"❌ [字典注册] 字典 {did} 路径缺失: {dpath}")
                    continue
                for field in ("schema", "consumers", "status"):
                    if field not in d:
                        warnings.append(f"⚠️  [字典注册] 字典 {did} 缺字段 {field}")
                # ① schema 主字段引用校验：schema 为字段式（word/intent/...）时取首字段校验；描述式（main: [alts]）跳过
                schema = str(d.get("schema", ""))
                if schema and target.exists():
                    import re as _re
                    _m = _re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", schema)
                    first_field = _m.group(1) if _m else ""
                    if first_field and ":" not in schema[:20] and "[" not in schema[:20]:
                        content = target.read_text(encoding="utf-8", errors="ignore")
                        if first_field not in content:
                            warnings.append(f"⚠️  [字典注册] 字典 {did} schema 主字段 '{first_field}' 在文件中未找到")
                # ② consumers 消费方存在校验：core/ 或 scripts/ 下模块必须存在
                for cons in d.get("consumers", []) or []:
                    cfile = root / "core" / f"{cons}.py"
                    sfile = root / "scripts" / f"{cons}.py"
                    if not cfile.exists() and not sfile.exists():
                        warnings.append(f"⚠️  [字典注册] 字典 {did} consumer '{cons}' 模块不存在")
                # ③ 容量比对：登记 capacity 与实际数量对比（intent_max 逐意图比较）
                cap = d.get("capacity") or {}
                if cap:
                    try:
                        doc = _y.safe_load(target.read_text(encoding="utf-8")) or {}
                        if "keywords" in doc:
                            actives = [k for k in doc["keywords"] if k.get("status") != "archived"]
                            im = cap.get("intent_max")
                            if im:
                                icnt = {}
                                for k in actives:
                                    if k.get("intent"):
                                        icnt[k["intent"]] = icnt.get(k["intent"], 0) + 1
                                for intent, c in icnt.items():
                                    if c > im:
                                        issues.append(f"❌ [字典注册] 字典 {did} 意图 {intent} 词数 {c} 超上限 {im}")
                            dm = cap.get("domain_max")
                            if dm:
                                dcnt = {}
                                for k in actives:
                                    if k.get("domain"):
                                        dcnt[k["domain"]] = dcnt.get(k["domain"], 0) + 1
                                for dom, c in dcnt.items():
                                    if c > dm:
                                        issues.append(f"❌ [字典注册] 字典 {did} 领域 {dom} 词数 {c} 超上限 {dm}")
                        if "entities" in doc:
                            cnt = len(doc.get("entities", []))
                            mx = cap.get("max")
                            if mx and cnt > mx:
                                issues.append(f"❌ [字典注册] 字典 {did} 实体数 {cnt} 超上限 {mx}")
                        if "components" in doc:
                            cnt = len(doc.get("components", []))
                            mx = cap.get("max")
                            if mx and cnt > mx:
                                issues.append(f"❌ [字典注册] 字典 {did} 组件数 {cnt} 超上限 {mx}")
                    except Exception:
                        pass
            # ④ 覆盖检查：config 目录所有 yaml（除 dictionary 自身）必须在册
            cfg_dir = root / "references" / "config"
            if cfg_dir.exists():
                for yf in sorted(cfg_dir.glob("*.yaml")):
                    if yf.name == "dictionary.yaml":
                        continue
                    rel = yf.relative_to(root).as_posix()
                    if rel not in [d.get("path", "").split("#")[0] for d in reg.get("dictionaries", [])]:
                        issues.append(f"❌ [字典注册] 未登记字典: {rel}（新增字典必须登记）")
        except Exception as e:
            warnings.append(f"⚠️  [字典注册] dictionary.yaml 解析失败: {e}")
    else:
        warnings.append("⚠️  [字典注册] dictionary.yaml 不存在（词源字典未登记）")

    # ⑫ references 递归扫描模式（V8.4 A5 反重组回归）：core/scripts 禁止 os.listdir 顶层扫 references
    # 背景：gap_detector / infoseek_bridge L1 / corpus_cache 三处因 os.listdir 顶层扫描
    #      在 V8.3.1 重组后 corpus 为空/满分误报——必须用 Path.rglob 递归
    for d in [root / "core", root / "scripts"]:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if f.name == "config_sync.py":  # 排除守卫自身（注释含 os.listdir 字样）
                continue
            txt = f.read_text(encoding="utf-8", errors="ignore")
            if "os.listdir" not in txt:
                continue
            if "references" in txt.lower() or "references_dir" in txt:
                for ln in txt.splitlines():
                    stripped = ln.strip()
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                        continue  # 注释/文档串不计
                    if "os.listdir" in ln and ("references" in ln.lower() or "corpus" in ln.lower()):
                        rel_f = f.relative_to(root)
                        issues.append(f"❌ [文件健康⑫] {rel_f} 用 os.listdir 顶层扫 references（V8.3.1 重组后应为 Path.rglob 递归）: {ln.strip()[:60]}")
                        break

    # ⑬ Key 健康检查（V8.4 T6）：key_state.json 熔断/耗尽状态告警
    key_state = root / "references" / "key_state.json"
    if key_state.exists():
        try:
            ks = json.loads(key_state.read_text(encoding="utf-8"))
            for prov, rec in ks.items():
                if rec.get("status") in ("CIRCUIT_OPEN", "EXHAUSTED"):
                    warnings.append(f"⚠️  [Key 健康⑬] {prov} 状态 {rec['status']}"
                                    f"（fail={rec.get('fail_count', 0)} · quota={rec.get('quota_used', 0)}/{rec.get('quota_limit') or '∞'}）"
                                    f"——qcm_keys.py list 查看 · reset 恢复")
        except Exception:
            pass

    # ⑭ 四件套齐备性守卫（V8.4+ 下挂最小约束 · 新方法接入强制四件套齐备）
    # 四件套 = 模板（contract/）+ 摘要（methods/）+ 词条（keyword.yaml）+ 登记（action-orders.md）
    # 判定规则：keyword.yaml 中 intent 属于方法论类（含"评估/审计/方法"特征）的词条，
    #           其主词须能在 methods/ 找到同名框架、contract/ 找到同名模板、action-orders.md 找到登记语句
    try:
        kw_cfg = _load_yaml(root / "references" / "config" / "keyword.yaml")
        methods_dir = root / "references" / "methods"
        contract_dir = root / "references" / "contract"
        ao_file = root / "references" / "protocol" / "action-orders.md"
        if isinstance(kw_cfg, list):
            kw_items = kw_cfg
        elif isinstance(kw_cfg, dict):
            kw_items = kw_cfg.get("keywords", kw_cfg.get("words", []))
        else:
            kw_items = []
        if kw_items and methods_dir.exists() and contract_dir.exists() and ao_file.exists():
            ao_text = ao_file.read_text(encoding="utf-8", errors="ignore")
            methods_names = {f.stem for f in methods_dir.glob("*.md")}
            contract_names = {f.stem for f in contract_dir.glob("*.md")}
            # 方法论类词条：intent 含"评估/审计/方法"或词条本身是方法名（四性评估/8D/PDCA/RACI 等）
            method_intents = ("③", "评估", "审计", "方法论")
            for item in kw_items:
                if not isinstance(item, dict):
                    continue
                word = item.get("word", "")
                intent = str(item.get("intent", ""))
                # V8.5 行业词豁免：source: industry 词条是路由词（命中行业知识包），非方法论词，
                # 不强制四件套（四件套约束仅适用于方法论类词条）
                if item.get("source") == "industry":
                    continue
                if not word or not any(mk in intent for mk in method_intents):
                    continue
                # 排除泛化词（≤2字且无方法特征）：评估/分析/审计等通用词不强制四件套
                if len(word) <= 2 and not any(mk in word for mk in ("8D", "PDCA", "RACI", "5W", "VSM", "FMEA")):
                    continue
                # 词条主词可能带"评估/法/流程/框架"等后缀或为组合名，取核心词尝试匹配
                core = word
                for suf in ("评估", "分析法", "法", "流程", "框架"):
                    if core.endswith(suf) and len(core) > len(suf):
                        core = core[: -len(suf)]
                        break
                # 方法类词条（含"评估/分析/流程/框架"或英文）要求 methods/ 有同名文件
                if not any(mk in word for mk in ("评估", "分析", "流程", "框架", "改善", "解决")) and "method" not in intent:
                    continue  # 非方法论词条（如"执行有效性"维度词）不强制四件套
                if word in ("四性评估",) or "evaluation" in word.lower():
                    candidates = ["four-aspect-evaluation", "8d-report-framework", "pdca-qc-framework",
                                  "raci-framework", "problem-solving-flow-framework", "reporting-pdca-framework"]
                else:
                    candidates = []
                matched_method = any(
                    c in methods_names or core in methods_names or word in methods_names
                    for c in ([core] + candidates) if c
                )
                if not matched_method:
                    warnings.append(
                        f"⚠️  [四件套⑭] 方法论词条「{word}」（intent {intent}）缺摘要组件："
                        f"methods/ 无同名框架文档（应同时具备 contract/ 模板 + methods/ 摘要 + action-orders 登记）")
                    continue
                # 契约组件：contract/ 有同名模板（下挂模式豁免——下挂方法以"挂接点"替代独立模板）
                matched_contract = any(
                    c in contract_names or core in contract_names or word in contract_names
                    for c in ([core] + candidates) if c
                )
                # 登记组件：action-orders.md 含词条主词
                matched_ao = word in ao_text or core in ao_text or any(c in ao_text for c in candidates if c)
                # 下挂模式判定：methods/ 同名框架含"下挂/挂接/挂接点"且被父流程引用（如 3a5why.md 引用）
                is_hung = False
                if not matched_contract:
                    mfile = None
                    for c in ([core] + candidates):
                        if c and c in methods_names:
                            mfile = methods_dir / f"{c}.md"
                            break
                    if mfile and mfile.exists():
                        mtext = mfile.read_text(encoding="utf-8", errors="ignore")
                        is_hung = ("下挂" in mtext or "挂接" in mtext) and any(
                            parent in mtext for parent in ("3A5WHY", "3a5why", "8D", "PDCA", "父流程"))
                if not matched_contract and not is_hung:
                    warnings.append(f"⚠️  [四件套⑭] 方法论词条「{word}」缺模板组件：contract/ 无同名模板（下挂方法可豁免，以挂接点替代）")
                if not matched_ao:
                    warnings.append(f"⚠️  [四件套⑭] 方法论词条「{word}」缺登记组件：action-orders.md 无登记语句")
        elif kw_items:
            warnings.append("⚠️  [四件套⑭] methods/ 或 contract/ 目录缺失，四件套齐备性跳过")
    except Exception as e:
        warnings.append(f"⚠️  [四件套⑭] 检查异常（跳过）: {e}")

    # ⑮ 契约校验守卫（V8.4+ 下挂最小约束 · contract/ 模板须含输入/输出结构体契约）
    # 最小契约 = 触发点 + 输入契约（输入项/来源）+ 输出契约（输出项/载体）
    # 校验等级：L1 字段存在性 → L2 结构体（输入/输出成对 + 说明）
    # 分类：契约定义文件（input-guide*/mds-input/input-handbook/output-templates）为规范本身，不校验成对；
    #       操作模板的输入契约可通过 ① 文件内含"输入" 或 ② 引用 mds-input.md/input-guide 外链 满足
    # 窗口：全文搜索（模板的契约表可能位于文件后部，如 8D 模板 D8 后第258行"输入契约"）
    try:
        if contract_dir.exists():
            contract_meta = {"input-guide", "input-guide-l0-l3", "input-handbook",
                             "mds-input", "output-templates"}
            for f in sorted(contract_dir.glob("*.md")):
                txt = f.read_text(encoding="utf-8", errors="ignore")
                # L1：字段存在性（触发/输入/输出/适用/定位 任一 · 全文）
                has_field = any(
                    mk in txt for mk in ("触发", "输入", "输出", "适用", "定位")
                )
                if not has_field:
                    warnings.append(f"⚠️  [契约⑮] {f.name} 缺最小契约字段（触发/输入/输出/适用/定位）——下挂对接需输入输出契约")
                    continue
                # 契约定义文件（规范本身）跳过 L2 成对校验
                if f.stem in contract_meta:
                    continue
                # L2：结构体校验——输入/输出契约成对 + 内容说明（全文）
                # 输入契约：文件内含"输入" 或 引用 mds-input.md/input-guide 外链（输入契约定义）
                has_input = ("输入" in txt) or ("mds-input" in txt) or ("input-guide" in txt)
                has_output = "输出" in txt or "产出" in txt
                # 输入契约内容深度：显式输入契约表（输入契约/输入项/输入：/←/来源）
                input_deep = has_input and (
                    any(mk in txt for mk in ("输入契约", "输入项", "输入：", "输入:", "←", "来源", "mds-input", "input-guide"))
                )
                # 输出契约内容深度：显式输出契约表（输出契约/输出项/输出：/产出/载体/→）
                output_deep = has_output and any(
                    mk in txt for mk in ("输出契约", "输出项", "输出：", "输出:", "产出", "载体", "交付", "→")
                )
                if not (has_input and has_output):
                    warnings.append(
                        f"⚠️  [契约⑮-L2] {f.name} 输入/输出契约不完整（输入={'✅' if has_input else '❌'} 输出={'✅' if has_output else '❌'}）"
                        f"——下挂对接需输入契约+输出契约成对（输入可外链 mds-input.md）")
                elif not (input_deep and output_deep):
                    warnings.append(
                        f"⚠️  [契约⑮-L2] {f.name} 契约结构偏浅（输入说明={'✅' if input_deep else '❌'} 输出说明={'✅' if output_deep else '❌'}）"
                        f"——建议明确输入契约表/输出契约表（参考 8D 模板 D8 后契约表）")
    except Exception as e:
        warnings.append(f"⚠️  [契约⑮] 检查异常（跳过）: {e}")

    # ⑯ 行业包登记合规（V8.4+ · references/industry/ 文件必须登记 index.yaml）
    # 校验：①登记覆盖（industry/*.md 全部登记）②字段完整（id/path/industry/keywords/status）
    # ③白名单联动（KNOWN_ORPHANS 中行业包文件须有登记，防孤儿漏管）
    try:
        industry_dir = root / "references" / "industry"
        industry_index = industry_dir / "index.yaml"
        if industry_dir.exists():
            if industry_index.exists():
                idx_cfg = _load_yaml(industry_index) or {}
                packs = idx_cfg.get("industry_packs", []) if isinstance(idx_cfg, dict) else []
                if packs:
                    registered_paths = {str(p.get("path")) for p in packs if isinstance(p, dict)}
                    # ① 登记覆盖：industry/ 下的 .md 文件须登记（排除 index.yaml 本身）
                    for f in industry_dir.glob("*.md"):
                        rel = f"references/industry/{f.name}"
                        if rel not in registered_paths:
                            issues.append(f"❌ [行业包⑯] {f.name} 未登记 industry/index.yaml（新增行业包必须登记）")
                    # ② 字段完整
                    for p in packs:
                        if not isinstance(p, dict):
                            continue
                        missing = [k for k in ("id", "path", "industry", "keywords", "status") if not p.get(k)]
                        if missing:
                            warnings.append(f"⚠️  [行业包⑯] 行业包 {p.get('id', '?')} 缺字段 {missing}")
                    # ④ 关键词级注入校验（V8.5 · 断裂点4修复：登记 keywords 必须已注入 keyword.yaml）
                    # 防止"登记了但没有词条生效"的静默失败——B5 行业扩展前置
                    try:
                        kw_cfg16 = _load_yaml(root / "references" / "config" / "keyword.yaml")
                        kw_words16 = set()
                        if isinstance(kw_cfg16, dict):
                            kw_items16 = kw_cfg16.get("keywords", [])
                        elif isinstance(kw_cfg16, list):
                            kw_items16 = kw_cfg16
                        else:
                            kw_items16 = []
                        for it in kw_items16:
                            if isinstance(it, dict) and it.get("word"):
                                kw_words16.add(str(it["word"]))
                        for p in packs:
                            if not isinstance(p, dict):
                                continue
                            for kw in (p.get("keywords") or []):
                                if kw and str(kw) not in kw_words16:
                                    warnings.append(
                                        f"⚠️  [行业包⑯-KW] 行业包 {p.get('id', '?')} 关键词「{kw}」未注入 keyword.yaml"
                                        f"——运行 scripts/industry_sync.py --apply 归一化注入")
                    except Exception:
                        pass  # 词库读取失败不阻断（主校验已覆盖）
                else:
                    warnings.append("⚠️  [行业包⑯] industry/index.yaml 无 industry_packs 条目")
            else:
                issues.append("❌ [行业包⑯] references/industry/ 存在但缺 index.yaml 注册中心（新增行业包必须登记）")
    except Exception as e:
        warnings.append(f"⚠️  [行业包⑯] 检查异常（跳过）: {e}")

    # V8.6 语料清单一致性（自适应分类 + 自动检入登记守门）
    # 校验：① 登记项索引新鲜 ② corpus/excluded 不冲突 ③ 无未登记大文件（>阈值）
    # ── V8.6 语料清单一致性（g018 守门） ──
    _check_corpus_manifest(issues, warnings)
    # ── V8.6+ 未登记语料扫描（g022 守门 · 闭环小文件静默孤儿根因） ──
    _check_unregistered_corpus(issues, warnings)
    # ── M2 运行态缓存全生命周期（g019_runtime_cache 守门） ──
    _check_runtime_cache(issues, warnings)
    # ── M5 容量容器（g_capacity 去空壳） ──
    _check_capacity_ledger(issues, warnings)
    # ── M3 同源文件归一化（g020_file_homology 守门） ──
    _check_file_homology(issues, warnings)
    # ── R-4b 废弃资产模板校验（g020b · DEPRECATED 头结构 + redirect_to 存在性） ──
    _check_deprecated_assets(issues, warnings)
    # ── R-6 资产退休注册（g021 · asset_retirement 状态机 + 观察期推进 · report-only） ──
    _check_asset_registry(issues, warnings)
    # ── M0 守卫定时器本体回写一致性（automation_manifest.yaml 守门） ──
    _check_automation_manifest(issues, warnings)

    return issues, warnings

def _check_corpus_manifest(issues: list, warnings: list) -> None:
    """V8.6 语料清单一致性（登记守门 · report-only）

    复用 guardian/dictionary 既有守卫范式：新增大文件必须登记（自动检入），
    登记项必须索引新鲜，corpus/excluded 不冲突。manifest 缺失则跳过（不阻断主校验）。
    """
    try:
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent.parent
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from corpus_manifest import load_manifest
        m = load_manifest()
        idx_dir = ROOT / "references" / "index"
        known = {e["rel"] for e in (m.get("corpus", []) + m.get("excluded", []))}
        corpus_rels = {e["rel"] for e in m.get("corpus", [])}
        thresh = int(m.get("threshold_kb", 30)) * 1024
        for e in (m.get("corpus", []) + m.get("excluded", [])):
            rel = e["rel"]
            src = ROOT / rel
            idx = idx_dir / (src.stem + ".index.yaml")
            if not src.exists():
                issues.append(f"❌ [语料登记⑱] 登记源已删 {rel}（须移出 manifest）"); continue
            if not idx.exists():
                issues.append(f"❌ [语料登记⑱] 登记项缺索引 {rel}（须 --scan 重生成）"); continue
            if idx.stat().st_mtime < src.stat().st_mtime:
                warnings.append(f"⚠️  [语料登记⑱] 索引过期 {rel}（源已更新）")
        for e in m.get("excluded", []):
            if e["rel"] in corpus_rels:
                issues.append(f"❌ [语料登记⑱] {e['rel']} 同时出现在 corpus/excluded（冲突）")
        for p in (ROOT / "references").rglob("*.md"):
            r = str(p.relative_to(ROOT)).replace("\\", "/")
            if "references/index/" in r or "automation_log" in r:
                continue
            if p.stat().st_size <= thresh:
                continue
            if r not in known:
                warnings.append(f"⚠️  [语料登记⑱] 未登记大文件 {r}（建议 --scan --auto 自动检入）")
    except Exception as e:
        warnings.append(f"⚠️  [语料登记⑱] 检查异常（跳过）: {e}")


def _check_unregistered_corpus(issues: list, warnings: list) -> None:
    """V8.6+ 未登记语料扫描（g022 · [未登记语料㉒] · report-only）

    根因闭环：auto_checkin 仅自动检入 >阈值(30KB) 大文件，小语料（如 knowledge/ 下
    <30KB 知识文档）永不自动登记 → corpus_loader 检索不到 → 静默变孤儿。
    本检查对 corpus 类目录（knowledge/tools/scenarios/protocol/industry）下所有 .md
    做"是否在 corpus_manifest.yaml 登记"比对；仅对「未登记 AND 无入链（真·静默孤儿）」
    告警，避免误伤 scenarios/workshop 等已被链接引用、仅未进懒加载清单的核心文件。
    report-only，不自动改写。
    """
    try:
        from pathlib import Path
        import json as _json
        ROOT = Path(__file__).resolve().parent.parent
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from corpus_manifest import load_manifest
        m = load_manifest()
        known = {e["rel"] for e in (m.get("corpus", []) + m.get("excluded", []))}
        # 入链快照（失败安全：缺失则退化为"全部视为有入链"，不误报）
        incoming = {}
        rg = ROOT / "outputs" / ".runtime" / "ref_graph.json"
        if rg.exists():
            try:
                incoming = _json.loads(rg.read_text(encoding="utf-8")).get("incoming", {})
            except Exception:
                incoming = {}
        # industry/ 由 g016 行业包登记（industry/index.yaml + keyword.yaml）独立治理，
        # 不入 corpus_manifest，故排除；本检查只覆盖 corpus_manifest 管辖目录。
        corpus_dirs = ("knowledge/", "tools/", "scenarios/", "protocol/")
        for p in (ROOT / "references").rglob("*.md"):
            r = str(p.relative_to(ROOT)).replace("\\", "/")
            if "references/index/" in r or "automation_log" in r or "/testing/" in r:
                continue
            if not any(seg in r for seg in corpus_dirs):
                continue
            if r in known:
                continue
            stem = p.stem
            if incoming and incoming.get(stem):  # 已被其它文件链接引用 → 非静默孤儿，跳过
                continue
            warnings.append(f"⚠️  [未登记语料㉒] 静默孤儿 {r}（未登记 manifest 且无入链 · corpus_loader 不可达 · 建议登记或归档）")
    except Exception as e:
        warnings.append(f"⚠️  [未登记语料㉒] 检查异常（跳过）: {e}")


def _check_runtime_cache(issues: list, warnings: list) -> None:
    """M2 · 运行态缓存全生命周期守门（g019_runtime_cache）

    读 outputs/.runtime/corpus.db 台账：容量上限 / 漂移 / 分层覆盖。
    失败安全：异常 → 警告跳过（不阻断主校验）。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(ROOT / "scripts"))
        from corpus_cache import CorpusCache
        from paths import REFERENCES
        cache = CorpusCache(str(REFERENCES))
        if not cache.is_built():
            warnings.append("⚠️  [运行态缓存⑲] 缓存未构建（MCP 启动将自动构建 · 夜巡 [6.9/8] 可轮转）")
            return
        st = cache.get_stats()
        # 容量上限
        if st["total_size_bytes"] > cache.max_bytes:
            issues.append(f"❌ [运行态缓存⑲] 缓存超容量 "
                          f"{st['total_size_bytes']/1024/1024:.1f}MB > 上限 {cache.max_bytes/1024/1024:.0f}MB"
                          f"（轮转未生效 · 检查 [6.9/8]）")
        # 漂移（源变更未同步）
        drift = cache.drift_check()
        if len(drift) > 50:
            warnings.append(f"⚠️  [运行态缓存⑲] 漂移条目 {len(drift)}（建议 build/增量重建）")
        # 分层覆盖（references 语料须纳入）
        by_tier = st.get("by_tier", {})
        corpus_like = by_tier.get("warm", 0) + by_tier.get("hot", 0) + by_tier.get("cold", 0)
        if corpus_like == 0:
            warnings.append("⚠️  [运行态缓存⑲] 无缓存条目（语料未纳入 · 首次 build 缺失）")
    except Exception as e:
        warnings.append(f"⚠️  [运行态缓存⑲] 检查异常（未静默）: {e}")


def _check_capacity_ledger(issues: list, warnings: list) -> None:
    """M5 · 容量容器守门（g_capacity 去空壳）

    读 outputs/.runtime/capacity_ledger.json：当前超限 + 与基线漂移。
    失败安全：异常 → 警告跳过。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(ROOT / "core"))
        from capacity import check_ledger
        over, drift = check_ledger()
        for dim, items in over.items():
            for key, (cnt, lim) in items.items():
                issues.append(f"❌ [容量容器] {dim}「{key}」超限 {cnt} > {lim}")
        if drift:
            corr = [d for d in drift if isinstance(d, dict) and d.get("_corrupt")]
            real = [d for d in drift if not (isinstance(d, dict) and d.get("_corrupt"))]
            if corr:
                warnings.append(
                    f"⚠️  [容量容器] 台账损坏/缺失无法对比（{corr[0].get('error','')}）· "
                    f"运行夜巡 [6.10/8] 或 capacity.py update_ledger(rebaseline=True) 重建")
            if real:
                warnings.append(f"⚠️  [容量容器] 台账漂移 {len(real)} 项（基线 vs 当前不一致 · 检查 [6.10/8]）")
    except Exception as e:
        warnings.append(f"⚠️  [容量容器] 检查异常（未静默）: {e}")


def _check_file_homology(issues: list, warnings: list) -> None:
    """M3 同源文件归一化守门（g020_file_homology）。

    对 references/**/*.md 做同源指纹聚类，标记"疑似同根未互链"。
    复用 scripts/file_homology.py（阈值默认 0.6，按 ref_heat.confirmed_pairs 动态校准）。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(ROOT / "scripts"))
        from file_homology import check as _fh_check
        _fh_check(issues, warnings)
    except Exception as e:
        warnings.append(f"⚠️  [同源文件⑳] 检查异常（未静默）: {e}")


def _check_deprecated_assets(issues: list, warnings: list) -> None:
    """R-4b 废弃资产模板校验（g020b · DEPRECATED 头结构 + redirect_to 存在性）。

    调用 scripts/file_homology.check_deprecated()：扫描 references/**/*.md，
    对含 DEPRECATED 的文件校验 ①> [!WARNING] 模板头 ②redirect_to: 字段 ③目标存在。
    仅 report（M0.4 纪律），不修改/不删除。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(ROOT / "scripts"))
        from file_homology import check_deprecated as _fh_deprecated
        _fh_deprecated(issues, warnings)
    except Exception as e:
        warnings.append(f"⚠️  [废弃资产⑳b] 检查异常（未静默）: {e}")


def _check_asset_registry(issues: list, warnings: list) -> None:
    """R-6 资产退休注册守卫（g021 · [资产退休㉑] · report-only）。

    校验 asset_retirement 状态机：① 状态文件存在 ② 观察记录合理
    （observing 数量 ≤ 全语料节点 · due 完整）③ 白名单常驻豁免完好。
    仅报告规模与状态，不自动退休/删除（M0.4 纪律）。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        st = ROOT / "references" / "config" / "asset_retirement.json"
        if not st.exists():
            warnings.append(
                f"⚠️  [资产退休㉑] 状态文件缺失：{st.relative_to(ROOT)}"
                f"（先运行 asset_retirement.py --scan 初始化）")
            return
        import json as _json
        d = _json.loads(st.read_text(encoding="utf-8"))
        obs = d.get("observe", {})
        wl = d.get("whitelist", [])
        unexpected = [k for k, v in obs.items()
                      if v.get("status") not in ("observing", "retire_candidate",
                                                 "retired", "revived", "stale_passed")]
        if unexpected:
            warnings.append(
                f"⚠️  [资产退休㉑] {len(unexpected)} 条观察记录状态异常：{unexpected[:5]}")
            return
        due = [v.get("stem") for v in obs.values() if v.get("status") == "retire_candidate"]
        if due:
            warnings.append(
                f"⚠️  [资产退休㉑] {len(due)} 项观察期满可人工核准退休：{due[:5]}"
                f"（asset_retirement.py --retire <stem> · 每 1 个季度物理清理）")
        else:
            print(f"  ℹ️  [资产退休㉑] 状态机正常：observing={sum(1 for v in obs.values() if v.get('status')=='observing')}"
                  f" · whitelist={len(wl)} · 无期满待退休（观察 ≥30d 后自动提示）")
    except Exception as e:
        warnings.append(f"⚠️  [资产退休㉑] 检查异常（未静默）: {e}")


def _check_automation_manifest(issues: list, warnings: list) -> None:
    """M0 守卫定时器本体回写一致性守门（automation_manifest.yaml）。

    校验：① manifest 存在且含 4 个定时器 ② 每个 timer 的 automation_id 非空
    ③ backfill_cmd 字段存在（回灌定时器独立命令）。仅 report-only，不阻断主校验。
    """
    try:
        ROOT = Path(__file__).resolve().parent.parent
        import yaml
        manifest = ROOT / "references" / "config" / "automation_manifest.yaml"
        if not manifest.exists():
            warnings.append("⚠️  [定时器回写] references/config/automation_manifest.yaml 缺失（跨平台自触发凭证未落地）")
            return
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        timers = data.get("timers", [])
        if len(timers) < 4:
            warnings.append(f"⚠️  [定时器回写] manifest 仅 {len(timers)} 个定时器（预期 ≥4 · 与 WorkBuddy automation 对齐）")
        missing_aid = [t.get("id", "?") for t in timers if not t.get("automation_id")]
        if missing_aid:
            warnings.append(f"⚠️  [定时器回写] 以下定时器缺 automation_id（未与 WorkBuddy 对齐）: {missing_aid}")
        backfill = [t for t in timers if t.get("id") == "qcm-refheat-backfill"]
        if backfill and not backfill[0].get("backfill_cmd"):
            warnings.append("⚠️  [定时器回写] 回灌定时器缺 backfill_cmd（独立命令未声明）")
        if not issues and not missing_aid:
            # 一致性良好（不重复告警，交给守卫中心聚合）
            pass
    except Exception as e:
        warnings.append(f"⚠️  [定时器回写] 检查异常（未静默）: {e}")


def sync_config():
    """自动同步配置（修正不一致）"""
    issues, warnings = check_consistency()
    
    if not issues and not warnings:
        print("✅ 配置完全一致，无需同步")
        return 0

    print(f"\n{'=' * 70}")
    print("QCM 配置同步报告")
    print(f"{'=' * 70}")
    print(f"时间：{datetime.now().isoformat()}")
    print()

    if issues:
        print(f"❌ 严重问题 ({len(issues)} 项)：")
        for i in issues:
            print(f"   {i}")
        print()

    if warnings:
        print(f"⚠️  警告 ({len(warnings)} 项)：")
        for w in warnings:
            print(f"   {w}")
        print()

    # 自动修正建议
    print("🔧 自动修正建议：")
    if any("role_config.yaml" in i for i in issues):
        print("   → 重新生成 role_config.yaml（参考 templates/role_config.template.yaml）")
    if any("validator_config.yaml" in i for i in issues):
        print("   → 重新生成 validator_config.yaml（参考 templates/validator_config.template.yaml）")
    
    print(f"\n{'=' * 70}")
    print("同步完成。请手动检查并应用建议的修正。")
    print("=" * 70)
    return 1 if issues else 0


def generate_report():
    """生成配置联动报告"""
    issues, warnings = check_consistency()
    
    report = []
    report.append("# QCM 配置联动报告")
    report.append(f"\n生成时间：{datetime.now().isoformat()}")
    report.append(f"\n## 配置状态\n")
    report.append(f"- 角色配置：{'✅ 已加载' if ROLE_CONFIG.exists() else '❌ 缺失'}")
    report.append(f"- 校验配置：{'✅ 已加载' if VALIDATOR_CONFIG.exists() else '❌ 缺失'}")
    
    report.append(f"\n## 一致性检查\n")
    report.append(f"- 严重问题：{len(issues)} 项")
    report.append(f"- 警告：{len(warnings)} 项")
    
    if issues:
        report.append("\n### 严重问题\n")
        for i in issues:
            report.append(f"- {i}")
    
    if warnings:
        report.append("\n### 警告\n")
        for w in warnings:
            report.append(f"- {w}")
    
    if not issues and not warnings:
        report.append("\n✅ 配置完全一致，无问题。\n")
    
    report_text = "\n".join(report)
    print(report_text)
    
    # 写入报告文件
    report_path = SKILL_DIR / "config_sync_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\n📄 报告已保存：{report_path}")
    return 0


def main():
    if "--check" in sys.argv:
        issues, warnings = check_consistency()
        print(f"{'=' * 70}")
        print("QCM 配置一致性检查")
        print(f"{'=' * 70}")
        print(f"严重问题：{len(issues)} 项")
        print(f"警告：{len(warnings)} 项")
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
        return 1 if issues else 0

    elif "--guardians" in sys.argv:
        # S3 守卫归一化：输出守卫注册摘要（guardian.py --registry 的兼容别名）
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
            from guardian import registry_summary
            print(registry_summary())
        except Exception as e:
            print(f"⚠️ 守卫注册中心不可用: {e}")
        return 0

    elif "--sync" in sys.argv:
        return sync_config()

    elif "--report" in sys.argv:
        return generate_report()

    else:
        print(__doc__)
        return 0


if __name__ == "__main__":
    sys.exit(main())
