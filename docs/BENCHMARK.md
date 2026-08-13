# Reproducible Benchmark

## 数据与方法

- 数据：`evaluation_data/vul4j_40.jsonl`
- 来源：Vul4J 公开漏洞记录、公开安全修复提交与 NVD 严重级别证据
- 完整数据：40 案例，20 risk / 20 clean，14 个公开仓库
- 本次结果：Validation 8 案例，4 个仓库，4 risk / 4 clean
- Split：按 repository 确定性划分，不允许仓库跨分区
- 评分：target-CWE case-level；目标 CWE 不进入模型 Prompt
- 模型：DeepSeek `deepseek-chat`
- 上下文预算：1,200 Token，其中 256 Token 留给指令/运行状态
- 输出预算：每次调用最多 1,200 Token、最多 4 个 Finding、最多一次非空 JSON 修复

Validation 子集 SHA-256：

```text
b4c7d8a80539fa3bcd5ebbd2b250a9fa42f58649982a97df0853424830cb3760
```

## 结果

| Route | TP | FP | FN | Precision | Recall | F1 | Clean Accuracy | Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Local rules | 0 | 0 | 4 | 0.00 | 0.00 | 0.00 | 1.00 | 0 | 0 |
| Single DeepSeek | 2 | 2 | 2 | 0.50 | 0.50 | 0.50 | 0.75 | 8 | 14,671 |
| Multi-agent | 1 | 0 | 3 | 1.00 | 0.25 | 0.40 | 1.00 | 25 | 54,281 |

成本保持 `unavailable`：实验没有配置不可变价格快照，因此不根据当前网页价格倒推历史成本。

## 解读边界

- 8 个 Validation 案例只能作为工程回归证据，不能宣称生产环境普遍有效率。
- `clean` 表示目标漏洞已被基准补丁修复，不代表提交中不存在任何其他问题。
- Vul4J 的旧版宽泛 CWE 与模型输出的细分 CWE 可能不同；被过滤分类会被审计记录，但不会强行映射成命中。
- 多 Agent 在这组数据上更保守但更昂贵，说明路由应由评测决定，而不是默认全量启用。
- Holdout 尚未用于本轮调优，只有 Prompt、预算和路由冻结后才应最终运行一次。

## 复现

```bash
export CODEEVO_LLM_PROVIDER=deepseek
export CODEEVO_DEEPSEEK_API_KEY='<your-key>'

codeevo-benchmark \
  --dataset evaluation_data/vul4j_40.jsonl \
  --output-dir output/vul4j-validation \
  --routes local,single,multi \
  --splits validation \
  --resume
```

报告会生成 JSON、Markdown、静态 HTML 和每案例原子 checkpoint。Prompt、模型、预算、协作协议或案例内容变化时，
checkpoint cache key 会变化，旧结果不会被错误复用。
