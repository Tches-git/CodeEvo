# 招聘方 3 分钟体验路线

在线入口：<https://vm-0-13-ubuntu.taila0420b.ts.net:8443>

## 0:00 - 0:20 进入工作台

点击“进入公开工程工作台”。无需账号密码，也不会产生模型费用。顶部显示“公开访客”，导航提供总览、
审查工作台、任务中心、Evaluation Lab 和 Evolution Lab。

## 0:20 - 1:00 执行真实审查

进入“审查工作台”，选择“命令注入与敏感日志”，点击“执行 Sandbox”：

1. 确认响应明确标记 LLM used `NO`、Ephemeral `YES`、Writeback `NO`；
2. 在逐行证据中核对 `shell=True` 与 `print` 的 Finding 标记；
3. 查看 Parse、Plan、Execute、Gate 状态机和 Agent 消息链；
4. 确认结果没有进入任务中心的生产任务列表。

## 1:00 - 1:45 看路线权衡

进入“Evaluation Lab”：

- Single DeepSeek 的 F1 为 0.50；
- Multi-agent 的 Precision 为 1.00，但 Recall 为 0.25；
- Multi-agent 使用 54,281 Tokens、25 次调用，P95 约 49.13 秒。

选择 `VUL4J-14-risk`，可看到 Local Rules 为 FN，Single DeepSeek 与 Multi Agent 为 TP。这里要验证的
不是“Agent 越多越好”，而是系统能否用统一 Harness 量化质量、延迟和成本。

## 1:45 - 2:25 看自进化门禁

进入“Evolution Lab”：

1. 查看 32 个漏报如何生成候选，并在激活后解决；
2. 核对 v1 到 v2 的父子关系和 Prompt SHA；
3. 比较 Validation 与封存 Holdout 的 baseline/candidate；
4. 查看每个质量、延迟、Token 和成本 Gate；
5. 确认生产数据来源未通过时，Production activation 为 `NOT ALLOWED`。

## 2:25 - 3:00 看安全边界

- Guest 只有 `demo_read` 与 `demo_execute`，原始审查、反馈、标注、修复、Skill 和发布请求返回 403；
- Sandbox 只请求固定的 `api.github.com`，限制 Diff 大小与执行频率，结束后销毁临时数据库；
- Prompt、Skill 和 Route 候选必须经过 Validation/Holdout 与资源非退化门禁；
- PostgreSQL 有每日校验备份，健康探针每 5 分钟运行，恢复在隔离数据库演练。

面试继续追问可参考 [简历与面试讲解](RESUME_PROJECT.md) 和 [架构说明](ARCHITECTURE.md)。
