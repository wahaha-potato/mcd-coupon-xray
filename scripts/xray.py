"""麦门券力透视 · 纯函数模块

把麦当劳 MCP 的原始返回，转成「门店 × 券 × 券后实付」的对比表。
本模块不发任何网络请求、不读写文件、不依赖 MCP 连接，可独立单测。

设计约束（来自真实实测，见 MCP_INTEGRATION.md）：
1. available-coupons 的条目数 != 券数量，同一券名可能多条，图片域名不同。
   -> 去重必须按券名，不能按 URL、也不能按条数统计。
2. query-store-coupons 同一 couponId 可对应多个 couponCode。
   -> 统计张数按 couponCode 计，展示按 couponId 分组。
3. 门店 longitude / latitude 恒为 0.0，只有 distance 有效。
   -> 排序一律用 distance。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "dedupe_coupons",
    "group_by_coupon_id",
    "build_matrix",
    "rank_stores",
    "sort_stores_by_distance",
]


def dedupe_coupons(raw: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """按券名归并可领券列表。

    Args:
        raw: available-coupons 的原始条目，每项至少含 ``title``。

    Returns:
        ``(去重后的券列表, 原始条目数, 被合并掉的重复条目数)``

    Raises:
        ValueError: 条目缺少 ``title`` 或 ``title`` 为空。
    """
    merged: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(raw):
        title = (item.get("title") or "").strip()
        if not title:
            raise ValueError(f"第 {idx} 条记录缺少 title，无法按券名归并")
        if title in merged:
            merged[title]["occurrences"] += 1
            continue
        merged[title] = {"title": title, "occurrences": 1}

    coupons = list(merged.values())
    total = len(raw)
    duplicated = total - len(coupons)
    for c in coupons:
        c["is_duplicated"] = c["occurrences"] > 1
    return coupons, total, duplicated


def group_by_coupon_id(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """把 query-store-coupons 的结果按 couponId 归并。

    同一 couponId 下的多个 couponCode 表示多张同款券。

    Returns:
        每项形如 ``{"couponId", "title", "codes": [...], "codeCount", "tradeDateTime", "products"}``
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        coupon_id = str(row.get("couponId") or "").strip()
        if not coupon_id:
            raise ValueError("query-store-coupons 返回记录缺少 couponId")
        entry = grouped.setdefault(
            coupon_id,
            {
                "couponId": coupon_id,
                "title": (row.get("title") or "").strip(),
                "codes": [],
                "tradeDateTime": row.get("tradeDateTime"),
                "products": [],
            },
        )
        code = row.get("couponCode")
        if code and code not in entry["codes"]:
            entry["codes"].append(code)
        for product in row.get("products") or []:
            if product not in entry["products"]:
                entry["products"].append(product)

    result = list(grouped.values())
    for entry in result:
        entry["codeCount"] = len(entry["codes"])
    return result


