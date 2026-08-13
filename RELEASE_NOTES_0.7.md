# CodeEvo 0.7.0

本版本为单人维护场景增加无需人工标注的可执行安全基准流水线。

## 新增

- 从 Vul4J 官方 CSV、GitHub 安全修复提交和 NVD CVSS 自动生成风险/修复案例对；
- 反向补丁构造 `vulnerability-introducing` 风险 Diff，正向补丁构造目标 CWE 修复 Diff；
- `target-cwe` 案例级计分，明确避免把自动候选区域表述成精确根因行；
- `benchmark-derived` 来源模型，记录原始数据行及哈希、commit/parent SHA、原始/派生 Diff SHA-256、许可证和复现证据；
- repository-level Train/Validation/Holdout 确定性隔离；
- GitHub/NVD 响应缓存、断点重跑、限流识别、严格 TLS CA 校验；
- 生产数据门禁支持来源完整的公开 PR 与可执行基准，继续拒绝 demo 和 synthetic 数据。

## 数据声明

- `reviewer_count=0`，不冒充人工标注；
- clean 只表示目标 CWE/CVE 被官方补丁修复，不代表提交不存在其他问题；
- 默认采用 Vul4J 发布的可复现状态；只有实际本地运行复现命令后才能标为 `locally-reproduced`；
- 外部数据和仓库代码继续受其各自许可证约束。

## 验证

- Ruff 静态检查通过；
- 98 项测试：94 项通过，4 项 PostgreSQL/Redis 容器集成测试因未配置服务跳过；
- 真实网络烟测成功生成 Vul4J 派生风险/修复案例对；
- JSONL、manifest、来源验证、反向 Diff 和目标 CWE 计分均覆盖自动化测试。
