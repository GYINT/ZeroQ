#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 实体层生成器（V8.6 M0.9 P1 · 词源管理 实体索引）

从知识库半自动提取实体 → 生成/校验 references/config/entities.yaml：
  - standards.md 表格 → 标准实体（type=standard · domain=E体系 · intent=③评估审计）
  - masters.md 章节标题 → 大师实体（type=master · domain=通用 · intent=④知识学习）
  - tools.md 工具编号实例 → 方法实体（type=method · domain=主领域 · intent="" 跨意图上下文锚点）

设计原则：
  - 单一真源：entities.yaml 由本脚本从知识库生成（知识库演进 → 实体层自动同步）
  - 只读知识库：本脚本只读 standards/masters/tools，不修改
  - 别名维护：中英文名/缩写手工补充在 entities.yaml 的 aliases 字段（脚本不覆盖已有人工别名）
  - 方法实体不绑定意图（intent=""）：同工具天然跨 ①危机处置/②流程优化/③评估审计/④知识学习
    等多意图，意图由"信号词 + 语境"驱动（见 action-orders §14.8），方法实体仅作领域上下文锚点

用法：
  python3 scripts/extract_entities.py            # 生成/更新 entities.yaml（auto-checkin：写回）
  python3 scripts/extract_entities.py --scan    # 干跑：报告将新增/剔除的实体（不写盘）
  python3 scripts/extract_entities.py --auto    # 等同默认：auto-checkin 写回 entities.yaml
  python3 scripts/extract_entities.py --check   # 校验实体层与知识库同步（CI 接入）
  python3 scripts/extract_entities.py --sync    # 源变更感知 auto-checkin（幂等 · 夜巡/CI-watch 安全）
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARDS = ROOT / "references" / "tools" / "standards.md"
MASTERS = ROOT / "references" / "tools" / "masters.md"
TOOLS = ROOT / "references" / "tools" / "tools.md"
ENTITIES = ROOT / "references" / "config" / "entities.yaml"

# 自动源（由本脚本从知识库派生 · auto-checkin 可重写/剔除）
AUTO_SOURCES = {"standards.md", "masters.md", "tools.md"}

# 标准号 → 领域映射（未显式标注的兜底）
STANDARD_DOMAIN = {"E体系": "质量管理体系（QMS）类标准"}

# ── 分层字段默认值（M1.0 ① · status/level/lifecycle/tier） ──
# status:    生命周期状态 ∈ {active, deprecated, archived}
# level:     权威级别   ∈ {core, derived}（core=标准/大师权威源 · derived=方法派生）
# lifecycle: 成熟度     ∈ {draft, evolving, stable, mature}
# tier:      热度分层   ∈ {hot, warm, cold}（默认 warm · 由使用事实校准覆盖，见 guardian_reverse R8）
LAYER_ENUMS = {
    "status": {"active", "deprecated", "archived"},
    "level": {"core", "derived"},
    "lifecycle": {"draft", "evolving", "stable", "mature"},
    "tier": {"hot", "warm", "cold"},
}


def default_layering(type_: str) -> dict:
    """按 type 派生默认分层字段（method 为派生/演进；标准/大师为权威/稳定）"""
    if type_ == "method":
        return {"status": "active", "level": "derived", "lifecycle": "evolving", "tier": "warm"}
    return {"status": "active", "level": "core", "lifecycle": "stable", "tier": "warm"}


def ensure_layering(e: dict) -> dict:
    """补全/校验分层字段：已有合法值保留，缺失补默认，非法枚举回退默认。
    auto-checkin 对全部实体（含人工实体）生效，保证 ① 分层字段无缺口。"""
    d = default_layering(e.get("type", "method"))
    for k, v in d.items():
        cur = e.get(k)
        if cur in (None, ""):
            e[k] = v
        elif cur not in LAYER_ENUMS.get(k, set()):
            e[k] = v  # 非法枚举回退默认
    return e

TOOL_CODE_RE = re.compile(r"^##\s+([A-Za-z0-9]+)\.\s+(.+?)\s*$")
DOMAIN_RE = re.compile(r"主[:：]\s*([^\s·]+)")


