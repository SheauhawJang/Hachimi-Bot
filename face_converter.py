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


def convert_mentions_to_cq(
    text: str,
    mention_map: dict[str, str] | None = None,
    self_names: list[str] | None = None,
) -> str:
    """
    将模型文本输出中的 @群友昵称、@群名片 或 @纯数字QQ 转换为 OneBot 11 标准 [CQ:at,qq=XXX]
    1. 自动转换 @12345678 为 [CQ:at,qq=12345678] 
    2. 依据传入的 mention_map 字典按名称长度降序优先替换最长名称
    3. 严密避开邮箱地址（如 abc@qq.com）与机器人自身昵称
    4. 保持原有已存在的 [CQ:at,qq=XXX] 完好
    """
    if not text:
        return text

    # 1. 转换纯数字 QQ 号（5-12位数字）
    # 避开邮箱前缀 (abc@) 和变量名，纯数字后不能紧随数字
    text = re.sub(r"(?<![a-zA-Z0-9_.])@(\d{5,12})(?![0-9])", r"[CQ:at,qq=\1] ", text)

    if not mention_map:
        return text

    ignored_names = set(self_names or ["哈基米", "机器人", "bot", "Bot", "BOT"])

    # 2. 按群友名称长度降序排列，避免“张三”截断“张三丰”
    sorted_names = sorted(mention_map.keys(), key=lambda x: len(x), reverse=True)

    for name in sorted_names:
        clean_name = str(name).strip()
        if not clean_name or clean_name in ignored_names or len(clean_name) < 2:
            continue
        qq = str(mention_map[name]).strip()
        if not qq:
            continue

        # 匹配 @name，前面不得是英数字及邮箱连接符
        pattern = re.compile(rf"(?<![a-zA-Z0-9_.])@{re.escape(clean_name)}", re.IGNORECASE)
        text = pattern.sub(f"[CQ:at,qq={qq}] ", text)

    return text


def format_bot_reply(
    text: str,
    mention_map: dict[str, str] | None = None,
    self_names: list[str] | None = None,
) -> str:
    """格式化哈基米的最终发送文本（表情转换、Markdown 清洗、@提及转 CQ 码）"""
    cleaned = clean_response_text(text)
    with_faces = convert_faces_to_cq(cleaned)
    return convert_mentions_to_cq(with_faces, mention_map=mention_map, self_names=self_names)
