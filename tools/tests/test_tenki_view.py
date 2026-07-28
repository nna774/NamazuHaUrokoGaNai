import datetime
import zoneinfo

import tenki_view

# tenki.jp 地震詳細ページの当該テーブル部分を模したフィクスチャ（構造は実物準拠）。
FIXTURE = """
<table class="earthquake-detail-table">
<tr><th colspan="2">発生時刻</th>
    <td id="earthquake-generating-datetime">2026年07月24日 20時53分頃</td></tr>
<tr><th colspan="2">震源地</th>
    <td><a href="/bousai/earthquake/center/289/" class="text-link">福島県沖</a></td></tr>
<tr><th colspan="2">最大震度</th><td>震度1</td></tr>
<tr><th rowspan="2">位置</th><th>緯度</th><td>北緯 37.7度</td></tr>
<tr><th>経度</th><td>東経 141.7度</td></tr>
<tr><th rowspan="2">震源</th><th>マグニチュード</th><td>M4.0</td></tr>
<tr><th>深さ</th><td>約50km</td></tr>
</table>
"""


def test_parse_tenki_full():
    q = tenki_view.parse_tenki(FIXTURE)
    assert q["lat"] == 37.7
    assert q["lon"] == 141.7
    assert q["depth_km"] == 50.0
    assert q["mag"] == 4.0
    assert q["region"] == "福島県沖"
    assert q["max_intensity"] == "震度1"
    jst = zoneinfo.ZoneInfo("Asia/Tokyo")
    dt = datetime.datetime.fromtimestamp(q["origin_us"] / 1e6, jst)
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2026, 7, 24, 20, 53, 0)


def test_parse_tenki_gokuasai_and_west():
    # 「ごく浅い」は10km、西経/南緯は負に。
    html = FIXTURE.replace("約50km", "ごく浅い").replace("北緯", "南緯").replace("東経", "西経")
    q = tenki_view.parse_tenki(html)
    assert q["depth_km"] == 10.0
    assert q["lat"] == -37.7
    assert q["lon"] == -141.7


def test_parse_tenki_preliminary_missing():
    # 速報段階で「---」だと緯度経度が取れない → None。
    html = FIXTURE.replace("北緯 37.7度", "---").replace("東経 141.7度", "---")
    q = tenki_view.parse_tenki(html)
    assert q["lat"] is None and q["lon"] is None
    assert q["origin_us"] is not None  # 発生時刻は取れる


def test_default_band_by_distance():
    assert tenki_view.default_band(869) == ("0.3", "1.5")  # 遠地
    assert tenki_view.default_band(400) == ("0.5", "3")
    assert tenki_view.default_band(150) == ("1", "10")     # 近地