def extract_standards() -> list:
    """从 standards.md 表格提取标准实体"""
    out = []
    if not STANDARDS.exists():
        return out
    text = STANDARDS.read_text(encoding="utf-8")
    # 表格行：| 标准号 | 名称 | 适用范围 | 状态 |（标准号含版本冒号如 ISO 9001:2015）
    rows = re.findall(r"^\|\s*([A-Z][A-Z0-9/.:\-\s]{2,40}?)\s*\|\s*([^|]+?)\s*\|", text, re.M)
    seen = set()
    for code, name in rows:
        code = code.strip()
        if not code or code in seen or code.startswith("标准号"):
            continue
        # 过滤工具编号行（F01 8D / A01 SPC 等非标准实体）
        if re.match(r"^[A-Z]\d{2}\s", code):
            continue
        # 去掉版本号作为别名（ISO 9001:2015 → ISO 9001 + ISO9001）
        base = re.sub(r":\d{4}$", "", code)
        aliases = sorted({base, base.replace(" ", "")})
        seen.add(code)
        out.append({
            "name": base, "type": "standard",
            "aliases": aliases, "source": "standards.md",
            "domain": "E体系", "intent": "③评估审计",
            "status": "active", "level": "core", "lifecycle": "stable", "tier": "warm",
        })
    return out


def extract_masters() -> list:
    """从 masters.md 章节标题提取大师实体（标题：中文名（外文名, 生卒年））"""
    out = []
    if not MASTERS.exists():
        return out
    for line in MASTERS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^# (.+?)\s*（(.+?),\s*\d{4}", line)
        if not m:
            m = re.match(r"^# (.+?)\s*\((.+?),\s*\d{4}", line)
        if m:
            zh, en = m.group(1).strip(), m.group(2).strip()
            # name = 英文全名（更精确）；aliases = 中文简称 + 中文全名 + 姓 + 英文名
            surname = en.split()[-1] if en.split() else en
            zh_short = re.split(r"[·．.]", zh)[-1] if re.split(r"[·．.]", zh) else zh
            aliases = {zh, zh_short, en, surname}
            out.append({
                "name": en, "type": "master",
                "aliases": sorted(aliases),
                "source": "masters.md",
                "domain": "通用", "intent": "④知识学习",
                "status": "active", "level": "core", "lifecycle": "stable", "tier": "warm",
            })
    return out


def extract_methods() -> list:
    """从 tools.md 工具实例标题提取方法实体（V8.6 M0.9 P1-ctx）

    标题形如 `## A01. SPC 统计过程控制（控制图 + 过程能力）`，紧跟一行
    `- **领域**：主:A制造 · 次:R风险` 给出主领域。方法实体不绑定意图
    （intent=""），仅作跨意图上下文锚点（领域增强 + 歧义消解锚定）。
    """
    out = []
    if not TOOLS.exists():
        return out
    lines = TOOLS.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = TOOL_CODE_RE.match(line)
        if not m:
            continue
        code = m.group(1)
        title = m.group(2).strip()
        # 领域：向后扫描 ≤6 行内的 `主:X`
        domain = "通用"
        for j in range(i + 1, min(i + 7, len(lines))):
            dm = DOMAIN_RE.search(lines[j])
            if dm:
                domain = dm.group(1)
                break
        # 别名派生
        short = re.split(r"[（(]", title)[0].strip()            # SPC 统计过程控制
        full_no_paren = re.sub(r"[（(][^）)]*[）)]", "", title).strip()  # 去括号
        en = re.match(r"^[A-Za-z0-9\-]+", title)               # 首个英文/数字缩写（SPC / 8D / QFD）
        en_tok = en.group(0) if en else ""
        aliases = {code, short, short.replace(" ", ""),
                   full_no_paren, full_no_paren.replace(" ", "")}
        if en_tok:
            aliases.add(en_tok)
        out.append({
            "name": code, "type": "method",
            "aliases": sorted(aliases),
            "source": "tools.md",
            "domain": domain, "intent": "",
            "status": "active", "level": "derived", "lifecycle": "evolving", "tier": "warm",
        })
    return out


def merge_with_existing(new_entities: list) -> list:
    """合并：保留 entities.yaml 已有人工别名（不覆盖）"""
    if not ENTITIES.exists():
        return new_entities
    try:
        import yaml
        old = yaml.safe_load(ENTITIES.read_text(encoding="utf-8")) or {}
        old_map = {e["name"]: e for e in old.get("entities", [])}
    except Exception:
        return new_entities
    for e in new_entities:
        if e["name"] in old_map:
            old_aliases = old_map[e["name"]].get("aliases", [])
            if old_aliases:
                e["aliases"] = sorted(set(e["aliases"]) | set(old_aliases))
            # 保留已有人工分层字段（不覆盖）
            for k in ("status", "level", "lifecycle", "tier"):
                if old_map[e["name"]].get(k) not in (None, ""):
                    e[k] = old_map[e["name"]][k]
    return new_entities


