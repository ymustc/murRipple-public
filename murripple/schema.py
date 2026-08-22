"""timeline.json 的契约定义。

这是构建时管线与运行时渲染器之间唯一的接口。渲染器不认识 Demucs 或
librosa，只认识这份文档。
"""

from __future__ import annotations

import base64
import binascii

from jsonschema import Draft202012Validator, ValidationError, validate

SCHEMA_VERSION = 1

STEMS = ["vocals", "drums", "bass", "other"]


class SchemaError(Exception):
    """顶层 `stems` 与 `lanes[].stem` 之间的交叉校验失败。

    jsonschema 只能校验单个字段的形状（是不是非空字符串、数组元素是否
    唯一），管不了「这个字符串是否出现在另一个字段声明的清单里」这种
    跨字段约束，所以这一层校验单独放在 validate_timeline() 里，用这个
    专门的异常类型与 jsonschema.ValidationError（字段形状错误）区分开。
    """

# 注意：contentEncoding 在 JSON Schema Draft 2020-12 里只是注解关键字，
# jsonschema 默认不会强制校验它——一个非法 base64 字符串照样能通过 schema
# 校验。真正的强制校验在下面 validate_timeline() 里用 base64.b64decode(
# ..., validate=True) 完成。这里保留 contentEncoding 纯粹是给读 schema
# 的人一个文档提示，不要误以为它有约束力。
_B64 = {"type": "string", "contentEncoding": "base64"}

TIMELINE_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "murRipple timeline",
    "type": "object",
    # Task 1 落地时先不把 "stems" 塞进 required（那时 build_timeline() 还
    # 不产出它，必填会让 26 条既有用例转红）。Task 3 把 build_timeline()
    # 接上 doc["stems"] 产出之后，这里转正——四首真歌与全部测试用例现在
    # 都会带上这个字段。
    "required": [
        "meta", "sections", "beats", "downbeats", "ring", "stems", "lanes", "lyrics",
    ],
    "additionalProperties": False,
    "properties": {
        "meta": {
            "type": "object",
            "required": ["title", "duration", "bpm", "codec", "schemaVersion"],
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "duration": {"type": "number", "exclusiveMinimum": 0},
                "bpm": {"type": "number", "exclusiveMinimum": 0},
                "codec": {"type": "string", "minLength": 1},
                # 这一趟按什么语言听的（Whisper 语言码）。**可选，不在
                # required 里**，两个理由各自独立成立：
                # ① 四首已交付的 timeline 里没有这一格，必填会让它们当场
                #    校验失败——而它们是不许回归的验收基线；
                # ② 更要紧的是语义：没跑过 WhisperX 的那几条路（硬字幕、
                #    `--no-lyrics`、器乐曲）本来就没有答案，必填等于逼着
                #    `build_timeline` 编一个出来。缺席是一句实话。
                "language": {"type": "string", "minLength": 1},
                "schemaVersion": {"const": SCHEMA_VERSION},
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["t", "name", "energy"],
                "additionalProperties": False,
                "properties": {
                    "t": {"type": "number", "minimum": 0},
                    "name": {"type": "string"},
                    "energy": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        "beats": {"type": "array", "items": {"type": "number", "minimum": 0}},
        "downbeats": {"type": "array", "items": {"type": "number", "minimum": 0}},
        "ring": {
            "type": "object",
            "required": ["envelope", "presence"],
            "additionalProperties": False,
            "properties": {"envelope": _B64, "presence": _B64},
        },
        # 本曲实际有哪几条分轨。**从四条写死改成由数据声明**：
        # Demucs 只能反拆出四条，那是反向拆解的约束；自己合成时每个音符
        # 属于哪个声部是已知的，没有理由再压回四条。
        "stems": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
        "lanes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "label", "hue", "stem", "gain", "notes", "envelope"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "hue": {"type": "number", "minimum": 0, "maximum": 360},
                    # 放开 enum，改由 validate_timeline 交叉校验它在顶层
                    # stems 里——净损失约束是不行的。
                    "stem": {"type": "string", "minLength": 1},
                    "gain": {"type": "number", "exclusiveMinimum": 0},
                    "envelope": _B64,
                    "notes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["t", "v", "pitch"],
                            "additionalProperties": False,
                            "properties": {
                                "t": {"type": "number", "minimum": 0},
                                "v": {"type": "number", "minimum": 0, "maximum": 1},
                                "pitch": {"type": ["number", "null"]},
                            },
                        },
                    },
                },
            },
        },
        "lyrics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["t0", "t1", "text", "words"],
                "additionalProperties": False,
                "properties": {
                    "t0": {"type": "number", "minimum": 0},
                    "t1": {"type": "number", "minimum": 0},
                    "text": {"type": "string"},
                    "words": {
                        "type": ["array", "null"],
                        "items": {
                            "type": "object",
                            "required": ["t0", "t1", "c"],
                            "additionalProperties": False,
                            "properties": {
                                "t0": {"type": "number", "minimum": 0},
                                "t1": {"type": "number", "minimum": 0},
                                "c": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

Draft202012Validator.check_schema(TIMELINE_SCHEMA)


def _check_base64(value: str, field: str) -> None:
    """真正解一次 base64，contentEncoding 注解本身不做这件事。"""
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(f"{field} 不是合法的 base64: {exc}") from exc


def validate_timeline(doc: dict) -> None:
    """校验一份 timeline 文档。

    字段形状不合法时抛 jsonschema.ValidationError；顶层 `stems` 与
    `lanes[].stem` 之间的交叉关系不合法（重名、lane 指向未声明的分轨）
    时抛 SchemaError。
    """
    validate(instance=doc, schema=TIMELINE_SCHEMA)

    ring = doc["ring"]
    _check_base64(ring["envelope"], "ring.envelope")
    _check_base64(ring["presence"], "ring.presence")

    for i, lane in enumerate(doc["lanes"]):
        _check_base64(lane["envelope"], f"lanes[{i}].envelope")

    # 注意：重名检查不在这里单独写一遍。TIMELINE_SCHEMA["properties"]["stems"]
    # 已经有 "uniqueItems": True，`validate(instance=doc, schema=TIMELINE_SCHEMA)`
    # 会在走到这里之前就因为重名抛出 jsonschema.ValidationError——这里的代码
    # 永远跑不到重名的 stems 上。task-1-brief.md Step 3 给的实现在这里另外
    # 写了一段 Python 级重名检查，但那段代码是死代码：uniqueItems 已经把
    # 这一层截住了，Python 那段永远不会被触发（实测见 task-1-report.md 的
    # 变异检验部分）。按 CONSTRAINTS.md「测试尺子」的要求，不留一段测不到
    # 的代码，删掉它。
    #
    # "stems" 缺失的兼容兜底（旧文档回退到 enum: STEMS 白名单）也是同一
    # 类死代码，Task 3 已删除——"stems" 现在是 TIMELINE_SCHEMA["required"]
    # 的一员，validate() 会先于此处抛错，"stems" not in doc 永远走不到
    # （删除前的死代码证明与变异检验实测见 task-3-report.md）。
    declared = doc["stems"]
    for lane in doc["lanes"]:
        if lane["stem"] not in declared:
            raise SchemaError(
                f"lane {lane['id']!r} 指向未声明的分轨 {lane['stem']!r}；"
                f"顶层 stems 里只有：{'、'.join(declared)}"
            )
