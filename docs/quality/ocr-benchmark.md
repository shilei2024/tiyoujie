# OCR 离线评测

2026-10-24。工具只评估已有预测，**不会读取或上传图片，不调用任何供应商**。当前无真实授权数据、预测或预先批准的阈值，质量结论为 BLOCKED。

## 输入与执行

数据集 JSON 使用 `dataset_version`、`threshold_approval_ref`、`thresholds`、`minimum_per_stratum`、`samples`。每个样本需要以下字段：

| 字段 | 含义 |
| --- | --- |
| id / sha256 | 样本唯一编号、原始图片 SHA-256；拒绝重复图片，防止重复计数 |
| authorized / authorization_ref | 明确授权布尔值及离线权利证据编号；不得填入身份证明或密钥 |
| deidentified / synthetic | 已脱敏、是否合成；非真实样本会阻断质量通过 |
| grade_band / writing / question_type / quality | 学段、手写或印刷、题型、清晰度分层标签 |
| expected_text / formulas | 经人工复核的题干和公式字符串列表 |
| regions | 题目框 `[x,y,width,height]`，整数像素坐标 |

预测 JSON 使用 `run_metadata` 和 `samples`。`run_metadata` 应登记 provider、精确 model、识别模板版本、生成时间和原始结果审核编号；每个预测包含 id、text、formulas、regions、人工实际测量的 correction_seconds。元数据只用于溯源，工具不认证供应商响应或权利证据真伪。

```powershell
py -3.12 scripts/ocr_benchmark.py --dataset <dataset.json> --predictions <predictions.json> --report <new-report.json>
```

输出必须是新文件，拒绝覆盖已有报告。退出码 PASS=0、FAIL=1、BLOCKED=2。单文件最多 12 MB、最多 1000 样本、每段题干 4000 字符、每样本最多 40 个公式和区域。报告不包含原文或图片，只含编号、指标、版本和失败案例指标；仍应按内部学习数据保管。

## 指标和门禁

- CER：NFC 规范化、去空白后的字符编辑距离 / 参考字符数；不合并正负号或替换公式。
- formula_token_error：公式的数字、拉丁变量、LaTeX 命令和运算符 token 编辑率。
- key_symbol_error：题干中的数字、变量、运算符和数学标点 token 编辑率。
- segmentation_recall：IoU ≥ 0.5 的最大一对一框匹配数 / 参考框数。空参考框按 1 计，正式数据必须人工确认分题标注完整性。
- correction_seconds：人工修订秒数的总体中位数；同时输出各维度分层均值和错误样本编号。

`thresholds` 必须为上述五个指标分别提供非负上限，分题 recall 则为 0..1 的下限。`minimum_per_stratum` 必须覆盖四个维度，值为 `{标签: 最低样本数}`；负责人应预先指定需要覆盖的标签（包括低清、复杂符号和几何题等），不可事后缩小范围。总体错误率采用逐样本宏平均，不是字符加权率。阈值通过不代替人工检查各分层失败案例。

空集、未授权、未脱敏、合成样本、缺预测、缺版本、缺批准的阈值或分层样本不足，均 BLOCKED，不能对外宣传准确率。未提供合法配置时，不用合成预测伪装真实供应商结果。合成单元测试仅验证评分算法。

本轮空集实跑报告为 `artifacts/phase3-ocr-benchmark-final.json`（忽略产物）；samples=0、metrics 为空、BLOCKED。真实供应商联调与真实样本评测尚未执行。
