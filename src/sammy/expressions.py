"""Sammy 表情目录 —— 35 个表情的编号/名称/emoji，以及情绪→表情的映射。

资产来源：旧项目 assets/expressions/*.bmp（128×64 单色 OLED 取模图）
"""

from pathlib import Path

from .paths import assets_dir

# 表情编号 → 中文名
EXPR_NAMES: dict[int, str] = {
    1: "睡眠",
    2: "普通",
    3: "微笑",
    4: "开心",
    5: "疑惑",
    6: "伤心",
    7: "惊喜",
    8: "眨眼",
    9: "吐舌",
    10: "生气",
    11: "无语",
    12: "可怜",
    13: "得意",
    14: "亲亲",
    15: "惊吓",
    16: "思考",
    17: "生病",
    18: "酷",
    19: "流汗",
    20: "星星眼",
    21: "爱心",
    22: "尴尬",
    23: "满足",
    24: "燃",
    25: "邪恶",
    26: "无聊",
    27: "犯困",
    28: "鄙视",
    29: "偷笑",
    30: "震惊",
    31: "委屈",
    32: "期待",
    33: "不悦",
    34: "卖萌",
    35: "耍酷",
}

EXPR_EMOJI: dict[int, str] = {
    1: "😴",
    2: "😐",
    3: "🙂",
    4: "😄",
    5: "🤔",
    6: "😢",
    7: "😲",
    8: "😉",
    9: "😛",
    10: "😠",
    11: "😑",
    12: "🥺",
    13: "😏",
    14: "😘",
    15: "😱",
    16: "🤨",
    17: "🤒",
    18: "😎",
    19: "😅",
    20: "🤩",
    21: "🥰",
    22: "😅",
    23: "😊",
    24: "🔥",
    25: "😈",
    26: "😑",
    27: "🥱",
    28: "😏",
    29: "🤭",
    30: "😱",
    31: "🥺",
    32: "🥰",
    33: "😒",
    34: "🥹",
    35: "😎",
}

# 情绪语义 → 表情编号。大模型只能从这个集合里挑情绪，保证映射收敛。
EMOTIONS: dict[str, int] = {
    "normal": 2,  # 平静
    "smile": 3,  # 微笑
    "happy": 4,  # 开心
    "curious": 5,  # 疑惑/好奇
    "sad": 6,  # 难过
    "surprised": 7,  # 惊喜
    "wink": 8,  # 眨眼/俏皮
    "playful": 9,  # 吐舌
    "angry": 10,  # 生气
    "speechless": 11,  # 无语
    "wronged": 31,  # 委屈
    "proud": 13,  # 得意
    "thinking": 16,  # 思考
    "cool": 18,  # 酷
    "awkward": 22,  # 尴尬
    "content": 23,  # 满足
    "love": 21,  # 爱心
    "bored": 26,  # 无聊
    "sleepy": 27,  # 犯困
    "giggle": 29,  # 偷笑
    "shocked": 30,  # 震惊
    "expect": 32,  # 期待
    "cute": 34,  # 卖萌
    "sleep": 1,  # 睡着
}

EMOTION_KEYS = tuple(EMOTIONS.keys())

# 表情素材：源码运行看仓库 assets/，打包后看包内资源（见 paths.py）
ASSETS_DIR = assets_dir()


def expr_path(index: int) -> Path:
    return ASSETS_DIR / f"{index}.bmp"


def name_of(index: int) -> str:
    return EXPR_NAMES.get(index, "未知")


def emoji_of(index: int) -> str:
    return EXPR_EMOJI.get(index, "❓")


def expression_for(emotion: str) -> int:
    """情绪 key → 表情编号，未知情绪回落到「普通」。"""
    return EMOTIONS.get((emotion or "").strip().lower(), 2)
