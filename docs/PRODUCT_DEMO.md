# CodeEvo 产品界面

[打开公开工程工作台](https://vm-0-13-ubuntu.taila0420b.ts.net:8443) ·
[查看服务状态](https://vm-0-13-ubuntu.taila0420b.ts.net:8443/health/ready)

v1.1.0 的公开界面面向 AI Agent 招聘方和开发者：无需凭据即可执行隔离的本地 Agent Sandbox，
比较真实路线实验，并查看受门禁控制的自进化证明。访客不能修改生产数据。

## 一键体验首屏

![一键体验首屏](assets/codeevo-showcase-login.jpg)

左侧解释项目的核心判断：“先看证据，再相信 Agent”，右侧保留维护者登录。公开入口签发短期会话，
允许调用隔离 Sandbox，但不触发外部模型。

## 运行总览

运行总览展示真实 Runtime 阶段、当前本地模型状态、任务统计和 Agent 协作链。页面明确标记快照模式，
避免把已发布 DeepSeek 结果误解为实时在线模型。

## Review Workbench

公开 Workbench 支持三类输入：内置安全样例、粘贴 Unified Diff、严格格式的公开 GitHub PR URL。
每次请求使用临时 SQLite，真实执行 Parse、Plan、Execute、Gate，并返回逐行证据、Agent 消息和 Finding。

## Evaluation Lab

同一 Validation、同一评分逻辑比较 Local Rules、Single DeepSeek 和 Multi Agent。除 Precision、Recall、
F1、Clean Accuracy、P95、Tokens 和 Calls 外，还能按仓库、CWE、risk/clean 筛选并展开单个案例，
直接查看 TP、FP、FN、真值匹配和资源成本。

## Evolution Lab

演进页面展示失败反馈、学到的规则、Prompt 父子版本、Validation 与封存 Holdout 增量、质量和资源 Gate，
以及 Shadow 资格。即使量化门禁通过，生产数据来源未通过时仍明确禁止生产激活。

## Agent 任务详情

![Agent 任务详情](assets/codeevo-showcase-task.jpg)

任务报告按证据链组织：Route/Risk、模型成本、状态机、Agent 消息、Tool、Evidence、Verifier、Arbiter、
Finding、修复建议和验证建议。展示的是后端返回的真实预置数据，不是静态页面 Mock。

## 管理员标注工作台

![CodeEvo 标注工作台](assets/codeevo-annotations.jpg)

管理员能力仍覆盖双人盲审、冲突仲裁和 Evaluation Harness 导出，但不会向 Guest 暴露。

## 本地复现

公开体验模式需要认证和隔离配置：

```bash
CODEEVO_AUTH_REQUIRED=true \
CODEEVO_AUTH_SECRET='<至少 32 字节随机值>' \
CODEEVO_BOOTSTRAP_ADMIN_USERNAME=admin \
CODEEVO_BOOTSTRAP_ADMIN_PASSWORD='<强密码>' \
CODEEVO_GUEST_DEMO_ENABLED=true \
python -m codeevo
```

浏览器打开 `http://127.0.0.1:8080`，点击“进入公开工程工作台”。
