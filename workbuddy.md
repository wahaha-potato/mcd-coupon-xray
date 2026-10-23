# WorkBuddy 开发对话上下文

本文件记录本项目在腾讯 WorkBuddy 中的真实开发过程，用于核验联动活动（WorkBuddy 专项奖励）的符合性。

- **开发工具**：WorkBuddy（Agent 模式）
- **开发日期**：2026-10-23
- **MCP 接入方式**：WorkBuddy 左侧「专家·技能·连接器」→「连接器」→「自定义连接器」→「配置 MCP」→ 填入 `mcd-mcp` 的 streamablehttp 配置 → 启用
- **MCP Token**：由开发者在 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 通过手机号验证申请，全程未写入仓库任何文件

## 开发过程关键节点

### 1. 赛题与赛制梳理

读取活动仓库（`M-China/mcd-developer-innovation-challenge`）的 `README.md`、`activityGuidelines.md`、`RANKING.md`，确认：

- 排名依据为公开 Star 数，Star = 0 不进榜，榜尾门槛约 36，前三名门槛 900+
- 必交文件清单在 `README.md`（4 项）与 `activityGuidelines.md`（5 项）之间存在不一致，后者多一个 `mcp-config.example.json`，本项目按 5 项全做
- 项目创建时间下限为 2025-12-25，报名 Issue 的标题与正文之间不能换行、项目地址不能用 Markdown 链接

### 2. 选题推翻与重建（本次开发最关键的一步）

初版选题是「券 × 门店交叉匹配，告诉用户他卡包里 7 张券只有 2 张能用」。在 WorkBuddy 中接入真实 Token 后**实测**，该选题当场被证伪：

| 实测调用 | 返回 | 结论 |
|---|---|---|
| `now-time-info` | `2026-10-23 10:24:32`，`GMT+08:00` | Token 有效 |
| `available-coupons` | 5 条记录 | 实际只有 3 张券（同名重复，图片域名不同） |
| `query-my-coupons` | `暂无可用优惠券` | 新账户卡包为空 |
| `query-my-account` | `availablePoint = "0"`，`accountId` 正常 | 账号已登录，只是无券无积分 |
| `query-nearby-stores`（收藏） | `code 600050` 收藏为空 | 必须降级到城市+关键词搜索 |
| `query-nearby-stores`（北京/三里屯） | 5 家门店，`storeCode=1951066` 等 | 门店链可用 |
| `query-store-coupons`（`1951066`） | `data: []` | **卡包空则按店校验必空** |

空账户下原方案演示为空，说明它建立在「用户已攒了一堆券」这个不成立的前提上。

于是转向，把官方文档里的一句话变成产品内核：

> `query-my-coupons` 返回的是用户拥有的券，不进行门店、渠道、配送方式等下单规则校验，因此不承诺可用于当前订单。若业务目标是"当前门店/当前订单可用的券"，请调用 `query-store-coupons`。

**「能领」≠「能用」**——这个认知断层是官方自己承认的，且无人做。新方案对空账户天然成立：先领券，立刻就有 3 张可校验。

### 3. 从实测中沉淀的三条硬约束

写进 `SKILL.md`，避免后续实现重新踩坑：

1. 必须先领券再查门店，顺序颠倒会得到「这家店一张券都不支持」的假结论
2. `available-coupons` 条目数 ≠ 券张数，去重只能按券名（同券在不同 CDN 域名下）
3. 门店 `longitude` / `latitude` 恒为 `0.0`，只有 `distance` 可用

### 4. 工程实现

在 WorkBuddy 中生成 `scripts/xray.py`，把上述三条约束落成确定性纯函数（去重 / 归并 / 矩阵 / 排序），不依赖运行时推断：

- `dedupe_coupons` —— 按券名归并，返回 `(券列表, 原始条数, 重复条数)`；缺 `title` 直接抛 `ValueError`，不用静默跳过掩盖数据问题
- `group_by_coupon_id` —— 同 `couponId` 多 `couponCode` 归并，`products` 去重
- `build_matrix` —— 跨店可用性矩阵，字典缺键与空数组语义一致
- `rank_stores` —— 按券后实付升序，同价按省钱额降序，`after` 缺失排最后

配套 `tests/test_xray.py`，18 个用例，覆盖真实样本（5 条 → 3 张）、边界（空输入、缺字段、字典缺键）、排序（同价、`None`）。

WorkBuddy 中实际运行结果：

```
$ python scripts/xray.py --selftest
SELFTEST PASSED · 7 组用例全部通过

$ python tests/test_xray.py
18 passed, 0 failed
```

### 5. 未在开发阶段执行的操作及原因

`auto-bind-coupons`（领券）、`query-meals`（菜单）、`calculate-price`（算价）三个工具**未在开发阶段实跑**：

- `auto-bind-coupons` 会写入开发者本人的麦当劳账户，属于账户变更，开发阶段不做无必要的写入
- `query-meals` / `calculate-price` 需要真实结算上下文，且依赖上一步的领券结果

这三者在 `SKILL.md` 中的位置、参数与渠道矩阵已按官方文档固定，运行时按 S1→S4 顺序自然触发。`MCP_INTEGRATION.md` 中对每个工具逐个标注了「已实测 / 文档确认未执行」，不虚构验证状态。

## 结论

本项目从「选题被实测证伪」到「转向官方文档中的真实断层」，全部判断依据来自 WorkBuddy 中对麦当劳 MCP 的真实调用结果，而非文档推测。三个反直觉事实（空卡包导致按店校验必空、券条目数虚高、门店坐标全为 0）均可在 `MCP_INTEGRATION.md` 中溯源到具体的 `traceId` 级返回样本。
