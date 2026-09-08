# RE-50 实验运行报告

运行状态：首轮完成，失败项已按协议重试一次；未删除任何原始响应。

## 运行身份

| 项目 | 值 |
|---|---|
| 数据 | `DIVE_balanced` RE 50 条样本 |
| 运行时样本清单 SHA-256 | `a6be2950b052d883cecbf5bb9094b9e04aeb3a5290a6740f4010a56050286a04` |
| 当前整理后清单 SHA-256 | `66cc1c5a4818b4a1fde9f4c86690f34470765cdae385528d3b75b9f5da70afd4` |
| 模型 | `qwen3.5:9b` |
| 模型 digest | `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` |
| Ollama | `http://127.0.0.1:11436` |
| GPU | 3 |
| temperature | 0 |
| 固定关键词 | `balance`, `call` |

目录整理仅更新 `source_file` 路径，50 个源码文件字节和逐文件 SHA-256 未变；运行元数据保留运行时清单哈希。

## 总体结果

指标基于有效预测支持集；`no_candidate` 按未检出 `0` 计入，解析失败保留在总分母并通过 coverage 单独报告。

| 方法 | 有效数/50 | Coverage | TP | TN | FP | FN | Precision | Recall | F1 | MCC | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 直接 Qwen | 49 | 0.98 | 18 | 14 | 11 | 6 | 0.6207 | 0.7500 | 0.6792 | 0.3153 | 0.6531 |
| 固定规则 `balance/call` | 50 | 1.00 | 6 | 25 | 0 | 19 | 1.0000 | 0.2400 | 0.3871 | 0.3693 | 0.6200 |
| LLM keyword 检测 | 49 | 0.98 | 12 | 21 | 3 | 13 | 0.8000 | 0.4800 | 0.6000 | 0.3851 | 0.6735 |

## 复杂度分层

完整分层指标见 `metrics_by_stratum.csv`。本批次中，直接 Qwen 在 `<100` 行样本 Recall 为 1.00，在 `100–300` 行为 0.60，在 `>300` 行为 0.6364；LLM keyword 检测分别为 1.00、0.40 和 0.1667；固定规则分别为 0.625、0.20 和 0.00。

## 失败与证据

- 直接 Qwen：49/50 成功，1 条 `parse_failed`。
- 固定规则：49/50 成功，1 条 `no_candidate`。
- LLM keyword：47/50 成功，2 条 `no_candidate`，1 条 `parse_failed`。
- 模型原始响应全部保存在 `raw_results.jsonl`，包括首轮和重试记录。
- `experiment_results.csv` 中的 `*_evidence_text` 由模型返回行号回查冻结源码生成；模型原始证据文本保存在对应的 `*_reported_evidence_text` 列。
- `*_verified_evidence_status` 区分 `verified`、`empty` 和 `invalid_line`。

## 解释边界

这是单模型、单温度、50 条分层样本的探索性结果。固定关键词方法只检索 `balance` 与 `call`，其低 Recall 不能直接推广到所有关键词规则。下一步如需形成论文主结果，应冻结本版本并按相同协议扩展到全部 398 条 RE 记录。
