"""common/event_backfill.py の純粋関数のテスト。

merge_meta: 弱い再発火が meta.json の強い記録を上書きしないことの確認。
M5.9地震の事後解析(2026-08-23)で、セッション後半の弱いcoda再発火が meta.json を
弱い値(max_intensity=0.8)で上書きし、本来の最大値(2.6/2.7)が消えていたのを見つけた。

needs_backfill: 「onset+POST_SECONDS経過後に一度だけ全区間コピーする」という
後追いバックフィルの対象判定。茨城県南部M4.8の事後解析(2026-09-17)で、確定検知
(cloud_confirmed)イベントは`_confirm`が早期に`waveform_prefix`を立てるせいで
この後追いが永久にスキップされ、保存範囲がonset+600秒に届かないまま切れている
バグを見つけた(docs/log/2026-09-17-event-post-window-backfill-mechanism-fix.md)。
"""

import os

os.environ.setdefault("NAMZ_BUCKET", "test-bucket")

from common import event_backfill  # noqa: E402

POST_US = int(event_backfill.POST_SECONDS * 1e6)


def test_no_prev_meta_passes_through():
    onset, intensity, peak, a0 = event_backfill.merge_meta(None, 100, 2.7, 1.2, 0.9)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_weaker_retrigger_does_not_regress_recorded_max():
    prev = {"onset_us": 100, "max_intensity": 2.7, "peak_gal": 1.2, "a0_gal": 0.9}
    onset, intensity, peak, a0 = event_backfill.merge_meta(prev, 200, 0.8, 0.3, 0.2)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_stronger_retrigger_updates_max():
    prev = {"onset_us": 100, "max_intensity": 0.8, "peak_gal": 0.3, "a0_gal": 0.2}
    onset, intensity, peak, a0 = event_backfill.merge_meta(prev, 150, 2.7, 1.2, 0.9)
    assert (onset, intensity, peak, a0) == (100, 2.7, 1.2, 0.9)


def test_onset_keeps_earliest():
    prev = {"onset_us": 100, "max_intensity": 1.0, "peak_gal": 0.5}
    onset, *_ = event_backfill.merge_meta(prev, 50, 0.5, 0.2, None)
    assert onset == 50


def test_a0_missing_from_prev_and_call_stays_none():
    prev = {"onset_us": 100, "max_intensity": 1.0, "peak_gal": 0.5}
    _, _, _, a0 = event_backfill.merge_meta(prev, 100, 1.0, 0.5, None)
    assert a0 is None


def _item(**overrides):
    base = {"device_prompt": True, "cloud_confirmed": False, "onset_us": 0}
    base.update(overrides)
    return base


def test_cloud_confirmed_event_is_eligible_after_post_seconds():
    """バグの再現ケース: cloud_confirmedでもwaveform_backfilledが未設定なら対象。"""
    item = _item(device_prompt=False, cloud_confirmed=True, waveform_prefix="events/x/")
    assert event_backfill.needs_backfill(item, POST_US) is True


def test_already_backfilled_is_skipped():
    item = _item(waveform_backfilled=True)
    assert event_backfill.needs_backfill(item, POST_US) is False


def test_manual_event_is_never_backfilled_here():
    """manualはpromote_event.pyが自前で範囲を決めるので対象外。"""
    item = _item(manual=True)
    assert event_backfill.needs_backfill(item, POST_US) is False


def test_neither_prompt_nor_confirmed_is_skipped():
    item = _item(device_prompt=False, cloud_confirmed=False)
    assert event_backfill.needs_backfill(item, POST_US) is False


def test_too_early_is_skipped():
    item = _item()
    assert event_backfill.needs_backfill(item, POST_US - 1) is False


def test_too_old_is_given_up():
    item = _item(onset_us=-(3_600_000_001))
    assert event_backfill.needs_backfill(item, POST_US) is False
