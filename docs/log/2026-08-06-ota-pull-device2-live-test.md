# pull型OTAをdevice2実機で通しで試し、3つの不具合を直した

PR#12（HTTPSプル型OTA実装）マージ・device2への初回書き込み後、実際に
`tools/publish_ota.sh`→`tools/request_ota.py`でpull型OTAを起動させて初めて
通しで試した。3つの実機不具合を踏み、その場で直して最終的に成功した。

## 何が起きたか、何を決めたか

### 1. TLS証明書検証が2段階で失敗した

- 当初案(ESP-IDF低レベルAPI + `crt_bundle_attach`)は実機で
  `Failed to attach bundle`。ユーザーから「insecureにしていいか聞け」と
  指摘され、`HTTPUpdate`（`WiFiClientSecure`の既定CAバンドル検証）への
  切り替えを提案・承認を得て実装したが、これも`start_ssl_client: -1`で
  同じ理由（PlatformIO Arduinoフレームワークビルドでは既定バンドルの実体が
  空）で失敗した。
- ユーザーから「バンドルする方法はないか」と重ねて指摘され、実機で
  `namazu.dark-kuins.net`の証明書チェーンを`openssl s_client -showcerts`で
  確認し、Amazon Root CA 1を特定。`firmware/certs/amazon_root_ca1.pem`を
  `board_build.embed_txtfiles`でリンクし`setCACert()`で明示検証する方式で
  ようやく成功した。**2回とも、ユーザーに確認を取ってから次の手を選んだ**
  （[[feedback_ask_before_spec_changes]]と同じ教訓の実践）。

### 2. 失敗時の高頻度リトライで実測が止まった

トリガー用ヘッダ値は`Uploader`のキャッシュなので、失敗直後の再チェックは
同じ値のまま——バックオフが無いと`uploaderTask`のループ周期(約50ms)ごとに
取得を再試行し、そのたびに測定タイマーが止まったまま戻らなかった。device2で
実際に踏み、lag_sが伸び続けるのを見て気づいた。1分のバックオフを追加。

ユーザーからは「device2は今回検証用の状態だから直せればいい」と言われ、
実害への過度な心配より修正を優先してよいと判断した。

### 3. cert検証失敗などOTA失敗に気づける手段が無かった

ユーザーから「cert検証失敗したら気づけるようにしてほしい」と依頼され、
watchdog Lambdaに停滞検知を追加した。`pending_ota_version`は一回性でなく
持ち続ける設計なので、サーバは「デバイスが取得できたか」を直接観測できない。
代わりに「要求してから30分（既定）を超えて解消しなければSlack通知」する
形にした（`lambda/common/ota_watch.py`の`evaluate_ota_stuck`、原因は問わない
——原因の切り分けは実機シリアルログに委ねる）。

## 最終確認

device2実機で実際に:
1. `tools/request_ota.py request 2 <version>`で許可
2. デバイスが次のバッチ送信時に気づき、安全停止→`HTTPUpdate`で取得
   （TLS検証込み）→書き込み→`ESP.restart()`
3. 新バージョンで起動し、`fw=<version>`ログとバッチ送信の再開を確認

という一連の流れが実機で成功した。**pull型OTAが実機で動作確認できた最初の
記録。**

## 次に何が可能になったか

- push型OTAの実機確認（`unnamed_network_g`に接続した端末からのespota、
  docs/log/2026-08-06-ota-network-isolation.md）と合わせて、OTA関連の
  実機確認タスクが両方進んだ。
- ロールバック（`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`）は今回も見送った
  （TLS・リトライの修正で手一杯だったため）。次回の実機作業で検討する。

詳細は[ota.md §7](../ota.md#7-httpsプル型外出先からの更新無人運用向け)を参照。
