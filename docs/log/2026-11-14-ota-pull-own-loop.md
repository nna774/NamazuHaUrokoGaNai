# 2026-11-14 pull型OTAの取得をHTTPUpdateから自前ループに置き換える

## きっかけ

device2をa6c495dへOTAした際、取得中のTASK_WDTパニックが2回出てから着地した
（coredump `coredump/0002/cf36e46-00001794654988968166.bin`・`...655041968045.bin`、
解析は[2026-11-14-batch-uplink-v3.4.1-issynced.md](2026-11-14-batch-uplink-v3.4.1-issynced.md)）。
スタックは`HTTPUpdate`→`UpdateClass::writeStream`→`Stream::readBytes`→
`WiFiClientSecure::read`→`mbedtls_ssl_read`→`lwip_recvfrom`。許可は立てたままなので
いずれ着地するが、1回落ちるたびに数十秒〜1分半の欠測が出る。

## 原因（Arduino-ESP32 2.0.17のソースで確認）

[2026-09-06](2026-09-06-ota-pull-timeout-budget-fix.md)の「readの締切は8秒なのでWDT(20秒)に
収まる」という判断は、締切が1バイトごとに掛かる点を見落としていた。

- `Updater.cpp`の`writeStream()`は`data.readBytes(buf, 4096 - 溜まった分)`でセクタを
  埋めようとする。`onProgress`が呼ばれるのはセクタを書いた時だけ。
- `Stream::readBytes()`は`WiFiClientSecure`でoverrideされておらず、1バイトごとに
  `timedRead()`(締切`_timeout`=8秒。`HTTPUpdate`の`_httpClientTimeout`由来)を回す。
  1バイトでも届けば締切がリセットされるので、細切れに届くと1回の`readBytes`に上限が無い。
- `readBytes`が0を返した（8秒間1バイトも来なかった）場合も、`writeStream()`は100ms待って
  最大300回再試行する。完全に止まっても3回目の途中で20秒を超える。
- `ssl_client.cpp`はソケットを`O_NONBLOCK`にしたまま戻さないので、`mbedtls_ssl_read`
  自体はブロックしない。coredumpが`lwip_recvfrom`に居たのは、`timedRead()`の
  ビジーポーリングの中で最も時間を食う場所だったからと読める。

つまり「1回のreadが長い」のではなく、「WDTを養う点（セクタ書き込み）の間隔に上限が無い」。

## 決めたこと

候補は2つあった。(a) OTA中だけuploaderタスクをWDTから外し、全体締切を自前で持つ。
(b) `HTTPUpdate`をやめ、自前ループで`Update.write()`しながらWDTを養う。**(b)を選んだ。**

- (a)では`httpUpdate.update()`の中から抜ける手段が無い。全体締切を過ぎた時にできるのは
  別タスクから再起動することだけで、`HTTP_UPDATE_FAILED`→60秒バックオフという既存の
  穏当な失敗パスに乗せられない。最悪`writeStream()`の再試行で約40分戻らない。
- (b)なら停滞も全体締切も同じループの中で判定でき、`Update.abort()`して普通に失敗を返せる。
  `HTTPUpdate`が担っていたのはGET・サイズ確認・`Update.begin/end`程度で、写すのは小さい。

実装は`firmware/lib/PullOta`（`pullota::fetchAndWrite()`）。`main.cpp`と`piezo_main.cpp`の
`performPullOta()`が同じ穴を持っていたので、両方からこれを呼ぶ形で重複も消した。

- `HTTPClient`で`useHTTP10(true)`(chunkedを避ける)・`Cache-Control: no-cache`は
  `HTTPUpdate`と同じにした。`x-ESP32-*`ヘッダは送らない（CloudFront/S3側で誰も見ていない）。
- ボディは`available()`分（最大1KB）ずつ`read()`して`Update.write()`。毎周
  `esp_task_wdt_reset()`。データが無ければ`delay(5)`。
- 締切: 受信停滞15秒、取得全体180秒。180秒は測定を止めている時間の上限でもあるので、
  ~1MBのイメージを遅い回線でも取り切れる程度に留めた。
- マジック・イメージ検証は`Update.write()`/`Update.end()`が`writeStream()`の時と同じく行う。

## 残っている穴

- `http.GET()`中のレスポンスヘッダ読み取りは`HTTPClient`既定(5秒/行、最終受信から)のまま。
  ヘッダが細切れに届けば理論上は20秒を超えうる。ヘッダは十数行なので実害は小さいと見て
  今回は触っていない。
- DNS解決の締切はlwIP既定のまま（[design.md](../design.md)「ネットワークI/Oのタイムアウト予算」）。

## 確認

`pio run -e adxl355 -e esp32dev -e piezo`が通ることを確認した。実機OTA配信はまだ
（ユーザー確認後に行う）。配信したら、シリアル出力の`[ota-pull] N bytes in M ms`で所要時間を、coredumpが
増えないことでパニックが消えたかを見る。
