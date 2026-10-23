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

def test_dedupe_real_sample_five_to_three():
    """真实样本：available-coupons 返回 5 条，实际 3 张券。"""
    raw = [
        {"title": "11.9元麦辣鸡腿堡", "img": "https://img.mcd.cn/cms/images/289fd13e1138b66b.png"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://img.mcd.cn/cms/images/edc67c7e8284bc71.png"},
        {"title": "免费脆薯饼", "img": "https://img.mcd.cn/cms/images/858839306b7cca66.png"},
        {"title": "11.9元麦辣鸡腿堡", "img": "https://cos.example.com/a.png?sign=1"},
        {"title": "19.9元王牌炸鸡任选2", "img": "https://cos.example.com/b.png?sign=2"},
    ]
    coupons, total, duplicated = xray.dedupe_coupons(raw)

    assert len(coupons) == 3
    assert total == 5
    assert duplicated == 2
    assert [c["title"] for c in coupons] == ["11.9元麦辣鸡腿堡", "19.9元王牌炸鸡任选2", "免费脆薯饼"]


def test_dedupe_marks_duplicated_flag():
    coupons, _, _ = xray.dedupe_coupons(
        [{"title": "A"}, {"title": "A"}, {"title": "B"}]
    )
    by_title = {c["title"]: c for c in coupons}
    assert by_title["A"]["is_duplicated"] is True
    assert by_title["A"]["occurrences"] == 2
    assert by_title["B"]["is_duplicated"] is False


def test_dedupe_empty_input():
    assert xray.dedupe_coupons([]) == ([], 0, 0)


def test_dedupe_rejects_missing_title():
    """缺 title 必须抛错：静默跳过会让「券张数」这个核心指标失真。"""
    try:
        xray.dedupe_coupons([{"img": "https://img.mcd.cn/x.png"}])
    except ValueError:
        return
    raise AssertionError("缺少 title 时未抛 ValueError")


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
