#!/usr/bin/env python3
"""ZeroQ 跨 Skill 依赖解析器（归一化 · 消灭跨 Skill 硬编码）

背景：ZeroQ 与生态 Skill（如 Infoseek 调研引擎）双向联用。此前各文件硬编码
开发机绝对路径，环境迁移/部署必坏。本模块统一收敛：env > 探测列表 > 验证 > 降级。

原则（跨 Skill 专用）：
  ① 探测优先于硬编码：枚举常见安装路径 + 验证标志文件存在
  ② env 是唯一覆盖入口：INFOSEEK_ROOT 显式指定优先
  ③ 缺失降级显式化：找不到返回 None + 告警（不静默失败）
  ④ 测试可注入：测试用 env 指向隔离目录

用法：
  from registry import find_skill
  infoseek_root = find_skill("infoseek")   # Path | None
  infoseek_server = infoseek_root / "scripts" / "infoseek_mcp_server.py"
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 已知 Skill 探测配置（跨 Skill 契约 · 单一真源） ──
SKILL_DEFS = {
    "infoseek": {
        "env": "INFOSEEK_ROOT",
        "paths": [
            "~/.workbuddy/skills/infoseek",   # 本地用户级（Windows/macOS/Linux）
        ],
        "markers": ["SKILL.md", "scripts/infoseek_mcp_server.py"],
    },
    # 未来扩展：本 Skill 自身注册（供其他 Skill 反向依赖）时在此追加
}


def find_skill(name: str) -> Optional[Path]:
    """探测指定 Skill 的安装根目录。

    优先级：env 显式指定 > 常见路径探测 > None（降级）
    验证：目录存在 + markers 全部存在（防误判）。
    """
    cfg = SKILL_DEFS.get(name)
    if not cfg:
        logger.warning(f"skill_registry: 未知 skill '{name}'（未注册）")
        return None

    candidates = []
    env_val = os.environ.get(cfg["env"], "").strip()
    if env_val:
        candidates.append(env_val)
    candidates.extend(cfg["paths"])

    for c in candidates:
        # V8.4 A3 修复：支持 ~ 展开（本地用户级 skills 目录探测）
        p = Path(c).expanduser()
        if not p.is_dir():
            continue
        # 验证标志文件（防"同名目录非目标 skill"）
        if all((p / m).exists() for m in cfg["markers"]):
            return p.resolve()

    logger.warning(f"skill_registry: 未找到 skill '{name}'（env={cfg['env']} 未设置或路径无效）")
    return None


def require_skill(name: str) -> Path:
    """强依赖版本：找不到直接抛异常（用于必须联用的场景）。"""
    p = find_skill(name)
    if p is None:
        raise FileNotFoundError(
            f"跨 Skill 依赖缺失: '{name}' 未安装（设置 {SKILL_DEFS[name]['env']} 或安装到常见路径）")
    return p


if __name__ == "__main__":
    for name in ["infoseek"]:
        p = find_skill(name)
        print(f"{name:10s} → {p if p else '❌ 未找到'}")
