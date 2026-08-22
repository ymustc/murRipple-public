import pytest
from jsonschema import ValidationError

from murripple.schema import SCHEMA_VERSION, SchemaError, validate_timeline


def minimal_timeline() -> dict:
    """一份字段齐全的最小合法 timeline。"""
    return {
        "meta": {
            "title": "demo",
            "duration": 10.0,
            "bpm": 120.0,
            "codec": "aac-96k",
            "schemaVersion": SCHEMA_VERSION,
        },
        "sections": [{"t": 0.0, "name": "启", "energy": 0.3}],
        "beats": [0.0, 0.5, 1.0],
        "downbeats": [0.0, 2.0],
        "ring": {"envelope": "AAAA", "presence": "AAAA"},
        "stems": ["vocals", "drums", "bass", "other"],
        "lanes": [
            {
                "id": "kick",
                "label": "底鼓",
                "hue": 28,
                "stem": "drums",
                "gain": 1.0,
                "notes": [{"t": 0.5, "v": 0.8, "pitch": None}],
                "envelope": "AAAA",
            }
        ],
        "lyrics": [{"t0": 1.0, "t1": 3.0, "text": "第一句", "words": None}],
    }


def test_minimal_timeline_is_valid():
    validate_timeline(minimal_timeline())


def test_missing_meta_is_rejected():
    doc = minimal_timeline()
    del doc["meta"]
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_unknown_stem_is_rejected():
    """lanes[].stem 不再是 enum：`"guitar"` 本身形状合法，是「没出现在
    顶层 stems 声明里」这条交叉校验把它挡下来的，所以抛的是 SchemaError
    而不是 jsonschema.ValidationError。"""
    doc = minimal_timeline()
    doc["lanes"][0]["stem"] = "guitar"
    with pytest.raises(SchemaError):
        validate_timeline(doc)


def test_timeline_without_stems_is_rejected():
    """`stems` 从 Task 3 起是必填字段——不再有旧文档兼容的空子可钻。

    Task 1 落地时 `stems` 先设成可选，是因为那时 build_timeline() 还不
    产出它；Task 3 把 build_timeline() 接上产出后，必填才有意义。缺
    `stems` 的文档现在直接在 jsonschema 层被拒（required 校验先于
    validate_timeline() 里任何 Python 代码跑），异常消息里必须点名
    `stems`，方便定位是哪个必填字段缺了。

    match 卡在 `"'stems' is a required property"`（jsonschema 报错的第
    一行）而不是裸的 `"stems"`——`str(ValidationError)` 会把整份
    `TIMELINE_SCHEMA` 的 dump 一并打印出来，`required` 与
    `properties` 两处都含有 "stems" 这个词，裸子串匹配对任何一个必填
    字段缺失（`beats`/`downbeats`/`lyrics`……）都会通过，等于没断言。
    见 task-3-report.md 里这条 match 的对照实验实测输出。"""
    doc = minimal_timeline()
    del doc["stems"]
    with pytest.raises(ValidationError, match=r"'stems' is a required property"):
        validate_timeline(doc)


def test_hue_out_of_range_is_rejected():
    doc = minimal_timeline()
    doc["lanes"][0]["hue"] = 400
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_wrong_schema_version_is_rejected():
    doc = minimal_timeline()
    doc["meta"]["schemaVersion"] = 99
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_ring_envelope_invalid_base64_is_rejected():
    doc = minimal_timeline()
    doc["ring"]["envelope"] = "not-valid-base64!!!"
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_ring_presence_invalid_base64_is_rejected():
    doc = minimal_timeline()
    doc["ring"]["presence"] = "not-valid-base64!!!"
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_lane_envelope_invalid_base64_is_rejected_with_location():
    doc = minimal_timeline()
    lane = doc["lanes"][0]
    # 复制成三条 lane，让第三条（索引 2）的 envelope 非法，
    # 用来断言错误信息定位到了正确的下标，而不是随便报个笼统错误。
    doc["lanes"] = [dict(lane), dict(lane), dict(lane)]
    doc["lanes"][2]["envelope"] = "not-valid-base64!!!"
    with pytest.raises(ValidationError) as exc_info:
        validate_timeline(doc)
    assert "lanes[2].envelope" in str(exc_info.value)


def test_valid_base64_envelope_is_accepted():
    doc = minimal_timeline()
    doc["ring"]["envelope"] = "AAAA"
    doc["ring"]["presence"] = "AAAA"
    doc["lanes"][0]["envelope"] = "AAAA"
    validate_timeline(doc)


