# CodeEvo 产品路线图

## 第一阶段：工程与安全基线（已完成）

- 完成产品、Python 包、环境变量、数据库和运行时命名空间重命名。
- 修复 macOS 动态 Skill 资源限制失败，保留 Linux 容器内存限制。
- 补齐 PostgreSQL 影子发布存储契约与自动晋级数据结构。
- GitHub App 安装使用短期签名 state，并按管理员租户绑定。
- 自动修复拒绝跨租户 GitHub installation。
- 认证部署的仓库访问改为默认拒绝。
- Compose 移除默认密码和签名密钥，缺少配置时拒绝启动。
- Docker 使用非 root 用户运行。
- 增加 pyproject、Ruff 和 GitHub Actions。

## 第二阶段：服务架构重构（已完成）

- 使用 FastAPI 与 Pydantic 重构 HTTP API。（已完成）
- 增加 OpenAPI、统一错误模型、请求 ID、安全响应头和登录限流。（已完成）
- 核心认证、审查、任务、反馈、Webhook、发布与演进接口完成迁移。（已完成）
- 引入 SQLAlchemy Repository、连接池与 Alembic 数据库迁移。（已完成）
- 建立 PostgreSQL、Redis、GitHub Webhook 容器集成测试。（已完成）
- 增加结构化 JSON 日志和显式可信代理配置。（已完成）

## 第三阶段：仓库上下文 Agent（已完成）

- 增加文件读取、符号搜索、引用定位和调用方检索工具。（已完成）
- 使用 Tree-sitter 构建语言感知的代码上下文。（已完成）
- 高风险 Finding 必须绑定已读取代码和可复核证据。（已完成）

## 第四阶段：真实数据 Evaluation Harness（已完成平台能力）

- 建立仓库隔离的 Train、Validation、Holdout 和真实 PR 测试集。（已完成导入、校验与清单；真实标注数据持续扩充）
- 同时评估质量、P50/P95/P99 延迟、Token、模型调用和调用成本。（已完成）
- 让 Prompt、Skill 和路由策略变更自动触发统一非退化门禁。（已完成）
- 对公开 PR 绑定 URL、base/head SHA、Diff SHA-256、License 和人工标注证据。（已完成）

## 第五阶段：受控进化与自动修复

- 从确认反馈生成 Prompt、声明式 Skill 和路由候选。
- 接入 Shadow、Canary、审批和回滚。
- 在无网络容器中生成、比较并验证候选补丁，最终创建 Draft PR。

## 第六阶段：公开 PR 标注与真值生产（已完成）

- 从 GitHub 在线验证并导入真实公开 PR，绑定许可证和不可变来源证据。（已完成）
- 使用两个不同账号完成盲审，标签签名一致时自动通过。（已完成）
- 双人结论不一致时由非原标注者完成可审计仲裁。（已完成）
- 复用仓库级 Train、Validation、Holdout 分区并保护 Holdout 真值。（已完成）
- 只将通过来源、位置、泄漏和重复门禁的案例导出到 Evaluation Harness。（已完成）
- 提供管理台完整状态、响应式布局、演示数据和 PostgreSQL/SQLite 持久化。（已完成）
