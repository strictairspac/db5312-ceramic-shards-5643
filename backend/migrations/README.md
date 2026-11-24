# 版本化迁移

`ensure_schema` 在 API 启动和 `python -m scripts.seed_demo` 时执行：先补建缺失表，再为已有演示卷补上更正与交接所需的列（`business_cases.revision`、`business_runs.revision`、`business_evidence.revision/state/voided_at/void_reason`），并补建 `case_revisions`、`business_corrections`、`business_handovers` 表。历史证据默认视为其版本的 `valid`。

需要在已有生产库升级表结构时，应单独引入版本化迁移；本文件只覆盖演示环境的向前兼容。