def gen_yaml(entities: list) -> str:
    lines = [
        "# QCM 实体索引（V8.6 M0.9 P1 · 由 scripts/extract_entities.py 从知识库生成）",
        "# 用途：用户输入实体识别 → 精确路由（标准→E体系+工具 · 大师→大师库 · 方法→跨意图领域锚点）",
        "# 维护：运行 extract_entities.py 重新生成；人工别名直接编辑本文件 aliases（生成时不覆盖）",
        "# 方法实体 intent=\"\" 表示不绑定单一意图（跨意图上下文锚点），见 action-orders §14.8",
        "# 分层字段（M1.0 ①）：status∈{active,deprecated,archived} · level∈{core,derived} ·",
        "#   lifecycle∈{draft,evolving,stable,mature} · tier∈{hot,warm,cold}（tier 由使用事实校准，见 guardian_reverse R8）",
        "",
        "entities:",
    ]
    for e in entities:
        intent = '""' if e.get("intent") in ("", None) else e["intent"]
        domain = e.get("domain", "通用")
        aliases = ", ".join(f'"{a}"' for a in e["aliases"])
        status = e.get("status", "active")
        level = e.get("level", "core")
        lifecycle = e.get("lifecycle", "stable")
        tier = e.get("tier", "warm")
        lines.append(
            f'  - {{name: "{e["name"]}", type: {e["type"]}, aliases: [{aliases}], '
            f'domain: {domain}, intent: {intent}, source: {e["source"]}, '
            f'status: {status}, level: {level}, lifecycle: {lifecycle}, tier: {tier}}}'
        )
    return "\n".join(lines) + "\n"


def scan_and_build() -> tuple:
    """扫描知识库 → (标准, 大师, 方法) 三元组（自动派生实体）"""
    return extract_standards(), extract_masters(), extract_methods()


def auto_checkin(write_back: bool = False) -> tuple:
    """实体层 auto-checkin（V8.6 M0.9 · 对齐 corpus auto-checkin）

    单一真源：自动派生实体（标准/大师/方法）从知识库重建；人工补充实体
    （source 不在 AUTO_SOURCES 或不在自动集）一律保留，永不因重跑被剔除。

    Args:
        write_back: True=写回 entities.yaml；False=干跑（仅返回最终集）
    Returns:
        (final, auto, manual) 列表元组
    """
    std, mst, mtd = scan_and_build()
    auto = std + mst + mtd
    auto_names = {e["name"] for e in auto}
    manual = []
    if ENTITIES.exists():
        try:
            import yaml
            old = yaml.safe_load(ENTITIES.read_text(encoding="utf-8")) or {}
            old_list = old.get("entities", [])
            # 保留非自动源实体（人工补充）与不在自动集内的实体
            manual = [e for e in old_list
                      if e.get("source") not in AUTO_SOURCES and e.get("name") not in auto_names]
        except Exception:
            manual = []
    merged_auto = merge_with_existing(auto)
    final = [ensure_layering(e) for e in (merged_auto + manual)]
    if write_back:
        ENTITIES.parent.mkdir(parents=True, exist_ok=True)
        ENTITIES.write_text(gen_yaml(final), encoding="utf-8")
    return final, auto, manual


def validate_entities() -> int:
    """CI 同步校验：entities.yaml 与知识库同源、分层字段合法。

    Returns:
        0 = 绿（同步且分层合法）· 1 = 偏差（落后知识库 / 分层非法）
    """
    if not ENTITIES.exists():
        print("❌ entities.yaml 不存在（应先运行 extract_entities.py 生成）")
        return 1
    import yaml
    cur = yaml.safe_load(ENTITIES.read_text(encoding="utf-8")) or {}
    cur_list = cur.get("entities", [])
    cur_names = {e["name"] for e in cur_list}
    std, mst, mtd = scan_and_build()
    src_names = {e["name"] for e in (std + mst + mtd)}
    missing = src_names - cur_names
    # 统计当前各类型数 + 分层字段校验（M1.0 ①）
    cnt = {}
    bad = []
    for e in cur_list:
        cnt[e.get("type", "?")] = cnt.get(e.get("type", "?"), 0) + 1
        for k, allowed in LAYER_ENUMS.items():
            if e.get(k) not in allowed:
                bad.append((e.get("name"), k, e.get(k)))
    if bad:
        print(f"❌ 分层字段非法 {len(bad)} 处：")
        for name, k, v in bad[:8]:
            print(f"   {name}: {k}={v!r} ∉ {sorted(LAYER_ENUMS[k])}")
        return 1
    if missing:
        print(f"❌ 实体层落后知识库 {len(missing)} 个：{sorted(missing)[:8]}")
        return 1
    print(f"✅ 实体层与知识库同步（{len(cur_names)} 实体 · "
          f"标准 {cnt.get('standard',0)} / 大师 {cnt.get('master',0)} / 方法 {cnt.get('method',0)}）")
    return 0


