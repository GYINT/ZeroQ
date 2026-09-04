# tests/_migrate_pytest_shim.py
# 一次性迁移脚本：为 30 个 `run_X_tests()` / `main()` 测试文件追加 pytest 入口 `test_suite()`。
# 保留原 `if __name__ == "__main__"` 直跑能力；不改写断言逻辑（行为等价）。
# 运行后即删除（不属于测试套件，非 *_test.py 故不被收集）。
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAK = ROOT / ".bak" / "2026-08-25-pytest"
BAK.mkdir(parents=True, exist_ok=True)

# 文件相对路径 -> __main__ 入口函数名
ENTRY = {
    "tests/basic/qcm_mcp_test.py": "run_all_tests",
    "tests/basic/qcm_mcp_v02_test.py": "run_v02_tests",
    "tests/basic/qcm_mcp_v021_test.py": "run_v021_tests",
    "tests/basic/qcm_mcp_v022_test.py": "run_v022_tests",
    "tests/basic/qcm_mcp_v03_test.py": "run_v03_tests",
    "tests/basic/qcm_mcp_v041_test.py": "run_v041_tests",
    "tests/basic/qcm_mcp_v042_test.py": "run_v042_tests",
    "tests/basic/qcm_mcp_v043_test.py": "run_v043_tests",
    "tests/basic/qcm_mcp_v044_test.py": "run_v044_tests",
    "tests/basic/qcm_mcp_v05_test.py": "run_v05_tests",
    "tests/basic/qcm_mcp_v050_test.py": "run_v050_tests",
    "tests/basic/qcm_mcp_v06_test.py": "run_v06_tests",
    "tests/basic/qcm_mcp_v060_test.py": "run_v060_tests",
    "tests/basic/qcm_mcp_v061_test.py": "run_v061_tests",
    "tests/basic/qcm_mcp_v07_test.py": "run_v07_tests",
    "tests/basic/qcm_mcp_v070_test.py": "run_v070_tests",
    "tests/basic/qcm_mcp_v071_test.py": "run_v071_tests",
    "tests/basic/qcm_mcp_v08_test.py": "run_v08_tests",
    "tests/basic/qcm_mcp_v09_test.py": "run_v09_tests",
    "tests/basic/qcm_mcp_v081_test.py": "run_v081_tests",
    "tests/protocol/qcm_mcp_v110_test.py": "run_v110_tests",
    "tests/protocol/qcm_mcp_v120_test.py": "run_v120_tests",
    "tests/protocol/qcm_mcp_v121_test.py": "run_v121_tests",
    "tests/protocol/qcm_mcp_v123_test.py": "run_v123_tests",
    "tests/protocol/qcm_mcp_v131_test.py": "run_v131_tests",
    "tests/protocol/qcm_mcp_v140_test.py": "run_v140_tests",
    "tests/protocol/qcm_mcp_v151_test.py": "run_v151_tests",
    "tests/protocol/qcm_mcp_v160_test.py": "run_v160_tests",
    "tests/qcm_v82_test.py": "run_v82_tests",
    "tests/qcm_router_golden_test.py": "main",
}

SHIM = '''

# === pytest 适配（不影响 `python <本文件>` 直跑）===
def test_suite():
    """pytest 入口：等价运行整套断言（run_X_tests / main）。"""
    import sys as _sys
    try:
        _r = ENTRY()
    except _sys.exit as _e:
        assert _e.code in (0, None), "测试套件退出码非0/None: %r" % (_e.code,)
        return
    assert _r, "测试套件未全部通过"
'''


def main():
    for rel, entry in ENTRY.items():
        p = ROOT / rel
        if not p.exists():
            print("MISSING:", rel)
            continue
        src = p.read_text(encoding="utf-8")
        if "def test_suite" in src:
            print("skip (已迁移):", rel)
            continue
        shutil.copy(p, BAK / p.name)
        shim = SHIM.replace("ENTRY()", entry + "()")
        if not src.endswith("\n"):
            src += "\n"
        p.write_text(src + shim, encoding="utf-8")
        print("migrated:", rel, "->", entry)
    print("DONE")


if __name__ == "__main__":
    main()
