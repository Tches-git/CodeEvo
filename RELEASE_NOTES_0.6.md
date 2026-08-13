# CodeEvo 0.6.0

CodeEvo 0.6.0 增加了从真实公开 Pull Request 生产可审计 Evaluation Harness 真值的完整工作台。

## 本版本新增

- 公开 PR 在线导入，绑定 GitHub URL、API URL、base/head SHA、Diff SHA-256、License 和获取时间。
- 仓库级确定性 Train、Validation、Holdout 分区，避免同仓库跨集合泄漏。
- 两个不同账号独立盲审，第一份提交不会在第二份提交前暴露。
- `risk` 要求有效 Finding，`clean` 必须显式提交空 Finding 数组。
- Finding 必须包含新增行范围、CWE、严重级别以及说明或 HTTPS 证据。
- 可复现标签签名一致时自动通过，不一致时进入第三人仲裁。
- 原始标注者不能仲裁同一案例，导入、提交、仲裁和导出全程写入审计日志。
- Holdout 真值不向普通读取接口暴露。
- 导出前重新执行 Harness case 校验、公开来源校验、仓库泄漏和重复 Diff 检测。
- 标注队列、Diff 证据、Finding 编辑、冲突对比、仲裁和 JSONL 下载管理台。
- SQLite、PostgreSQL、SQLAlchemy metadata 和 Alembic 同步支持四张新表。
- 明确标记为 `demo-fixture` 的离线界面演示数据脚本，演示记录不能通过真实来源导出门禁。

## 安全与一致性

- 数据集下载响应携带 `X-Dataset-SHA256`，文件名和版本字段经过安全字符归一化。
- 唯一约束禁止同一账号占用两个标注席位，并限制同一租户重复导入同一 PR。
- PostgreSQL 使用行锁保护标注席位，状态更新使用单向迁移和并发保护。
- 管理员也只能在双人提交完成后查看对比答案，避免提前影响第二位评审。

## 验证状态

- Ruff、Python compileall 和 JavaScript 语法检查通过。
- 94 项测试：90 项通过，4 项 PostgreSQL/Redis 容器集成测试在未配置容器服务时跳过。
- Alembic SQLite 烟测创建 26 张表并写入最新 revision。
- 浏览器 QA 覆盖 1280x720 桌面和 390x844 移动视口，无横向溢出或控制台错误。
