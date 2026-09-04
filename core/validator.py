#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QCM 输出验证脚本 （配置驱动）
依据：Skill 设计 5 原则之 ④ 可观测设计

功能：
1. 从 YAML 配置加载检查规则，动态验证 4 形态输出
2. 支持角色配置与校验配置联动
3. 输出验证报告

用法：
  python3 qcm_output_validator.py            # 验证 4 形态
  python3 qcm_output_validator.py --form case_application # 验证指定形态

版本：8.3.0（2026-08-18）
"""

import sys
import re
import os
from pathlib import Path
from datetime import datetime

# 路径配置
SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR = SCRIPT_DIR.parent
OUTPUTS_DIR = SKILL_DIR / "outputs"
REFERENCES_DIR = SKILL_DIR / "references"

# 4 形态文件
OUTPUT_FORMS = {
    "case_application": "case-application.md",
    "decision_card": "decision-card.md",
    "assessment_report": "assessment-report.md",
    "quick_response": "quick-response.md",
}

# 兼容：保留 SECTION_PATTERNS（硬编码 fallback）
SECTION_PATTERNS = {
    "case_application": ["行动要项", "事态导航", "危机沟通", "行动措施", "后续计划", "双归零"],
    "decision_card": ["决策", "责任", "动作"],
    "assessment_report": ["评估摘要", "现状评估", "关键缺口", "改进建议", "后续计划"],
    "quick_response": ["判定", "立即动作"],
}

# 兼容：保留 CHECK_ITEMS（硬编码 fallback）
CHECK_ITEMS = [
    "has_section_template", "has_side_effects", "has_input_schema",
    "has_output_schema", "has_degradation_paths", "has_execution_trace",
    "has_unverified_marker", "has_data_freshness", "has_boundary_declaration",
    "has_forbidden_content_list", "has_raci", "has_owner",
    "has_positioning_depth", "has_multi_chain", "has_explicit_marker",
    "has_zero_depth", "has_zero_layer", "has_zero_status",
    "has_component_manifest", "has_component_engine", "has_component_mapping",
]

# ── 配置加载 ──

def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_validator_config() -> dict:
    """加载校验配置（validator_config.yaml）"""
    cfg_path = REFERENCES_DIR / "config" / "validator.yaml"
    if cfg_path.exists():
        return _load_yaml(cfg_path)
    return {}


def load_role_config() -> dict:
    """加载角色配置（role_config.yaml）"""
    cfg_path = REFERENCES_DIR / "config" / "role.yaml"
    if cfg_path.exists():
        return _load_yaml(cfg_path)
    return {}


# ── 组件检查（保留） ──

def check_component_closure() -> bool:
    try:
        import yaml
    except ImportError:
        return False
    root = Path(__file__).resolve().parent.parent
    man_path = root / "references" / "config" / "components.yaml"
    map_path = root / "references" / "config" / "constraint.yaml"
    if not man_path.exists() or not map_path.exists():
        return False
    try:
        man = yaml.safe_load(man_path.read_text(encoding="utf-8")) or {}
        cmap = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
        registered = set(man.get("components", {}).keys())
        referenced = set()
        for m in cmap.get("mapping", []):
            referenced.update(m.get("components", []))
        return referenced.issubset(registered)
    except Exception:
        return False


def check_component_engine() -> bool:
    root = Path(__file__).resolve().parent.parent
    engine = root / "core" / "assembler.py"
    if not engine.exists():
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("qcm_assembler_check", engine)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cats = {}
        for cid, cat in mod.COMPONENT_CATEGORY.items():
            cats.setdefault(cat, 0)
            cats[cat] += 1
        return cats.get("analysis", 0) >= 10 and cats.get("output", 0) >= 10
    except Exception:
        return False


def check_component_mapping() -> bool:
    root = Path(__file__).resolve().parent.parent
    engine = root / "core" / "assembler.py"
    if not engine.exists():
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("qcm_mapping_check", engine)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return len(mod.validate_mapping()) == 0
    except Exception:
        return False


# ── 配置驱动检查 ──

def _check_from_config(content: str, check_def: dict, form_name: str) -> bool:
    """根据配置定义执行单条检查"""
    forms_cfg = check_def.get("forms", {})
    form_cfg = forms_cfg.get(form_name, {})
    
    # 未定义该形态 → 宽松通过
    if not form_cfg:
        return True
    
    required = form_cfg.get("required", False)
    if not required:
        return True
    
    # 特殊检查（组件类）
    special = check_def.get("special")
    if special == "check_component_closure":
        return check_component_closure()
    if special == "check_component_engine":
        return check_component_engine()
    if special == "check_component_mapping":
        return check_component_mapping()
    
    # 正则匹配
    pattern = form_cfg.get("pattern", ".*")
    return bool(re.search(pattern, content))


def check_form(form_name: str, form_path: Path, config: dict) -> dict:
    """验证单个输出形态（配置驱动）"""
    result = {
        "form": form_name,
        "file": str(form_path),
        "exists": form_path.exists(),
        "checks": {},
    }

    if not result["exists"]:
        for item in CHECK_ITEMS:
            result["checks"][item] = False
        return result

    with open(form_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 配置驱动检查
    checks_def = config.get("checks", [])
    for check_def in checks_def:
        check_id = check_def.get("id")
        if not check_id:
            continue
        result["checks"][check_id] = _check_from_config(content, check_def, form_name)

    # 段模板完整性（配置未覆盖时 fallback 硬编码）
    if "has_section_template" not in result["checks"]:
        required_sections = SECTION_PATTERNS.get(form_name, [])
        missing = [s for s in required_sections if s not in content]
        result["checks"]["has_section_template"] = len(missing) == 0
        if missing:
            result["missing_sections"] = missing

    return result


def main():
    """主验证流程"""
    print("=" * 70)
    print("QCM 输出验证脚本（配置驱动）")
    print("=" * 70)
    print(f"验证时间：{datetime.now().isoformat()}")
    print(f"输出目录：{OUTPUTS_DIR}")

    # 加载配置
    config = load_validator_config()
    role_cfg = load_role_config()
    print(f"校验配置：{'✅ 已加载' if config else '⚠️ 未找到，使用硬编码 fallback'}")
    print(f"角色配置：{'✅ 已加载' if role_cfg else '⚠️ 未找到'}")
    print()

    # 解析 --form 参数
    target_form = None
    if "--form" in sys.argv:
        idx = sys.argv.index("--form")
        if idx + 1 < len(sys.argv):
            target_form = sys.argv[idx + 1]

    forms_to_check = [target_form] if target_form else list(OUTPUT_FORMS.keys())

    all_pass = True
    total_checks = 0
    total_pass = 0

    for form_name in forms_to_check:
        if form_name not in OUTPUT_FORMS:
            print(f"❌ 未知形态：{form_name}")
            continue

        form_path = OUTPUTS_DIR / OUTPUT_FORMS[form_name]
        result = check_form(form_name, form_path, config)

        print(f"\n{'=' * 70}")
        print(f"形态：{form_name} ({OUTPUT_FORMS[form_name]})")
        print(f"状态：{'✅ 通过' if result['exists'] else '❌ 文件不存在'}")
        print("-" * 70)

        if not result["exists"]:
            all_pass = False
            continue

        for check_id, passed in result["checks"].items():
            status = "✅" if passed else "❌"
            print(f"  {status} {check_id}")
            total_checks += 1
            if passed:
                total_pass += 1

        if "missing_sections" in result:
            print(f"  ⚠️  缺失段落：{', '.join(result['missing_sections'])}")

    print(f"\n{'=' * 70}")
    print(f"📊 验证汇总：{total_pass}/{total_checks} 通过")
    print("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
