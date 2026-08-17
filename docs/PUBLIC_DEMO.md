# CodeEvo 公开 Demo 部署

公开 Demo 部署在腾讯云主机 `tencent-111`：

- 在线入口：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443>
- 就绪状态：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443/health/ready>
- 应用内部监听：`127.0.0.1:18181`
- HTTPS：Tailscale Funnel 独立端口 `8443`
- 数据层：PostgreSQL 16 + Redis 7
- 实时 Agent：本地确定性规则，不需要模型 Key

首页提供“进入公开工程工作台”。访客会话约 5 分钟，不需要账号密码，可以读取隔离的
`public-demo` 租户并运行临时本地 Agent Sandbox。已发布的 DeepSeek Benchmark 只作为实验制品展示，
浏览和 Sandbox 执行都不会调用付费模型。

## 部署布局

```text
Internet
  -> Tailscale Funnel :8443 (HTTPS)
  -> 127.0.0.1:18181
  -> CodeEvo container :8080
  -> PostgreSQL + Redis (仅 Compose 内部网络)
```

```text
/opt/codeevo/repository   部署清单、源码和运维脚本
/opt/codeevo/credentials  服务器私密环境文件
/opt/codeevo/backups      0600 PostgreSQL 逻辑备份
codeevo-demo              独立 Compose 项目
```

这个部署不占用公网 `80`/`443`，不修改已有 Nginx、Caddy 或其他 Compose 项目。CodeEvo 只绑定
回环地址，并以非 root 用户、只读根文件系统和零 Linux capabilities 运行。

## 访客安全边界

- `CODEEVO_AUTH_REQUIRED=true`，Guest 不是绕过认证；
- Guest Principal 只有 `demo_read/demo_execute`，没有 `read/review/fix/manage/audit`；
- Guest 固定进入 `public-demo`，不能传入或切换租户；
- 只允许 Dashboard、任务列表/报告、Evaluation/Evolution 实验制品和临时 Sandbox；
- Sandbox 使用临时 SQLite，只加载本地 Security/Reliability Agent，请求结束后自动销毁；
- GitHub 输入只接受严格 PR URL 并固定请求 `api.github.com`，同时限制 Diff 大小和执行频率；
- 生产写入口在 UI 隐藏，后端仍对直接 API 请求返回 403；
- 自动 PR 回写、自动修复和付费模型在线调用保持关闭。

## 日常检查

```bash
ssh tencent-111 '
  cd /opt/codeevo/repository
  CODEEVO_COMPOSE_PROJECT=codeevo-demo \
  CODEEVO_HEALTH_LOCAL_URL=http://127.0.0.1:18181 \
  CODEEVO_HEALTH_PUBLIC_URL=https://vm-0-13-ubuntu.taila0420b.ts.net:8443 \
  ./ops/health_check.sh
  systemctl list-timers "codeevo-*" --no-pager
'
```

管理员凭据只用于维护，保存在服务器私密目录，不需要也不应提供给公开访客。

## 更新服务

先运行备份，再同步已通过测试的新版本：

```bash
ssh tencent-111 '
  cd /opt/codeevo/repository
  export CODEEVO_COMPOSE_PROJECT=codeevo-demo
  export CODEEVO_BACKUP_DIR=/opt/codeevo/backups
  ./ops/backup_postgres.sh
  docker compose --project-name codeevo-demo build codeevo
  docker compose --project-name codeevo-demo up -d --wait
  CODEEVO_HEALTH_LOCAL_URL=http://127.0.0.1:18181 ./ops/health_check.sh
'
```

服务器 `.env` 至少应包含 Guest 配置和 `CODEEVO_IMAGE_TAG=1.1.0`，但不要输出或提交完整文件。

## 备份、恢复与告警

- `ops/backup_postgres.sh`：custom-format 原子备份、`pg_restore --list` 校验、0600 权限、默认保留 14 天；
- `ops/restore_postgres.sh`：必须显式指定目标和 `--confirm`，默认拒绝覆盖 `codeevo`；
- `ops/health_check.sh`：检查三容器、live、ready 和可选公网入口；
- `ops/disk_guard.sh`：80% warning、90% critical，可选 Webhook，不自动删除；
- `ops/docker_prune_safe.sh`：只清 dangling image 和 7 天前 build cache，不删除 volume；
- `ops/install_systemd.sh --enable`：安装每日备份、每 5 分钟探针和每日磁盘检查。

恢复演练使用临时数据库并在核验表数和任务数后删除，生产 CodeEvo 无需停机。

## 验收标准

- `/health/live` 与 `/health/ready` 为 HTTP 200；
- 未登录业务 API 返回 401，Guest 登录返回短期 Token；
- Guest 可读取 3 个展示任务、8 个 Validation 案例和演进证明，并可执行隔离 Sandbox；
- Guest 对生产审查、反馈、修复、标注和配置写请求返回 403；
- PostgreSQL、Redis、CodeEvo 容器均 healthy；
- 最新备份可通过 `pg_restore --list` 并成功恢复到隔离数据库；
- 重启 CodeEvo 后 readiness 恢复，Guest 登录仍可用；
- Tailscale Funnel 的 8443 HTTPS 转发正常。

根目录 `render.yaml` 是备用托管方案，不是当前线上实例的部署来源。
