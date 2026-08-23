"""ingest handlerが実際に組み立てる形——batch_uplink.devices.record_batch_fragments()と
ローカルの断片(watchdog_mute/device_meta)をUpdateItemBuilderで1回のupdate_itemに
まとめる経路——の統合テスト（DynamoDB を直接叩かず FakeTable で代替する）。
"""

from decimal import Decimal

import pytest
from batch_uplink import devices

from common import device_meta, watchdog_mute
from common.dynamo_update import UpdateItemBuilder


class FakeTable:
    def __init__(self):
        self.calls: list[dict] = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def table():
    return FakeTable()


def _build_and_execute(table, item, batch_start_us, ingest_at_us, sensor_type,
                       last_batch_key="k", fw_version=""):
    builder = UpdateItemBuilder()
    for expr, values in devices.record_batch_fragments(
            item, batch_start_us, ingest_at_us,
            last_batch_key=last_batch_key, fw_version=fw_version):
        builder.add(expr, values)
    builder.add(*watchdog_mute.clear_mute_fragment())
    builder.add(*device_meta.sensor_type_fragment(sensor_type))
    builder.execute(table, 2)


def test_single_update_item_call_per_batch(table):
    _build_and_execute(table, None, 1_000_000, 2_000_000, sensor_type=1)
    assert len(table.calls) == 1


def test_combined_expression_has_set_add_and_remove(table):
    _build_and_execute(table, None, 1_000_000, 2_000_000, sensor_type=1)
    expr = table.calls[0]["UpdateExpression"]
    assert expr.startswith("SET ")
    assert " ADD batches_total :one" in expr
    assert expr.endswith("REMOVE watchdog_muted")


def test_values_include_all_fragments(table):
    _build_and_execute(table, None, 1_000_000, 2_000_000, sensor_type=1, fw_version="1.2.3")
    values = table.calls[0]["ExpressionAttributeValues"]
    assert values[":now"] == Decimal(2_000_000)
    assert values[":bs"] == Decimal(1_000_000)
    assert values[":fw"] == "1.2.3"
    assert values[":one"] == Decimal(1)
    assert values[":s"] == 1


def test_backfilled_older_batch_omits_last_batch_start_us_but_still_one_call(table):
    item = {"last_batch_start_us": Decimal(5_000_000)}
    _build_and_execute(table, item, 1_000_000, 2_000_000, sensor_type=1)
    assert len(table.calls) == 1
    expr = table.calls[0]["UpdateExpression"]
    assert "last_batch_start_us" not in expr
    assert ":bs" not in table.calls[0]["ExpressionAttributeValues"]
