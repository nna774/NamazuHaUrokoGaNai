# 未送信バックログ件数(spill/ram)を毎バッチヘッダで送り、詳細画面に出す

## 決めたこと

`gUploader->spillCount()`(LittleFS退避済み件数)・`ramQueued()`(RAMキュー内件数)を、
既存のヒープ空き容量ヘッダと同じ仕組みで毎バッチ`X-Namz-Spill-Count`/`X-Namz-Ram-Queued`
ヘッダとして送るようにした(`firmware/src/main.cpp`)。2本に分けたのはheap free/maxblockと
同じ理由——spillが多いのは電源断からの復旧中、ramが多いのは今まさに送信が詰まっている、で
意味が違うため合算すると見分けが付かなくなる。

サーバ側はingestが受けてCloudWatchカスタムメトリクス(`SpillCount`/`RamQueued`、
`lambda/common/metrics.py`の`record_backlog`/`latest_backlog`、ヒープと同じ設計)へ送り、
api Lambdaの`_device()`(詳細ページ限定、一覧はCloudWatch呼び出しを増やさないため対象外)が
最新1点を返す。dashboardのデバイス詳細画面に「未送信バックログ」行を追加し、
`退避N件 / RAM N件`とCloudWatchコンソールへの深リンクを表示する。

## なぜ

`spillCount()+ramQueued()`は元々ファーム内で使っていた(OLED表示のbacklog件数・
`gBacklogAgeS`の計算)が、これまではデバイス本体の画面にしか出ておらず、サーバ側
（dashboard・watchdog）から今の滞留量を知る手段が無かった。`memo.md`の
「batch okuru toki spill youryou mo issyo ni okurenaika」という要望から着手。

バイト単位の容量は`Uploader`(batch-uplink)にAPIが無く、追加するには別リポジトリの
タグ更新が要る。1バッチはほぼ固定サイズなので件数からおおよその容量は逆算できると判断し、
今回は件数のみとした（ユーザー確認済み）。

## 次に可能になったこと

デバイス詳細画面で未送信バックログの現在値を見られるようになり、CloudWatchで推移も追える。
`memo.md`にある他の2項目（batch queue吸い出しtaskの分離案、backlog優先順位変更後の
watchdog遅延判定の再確認）はこの変更のスコープ外で、未着手のまま残っている。
