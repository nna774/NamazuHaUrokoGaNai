# 茨城県南部M4.8 事後解析

## 震源要素

- 発生: 2026-09-17 00:07頃(JST)
- 震央: 茨城県南部 N36.1/E140.1、深さ70km
- マグニチュード: 4.8
- 最大震度: 3（気象庁公開地震一覧 `list.json` より）

## 1. 自動検知の有無

`/events?all=1` で自動確定を確認できた。

- `0001-59652376`（device1）: onset 2026-09-17 00:08:09.17 JST、確定震度2.0、peak 4.64gal
- `0002-59652376`（device2）: onset 2026-09-17 00:08:09.48 JST、確定震度2.0、peak 4.49gal

震央距離147km・震源距離163km。propagation遅延は約69秒（発生00:07:00→onset00:08:09）。

onsetからlast_usまで約91秒あるのは`lambda/common/events.py`のセッションマージ
（`MERGE_GAP_US`=60秒以内の新規onsetを同一event_idに延長）が自動で効いた結果で、
下記のコーダ解析で見る揺れの実体（相関が背景に戻るまでの区間）とほぼ一致していた。

### 保存済み範囲の先のコーダ確認

`detectlab.py --minutes 15`（発生時刻を起点に900秒先まで、`POST_SECONDS=600`の保存範囲を
超えて確認）を実行:

```
python tools/detectlab.py --at "2026-09-17 00:07:00" \
  --eew "36.1,140.1,70,2026-09-17 00:07:00" --minutes 15 --device 1 2 --intensity \
  --out docs/log/img/2026-09-17-ibaraki-nanbu-m4.8-15min.png --corr-bin 20
```

`--corr-bin`の結果、t=160-180s帯（onsetから見て約90-110秒後、last_usとほぼ同時刻）で
一致度frac 0.6→0.14まで落ち、以降t=900sまでずっと背景水準(frac 0.17前後)のまま再上昇
していない。**保存済み600秒枠の外にコーダの延長は無い**——延長作業は不要と判断した。

## 2. detectlabで解析する

- 重ね合わせ図（`--intensity`付き）: [2026-09-17-ibaraki-nanbu-m4.8-15min.png](img/2026-09-17-ibaraki-nanbu-m4.8-15min.png)
- device1単体: [2026-09-17-ibaraki-nanbu-m4.8-device1.png](img/2026-09-17-ibaraki-nanbu-m4.8-device1.png)
- device2単体: [2026-09-17-ibaraki-nanbu-m4.8-device2.png](img/2026-09-17-ibaraki-nanbu-m4.8-device2.png)

標準設定（3軸・1-10Hz）:

| device | STA/LTA peak | P窓SNR/直線性 | S窓SNR/直線性 | コーダ想定域SNR/直線性 |
|---|---|---|---|---|
| 1 | 16.47 | 1.00/0.41(微妙) | 0.96/0.36(微妙) | 7.49/0.82(地震らしい) |
| 2 | 18.10 | 1.01/0.55(微妙) | 0.97/0.58(微妙) | 10.38/0.81(地震らしい) |

理論P窓・S窓の中ではSNR≈1で埋もれ気味だが、S窓終了後の**コーダ想定域**でSNR 7.5〜10.4・
直線性0.81〜0.82と明瞭に立ち上がっている。実際の検知onset（00:08:09〜10）もS窓
（00:07:36-46）より約25秒遅れてこのコーダ想定域の中に来ており、
`docs/post_hoc_detection.md`が言う「初動そのものより初動直後のコーダにエネルギーが乗る」
典型パターンだった。`--corr-bin`のt=60-140s帯（00:08:00〜00:09:20相当）で両機の一致度
frac 0.77-1.00・mean_corr 0.75-0.91と背景(frac 0.17)を大きく上回っており、機間相関からも
本物の揺れと確認できる。

## 判定

**probable detection（good）**。2機とも同時刻・同特徴（コーダ想定域での高SNR・高直線性・
高い機間相関）で一致しており、確定検知(`cloud_confirmed`)とも整合する。

## 3.5 / 4 実施内容

- `tools/detection_events.csv`に`ibaraki-nanbu-m4.8`として追記
- `flag_event.py verdict good 0001-59652376 0002-59652376`
- `flag_event.py relate 0001-59652376 0002-59652376`（自動確定だけでは相互リンクされない
  ため。両event_idは確定済みで既に一般に取得され得た状態だったため、書き換え後
  CloudFront invalidationを`/event?id=0001-59652376`・`/event?id=0002-59652376`に打った）
