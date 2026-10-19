# KDE/kmymoney

- 分类：06 个人财务（桌面复式）
- 语言 / 许可证 / 最近提交：C++ (Qt/KDE) / GPL-2.0+ / 2026-10-18
- 审查范围：`kmymoney/mymoney/{mymoneyaccount,mymoneytransaction,mymoneysplit,mymoneypayee,mymoneyschedule,mymoneybalancecache,mymoneyprice,mymoneyreport}`、`kmymoney/converter/{mymoneystatementreader,existingtransactionmatchfinder,scheduledtransactionmatchfinder}`、`plugins/{csv,ofx,kbanking,reconciliationreport,sql}`

## 定位

KDE 桌面个人理财：复式交易、计划交易、投资、预算、预测、在线银行（OFX/HBCI）与多格式导入。

## 数据模型

- Transaction（多 split，split 有 shares（账户商品数量）与 value（交易币种价值）、对账状态、银行 ID）、Account（含贷款账户）、Payee（**匹配规则：按名称 / 按关键字列表 / 精确名称，是否忽略大小写，并带默认分类**）、Schedule、Price、CostCenter、Budget、Report；
- 余额缓存（balance cache）按账户+日期缓存。

## 导入与匹配

- 对账单导入（StatementReader）对每笔导入交易：
  1. 按银行交易 ID 判重；
  2. **ExistingTransactionMatchFinder**：同账户、**同金额**、日期在 ±N 天窗口（可配置）内的已有交易作为候选，逐个找匹配分录；
  3. **ScheduledTransactionMatchFinder**：与计划交易匹配（到期的定期付款）；
  4. 收付款方通过 payee 匹配规则识别，带出默认分类；
  5. 结果分“完全匹配 / 疑似匹配（需确认）/ 无匹配”。
- 对账报告插件：对账完成后生成报告（期初、勾对、未勾对、差额）。

## 可借鉴

- [KM1] 收付款方匹配规则（名称/关键字/精确 + 默认分类），由对手名推断分类。
- [KM2] 导入匹配分三级（完全/疑似/无），疑似需人工确认。
- [KM3] 与计划交易匹配。
- [KM4] 对账报告留档。

## 不采用 / 风险

- 桌面应用；GPL。

## 对新系统的启示

- 交易对手（供应商/渠道）实体带“识别关键字/别名”与默认交易类型；
- 导入匹配结果三态并给出原因；对账完成生成可下载的对账报告。
