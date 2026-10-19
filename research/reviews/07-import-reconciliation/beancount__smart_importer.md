# beancount/smart_importer

- 分类：07 自动分类（机器学习）
- 语言 / 许可证 / 最近提交：Python (scikit-learn) / MIT / 2026-07
- 审查范围：`smart_importer/{predictor,pipelines,wrapper,entries,__init__}.py`、README

## 定位

给任意 Beancount 导入器加上“预测科目/收付款方”能力的钩子（去重由 beangulp 负责）。

## 设计要点

- 以已有账本中的交易为训练数据（只取涉及导入账户且该账户仍开立的交易），特征按 `weights` 配置组合：字符串属性（narration、payee 等）用计数向量化，数值属性直接取值；默认权重 narration 0.8、payee 0.5、date.day 0.1，以 FeatureUnion 加权合并，分类器为线性核 SVC；
- 作为导入器包装器使用：`PredictPostings().wrap(importer)` / `PredictPayees()`；可设置 `overwrite` 决定是否覆盖已有值；
- 只在模型有足够训练数据时预测，否则保持 FIXME；预测结果仍需人工确认。

## 可借鉴

- [SI-1] 以历史已确认交易为训练集的分类建议（插件式，可关闭）。
- [SI-2] 预测与规则并存：规则优先，模型补充，置信度低则不填。

## 对新系统的启示

- 分类建议服务分三层：确定性规则 → 历史相似度（同对手/同摘要）→ 可选模型；输出建议 + 置信度 + 依据，不自动过账。
