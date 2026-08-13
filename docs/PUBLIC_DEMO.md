# CodeEvo 公开 Demo 部署

公开 Demo 已部署在腾讯云主机 `tencent-111`：

- 在线入口：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443>
- 就绪状态：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443/health/ready>
- 应用内部监听：`127.0.0.1:18181`
- HTTPS：Tailscale Funnel 独立端口 `8443`
- 数据层：PostgreSQL 16 + Redis 7
- Agent：本地确定性规则，不需要模型 Key

公开实例强制登录，自动 PR 回写和自动修复保持关闭。管理员密码、认证签名密钥和数据库
密码只保存在服务器，不能写入仓库或命令历史。

## 部署布局

```text
Internet
  -> Tailscale Funnel :8443 (HTTPS)
  -> 127.0.0.1:18181
  -> CodeEvo container :8080
  -> PostgreSQL + Redis (仅 Compose 内部网络)
```

服务器路径与 Compose 项目名：

```text
/opt/codeevo/repository   部署清单与源码
/opt/codeevo/credentials  公开 Demo 登录信息（0600）
codeevo-demo              独立 Compose 项目
```

这个部署不会占用公网 `80`/`443`，也不会修改服务器已有的 Nginx、Caddy 或其他 Compose
项目。CodeEvo 容器只绑定回环地址，并以非 root 用户、只读根文件系统和零 Linux
capabilities 运行。

## 日常检查

```bash
ssh tencent-111 '
  cd /opt/codeevo/repository
  COMPOSE_PROJECT_NAME=codeevo-demo docker compose ps
  curl --fail http://127.0.0.1:18181/health/live
  curl --fail http://127.0.0.1:18181/health/ready
  tailscale funnel status
'
```

从外部网络检查：

```bash
curl --fail https://vm-0-13-ubuntu.taila0420b.ts.net:8443/health/live
curl --fail https://vm-0-13-ubuntu.taila0420b.ts.net:8443/health/ready
```

登录信息不在 README 公开。项目维护者可以在受信任的终端查看：

```bash
ssh tencent-111 'sudo cat /opt/codeevo/credentials'
```

不要把该命令的输出粘贴到 Issue、CI 日志或公开聊天中。

## 更新服务

先备份数据库，再同步已验证的新版本到 `/opt/codeevo/repository`，然后运行：

```bash
ssh tencent-111 '
  cd /opt/codeevo/repository
  export COMPOSE_PROJECT_NAME=codeevo-demo
  docker compose build codeevo
  docker compose up -d --wait
  docker compose ps
'
```

如果官方 PyPI 在国内网络下载缓慢，可在服务器 `.env` 中设置
`CODEEVO_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 后重新构建。完整备份、恢复、
迁移和回滚流程见 [部署指南](DEPLOYMENT.md)。

## 安全边界

- 保持 `CODEEVO_AUTH_REQUIRED=true`；
- 不向公网映射 PostgreSQL 和 Redis 端口；
- 不在公开 Demo 配置具有 PR 写权限的 GitHub Token；
- 只为明确允许的演示仓库创建 repository grant；
- 启用付费模型时使用一枚未曾公开的新 Key，并配置调用预算；
- 凭据泄漏后同时轮换登录密码、`CODEEVO_AUTH_SECRET` 和相关 Token。

## 验收结果

- `/health/live`：HTTP 200；
- `/health/ready`：HTTP 200，`persistence=true`、`queue=true`；
- 未登录访问 `/api/dashboard`：HTTP 401；
- 管理员登录与 Dashboard：HTTP 200；
- 异步本地规则审查：提交 HTTP 202，最终状态 `SUCCESS`；
- 容器安全参数：`user=codeevo`、`read_only=true`、`cap_drop=ALL`；
- HTTPS 证书与公网转发：已验证。

## 备用托管方案

根目录的 `render.yaml` 可以创建 Render Web Service 和托管 PostgreSQL，适合没有可用服务器时
快速演示。它不是当前线上实例的部署来源；使用时仍需配置强管理员密码，并保持认证与写操作
安全边界不变。
