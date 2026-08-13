# CodeEvo 0.8.0

本版本增加可恢复的三路线 Benchmark Runner，用同一数据与同一评分口径比较本地规则 Agent、单 DeepSeek Agent 和多 Agent 协作。

## 新增

- `codeevo-benchmark` CLI，默认只运行 Validation，Holdout 需要显式确认；
- 每案例原子 checkpoint，绑定数据集、案例、路线、模型、Prompt 与协作配置指纹；
- 中断续跑与失败案例定向重试；
- JSON、Markdown 和无外部依赖的静态 HTML 报告；
- Split、CWE、Severity、Repository 多维统计；
- P50/P95/P99 延迟、Input/Output/Total Token、模型调用与成本可用状态；
- 安全发现统一要求 CWE 编号，避免 LLM 使用自定义规则名导致错误漏报；
- 多 Agent 输出按规范 CWE、文件和行号去重；
- 单 Agent 与多 Agent 共用标签无关的风险 Hunk 压缩，Benchmark 默认输入预算为 1200 Token；
- 模型调用具有显式输出 Token 和 Finding 数量上限，避免推理输出失控；
- 案例报告记录压缩前后 Token、策略、遗漏范围及 Diff SHA-256，不记录完整 Prompt；
- Target-CWE 评分会审计记录被过滤的具体 CWE，不把不等价分类强行映射为命中；
- DeepSeek 官方路线默认使用稳定的 `deepseek-chat` 别名；
- 离线 Benchmark 的多 Agent 路线关闭无仓库 checkout 时价值有限的工具循环，仍保留规划、专家分工、质疑、验证和仲裁；线上仓库上下文 Agent Loop 不受影响；
- 输入/输出预算和压缩策略进入路线公开配置及 checkpoint 指纹；
- DeepSeek 的系统信任链使用操作系统证书或 Certifi，始终保持 TLS 验证开启。

## 公平性与安全边界

- 所有路线共享同一有序案例、Split、数据指纹与 Harness 评分逻辑；
- 目标 CWE 不进入模型提示词，避免标签泄漏；
- 未配置单价时成本为 `unavailable`，不推测价格；
- HTML 对数据和错误文本进行转义，不包含 API Key、完整环境变量或私有凭据；
- 受控合成数据只用于回归验证，不能冒充公开生产效果。

## 验证

- 本地规则 Runner 已真实生成 JSON、Markdown 和 HTML 报告；
- 单 DeepSeek 冒烟返回规范 CWE，Token usage 可观测，未配置价格时成本保持不可用；
- Vul4J 真实 Validation（8 案例、4 仓库）上的单 `deepseek-chat` 路线：Precision/Recall/F1 均为 `0.50`，Clean Accuracy 为 `0.75`，执行成功率 `1.00`；
- 上述完整 Validation 共 8 次模型调用、14,671 Token，P50 延迟约 6.04 秒、P95 约 8.36 秒；成本因未配置价格快照保持 `unavailable`；
- 同一 Validation 上，多 Agent 的 Precision 为 `1.00`、Recall 为 `0.25`、F1 为 `0.40`、Clean Accuracy 为 `1.00`；结果显示协作路线更保守但成本更高，不把“多 Agent”包装成必然优于单 Agent；
- 断点续跑、缓存失效、Holdout 保护、HTML 转义、错误分类和多维聚合均有自动化测试。
