# coredump自動クラウド送信構想の一次検討

## 背景

PR#165（[log/2026-08-29-device2-task-wdt-coredump-tls-handshake.md](2026-08-29-device2-task-wdt-coredump-tls-handshake.md)）でdevice2のTASK_WDT再起動の原因をESP-IDFのcoredump-to-flash機構で特定できたことを受け、「起動時にcoredumpがあれば自動でクラウドへ送る」構想（`docs/design.md`の2026-08-29未実装メモ）について、実装前の一次検討をチャットで行った。設計判断はまだ何もしていない——ここで得た事実を、次に設計する時の前提として残す。

## 秘密情報が写り込むか

`firmware/src/main.cpp`のグローバル`gIdentity`がWiFiパスワード(`wifiPass`)・HMAC共有鍵(`hmacSecret`)をブート中ずっと保持している（`connectWifi()`・HMAC設定呼び出し箇所で`.c_str()`を渡している）。

一方、実機が使っているESP-IDFの`sdkconfig`（`~/.platformio/packages/framework-arduinoespressif32/tools/sdk/esp32/sdkconfig`）を確認したところ`CONFIG_ESP_COREDUMP_DATA_FORMAT_ELF=y`で、ヒープ/BSS全体を捕る`CONFIG_ESP_COREDUMP_CAPTURE_DRAM`は有効になっていない。既定ではパニック時の**各タスクのスタックとレジスタのみ**が残る仕様で、`gIdentity`のようなグローバル変数がまるごと写り込むわけではなさそうだと分かった。

ただしこれは「絶対に写らない」ことの証明にはならない。HMAC計算やTLS処理の途中でキーの一部がローカル変数（＝スタック）へ一時的にコピーされる瞬間は原理的にあり得るし、クラッシュ箇所次第で結果は変わる——検証にはコストがかかりすぎる。**「写らないはず」に賭けず、「写るかもしれない」前提で保存先・アクセス制御を設計する方針とする。**

## パーティションは1回分しか保持しない

`espcoredump`のヘッダ（`esp_core_dump.h`）を確認した。`esp_core_dump_image_get()`は単一のアドレス/サイズを返す設計で、複数世代を並べるリングバッファのような仕組みは無い。次のパニックが起きれば同じ場所に上書きされる——`firmware/README.md`に既にある「次に別のクラッシュが起きて上書きされるまで」という記述は、この実装に基づく正確な記述だと確認できた。

また`esp_core_dump_image_erase()`という「送信成功後に消す」ための公式APIが用意されている。自動送信を実装する際そのまま使え、「ACKが返るまで捨てない」という、このリポで一貫している不変条件と自然に噛み合う。

64KB（`partitions_16mb.csv`の`coredump`パーティション）は「1回分の記録が最大64KBまで」という上限であり、複数クラッシュの履歴を溜める容量ではない。device2のように同じ機構が周期的に再発するケースでは、直前の1回分しか残らない——原因調査のためには「気づいたら早めに手動で吸い出す」か「起動時に必ず自動送信する」かのどちらかが要る、という優先度判断の材料になる。

## 次に決めること（未着手のまま）

送信先（非公開ストレージに隔離）・認証（既存HMACデバイス認証の流用）・アップロード自体がハングしない設計（今回のバグそのものが`uploaderTask`のTLSハンドシェイクだった皮肉を踏まえる）・fw_versionをメタデータに含める・通知、は方向性のみ話した。実装はまだしていない。