def test_ring_envelope_bad_padding_is_rejected():
    """"AB==CD==" 的字符集完全合法（只含 A-Z 与 '='），单靠字符集/长度
    检查测不出问题——不带 validate=True 时 binascii 会悄悄只解出第一段
    （"AB=="），丢弃 "CD==" 且不报错。带 validate=True 才会因为
    "Excess data after padding" 拒绝它。

    没有 validate=True 也能识别的 "not-valid-base64!!!"（含 !，长度也不对）
    测不出这一点——那个字符串本身因为长度不对触发 Incorrect padding，
    不带 validate=True 时同样会抛，无法证明 validate=True 起了作用。

    （原评审给的例子是 "AAAA===="，但实测在本项目 Python 3.11 的
    binascii 实现下，这个输入即便带 validate=True 也会静默解出
    b'\\x00\\x00\\x00'、不抛错——CPython 3.11+ 的 strict_mode 只在「填充
    之后又出现数据」时才报错，单纯"完整分组后跟多余的填充符"不算违规。
    换成 "AB==CD==" 才是本仓库这个 Python 版本下真正有判别力的输入。）
    """
    doc = minimal_timeline()
    doc["ring"]["envelope"] = "AB==CD=="
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def test_additional_property_is_rejected():
    doc = minimal_timeline()
    doc["meta"]["unexpectedField"] = "surprise"
    with pytest.raises(ValidationError):
        validate_timeline(doc)


def _doc_with(stems, lane_stem):
    """一份最小的合法 timeline，只把 stems 与 lane.stem 换成参数给的值。

    注意：task-1-brief.md 里这个 helper 写的是
    ``"ring": {"env": ..., "envSmooth": ..., "presence": ...}``，
    与现有 schema（要求 "envelope" + "presence"，additionalProperties:
    False）不符——那份 ring 形状会先因为缺 "envelope"、多出 "env"/
    "envSmooth" 被拒，测不到 stems。这里改成与现实一致的 ring 字段，
    偏差已按 CONSTRAINTS.md「计划稿也会错」记入报告。
    """
    return {
        "meta": {"title": "t", "duration": 10.0, "bpm": 120.0,
                 "codec": "aac-64k", "schemaVersion": 1},
        "sections": [{"t": 0.0, "name": "", "energy": 0.5}],
        "beats": [0.0, 0.5],
        "downbeats": [0.0],
        "ring": {"envelope": "AAA=", "presence": "AAA="},
        "stems": stems,
        "lanes": [{"id": "x", "label": "轨", "hue": 200.0, "stem": lane_stem,
                   "gain": 1.0, "notes": [], "envelope": "AAA="}],
        "lyrics": [],
    }


def test_nine_stems_are_accepted():
    """合成曲要能声明九条分轨——这正是本次改动的目的。"""
    nine = ["vocals", "bass", "pad", "pluck", "arp", "bell", "kick", "snare", "hat"]
    validate_timeline(_doc_with(nine, "arp"))


def test_four_stems_still_accepted():
    """真歌那一路一行不变。"""
    validate_timeline(_doc_with(["vocals", "drums", "bass", "other"], "drums"))


def test_lane_pointing_at_an_undeclared_stem_is_rejected_by_name():
    """放开 enum 之后必须补上这条，否则约束是净损失的——
    lane 指向一条没声明的分轨，打包时会静默少一段音频。"""
    with pytest.raises(SchemaError, match="ghost"):
        validate_timeline(_doc_with(["vocals", "bass"], "ghost"))


def test_duplicate_stem_names_are_rejected():
    """重名会让 pack 覆盖掉前一条的音频。

    这条测试实际验的是 schema 层的 `uniqueItems: True`，不是交叉校验层
    的 SchemaError——`validate(instance=doc, schema=TIMELINE_SCHEMA)` 先
    跑，重名的 stems 数组在到达 validate_timeline() 里任何 Python 代码
    之前就已经被拒绝，抛的是 jsonschema.ValidationError。task-1-brief.md
    写的是 `pytest.raises(SchemaError, match="vocals")`，实测这个类型不对
    （实际抛出 ValidationError），已按 CONSTRAINTS.md「计划稿也会错」改回
    与现实一致的断言；match="vocals" 仍然成立，因为 jsonschema 的报错信息
    本身就带着重复的值。"""
    with pytest.raises(ValidationError, match="vocals"):
        validate_timeline(_doc_with(["vocals", "vocals"], "vocals"))


def test_empty_stems_is_rejected():
    """空 stems 数组被 schema 的 minItems: 1 挡住，属于字段形状错误，
    抛的是 jsonschema.ValidationError——这一层比交叉校验（SchemaError）
    先跑，根本轮不到「lane 指向未声明分轨」那条检查。task-1-brief.md
    写的是 `pytest.raises(SchemaError)`，与实际抛出类型不符，按
    CONSTRAINTS.md「计划稿也会错」改回与现实一致的断言。"""
    with pytest.raises(ValidationError):
        validate_timeline(_doc_with([], "vocals"))
