"""
QQ 真实表情转换与回复消息清洗模块
参考开源项目 dafeiyu-astrbot 的优秀架构设计：
1. 自动将模型输出中的 [表情名]（如 [旺柴]、[吃瓜]、[滑稽] 等）转为 OneBot 11 标准 CQ 码 [CQ:face,id=XXX]
2. 精准区分：动作神态描写（如 [动了动猫耳]）不会被误替换，只有真实存在的 QQ 表情才会替换
3. 清洗过滤 <think> 思考链标签与内部草稿，保证输出干净纯粹
"""
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FACE_MAP_FILE = os.path.join(BASE_DIR, "face_map.json")

FACE_MAP = {}
if os.path.exists(FACE_MAP_FILE):
    try:
        with open(FACE_MAP_FILE, "r", encoding="utf-8") as f:
            FACE_MAP = json.load(f)
    except Exception as e:
        print(f"⚠️ 加载 face_map.json 失败: {e}")

# 正则匹配形如 [表情名]
FACE_PATTERN = re.compile(r"\[([^\[\]]+)\]")
# 匹配思维链 <think>...</think>
THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def clean_markdown_formatting(text: str) -> str:
    """清理 QQ 无法原生解析的 Markdown 标记符号（加粗、斜体、标题等），保持群聊排版干净"""
    if not text:
        return ""
    # 1. 移除 Markdown 加粗 **text** -> text, __text__ -> text
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)

    # 2. 移除行内斜体 *text* 或 _text_（避开乘号与连续星号）
    text = re.sub(r"(?<!\*)\*([^\*\n]+)\*(?!\*)", r"\1", text)

    # 3. 移除行内代码块 `code` -> code
    text = re.sub(r"`([^`\n]+)`", r"\1", text)

    # 4. 移除 Markdown 标题符，例如 ### 标题 -> 标题
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)

    # 5. 移除 Markdown 分隔线 --- 或 ***
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # 6. 整理多余的连续换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_response_text(text: str) -> str:
    """清理多余标签与思维链及 Markdown 标记"""
    if not text:
        return ""
    # 移除 <think> 标签及其内容
    cleaned = THINK_PATTERN.sub("", text)
    # 移除 QQ 无法渲染的 Markdown 格式符号
    cleaned = clean_markdown_formatting(cleaned)
    # 去除首尾空白
    return cleaned.strip()


def convert_faces_to_cq(text: str, max_replace: int = 5) -> str:
    """
    将文本中的 [表情名] 转换为 OneBot 11 的 [CQ:face,id=XXX]
    仅替换在 face_map 中的真实表情，动作神态（如 [动了动耳朵]）保留原样
    """
    if not text or not FACE_MAP:
        return text

    replaced_count = 0

    def replace_match(match):
        nonlocal replaced_count
        name = match.group(1).strip()
        if replaced_count < max_replace and name in FACE_MAP:
            face_id = FACE_MAP[name]
            replaced_count += 1
            return f"[CQ:face,id={face_id}]"
        # 不在表情库中（例如是 [动了动耳朵] 等动作描写），保留原文
        return match.group(0)

    return FACE_PATTERN.sub(replace_match, text)


def format_bot_reply(text: str) -> str:
    """格式化哈基米的最终发送文本"""
    cleaned = clean_response_text(text)
    return convert_faces_to_cq(cleaned)