def _sources_stale() -> tuple:
    """源文档 mtime 是否晚于 entities.yaml。

    Returns:
        (stale: bool, detail: str)
    """
    if not ENTITIES.exists():
        return True, "entities.yaml 不存在"
    ent_mtime = ENTITIES.stat().st_mtime
    stale = []
    for s in (STANDARDS, MASTERS, TOOLS):
        if s.exists() and s.stat().st_mtime > ent_mtime:
            stale.append(s.name)
    if stale:
        return True, "源变更: " + ", ".join(stale)
    return False, "无源变更"


def sync_entities() -> int:
    """--sync：源变更感知的 auto-checkin（幂等 · 夜巡/CI-watch 安全）。

    - 源未变更且非 --force → 不触碰 entities.yaml，仅跑校验（幂等跳过）
    - 源变更或 --force   → auto_checkin 重生 + 输出 diff + 校验
    Returns:
        0 = 绿（含幂等跳过）· 1 = 重生后校验失败
    """
    force = "--force" in sys.argv
    stale, detail = _sources_stale()
    if not (stale or force):
        print(f"✅ [sync] 实体索引与源文档同频，幂等跳过（未触碰 {ENTITIES.name}）")
        return validate_entities()
    # 记录重生前状态用于 diff
    import yaml
    old_names, old_layer = set(), {}
    if ENTITIES.exists():
        old = yaml.safe_load(ENTITIES.read_text(encoding="utf-8")) or {}
        for e in old.get("entities", []):
            old_names.add(e.get("name"))
            old_layer[e.get("name")] = {k: e.get(k) for k in LAYER_ENUMS}
    final, auto, manual = auto_checkin(write_back=True)
    new_names = {e["name"] for e in final}
    new_layer = {e["name"]: {k: e.get(k) for k in LAYER_ENUMS} for e in final}
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names - {e["name"] for e in manual})
    updated = [n for n in (new_names & old_names) if old_layer.get(n) != new_layer.get(n)]
    print(f"🔄 [sync] {detail} → 重生 {ENTITIES.name}")
    print(f"   最终 {len(final)} 实体（标准/大师/方法 = "
          f"{sum(1 for e in final if e['type']=='standard')}/"
          f"{sum(1 for e in final if e['type']=='master')}/"
          f"{sum(1 for e in final if e['type']=='method')}）· 保留人工 {len(manual)}")
    if added:
        print(f"   新增 {len(added)}：{added[:10]}")
    if removed:
        print(f"   剔除（知识库已删除的自动实体） {len(removed)}：{removed[:10]}")
    if updated:
        print(f"   分层变更 {len(updated)}：{updated[:10]}")
    if not (added or removed or updated):
        print("   无差异（内容一致）")
    return validate_entities()


def main():
    # ---- --check：CI 同步校验（含方法实体） ----
    if "--check" in sys.argv:
        return validate_entities()

    # ---- --sync：源变更感知 auto-checkin（幂等 · 夜巡/CI-watch 安全 · M1.1） ----
    if "--sync" in sys.argv:
        return sync_entities()

    # ---- --scan：干跑报告（不写盘） ----
    if "--scan" in sys.argv:
        final, auto, manual = auto_checkin(write_back=False)
        cur_names = set()
        if ENTITIES.exists():
            import yaml
            cur = yaml.safe_load(ENTITIES.read_text(encoding="utf-8")) or {}
            cur_names = {e["name"] for e in cur.get("entities", [])}
        auto_names = {e["name"] for e in auto}
        would_add = sorted(auto_names - cur_names)
        would_drop = sorted(cur_names - auto_names - {e["name"] for e in manual})
        print(f"🔍 干跑 auto-checkin：")
        print(f"  自动派生实体 {len(auto)}（标准 {sum(1 for e in auto if e['type']=='standard')} / "
              f"大师 {sum(1 for e in auto if e['type']=='master')} / "
              f"方法 {sum(1 for e in auto if e['type']=='method')}）")
        print(f"  保留人工实体 {len(manual)}")
        print(f"  将新增 {len(would_add)}：{would_add[:10]}")
        print(f"  将剔除（知识库已删除的自动实体） {len(would_drop)}：{would_drop[:10]}")
        print(f"  最终集 {len(final)} 实体（--auto 写回生效）")
        return 0

    # ---- 默认 / --auto：auto-checkin 写回 ----
    final, auto, manual = auto_checkin(write_back=True)
    std_n = sum(1 for e in final if e["type"] == "standard")
    mst_n = sum(1 for e in final if e["type"] == "master")
    mtd_n = sum(1 for e in final if e["type"] == "method")
    print(f"✅ entities.yaml 已 auto-checkin：{len(final)} 实体"
          f"（标准 {std_n} · 大师 {mst_n} · 方法 {mtd_n}）"
          f"→ {ENTITIES}（保留人工实体 {len(manual)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
