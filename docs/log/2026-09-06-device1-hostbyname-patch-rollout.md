# 2026-09-06 device1へhostByName()暫定パッチをOTA配信

## 経緯

[同日の調査](2026-09-06-device1-udp-sendto-recurrence.md)で、device1が踏んだ`udp_sendto`/`pcb=1`
クラッシュの修正(`firmware/patches/patch_wifi_generic.py`、2026-09-01実装・PR#8672の
`esp_netif_tcpip_exec()`委譲手法)が**`esp32dev`(device1)には一度もOTA配信されていない**
と判明した。`adxl355`(device2)には同日中に`19a50a8`として配信済みで、以来
(`uptime_s`≈407,000秒=4.7日)パニック無しと確認できていた——ユーザーに報告したところ
「同時に焼くと同時に死ぬ可能性があるから分けていた」の意図的な分離と判明し、
「1にも焼くのはいい」と許可を得た。

## 配信

`master`(`57b2b25`)は`19a50a8`(パッチ含む)以降firmware/に変更が無いと確認した上で、
detached worktreeでクリーンに`esp32dev`をビルド・`tools/publish_ota.sh`で公開
(`fw_version=57b2b25`)、`tools/request_ota.py request 1 57b2b25`で許可した。

新しいマシンだったため、`tools/request_ota.py`が要求する`batch_uplink`パッケージ
(`pip install git+https://github.com/nna774/batch-uplink.git@v3.4.0`)がPython 3.12以上を
要求すると判明——ユーザーの意向で`pyenv`経由でPython 3.12.14を導入し、専用venvを
作って対応した（brewで直接`python@3.12`を入れる案は一度実施したが、ユーザー指示で
アンインストールしpyenvに切り替えた）。

## 着地確認中、別の既知バグ(OTA取得中のWDTパニック)にも遭遇した

許可後のポーリングで、device1は`57b2b25`着地の直前に**`TASK_WDT`で一度パニック・再起動**
していた（`reset_reason`が`PANIC`→`TASK_WDT`に変化、uptimeが一度リセットされてから
`57b2b25`で再度リセットして最終着地）。同時刻に3件目のcoredump
(`e82f81e-00001788678292342682.bin`、2026-09-06 16:04)が自動回収されており、
シンボライズしたところ**今回修正対象のDNSレースとは別の、既に2026-08-31に
device2で特定済みの既知バグ**だった:

```
Crashed task: 'uploader'
task_wdt_isr → abort() → esp_system_abort → panic_abort
stop_ssl_socket (ssl_client.cpp:343) → WiFiClientSecure::read/connect
→ ... → HTTPUpdate::runUpdate/handleUpdate (pull型OTA取得経路)
```

`performPullOta()`が使う生の`WiFiClientSecure`に`setHandshakeTimeout()`を一度も
呼んでおらず、TLSハンドシェイクの締切が既定**120秒**のままWDT(20秒)より長く残って
いる——`onProgress`によるWDT給餌は進捗があった時にしか効かないため、ハンドシェイクの
内部リトライループが20秒を超えるとすり抜けてパニックする、という2026-08-31時点の
分析がそのまま当てはまる（[後日の`/code-review`](2026-09-06-ota-pull-timeout-budget-fix.md)で、
read/write側の30秒という当初の見立ては誤りで、実際は`HTTPUpdate`が内部で強制的に
8秒へ揃えており最初から危険域ではなかったと判明した）。
pull型OTAは`pending_ota_version`をサーバ側に立てっぱなしにする設計のため、パニック後の
再起動でも許可が残り、次の巡回で自然に再試行されて着地した（今回も実害はパニック1回のみ）。

この一致で「device2固有ではなく`esp32dev`/`adxl355`共通の問題」という裏付けが強まった。
修正(setTimeout短縮/チャンク内給餌/WDT延長)は2026-08-31から未着手のまま——自然リトライで
実害が軽微なため緊急ではないが、据え置くかは別途判断が要る。

## 結果

device1は`fw_version: 57b2b25`(パッチ込み)で安定稼働中(`online: true`、heap正常)。
device2と合わせてフリート全体にhostByName()暫定パッチが行き渡った。

## 次に何が可能になったこと

- **`udp_sendto`/`pcb=1`バグの再発は、フリート全体でパッチ適用により当面止まるはず**
  ——ただし暫定パッチであり、根治(arduino-esp32 3.x移行)ではない点は変わらない
- **OTA取得中のWDTパニックがdevice1でも実地確認できた**——修正するかは別途ユーザー判断
- 新しいマシンでの`tools/request_ota.py`実行に必要な環境(`pyenv`経由のPython 3.12+
  batch-uplinkパッケージ)が明確になった
