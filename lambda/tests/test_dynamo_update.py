"""dynamo_update.UpdateItemBuilder（DynamoDB を直接叩かず FakeTable で代替する）。"""

import pytest

from common.dynamo_update import UpdateItemBuilder


class FakeTable:
    """update_item の呼び出し回数と引数を記録するだけの最小スタブ。"""

    def __init__(self):
        self.calls: list[dict] = []

    def update_item(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def table():
    return FakeTable()


def test_no_fragments_does_not_call_update_item(table):
    UpdateItemBuilder().execute(table, 2)
    assert table.calls == []


def test_single_set_fragment(table):
    b = UpdateItemBuilder()
    b.add("SET sensor_type = :s", {":s": 1})
    b.execute(table, 2)
    assert len(table.calls) == 1
    call = table.calls[0]
    assert call["Key"] == {"device_id": 2}
    assert call["UpdateExpression"] == "SET sensor_type = :s"
    assert call["ExpressionAttributeValues"] == {":s": 1}


def test_single_remove_fragment_omits_expression_attribute_values(table):
    b = UpdateItemBuilder()
    b.add("REMOVE watchdog_muted", {})
    b.execute(table, 2)
    call = table.calls[0]
    assert call["UpdateExpression"] == "REMOVE watchdog_muted"
    assert "ExpressionAttributeValues" not in call


def test_merges_set_and_remove_into_one_call(table):
    b = UpdateItemBuilder()
    b.add("SET sensor_type = :s", {":s": 1})
    b.add("REMOVE watchdog_muted", {})
    b.execute(table, 2)
    assert len(table.calls) == 1
    call = table.calls[0]
    assert call["UpdateExpression"] == "SET sensor_type = :s REMOVE watchdog_muted"
    assert call["ExpressionAttributeValues"] == {":s": 1}


def test_merges_multiple_set_fragments(table):
    b = UpdateItemBuilder()
    b.add("SET a = :a", {":a": 1})
    b.add("SET b = :b", {":b": 2})
    b.execute(table, 2)
    call = table.calls[0]
    assert call["UpdateExpression"] == "SET a = :a, b = :b"
    assert call["ExpressionAttributeValues"] == {":a": 1, ":b": 2}


def test_single_add_fragment(table):
    b = UpdateItemBuilder()
    b.add("ADD batches_total :one", {":one": 1})
    b.execute(table, 2)
    call = table.calls[0]
    assert call["UpdateExpression"] == "ADD batches_total :one"
    assert call["ExpressionAttributeValues"] == {":one": 1}


def test_merges_set_add_and_remove_into_one_call(table):
    b = UpdateItemBuilder()
    b.add("SET sensor_type = :s", {":s": 1})
    b.add("ADD batches_total :one", {":one": 1})
    b.add("REMOVE watchdog_muted", {})
    b.execute(table, 2)
    assert len(table.calls) == 1
    call = table.calls[0]
    assert call["UpdateExpression"] == \
        "SET sensor_type = :s ADD batches_total :one REMOVE watchdog_muted"
    assert call["ExpressionAttributeValues"] == {":s": 1, ":one": 1}


def test_rejects_unsupported_fragment():
    b = UpdateItemBuilder()
    with pytest.raises(ValueError):
        b.add("DELETE tags :t", {":t": {"x"}})
