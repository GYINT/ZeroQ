# scenarios/events/ · event 归一化语料入口（【可检索】corpus · 知识族）

> **定位**：event 资产化后的**归一化检索入口**，由 `enroll_corpus(event_id, apply=True)` 自动派生。
> **性质**：只读回链 —— 真源唯一为 `references/data/zero_events.yaml`，本目录绝不承载可写业务真值（红线）。
> **检索族**：本目录匹配 `/scenarios/ → corpus/知识族`（既有 classify 规则），无需新增规则。

## 文件形态（由 enroll_corpus 自动生成，勿手改）

每个 deposited 事件生成 `<event_id>`（落盘为 `.md`），固定结构：

```
# <event_id> · 归零事件资产化入口
<!-- id: case-ze-<event_id>; tags: <route>,<domain>,<severity>,<intent>,internal -->
> 本块由 enroll_corpus 自动派生（只读回链 · 真源唯一）；状态 / 路由
## 核心画像      （标题/领域/严重度/路由意图/关联标签）
## 治理闭环      （有效性验证/水平展开）
## 可借鉴点      （D6 沉淀 / D7 复用特征，deposit 后 enrich）
## 来源          （🔗 真源 + 🔗 原始证据 sources/events/）
```

- **tags 由 `intent_route` → tag 映射表统一派生**（②→standard / ③→audit·feedback / ⑤→spread / ⑥→culture），非写死⑥（G-UNI-1）。
- **状态门**：仅 `deposited/reused/resolved` 事件可入（对齐 `query_reuse` 状态门，G-EVT-3）。
- **双检索面去重**：与 `sources/events/` 共用同一 `event_id`；消费端（router/search）按 `event_id` 合并命中。

## 索引（G-EVT-2 绕 30KB）

enroll 时由 `_gen_event_index` 显式生成 `references/index/<event_id>.index.yaml` 并登记 corpus 段，绕过 30KB 自动跳过。

## 滞后检测（G-EVT-1 缓解）

`python core/zero_event.py --stale` 比对 P0 mtime vs 本目录入口 vs P2 证据，检出滞后项。
