# v1.1 演示录制脚本

建议录制 90 秒、1280×800、无声音或配简短旁白。录制前使用无痕窗口，避免出现个人浏览器信息。

1. `00:00-00:10`：停留登录首屏，点击“进入公开工程工作台”。
2. `00:10-00:35`：进入审查工作台，执行命令注入样例，指向 LLM/临时/写回边界和逐行 Finding。
3. `00:35-00:52`：滚动状态机、Agent 消息、Verifier、Arbiter、修复与验证建议。
4. `00:52-01:08`：进入 Evaluation Lab，比较 F1/P95/Tokens，并展开 `VUL4J-14-risk`。
5. `01:08-01:25`：进入 Evolution Lab，展示 v1 到 v2、Validation/Holdout 和资源 Gate。
6. `01:25-01:30`：停留 Production activation `NOT ALLOWED`，说明生产来源门禁不会被量化分数绕过。

不得在视频中打开管理员登录、服务器终端、`.env`、模型 Key 或 GitHub 私密设置。
