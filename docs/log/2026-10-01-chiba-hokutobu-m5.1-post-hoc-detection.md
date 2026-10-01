# 千葉県北東部M5.1(21:27) 事後解析

## 震源要素

- 発生: 2026-10-01 21:27頃(JST)
- 震央: 千葉県北東部 N35.8/E140.7、深さ50km
- マグニチュード: 5.1
- 最大震度: 3（全国。茨城県潮来市・神栖市、千葉県東金市等12市町村）
- 震源距離216km（`detection_range.md`の「近すぎ(ほぼ確実に捕れる)」ゾーン境界付近、
  レンジ下限218kmのすぐ内側）

## 1. 自動検知の有無

`/events?all=1&size=10`で確認したところ、`0001-59695256`(device1)・`0002-59695256`(device2)
がすでに存在していた。ただし**`device_prompt=true`（速報は両機とも自動で拾えた）のに
`cloud_confirmed=false`のまま**——`tools/README.md`「イベントのメモ・手動昇格」節に書かれている
「速報は拾えたが`cloud_confirmed`のHOLD_SECONDS条件に届かず一覧の既定から隠れる」パターン
そのもの。onset_usはdevice1=21:28:15.42、device2=21:28:15.30とわずか0.12秒差で、ノイズでは
まず起きない一致——この時点で実地震の可能性が高いと判断した。

約10分待って`checked`が`true`に変わった後も`cloud_confirmed`は`false`のままだった
（detectの`_confirm`はバッチ到着ごとに直近120秒の窓だけを再評価するため、強い揺れの
ピークが既に過ぎた後に評価のタイミングが来ると、しきい値を跨いだ瞬間を窓が捉えられない
まま確定し損ねることがありうる）。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [2026-10-01-chiba-hokutobu-m5.1-8min.png](img/2026-10-01-chiba-hokutobu-m5.1-8min.png)
- device1単体: [2026-10-01-chiba-hokutobu-m5.1-device1.png](img/2026-10-01-chiba-hokutobu-m5.1-device1.png)
- device2単体: [2026-10-01-chiba-hokutobu-m5.1-device2.png](img/2026-10-01-chiba-hokutobu-m5.1-device2.png)

```
python tools/detectlab.py --at "2026-10-01 21:27:19" --eew "35.8,140.7,50,2026-10-01 21:27:19" \
  --minutes 10 --device 1 2 --intensity --out docs/log/img/2026-10-01-chiba-hokutobu-m5.1-8min.png
```

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 8.87 | 2.78/0.72(地震らしい) | 6.67/0.88(地震らしい) | 1.79/0.68(地震らしい) |
| 2 | 10.04 | 3.54/0.75(地震らしい) | 8.52/0.88(地震らしい) | 2.18/0.73(地震らしい) |

両機ともSTA/LTA閾値(4)を大きく超過、P窓/S窓/コーダ想定域すべてで「地震らしい」判定。
`--corr-bin`では到達直後t=[20,40)〜[100,120)sでfrac(corr≥0.6)が0.79〜1.00、mean_corrが
+0.73〜+0.95まで上昇（背景はfrac=0.16・mean_corr=+0.02）——このデータセットの中でも
際立って明瞭な一致。計測震度（60秒移動窓FIR版）のピークはdevice1=1.0・device2=0.9
（いずれも震度1）で、到達から約160秒かけて平時水準へ減衰する波形も
[岩手県沖M4.9の明瞭例](2026-08-09-iwateoki-m4.9-post-hoc-detection.md)と同様の形。

## 判定

**probable detection（good）。** 自動の`cloud_confirmed`こそ立たなかったが、STA/LTA・SNR・
直線性・機間相関のすべてが揃った教科書的な検出で、判定に迷う余地はない。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`chiba-hokutobu-m5.1`として追記
- 既存イベントをそのまま確定表示へ昇格: `flag_event.py confirm 0001-59695256 0002-59695256`
- `flag_event.py relate 0001-59695256 0002-59695256`で相互リンク
- `flag_event.py verdict good 0001-59695256 0002-59695256`
- `flag_event.py note`で解析結果を両イベントに記録
- 書き換えた既存event_idのため、CloudFront invalidation（`/event?id=0001-59695256`・
  `/event?id=0002-59695256`）を実施

## 次に何が可能になったか

**「速報(device_prompt)が出たのに自動確定(`cloud_confirmed`)に至らない」事例を初めて
明瞭な地震で踏んだ。** detectの`_confirm`はバッチ到着ごとに直近`WINDOW_SECONDS`(120秒)の
窓だけを再評価する設計のため、揺れのピークと評価タイミングのズレ次第で確定を取りこぼし
うる構造的な弱点が見えた。今回は震源距離216kmで「近すぎ(ほぼ確実に捕れる)」ゾーンの
M5.1という明瞭な地震だったからこそ`tools/README.md`に既述の`confirm`手動昇格パスで
回収できたが、**この種の取りこぼしが実際にどれくらいの頻度で起きているかは未調査**。
気になるなら`detection_events.csv`で`device_prompt=true かつ cloud_confirmed=false`の
実例を棚卸しする価値がある（本件では未実施）。
