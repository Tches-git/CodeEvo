# CodeEvo 部署指南

本文给出单机 Docker Compose 的可复现部署方式。默认拓扑包含 CodeEvo、PostgreSQL 16 和 Redis 7，适合作品演示、小团队试用和单节点生产环境。

## 1. 前置条件

- Docker Engine 24+ 与 Docker Compose v2；
- 至少 2 CPU、4 GB 内存和 10 GB 可用磁盘；
- 如需公网访问，准备支持 HTTPS 的反向代理和域名；
- 如需 DeepSeek，使用新建且未出现在代码、聊天记录或日志中的 API Key。

## 2. 生成配置

```bash
cp .env.compose.example .env
python - <<'PY'
import secrets
print("CODEEVO_POSTGRES_PASSWORD=" + secrets.token_urlsafe(32))
print("CODEEVO_AUTH_SECRET=" + secrets.token_urlsafe(48))
print("CODEEVO_BOOTSTRAP_ADMIN_PASSWORD=" + secrets.token_urlsafe(24))
PY
```

把输出填入 `.env`。数据库密码必须使用 URL 安全字符，因为 Compose 会将它放入 PostgreSQL URL。`.env` 已被 Git 忽略，禁止提交或复制到 Issue、截图和日志中。

默认配置使用本地确定性 Agent，无需外部模型。如果启用 DeepSeek：

```dotenv
CODEEVO_LLM_PROVIDER=deepseek
CODEEVO_DEEPSEEK_API_KEY=<new-key>
```

## 3. 启动与验收

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8080/health/live
curl --fail http://127.0.0.1:8080/health/ready
```

如果当前网络无法稳定访问官方 PyPI，可在 `.env` 中设置一次构建镜像源，例如
`CODEEVO_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。该参数只作用于镜像构建，
不会进入最终运行时镜像；生产环境应使用组织审核过的包代理或官方源。

就绪响应示例：

```json
{"status":"ok","checks":{"persistence":true,"queue":true}}
```

打开 `http://127.0.0.1:8080`，使用 `.env` 中的 Bootstrap 管理员登录。管理员只在首次不存在时创建；以后修改环境变量不会覆盖已有密码。

## 4. 健康检查语义

| 路径 | 含义 | 失败行为 |
|---|---|---|
| `/health/live` | Python/FastAPI 进程仍能响应 | 进程或 HTTP 服务异常时失败 |
| `/health/ready` | 持久化与任务队列均可执行真实命令 | 任一依赖异常时返回 HTTP 503 |
| `/health` | 当前 Reviewer、Runtime、Queue 和模型摘要 | 不应作为编排流量门禁 |

Docker 镜像与 Compose 都使用 `/health/ready`。数据库或 Redis 断开时，容器保持存活但转为 unhealthy，便于保留日志和自动恢复连接。

## 5. 网络与反向代理

Compose 默认将端口绑定到 `127.0.0.1`，避免误把管理台直接暴露到公网。推荐由同机 Caddy、Nginx 或云负载均衡器终止 TLS，再代理到 `127.0.0.1:8080`。

只有实际代理来源网段应写入：

```dotenv
CODEEVO_TRUSTED_PROXY_CIDRS=172.16.0.0/12
CODEEVO_PUBLIC_BASE_URL=https://codeevo.example.com
```

不要把 `0.0.0.0/0` 设为可信代理。若只需要 GitHub Webhook，优先仅公开 `/webhooks/github` 和按需公开探针，而不是整个管理台。

## 6. 日常运维

查看状态与结构化日志：

```bash
docker compose ps
docker compose logs --tail=200 codeevo
docker compose logs --tail=100 postgres redis
```

拉取代码并滚动到新版本：

```bash
git pull --ff-only
docker compose build --pull codeevo
docker compose up -d
curl --fail http://127.0.0.1:8080/health/ready
```

数据库迁移默认在 API 启动时运行。严格发布环境可以先执行迁移，然后设置 `CODEEVO_DATABASE_AUTO_MIGRATE=false`：

```bash
docker compose run --rm codeevo codeevo-migrate head
docker compose up -d
```

## 7. 备份与恢复

仓库内置脚本会使用 custom format 创建原子备份，设为 0600，运行 `pg_restore --list` 校验，
并按默认 14 天保留策略清理过期文件：

```bash
CODEEVO_BACKUP_DIR=/srv/codeevo/backups ./ops/backup_postgres.sh
```

恢复必须显式提供备份、目标数据库与 `--confirm`。默认拒绝把目标设为生产库 `codeevo`。推荐先恢复到
隔离库，检查表数和任务数后自动删除：

```bash
./ops/restore_postgres.sh \
  --backup /srv/codeevo/backups/codeevo-20260813T032000Z.dump \
  --target-db codeevo_restore_drill \
  --confirm --drop-after-check
```

Redis 保存的是可重投递任务流，不是真值数据库。首先保护 PostgreSQL 备份；Redis volume 用于减少重启期间的排队任务损失。

## 8. 健康检查、告警与定时器

```bash
CODEEVO_HEALTH_LOCAL_URL=http://127.0.0.1:8080 \
CODEEVO_HEALTH_PUBLIC_URL=https://codeevo.example.com \
./ops/health_check.sh

CODEEVO_DISK_WARNING_PERCENT=80 \
CODEEVO_DISK_CRITICAL_PERCENT=90 \
./ops/disk_guard.sh
```

两者都支持通过服务器私密环境文件设置 `CODEEVO_ALERT_WEBHOOK_URL`。磁盘脚本只告警，不自动删除数据。
确需释放 Docker 空间时可执行 `ops/docker_prune_safe.sh`，它只清理 dangling image 和 7 天前的 build
cache，绝不删除 volume。

在固定部署路径 `/opt/codeevo/repository` 上安装 timers：

```bash
sudo ./ops/install_systemd.sh --enable
systemctl list-timers 'codeevo-*' --no-pager
```

默认计划为每日 03:20 备份、每 5 分钟健康检查、每日 04:00 磁盘检查。环境覆盖写入
`/opt/codeevo/credentials/ops.env` 并设为 0600，不要提交到仓库。

## 9. 仓库上下文挂载

如需 Tree-sitter 仓库工具，在 Compose 的 `codeevo` 服务下增加专用只读目录：

```yaml
environment:
  CODEEVO_REPOSITORY_ROOT: /repositories
volumes:
  - /srv/codeevo-repositories:/repositories:ro
```

宿主机目录必须按 `<owner>/<repository>` 组织。禁止挂载用户主目录、Docker Socket 或文件系统根目录。

## 10. 停止与清理

```bash
docker compose down
```

该命令保留 PostgreSQL 与 Redis volumes。只有确认数据已有备份且不再需要时，才使用 `docker compose down --volumes`；该操作会删除持久数据。

## 11. 常见故障

- `docker compose config` 报变量缺失：`.env` 中仍有必填项为空或文件不存在。
- `/health/live` 成功但 `/health/ready` 返回 503：查看 PostgreSQL、Redis 与 CodeEvo 日志，重点检查密码、服务名和迁移。
- 容器反复重启：运行 `docker compose logs codeevo`，常见原因是认证密钥不足 32 字节或管理员密码不符合长度要求。
- DeepSeek 请求失败：确认 Provider 与 Key 均配置，Key 未失效，并检查供应商额度；不要把 Key 输出到日志。
- 浏览器无法访问：确认默认绑定地址为 `127.0.0.1`。公网部署应配置反向代理，而不是直接改为裸 HTTP 公网暴露。
