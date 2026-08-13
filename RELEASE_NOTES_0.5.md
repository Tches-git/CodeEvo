# CodeEvo 0.5.0

CodeEvo 0.5.0 将 Evaluation Harness 升级为可用于 Agent 工程展示的统一评测与发布门禁平台。

## 本版本新增

- 真实公开 GitHub PR 导入：绑定公开 URL、API URL、base/head SHA、Diff SHA-256、License 与人工标注证据。
- 数据集完整性：确定性 repository-level Train/Validation/Holdout 分区，拒绝同仓库跨分区和重复 Diff。
- 资源评测：单案例延迟、P50/P95/P99、模型调用次数、输入/输出/总 Token 与估算成本。
- 可信 usage：本地 Agent 明确为 not applicable；供应商缺少 usage 或单价时为 unavailable，不伪造数值。
- 统一门禁：Prompt、声明式 Skill 和路由候选共享质量、延迟、Token 与成本非退化策略。
- 路由发布保护：未通过服务端重新计算的离线门禁，候选不能进入 Shadow 或 Canary。
- 新增 `POST /v1/evaluation/routing-policy` 与可复现路由策略评测脚本。
- Web 管理台作为 Python package data 随 wheel 分发，独立安装后可直接访问。

## 可复现结果

- 受控 100-case 基准：候选 F1 82.5%，高风险召回 94.7%，干净 PR 准确率 91.7%。
- 安全修复验证通过率 78.8%，端到端安全修复成功率 65.0%。
- Prompt 自进化证明：候选通过 Validation 与 Holdout 门禁并激活。
- 路由策略证明：质量、P95 延迟、Token 与成本门禁通过，结果为 eligible-for-shadow。

受控基准使用 `synthetic-controlled` 数据，因此生产数据来源门禁保持失败；只有带独立人工真值与完整来源证明的公开 PR 数据集才允许生产激活。

## 验证状态

- Ruff 与 compileall 通过。
- 90 项测试：87 项通过，3 项 PostgreSQL/Redis 容器集成测试因本机 Docker daemon 未运行而跳过。
- Alembic SQLite 烟测创建 22 张表并写入 `alembic_version`。
- wheel 独立安装、OpenAPI 0.5.0、Web 管理台与 Tree-sitter parser 烟测通过。
