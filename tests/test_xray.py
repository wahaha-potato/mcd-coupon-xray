"""mcd-coupon-xray 纯函数单元测试。

运行方式（二选一）：
    python -m pytest tests/ -v
    python tests/test_xray.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import xray  # noqa: E402


# ---------- dedupe_coupons ----------

def test_dedupe_real_auto_bind_sample_five_coupons():
    """真实样本：auto-bind-coupons 领取 5 条记录，5 个不同 couponId，即 5 张真实券。

    这推翻了早期「按券名去重得 3 张」的结论：同名券是两个不同活动
    （一批有效期到 10-23、一批从 10-26 开始），各有真实券码。
    """
    raw = [
        {"title": "11.9元麦辣鸡腿堡", "couponId": "A255280326E3328D179C362B7B8DDA65",
         "couponCode": "MCD60810900B7B5V04022"},
        {"title": "19.9元王牌炸鸡任选2", "couponId": "44928824D2D4273FE5ECA617BBF75483",
         "couponCode": "MCD6C9B100040402V0258"},
        {"title": "11.9元麦辣鸡腿堡", "couponId": "B34E5EC6710BEEECEC8B25C742D3F119",
         "couponCode": "MCD696B00V028E0418250"},
        {"title": "19.9元王牌炸鸡任选2", "couponId": "A03BC156F97B8937213963D7632F3338",
         "couponCode": "MCD6092770001B84220VF"},
        {"title": "免费脆薯饼", "couponId": "0D94B7923332F58026539DB8CCA81275",
         "couponCode": "MCD60V02702G492080B19"},
    ]
    coupons, total, duplicated = xray.dedupe_coupons(raw)

    assert (len(coupons), total, duplicated) == (5, 5, 0)
    assert len({c["couponId"] for c in coupons}) == 5
    titles = [c["title"] for c in coupons]
    assert titles.count("11.9元麦辣鸡腿堡") == 2, "同名券是两个活动，不能合并"
    assert titles.count("19.9元王牌炸鸡任选2") == 2


def test_dedupe_same_coupon_id_merges():
    """同一 couponId 出现两次才算重复（例如 query-store-coupons 的多券码场景）。"""
    raw = [
        {"title": "免费脆薯饼", "couponId": "C1", "couponCode": "A1"},
        {"title": "免费脆薯饼", "couponId": "C1", "couponCode": "A2"},
        {"title": "麦辣鸡腿汉堡", "couponId": "C2", "couponCode": "B1"},
    ]
    coupons, total, duplicated = xray.dedupe_coupons(raw)

    assert (len(coupons), total, duplicated) == (2, 3, 1)
    by_id = {c["couponId"]: c for c in coupons}
    assert by_id["C1"]["occurrences"] == 2
    assert by_id["C1"]["is_duplicated"] is True
    assert by_id["C2"]["is_duplicated"] is False


def test_dedupe_by_title_is_display_only():
    """available-coupons 的返回不含 couponId，只能传 key='title' 做展示归并。

    返回的 3 不等于真实张数——真实张数必须等 auto-bind 返回后按 couponId 统计。
    """
    raw = [
        {"title": "11.9元麦辣鸡腿堡", "img": "https://img.mcd.cn/a.png"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://img.mcd.cn/b.png"},
        {"title": "免费脆薯饼", "img": "https://img.mcd.cn/c.png"},
        {"title": "11.9元麦辣鸡腿堡", "img": "https://cos.example.com/a.png?sign=1"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://cos.example.com/b.png?sign=2"},
    ]
    coupons, total, duplicated = xray.dedupe_coupons(raw, key="title")

    assert (len(coupons), total, duplicated) == (3, 5, 2)
    assert [c["title"] for c in coupons] == ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2", "免费脆薯饼"]


def test_dedupe_default_key_rejects_records_without_coupon_id():
    """available-coupons 样本直接按默认键计数必须报错，而不是静默给出错误张数。"""
    raw = [{"title": "11.9元麦辣鸡腿堡", "img": "https://img.mcd.cn/a.png"}]
    try:
        xray.dedupe_coupons(raw)
    except ValueError as exc:
        assert "available-coupons" in str(exc), "报错信息应指明正确的替代口径"
        return
    raise AssertionError("缺 couponId 时未抛 ValueError")


def test_dedupe_empty_input():
    assert xray.dedupe_coupons([]) == ([], 0, 0)


def test_dedupe_missing_key_field_raises():
    for bad in ([{"title": "无ID"}], [{"couponId": "", "title": "空ID"}]):
        try:
            xray.dedupe_coupons(bad)
        except ValueError:
            continue
        raise AssertionError(f"缺 couponId 时未抛 ValueError: {bad}")


# ---------- group_by_coupon_id ----------

def test_group_merges_codes_of_same_coupon_id():
    rows = [
        {"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A1",
         "products": [{"productCode": "P1", "productName": "麦辣鸡腿堡"}]},
        {"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A2",
         "products": [{"productCode": "P1", "productName": "麦辣鸡腿堡"}]},
        {"couponId": "C2", "title": "免费脆薯饼", "couponCode": "B1",
         "products": [{"productCode": "P2", "productName": "脆薯饼"}]},
    ]
    grouped = xray.group_by_coupon_id(rows)

    assert len(grouped) == 2
    c1 = next(g for g in grouped if g["couponId"] == "C1")
    assert c1["codeCount"] == 2
    assert c1["codes"] == ["A1", "A2"]
    assert len(c1["products"]) == 1, "products 应按出现去重"


def test_group_rejects_missing_coupon_id():
    for bad_rows in ([{"title": "无 ID"}], [{"couponId": "", "title": "空 ID"}]):
        try:
            xray.group_by_coupon_id(bad_rows)
        except ValueError:
            continue
        raise AssertionError(f"缺少 couponId 时未抛 ValueError: {bad_rows}")


def test_group_empty():
    assert xray.group_by_coupon_id([]) == []


# ---------- build_matrix ----------

STORES = [
    {"storeCode": "1951066", "storeName": "长虹桥", "distance": 628, "longitude": 0.0, "latitude": 0.0},
    {"storeCode": "1950050", "storeName": "团结湖", "distance": 933, "longitude": 0.0, "latitude": 0.0},
    {"storeCode": "1950085", "storeName": "工体北路", "distance": 1355, "longitude": 0.0, "latitude": 0.0},
]


def test_matrix_shape_and_counts():
    mapping = {
        "1951066": [{"couponId": "C1", "title": "11.9元麦辣鸡腿堡", "couponCode": "A1"}],
        "1950050": [{"couponId": "C2", "title": "免费脆薯饼", "couponCode": "B1"}],
        "1950085": [],
    }
    m = xray.build_matrix(STORES, mapping)

    assert m["coupons"] == ["11.9元麦辣鸡腿堡", "免费脆薯饼"]
    assert [r["storeCode"] for r in m["rows"]] == ["1951066", "1950050", "1950085"]
    assert m["rows"][0]["available"] == {"11.9元麦辣鸡腿堡": True, "免费脆薯饼": False}
    assert m["rows"][2]["available"] == {"11.9元麦辣鸡腿堡": False, "免费脆薯饼": False}
    assert m["availableCount"] == {"11.9元麦辣鸡腿堡": 1, "免费脆薯饼": 1}


def test_matrix_treats_missing_key_as_empty():
    """字典里没有该门店 == 空数组，两者语义必须一致。"""
    with_key = xray.build_matrix(STORES, {"1951066": []})
    without_key = xray.build_matrix(STORES, {})
    assert with_key == without_key
    assert with_key["coupons"] == []


def test_matrix_same_coupon_in_multiple_stores_counts_each():
    mapping = {
        "1951066": [{"couponId": "C1", "title": "免费脆薯饼", "couponCode": "A1"}],
        "1950050": [{"couponId": "C1", "title": "免费脆薯饼", "couponCode": "B1"}],
    }
    m = xray.build_matrix(STORES, mapping)
    assert m["coupons"] == ["免费脆薯饼"]
    assert m["availableCount"] == {"免费脆薯饼": 2}


def test_matrix_empty_inputs():
    m = xray.build_matrix([], {})
    assert m == {"coupons": [], "rows": [], "availableCount": {}}


# ---------- rank_stores ----------

PRICING = {
    "1951066": {"bestCoupon": "11.9元麦辣鸡腿堡", "before": 25.5, "after": 11.9, "saved": 13.6},
    "1950050": {"bestCoupon": "免费脆薯饼", "before": 13.0, "after": 8.0, "saved": 5.0},
}


def test_rank_sorted_by_after_ascending():
    ranked = xray.rank_stores(STORES, PRICING)
    assert [r["storeCode"] for r in ranked] == ["1950050", "1951066"]
    assert ranked[0]["after"] == 8.0


def test_rank_skips_stores_without_pricing():
    ranked = xray.rank_stores(STORES, PRICING)
    assert "1950085" not in [r["storeCode"] for r in ranked]


def test_rank_tie_breaks_by_larger_saving():
    pricing = {
        "1951066": {"bestCoupon": "X", "before": 20.0, "after": 10.0, "saved": 10.0},
        "1950050": {"bestCoupon": "Y", "before": 30.0, "after": 10.0, "saved": 20.0},
    }
    ranked = xray.rank_stores(STORES, pricing)
    assert [r["storeCode"] for r in ranked] == ["1950050", "1951066"]


def test_rank_none_after_goes_last():
    pricing = {
        "1951066": {"bestCoupon": "X", "before": 20.0, "after": None, "saved": None},
        "1950050": {"bestCoupon": "Y", "before": 30.0, "after": 10.0, "saved": 20.0},
    }
    ranked = xray.rank_stores(STORES, pricing)
    assert [r["storeCode"] for r in ranked] == ["1950050", "1951066"]


def test_rank_empty_pricing_returns_empty():
    assert xray.rank_stores(STORES, {}) == []


# ---------- sort_stores_by_distance ----------

def test_sort_by_distance_ignores_zero_coordinates():
    reversed_stores = list(reversed(STORES))
    ordered = xray.sort_stores_by_distance(reversed_stores)
    assert [s["storeCode"] for s in ordered] == ["1951066", "1950050", "1950085"]


def test_sort_puts_missing_distance_last():
    stores = [
        {"storeCode": "A", "distance": None},
        {"storeCode": "B", "distance": 900},
    ]
    ordered = xray.sort_stores_by_distance(stores)
    assert [s["storeCode"] for s in ordered] == ["B", "A"]


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception:
            failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"PASS  {name}")
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
