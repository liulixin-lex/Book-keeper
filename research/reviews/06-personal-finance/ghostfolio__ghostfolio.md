# ghostfolio/ghostfolio

- 分类：06 财富/投资组合管理
- 语言 / 许可证 / 最近提交：TypeScript（Angular + NestJS + Prisma + PostgreSQL + Redis）/ AGPL-3.0 / 2026-10-18
- 审查范围：`apps/api/src/services/exchange-rate-data/*`、`apps/api/src/app/portfolio/calculator/{roi,twr,mwr,roai}`、`apps/api/src/app/{import,export,activities}`、`prisma/schema.prisma`、`libs/common/src/lib/config.ts`

## 定位

开源财富管理：记录买卖/分红/费用等活动，按多数据源行情与汇率计算净值与收益率。

## 数据模型

- Order（活动）：类型（买/卖/分红/费用/利息/负债…）、日期、数量、单价、费用、币种、账户、标的、标签（金额为浮点）；Account（含平台、余额历史）、SymbolProfile、MarketData（按日行情/汇率）。

## 算法

- **汇率服务**：
  - **派生币种**：如 GBp = GBP/100、ZAc = ZAR/100 这类固定倍率币种，在配置中声明（币种、倍率、根币种），换算时直接用固定因子，不去查行情；
  - 历史日期换算：先查该日 `FROMTO` 行情；查不到则**经基准币种间接换算**（FROM→USD→TO）；今日用实时汇率；
  - 定时任务从数据提供方（Yahoo、CoinGecko 等）批量拉取并缓存。
- 收益计算器：ROI、时间加权（TWR）、资金加权（MWR/XIRR）多种算法同一接口（工厂模式按用户设置选择）。
- 导入：CSV/JSON 活动导入（含重复检测、按标的校验）。

## 可借鉴

- [GF1] **派生币种 = 固定倍率声明**：可用来表达“上游额度美元 USD-credit 与 CNY 按 1:1 结算”这类内部换算约定，而不是把它伪装成真实汇率。
- [GF2] 历史汇率缺失时经基准币种间接换算，并能区分实时/历史口径。
- [GF3] 计算器接口 + 工厂选择不同算法（报表口径可插拔）。

## 不采用 / 风险

- 浮点金额；投资场景与本业务关系较远；AGPL。

## 对新系统的启示

- 币种表支持“派生/内部记账单位”（如 `USD_CREDIT`：上游站点额度单位，带默认折算规则和生效期间）；
- 汇率服务：直接汇率 → 间接汇率（经 USD/EUR）→ 失败报错，记录推导路径。
