# CodeEvo 0.9.0

本版本将项目从“可本地运行”推进到“可重复部署与验收”，重点补齐容器供应链、依赖就绪探针、运行时加固和运维文档。

## 新增

- `/health/live` 进程存活探针；
- `/health/ready` 依赖就绪探针，真实查询 SQLite/PostgreSQL 与内存队列/Redis；
- 任一核心依赖不可用时 readiness 返回 HTTP 503，且不暴露连接信息；
- PostgreSQL 和 Redis 探测使用有界连接/命令超时，避免网络黑洞拖死探针；
- 多阶段生产镜像，构建 Python Wheel 后安装到最小运行时；
- OCI 镜像来源、版本提交和许可证元数据；
- 可覆盖的构建包索引，默认保持官方 PyPI；
- 专用 `.env.compose.example`，区分本地开发配置与生产 Compose 必填项；
- 单机 Compose 部署、升级、迁移、备份、恢复、代理与排障手册；
- GitHub Actions 容器构建与真实 HTTP 冒烟测试。

## 安全与运维

- CodeEvo 容器使用非 root 系统用户；
- Compose 默认只绑定宿主机 `127.0.0.1`；
- 应用根文件系统只读，只提供受限 `/tmp`；
- 删除全部 Linux capabilities，并启用 `no-new-privileges`；
- PostgreSQL 与 Redis 使用持久 volume、健康检查和重启策略；
- Compose 等待数据库和队列健康后启动 API；
- 密钥、数据库密码和管理员凭据没有内置默认值，缺失时拒绝启动。

## 验证

- Ruff 与 Python 编译检查通过；
- 118 项测试通过，普通环境下 4 项外部后端测试按预期跳过；
- PostgreSQL/Redis 集成测试覆盖真实 readiness；
- 本地真实构建生产镜像，并确认容器以 `codeevo` 用户运行；
- 完整 Compose 中 PostgreSQL、Redis、CodeEvo 三个服务均达到 healthy；
- readiness 返回 `persistence=true`、`queue=true`；
- Alembic 在 PostgreSQL 中创建 26 张项目表；
- 容器运行状态确认 `read_only=true`、`cap_drop=ALL` 与 `no-new-privileges=true`。
