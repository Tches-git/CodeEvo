# 招聘方 3 分钟体验路线

在线入口：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443>

## 0:00 - 0:30 一键进入

点击“一键体验只读 Demo”。无需账号密码，也不会产生模型费用。注意顶部“只读访客”标识，以及访客导航
只保留总览、任务和路线对比。

## 0:30 - 1:15 看路线权衡

进入“路线对比”：

- Single DeepSeek 的 F1 为 0.50；
- Multi-agent 的 Precision 为 1.00，但 Recall 为 0.25；
- Multi-agent 使用 54,281 Tokens、25 次调用，P95 约 49.13 秒。

这里要验证的不是“Agent 越多越好”，而是系统能否用统一 Harness 量化质量、延迟和成本。

## 1:15 - 2:30 下钻证据链

点击“查看对应案例”，选择 `codeevo/payment-service`：

1. 查看 `PENDING → PLANNING → EXECUTING → REVIEWING → SUCCESS`；
2. 展开 Planner、Security、Critic、Evidence、Verifier、Arbiter 消息；
3. 核对 `changed_line` 工具调用和 evidence ID；
4. 查看 Shell 注入、硬编码凭据和敏感日志 Finding；
5. 对照修复与测试建议，确认结论可以被工程人员复核。

## 2:30 - 3:00 看安全与进化边界

- Guest 的审查、反馈、标注、修复、Skill 和发布请求由后端统一返回 403；
- Prompt、Skill 和 Route 候选必须经过 Validation/Holdout 与资源非退化门禁；
- PostgreSQL 有每日校验备份，健康探针每 5 分钟运行，恢复在隔离数据库演练。

面试继续追问可参考 [简历与面试讲解](RESUME_PROJECT.md) 和 [架构说明](ARCHITECTURE.md)。
