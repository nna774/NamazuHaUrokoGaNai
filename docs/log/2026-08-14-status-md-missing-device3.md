# docs/STATUS.md のデバイス一覧に3号機(ピエゾ実験機)が抜けていた

## 何が起きたか

`docs/STATUS.md`の「デバイス一覧」テーブルには1号機・2号機・テスト機
(device_id=4294967295)しか無く、2026-08-12にphase1（クラウド統合）まで
実機確認済みのdevice_id=3（ピエゾ実験機）が漏れていた。テーブル自体は
2026-08-11に新設したもの（[2026-08-11-devices-list-doc.md](2026-08-11-devices-list-doc.md)）だが、
その翌日に払い出したdevice 3の反映が漏れていた。

## 対応

`docs/STATUS.md`のデバイス一覧テーブルに device_id=3 の行を追加し、
`docs/piezo.md`を参照させた。他ドキュメント（README.md）にはデバイス個別の
一覧は無く、影響範囲は STATUS.md のみと確認した。
