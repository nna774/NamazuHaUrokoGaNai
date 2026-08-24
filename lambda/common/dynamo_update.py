"""複数の関心事による同一DynamoDB項目への書き込みを、1回のupdate_itemへ集約する。

`namazu-devices`はingestが毎バッチ触る項目で、`watchdog_mute`（監視mute解除）・
`device_meta`（センサ種別記録）のように無関係な関心事がそれぞれ書き込みたがる。
別々にupdate_itemを呼ぶとDynamoDBは呼び出し回数分のWCUを消費するので、まとめて
1回にしたい。かといって「Aの属性とBの属性を両方書く関数」をその場しのぎで作ると、
関心事の組み合わせが増えるたびに専用関数が要る（過去に`device_meta.
record_sensor_type_and_clear_mute()`でこれをやり、A×Bの知識がdevice_meta.py側に
漏れ出した）。

代わりに、各モジュールは「実行はしない、自分の関心事のSET/REMOVE式の断片だけを
返す」関数を公開する（例: `watchdog_mute.clear_mute_fragment()`）。呼び出し側
（ingest handler）がこのBuilderに断片を集めて、最後に1回だけexecuteする。
モジュールは自分の属性名だけを知っていればよく、組み合わせの数だけ関数を
書く必要が無い。
"""

from __future__ import annotations

Fragment = tuple[str, dict]


class UpdateItemBuilder:
    """SET/ADD/REMOVE式の断片を集約し、1回のupdate_itemに束ねる。"""

    def __init__(self) -> None:
        self._set: list[str] = []
        self._add: list[str] = []
        self._remove: list[str] = []
        self._values: dict = {}

    def add(self, expr: str, values: dict) -> None:
        """`("SET a = :x", {":x": 1})` ・ `("ADD b :y", {":y": 1})` ・
        `("REMOVE c", {})` 形式の断片を1つ追加する。"""
        if expr.startswith("SET "):
            self._set.append(expr[len("SET "):])
        elif expr.startswith("ADD "):
            self._add.append(expr[len("ADD "):])
        elif expr.startswith("REMOVE "):
            self._remove.append(expr[len("REMOVE "):])
        else:
            raise ValueError(f"unsupported fragment: {expr!r}")
        self._values.update(values)

    def execute(self, table, device_id: int) -> None:
        """集めた断片を1回のupdate_itemにまとめて書き込む。断片が無ければ何もしない。"""
        clauses = []
        if self._set:
            clauses.append("SET " + ", ".join(self._set))
        if self._add:
            clauses.append("ADD " + ", ".join(self._add))
        if self._remove:
            clauses.append("REMOVE " + ", ".join(self._remove))
        if not clauses:
            return
        kwargs: dict = {"Key": {"device_id": device_id}, "UpdateExpression": " ".join(clauses)}
        if self._values:
            kwargs["ExpressionAttributeValues"] = self._values
        table.update_item(**kwargs)
