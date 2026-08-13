# CodeEvo — 简历与面试讲解

## 简历项目描述（推荐版）

**CodeEvo｜可评测、可回滚的多 Agent 代码审查平台**
Python / FastAPI / DeepSeek / Multi-Agent / Tree-sitter / PostgreSQL / Redis / Docker / OpenTelemetry

- 设计自研 Agent Runtime，将代码审查建模为有界状态机，支持 Tool Schema 校验、结构化 Observation、逐节点
  checkpoint、失败重试和断点续跑，避免 LLM Agent 黑盒式执行。
- 构建 Planner–Specialist–Critic–Verifier–Arbiter 协作协议，并通过只读仓库工具、Tree-sitter 符号索引、
  文件 SHA-256 与 evidence ID 对高风险结论执行 fail-closed 证据门禁。
- 实现标签无关的风险 Hunk 上下文压缩与输入/输出预算控制；DeepSeek 单案例从实验模型的约 13.9k Token、
  93 秒异常长尾，优化到稳定聊天模型下约 1.2k–2.2k Token、秒级响应。
- 建立 repository-isolated Train/Validation/Holdout Evaluation Harness，统一评估 Precision、Recall、F1、
  P50/P95/P99、Token 和成本，并将 Prompt/Skill/Route 候选接入 Shadow、Canary、激活与回滚门禁。
- 基于 Vul4J 构建 40 条可审计 risk/clean 案例；真实 Validation 上单 Agent F1 0.50，多 Agent Precision 1.00，
  用实验说明多 Agent 的精度/召回/成本权衡，而非只展示架构复杂度。
- 发布隔离的只读访客模式与三条可复核演示链路，后端 RBAC 拒绝所有写操作；配套 PostgreSQL 原子备份、
  隔离恢复演练、健康探针和磁盘告警，使招聘方无需凭据即可安全验证项目。

## 30 秒口述

“这是一个把 AI Code Review 做成工程系统的项目。它的重点不是简单串联几个 Prompt，而是解决 Agent 不可控、
结论不可验证和版本无法安全进化的问题。我实现了有界 Agent Runtime、仓库级证据工具、评测 Harness 和
发布回滚门禁。项目用同一组 Vul4J 数据比较本地规则、单 Agent 和多 Agent，结果显示单 Agent F1 更高，
多 Agent Precision 更高但 Token 和延迟更贵，所以最终路由由评测数据决定。”

## STAR 深挖材料

- **Situation**：作品集既要允许招聘方直接体验，又不能暴露管理员能力、付费模型或真实租户数据。
- **Task**：在不弱化生产认证边界的前提下，提供可验证的 Agent 工程证据并确保单机 Demo 可恢复。
- **Action**：实现 5 分钟 Guest Principal、`public-demo` 租户隔离和后端 403 写门禁；固化三路线
  Benchmark 快照与 Agent/Tool/Evidence 轨迹；增加备份校验、隔离恢复、systemd 探针和磁盘告警。
- **Result**：招聘方一键即可比较 F1、延迟与 Token，并下钻到 Finding 证据；访客没有任何写权限，
  服务具备每日备份、5 分钟健康检查和可重复恢复演练。

## 高频追问

### 这是真正的“自进化 Agent”吗？

是受控进化，不是模型自动改权重。反馈会生成 Prompt、声明式 Skill 或 Route 候选；候选必须通过 Validation、
Holdout 和资源非退化门禁，随后才能进入 Shadow/Canary。系统保留父版本、数据指纹、决策原因和回滚能力。

### Harness 技术体现在哪里？

Harness 统一控制案例加载、执行、超时、checkpoint、usage 差值、CWE 匹配、维度聚合和报告生成。三条路线共享
相同案例顺序、Split、数据指纹和评分实现，配置变化会使 cache key 自动失效。

### 为什么多 Agent 没有获得最高 F1？

多 Agent 的 Verifier 和 Arbiter 更保守，因此减少误报但牺牲召回，而且协作会增加调用数。这是一个真实结论：
复杂架构不等于更好效果。生产中可以根据仓库风险和预算，用路由门禁决定是否启用协作路线。

### 如何防 Prompt Injection？

代码、注释、记忆和工具结果都被明确视为数据；模型只能调用 Registry 中有 Schema 的工具。Workspace 只读并拒绝
路径穿越和密钥文件，高危 finding 还必须绑定已读取文件的哈希证据，缺失时默认拒绝。

## 不建议写的表述

- “实现了模型权重的自主学习”——项目没有训练模型权重。
- “多 Agent 显著优于单 Agent”——当前 Validation 不支持这个结论。
- “达到生产级 50% 漏洞检出率”——数据量不足以外推生产效果。
- “Vul4J 数据由本人标注”——标签来自公开 Benchmark 与 NVD，不是人工原创标注。
