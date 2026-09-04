# zero_event 动态资产落地目录（QCM 子模块）

本目录承接 `core/zero_event.py` 归零事件全景维度子模块（ZE-PDM）的**事件级动态资产**，
与注册表本体 `references/data/zero_events.yaml`（system of record）分离管理，避免单一文件膨胀。

## 角色
- 事件级沉淀详情 / 复用报告 / 退休交接记录落盘处
- 受 `scripts/asset_retirement.py`（R4R 资产退休环）观察管理
- 注册表本体仍驻 `references/data/zero_events.yaml`（含 meta），遵循 QCM `data/` 约定

## 约定
- 默认关闭（`enabled=false`）：不挂 nightrun、不自动记录，仅用户 `--trigger` 主动记录
- 所有落地资产为只读观测 / 报告产物，不静默改写注册表
- 与 QCM 守卫一致：report-only、用户主动触发
