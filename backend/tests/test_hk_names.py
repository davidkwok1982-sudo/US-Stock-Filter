"""HKEX Traditional Chinese short-name mapping."""

from app.universe_hk import apply_name_zh, parse_zh_names, to_yahoo


def test_to_yahoo_zfill():
    assert to_yahoo("00001") == "0001.HK"
    assert to_yahoo("00700") == "0700.HK"
    assert to_yahoo("5") == "0005.HK"
    assert to_yahoo("09988") == "9988.HK"
    assert to_yahoo("10000") is None


def test_parse_zh_names_maps_known_tickers():
    mapping = parse_zh_names(
        [
            {"c": "00700", "n": "騰訊控股"},
            {"c": "00005", "n": "匯豐控股"},
            {"c": "09988", "n": "阿里巴巴－Ｗ"},
        ]
    )
    assert mapping["0700.HK"] == "騰訊控股"
    assert mapping["0005.HK"] == "匯豐控股"
    assert mapping["9988.HK"] == "阿里巴巴－Ｗ"


def test_apply_name_zh_stamps_rows():
    rows = [
        {"symbol": "0700.HK", "name": "TENCENT"},
        {"symbol": "0005.HK", "name": "HSBC HOLDINGS"},
        {"symbol": "9999.HK", "name": "MISSING"},
    ]
    apply_name_zh(rows, {"0700.HK": "騰訊控股", "0005.HK": "匯豐控股"})
    assert rows[0]["nameZh"] == "騰訊控股"
    assert rows[1]["nameZh"] == "匯豐控股"
    assert "nameZh" not in rows[2]
