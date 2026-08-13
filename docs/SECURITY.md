# CodeEvo 安全基线

## 部署要求

- 对外部署必须启用 `CODEEVO_AUTH_REQUIRED=true`。
- `CODEEVO_AUTH_SECRET` 至少包含 32 字节随机数据。
- Compose 要求显式提供 PostgreSQL、管理员和认证密钥配置。
- 默认只绑定宿主机 `127.0.0.1`；公网访问必须通过 TLS 反向代理。
- CodeEvo 容器使用非 root、只读根文件系统、`no-new-privileges` 和零 capabilities。
- 生产租户必须显式授予仓库访问权；没有授权记录时默认拒绝。
- 自动修复还需要仓库授权中的 `auto_fix` 权限。
- 登录失败按客户端地址与用户名组合限流；默认 5 次失败后锁定 300 秒。
- API 返回 CSP、禁止嵌入、MIME 嗅探保护和请求 ID。
- 默认忽略转发请求头；只有来源命中 `CODEEVO_TRUSTED_PROXY_CIDRS` 才解析代理链。
- JSON 请求日志只包含允许字段，不记录密码、请求体、Diff、Prompt 或 Token。
- 非空但不受支持的数据库 URL 会拒绝启动，不会静默降级到本地 SQLite。

## 仓库工作区

- `CODEEVO_REPOSITORY_ROOT` 只能指向专用的仓库 checkout 根目录，不能指向用户主目录或系统根目录。
- 容器部署必须使用只读挂载；仓库按 `<owner>/<repository>` 映射，调用方不能提交主机路径。
- 文件工具拒绝绝对路径、路径穿越、符号链接、二进制、超限文件、`.env`、私钥和凭据文件。
- Tree-sitter 索引受最大文件数、单文件字节数与索引总字节数约束。
- 启用仓库上下文后，Critical/High 结论缺少匹配的已读代码证据时默认拒绝。
- evidence ID 由相对路径、文件 SHA-256 和读取行范围生成，不暴露主机绝对路径。

## GitHub App

- installation 回调使用短期 HMAC 签名 state。
- state 绑定用户、租户、角色和过期时间，回调时重新检查成员关系。
- installation token 只能用于其绑定租户的任务。

## 动态 Skill

- 本地隔离进程适合可信 Skill 的故障隔离，不应视为不可信代码安全边界。
- 不可信 Skill 必须配置只读、无网络、无额外 capability 的容器镜像。
- 建议生产环境同时配置 Skill 签名密钥。
