# 实验仓库

本仓库保存可复核实验输入、运行脚本、模型原始响应和结果表。当前唯一实验集为 RE-50。

## 实验入口

| 实验 | 状态 | 入口 |
|---|---|---|
| RE-50：三种 RE 检测策略比较 | 首轮完成，探索性结果 | [data_RE/README.md](data_RE/README.md) |

## RE-50 导航

- 实验协议：[data_RE/README.md](data_RE/README.md)
- 输入契约与样本清单：[data_RE/00_contract/](data_RE/00_contract/)
- 冻结源码：[data_RE/01_sources/](data_RE/01_sources/)
- 结果表与指标：[data_RE/02_results/](data_RE/02_results/)
- 原始响应与运行身份：[data_RE/03_raw_evidence/](data_RE/03_raw_evidence/)
- 抽样、运行、汇总脚本：[data_RE/04_scripts/](data_RE/04_scripts/)

## 权威性规则

1. `data_RE/README.md` 定义实验问题、RE 定义、三种方法和评价协议。
2. `00_contract` 定义样本成员、标签、源码哈希和抽样约束。
3. `02_results/experiment_results.csv` 保存逐样本结果；`metrics_summary.csv` 和 `metrics_by_stratum.csv` 保存复算指标。
4. `03_raw_evidence/raw_results.jsonl` 保存模型首轮和重试的原始响应，不得用摘要覆盖。
5. 历史或失败结果保留；不得通过删除记录、修改标签或覆盖原始响应修复结果。

## 运行原则

- 新实验使用新版本或新目录，不覆盖已完成运行。
- 运行前冻结输入、Prompt、模型和匹配规则。
- 运行后先执行独立校验，再把结果写入论文。
