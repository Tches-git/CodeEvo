# CodeEvo v1.0.0

CodeEvo 1.0 把此前的多 Agent、Evaluation Harness 和受控进化能力，收口成一个招聘方可直接验证、维护者可恢复的公开作品集版本。

## 新增

- 一键只读 Guest Session，无需公开账号或密码；
- 隔离 `public-demo` 租户与后端 `demo_read` 权限；
- 三个确定性预置案例，覆盖 Local、Single DeepSeek 和 Multi-agent；
- Agent 状态机、消息链、工具调用、Evidence、Verifier 和 Arbiter 详情；
- Precision、Recall、F1、Clean Accuracy、P95、Tokens 和 Calls 路线对比；
- PostgreSQL 原子备份、校验、隔离恢复、保留策略；
- 容器/公网健康检查、磁盘告警、安全 Docker 清理和 systemd timers。

## 安全

- Guest 只能读取公开展示租户；创建审查、反馈、标注导入、修复、Skill、发布和审计均被服务端拒绝；
- Guest Token 默认 5 分钟，不创建公开密码账号；
- 浏览已发布 Benchmark 快照时不会调用付费模型；
- 恢复脚本默认拒绝覆盖生产数据库，清理脚本不删除 Docker volume。

## 界面

- 使用克制的深色技术产品语言重做登录首屏、访客导航、路线对比和任务详情；
- 支持 390px 移动端，无水平溢出；
- 清晰覆盖加载、空状态、错误状态和 reduced-motion。

## Benchmark 披露

Validation 为 8 个案例、4 个仓库。Single DeepSeek F1 0.50；Multi-agent Precision 1.00、F1 0.40，代价是更高的延迟和 Token。该结果用于说明路线权衡，不声称多 Agent 全面优于单 Agent。