def sort_stores_by_distance(stores: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """按 distance（米）升序。缺失 distance 的门店排到最后，不参与距离比较。"""
    items = [dict(s) for s in stores]
    return sorted(items, key=lambda s: (s.get("distance") is None, s.get("distance") or 0))


def build_matrix(
    stores: Sequence[Mapping[str, Any]],
    store_coupons: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """生成跨店可用性矩阵。

    Args:
        stores: 门店列表，每项含 ``storeCode`` / ``storeName`` / ``distance``。
        store_coupons: ``{storeCode: query-store-coupons 的 data 数组}``。
            某门店在字典中不存在等价于空数组（密钥缺失与空列表语义一致）。

    Returns:
        ``{"coupons": [券名...], "rows": [{storeCode, storeName, distance, available: {券名: bool}}], "availableCount": {券名: 家数}}``
    """
    coupon_titles: list[str] = []
    available_by_store: dict[str, set[str]] = {}

    for store in stores:
        code = str(store.get("storeCode") or "")
        rows = store_coupons.get(code) or []
        titles: set[str] = set()
        for grouped in group_by_coupon_id(rows):
            if grouped["title"]:
                titles.add(grouped["title"])
        available_by_store[code] = titles
        for t in titles:
            if t not in coupon_titles:
                coupon_titles.append(t)

    matrix_rows = []
    for store in sort_stores_by_distance(stores):
        code = str(store.get("storeCode") or "")
        titles = available_by_store.get(code, set())
        matrix_rows.append(
            {
                "storeCode": code,
                "storeName": store.get("storeName") or "",
                "distance": store.get("distance"),
                "available": {t: (t in titles) for t in coupon_titles},
            }
        )

    available_count = {
        t: sum(1 for r in matrix_rows if r["available"][t]) for t in coupon_titles
    }

    return {"coupons": coupon_titles, "rows": matrix_rows, "availableCount": available_count}


def rank_stores(
    stores: Sequence[Mapping[str, Any]],
    pricing: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """按「券后实付」升序给出可执行结论。

    Args:
        stores: 门店列表，每项含 ``storeCode`` / ``storeName`` / ``distance``。
        pricing: ``{storeCode: {"bestCoupon", "before", "after", "saved"}}``。
            没有可用券的门店不要放进 pricing。

    Returns:
        可用门店列表，按 ``after`` 升序；``after`` 缺失的排最后。
    """
    ranked: list[dict[str, Any]] = []
    for store in stores:
        code = str(store.get("storeCode") or "")
        if code not in pricing:
            continue
        price = pricing[code]
        ranked.append(
            {
                "storeCode": code,
                "storeName": store.get("storeName") or "",
                "distance": store.get("distance"),
                "bestCoupon": price.get("bestCoupon"),
                "before": price.get("before"),
                "after": price.get("after"),
                "saved": price.get("saved"),
            }
        )

    if not ranked:
        return []

    def _key(item: dict[str, Any]):
        after = item.get("after")
        saved = item.get("saved") or 0
        return (after is None, after if after is not None else 0, -saved)

    return sorted(ranked, key=_key)


def _selftest() -> int:
    """内置自检，等价于 tests/test_xray.py，不依赖 pytest。"""
    failures: list[str] = []

    # 1. available-coupons 实测样本：5 条 -> 3 张券
    raw = [
        {"title": "11.9元麦辣鸡腿堡", "img": "https://img.mcd.cn/cms/images/289fd13e1138b66b.png"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://img.mcd.cn/cms/images/edc67c7e8284bc71.png"},
        {"title": "免费脆薯饼", "img": "https://img.mcd.cn/cms/images/858839306b7cca66.png"},
        {"title": "11.9元麦辣鸡腿堡", "img": "https://mcd-portal-prod-cos1-xxxx.cos.ap-shanghai.myqcloud.com/a.png?sign=1"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://mcd-portal-prod-cos1-xxxx.cos.ap-shanghai.myqcloud.com/b.png?sign=2"},
    ]
    coupons, total, dup = dedupe_coupons(raw)
    if (len(coupons), total, dup) != (3, 5, 2):
        failures.append(f"dedupe_coupons 期望 (3, 5, 2)，实际 ({len(coupons)}, {total}, {dup})")
    if "免费脆薯饼" not in [c["title"] for c in coupons]:
        failures.append("dedupe_coupons 丢失了未重复的券")

    # 2. 空券列表不应抛错
    empty, t0, d0 = dedupe_coupons([])
    if (empty, t0, d0) != ([], 0, 0):
        failures.append("dedupe_coupons 对空输入处理错误")

    # 3. 同一 couponId 多 couponCode
    rows = [
        {"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A1", "products": [{"productCode": "P1", "productName": "麦辣鸡腿堡"}]},
        {"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A2", "products": [{"productCode": "P1", "productName": "麦辣鸡腿堡"}]},
        {"couponId": "C2", "title": "免费脆薯饼", "couponCode": "B1", "products": [{"productCode": "P2", "productName": "脆薯饼"}]},
    ]
    grouped = group_by_coupon_id(rows)
    if len(grouped) != 2:
        failures.append(f"group_by_coupon_id 期望 2 组，实际 {len(grouped)}")
    c1 = next((g for g in grouped if g["couponId"] == "C1"), None)
    if c1 is None or c1["codeCount"] != 2:
        failures.append("group_by_coupon_id 未合并同 couponId 的多张券码")
    if c1 is not None and len(c1["products"]) != 1:
        failures.append("group_by_coupon_id 未对 products 去重")

    # 4. 缺 couponId 应抛错（静默吞掉会导致张数统计失真）
    try:
        group_by_coupon_id([{"title": "无ID券"}])
    except ValueError:
        pass
    else:
        failures.append("group_by_coupon_id 对缺失 couponId 未抛 ValueError")

    # 5. 矩阵：三家店，券分布不同
    stores = [
        {"storeCode": "1951066", "storeName": "长虹桥", "distance": 628, "longitude": 0.0, "latitude": 0.0},
        {"storeCode": "1950050", "storeName": "团结湖", "distance": 933, "longitude": 0.0, "latitude": 0.0},
        {"storeCode": "1950085", "storeName": "工体北路", "distance": 1355, "longitude": 0.0, "latitude": 0.0},
    ]
    mapping = {
        "1951066": [{"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A1"}],
        "1950050": [{"couponId": "C2", "title": "免费脆薯饼", "couponCode": "B1"}],
        "1950085": [],
    }
    matrix = build_matrix(stores, mapping)
    if matrix["coupons"] != ["11.9元麦辣鸡腿堡", "免费脆薯饼"]:
        failures.append(f"build_matrix 券清单错误：{matrix['coupons']}")
    if [r["storeCode"] for r in matrix["rows"]] != ["1951066", "1950050", "1950085"]:
        failures.append("build_matrix 门店未按 distance 升序")
    if matrix["availableCount"] != {"11.9元麦辣鸡腿堡": 1, "免费脆薯饼": 1}:
        failures.append(f"build_matrix 可用家数错误：{matrix['availableCount']}")
    if matrix["rows"][2]["available"].get("免费脆薯饼") is not False:
        failures.append("build_matrix 未把空门店标为不可用")

    # 6. 排序：after 升序，after 缺失排最后
    pricing = {
        "1951066": {"bestCoupon": "11.9元麦辣鸡腿堡", "before": 25.5, "after": 11.9, "saved": 13.6},
        "1950050": {"bestCoupon": "免费脆薯饼", "before": 13.0, "after": 8.0, "saved": 5.0},
    }
    ranked = rank_stores(stores, pricing)
    if [r["storeCode"] for r in ranked] != ["1950050", "1951066"]:
        failures.append(f"rank_stores 排序错误：{[r['storeCode'] for r in ranked]}")

    # 7. 全无可用券 -> 空列表，不报错
    if rank_stores(stores, {}) != []:
        failures.append("rank_stores 对无可用券应返回空列表")

    if failures:
        print("SELFTEST FAILED")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST PASSED · 7 组用例全部通过")
    return 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)
    print("用法: python scripts/xray.py --selftest")
