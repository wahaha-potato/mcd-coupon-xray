# MCP 集成说明

## 服务信息

| 项 | 值 |
|---|---|
| MCP Server | 麦当劳中国 MCP Server（`mcd-mcp`） |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| Token 获取 | [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 手机号登录 → 控制台 → 激活 |
| 限流 | 600 次 / 分钟 / Token，超出返回 `429` |

本项目**只读取数据与领取免费券**，不执行支付、不创建订单、不取消订单，因此不会对用户资产产生资金影响。

## 使用的 Tool 清单

共调用 9 个 Tool，分五个环节。

| # | Tool | 环节 | 作用 | 实测状态 |
|---|---|---|---:|---|
| 1 | `available-coupons` | S1 领券 | 取麦麦省可领券列表 | ✅ 已实测 |
| 2 | `auto-bind-coupons` | S1 领券 | 一键领取全部可领券 | ✅ 已实测（写操作，经账户所有者授权） |
| 3 | `query-my-coupons` | S1 复核 | 复核卡包内已持有的券 | ✅ 已实测 |
| 4 | `query-nearby-stores` | S2 定位 | 取门店与 `storeCode` | ✅ 已实测（两种搜索方式） |
| 5 | `query-store-coupons` | S3 校验 | 门店 × 渠道下的可核销券 | ✅ 已实测（空卡包与有券两种状态） |
| 6 | `query-meals` | S4 算价 | 取该店在售菜单与 `productCode` | ✅ 已实测 |
| 7 | `calculate-price` | S4 算价 | 券前 / 券后金额与优惠额 | ✅ 已实测（两张券各算一次） |
| 8 | `now-time-info` | 全程 | 取服务器时间，判断券有效期与活动窗口 | ✅ 已实测 |
| 9 | `query-my-account` | 兜底 | 卡包为空时判断是未登录还是确实无券 | ✅ 已实测 |

9 个 Tool 全部在真实 Token 下执行过。其中 `auto-bind-coupons` 会写入账户（领取免费券），执行前已取得账户所有者明确授权；其余均为只读。

## 调用流程与参数

### S1 · 领券入库

```
available-coupons()
  → 按 title 归并，得到真实券数
auto-bind-coupons()
query-my-coupons(page="1", pageSize="200")
```

**实测返回**（`available-coupons`）：5 条记录，去重后 3 张券——

| 券名 | 状态 |
|---|---|
| 19.9 元王牌炸鸡任选 2 | 可领取 |
| 11.9 元麦辣鸡腿堡 | 可领取 |
| 免费脆薯饼 | 可领取 |

重复条目分别挂在 `https://img.mcd.cn/cms/images/...` 与 `https://mcd-portal-prod-cos1-1300270282.cos.ap-shanghai.myqcloud.com/...?sign=...` 两个域名下，因此**不能按 URL 去重，只能按券名**。

**实测返回**（`query-my-coupons`，空账户阶段）：`暂无可用优惠券`。
**实测返回**（`query-my-account`）：`availablePoint = "0"`，`accountId` 正常返回（证明账号已登录，只是积分与券为空）。

### 2026-10-23 11:03 完整链路复测（同一账号，领券后）

经账户所有者授权执行 `auto-bind-coupons` 后，整条链跑通，得到四个此前的空账户阶段无法发现的结论：

**结论一：领取 5 条记录 = 5 张真实券（5 个不同 couponId），不是 3 张**

`auto-bind-coupons` 返回「总计 5 张、成功 5 张、失败 0 张」，5 条记录的 `couponId` 互不相同：

| 券名 | couponId 前缀 | couponCode 前缀 |
|---|---|---|
| 11.9 元麦辣鸡腿堡 | `A2552803…` | `MCD60810900B7B5V04022` |
| 19.9 元王牌炸鸡任选 2 | `44928824…` | `MCD6C9B100040402V0258` |
| 11.9 元麦辣鸡腿堡 | `B34E5EC6…` | `MCD696B00V028E0418250` |
| 19.9 元王牌炸鸡任选 2 | `A03BC156…` | `MCD6092770001B84220VF` |
| 免费脆薯饼 | `0D94B792…` | `MCD60V02702G492080B19` |

「11.9 元麦辣鸡腿堡」出现两次是**两个不同活动**（见下），不是重复展示。按券名去重会漏券。

**结论二：领取成功 ≠ 进入卡包（5 → 4）**

领完立即 `query-my-coupons` 复核，卡包只有 **4 张**：两张麦辣（有效期分别为 10-19~10-23、10-26~10-30）、两张王牌（同上分两批）。**「免费脆薯饼」领取成功却不在卡包里**，两条接口都没有给出原因。

**结论三：进卡包 ≠ 今天可核销（4 → 2）**

卡包 4 张里有 2 张有效期从 10-26 才开始。5 家门店的 `query-store-coupons` 返回**完全相同**的 2 张：`44928824…`（王牌）与 `A2552803…`（麦辣），即今天真正能核销的只有 2 张。

同时说明：本批 5 家门店（三里屯周边）可用性完全一致，这两张是通用券。跨店矩阵的价值要在有门店限制的券上才显现，但逻辑必须先在。

**结论四：菜单编码 ≠ 计价编码**

`query-meals`（`storeCode=1951066`）返回的菜单映射里**没有**券的适用商品 `9900016534`，但 `calculate-price` 对它照常计价成功。因此不能用「菜单里没有」判断券不可用。

**实付结果（`calculate-price`，`orderType=1`、`beType=1`，金额单位为分）**

| 商品 | productCode | 原价 | 券后 | 省 |
|---|---|---:|---:|---:|
| 麦辣鸡腿汉堡 | `1440` | 2250 分 = 22.5 元 | **1190 分 = 11.9 元** | **1060 分 = 10.6 元** |
| 王牌炸鸡任选 2 | `9900016534` | 2380 分 = 23.8 元 | **1990 分 = 19.9 元** | **390 分 = 3.9 元** |

`takeWayList` 返回 `eat-in`（堂食）与 `take-in-store`（外带）两种取餐方式。

**漏斗汇总（本项目的核心数字）**

```
可领记录 5 条 → 实际领取 5 张 → 进入卡包 4 张 → 当天可核销 2 张
```

每一层都会安静地吃掉一部分，且接口不会主动提示差异——这正是「能领 ≠ 能用」的具体形态。

### S2 · 定位门店

```
query-nearby-stores(beType=1, searchType=1)                      # 先试收藏
query-nearby-stores(beType=1, searchType=2, city=..., keyword=...)  # 收藏为空时降级
```

**实测返回**（`searchType=1`，收藏为空）：

```json
{"success": false, "code": 600050, "message": "收藏餐厅列表为空，请您提供城市+关键词进行搜索"}
```

`code=600050` 是本项目识别「需降级到位置搜索」的唯一可靠信号，Skill 里据此分支。

**实测返回**（`searchType=2`，`city=北京`、`keyword=三里屯`）：5 家门店，`storeCode` 为纯数字字符串：

| storeName | storeCode | distance |
|---|---|---:|
| 麦当劳北京长虹桥餐厅 | `1951066` | 628 |
| 麦当劳北京团结湖餐厅 | `1950050` | 933 |
| 麦当劳北京吉市口东路（佳汇中心）餐厅 | `1951027` | 1351 |
| 麦当劳北京工体北路餐厅 | `1950085` | 1355 |
| 麦当劳北京东大桥餐厅 | `1950006` | 1397 |

**实测发现的字段缺陷**：5 家店的 `longitude` 与 `latitude` 全部为 `0.0`。只有 `distance`（米）可用。任何依赖坐标做地图渲染或自行计算距离的实现都会失效，本项目统一使用 `distance` 排序。

**实测发现的必传项**：`beType` 为必传且只接受 `1` / `5`；`searchType=2` 时 `city` 与 `keyword` 缺一不可。`beType` 漏传不会报错，但会拿到不符合渠道的结果。

### S3 · 逐店校验

```
query-store-coupons(storeCode=..., orderType=1, beType=1)
```

**实测返回**（`storeCode=1951066`，`orderType=1`，`beType=1`）：`{"success":true,"data":[]}`

这个空数组是本项目最核心的实测结论。结合 S1 的「卡包为空」，可以确定：

> `query-store-coupons` 的语义是**「已持有 ∩ 该门店可核销」**，不是「该门店全部可用券」。

推论：把顺序写成「先查门店再查券」的项目，在任何空卡包用户身上都会得到全空结果，并错误地告诉用户「这家店不支持任何优惠券」。**必须先领券。**

渠道参数矩阵（传错会导致查询结果为空，且不会报错，属于静默失败）：

| 场景 | `beType` | `orderType` | `beCode` |
|---|---|---|---|
| 到店自取 | `1` | `1` | 不传 |
| 得来速 | `5` | `1` | 必传，来自 `query-nearby-stores` |
| 麦乐送 | `2` | `2` | 必传，来自 `delivery-query-stores` |
| 企业团餐 | `6` | `2` | 必传，来自 `delivery-query-stores` |

返回结果按 `couponId` 分组：同一 `couponId` 对应多个 `couponCode` 时表示多张同款券，展示为「首个券码（共 N 张）」。字段 `tradeDateTime` 为有效期，`products[].productCode` 为券的适用商品编码，需要与 `query-meals` 的菜单编码对齐。

### S4 · 算价

```
query-meals(storeCode=..., orderType=1, beType=1)
calculate-price(...)
```

只对 S3 中「有可用券」的门店执行，避免对无券门店做无意义的价格计算。券的 `products[].productCode` 若在该店菜单中不存在，标注「券适用商品当前未上架」，不以其他商品替代计算。

### 全程 · 时间锚点

```
now-time-info()
```

返回服务器时间（含 `timestamp`、`formatted`、`timezone`、`dayOfWeek`）。用途有两个：判断券的有效期是否已过；判断当天的活动窗口（早/午/下午茶/夜市/宵夜）是否覆盖当前时刻。实测返回 `timezone = GMT+08:00`、`dayOfWeek = FRIDAY`。

## 业务价值

**对用户**：把一个原本需要「走到店里 → 点开点餐页 → 逐张券试 → 发现用不了」的试错过程，压缩成一次查询。核心价值不是「有多少券」，而是「哪家店、哪张券、实付多少」。

**对麦当劳 MCP**：券的可核销性判断需要跨 `query-my-coupons`、`query-nearby-stores`、`query-store-coupons`、`query-meals`、`calculate-price` 五个接口联动才能得出，单接口无法回答。本 Skill 是这组接口的一个高内聚组合用法，也顺带暴露了 `available-coupons` 重复条目与门店坐标缺失两个数据质量问题。

## 数据合规

- 仓库内 `mcp-config.example.json` 仅含占位符 `YOUR_MCP_TOKEN`，无真实凭据。
- 开发与测试过程中产生的 Token、`accountId`、`traceId` 均未写入仓库。
- 全部 Tool 调用为只读或「领取免费券」，不涉及支付、下单、取消。
- 不采集、不落盘任何用户个人信息。
