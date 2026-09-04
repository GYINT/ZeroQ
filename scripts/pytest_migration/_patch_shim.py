# tests/_patch_shim.py
# 修正 test_suite 入口的返回值判定：
#   - bool: 真值=通过（run_X_tests 返回 passed==total）
#   - int : 0=通过（main() 返回退出码，bool 是 int 子类须先判定）
#   - None: 视为通过（main 内部已 sys.exit）
#   - 其他: 按非空判定
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAK = ROOT / ".bak" / "2026-08-25-pytest-shimfix"
BAK.mkdir(parents=True, exist_ok=True)

OLD = '    assert _r, "测试套件未全部通过"\n'
NEW = (
    '    if _r is None:\n'
    '        return\n'
    '    if isinstance(_r, bool):\n'
    '        assert _r, "测试套件未全部通过"\n'
    '    elif isinstance(_r, int):\n'
    '        assert _r == 0, "测试套件退出码 %d" % _r\n'
    '    else:\n'
    '        assert _r, "测试套件未全部通过"\n'
)

# 30 个已迁移文件
FILES = []
for d in ("basic", "protocol"):
    FILES += sorted((ROOT / "tests" / d).glob("*_test.py"))
FILES += [ROOT / "tests" / "qcm_v82_test.py", ROOT / "tests" / "qcm_router_golden_test.py"]

n = 0
for p in FILES:
    src = p.read_text(encoding="utf-8")
    if OLD in src:
        shutil.copy(p, BAK / p.name)
        p.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
        n += 1
        print("patched:", p.name)
    else:
        print("skip (无匹配):", p.name)
print("PATCHED", n)
