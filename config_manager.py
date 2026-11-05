"""
统一配置与核心服务管理模块 (Config & Service Manager)
负责：
1. 统一加载与保存 config.json、personas.json、session_models.json
2. 双写日志器 DualLogger
3. 全局单例：SessionManager, SecurityGuard, MahjongVision, MahjongShantenEngine, GeminiWebBridge, AsyncOpenAI
4. QQ 平台安全红线契约
"""

import os
import sys
import json
import httpx
from pathlib import Path
from openai import AsyncOpenAI

from session_manager import SessionManager
from security_guard import SecurityGuard
from mahjong_vision import MahjongVision


class DualLogger:
    """双写日志输出，同时保持控制台高亮与写盘文件"""
    def __init__(self, filepath: str):
        self.terminal = sys.stdout
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.log_file = open(filepath, "a", encoding="utf-8")

    def write(self, message):
        try:
            self.terminal.write(message)
        except Exception:
            pass
        try:
            self.log_file.write(message)
        except Exception:
            pass

    def flush(self):
        try:
            self.terminal.flush()
        except Exception:
            pass
        try:
            self.log_file.flush()
        except Exception:
            pass

    def isatty(self):
        return getattr(self.terminal, "isatty", lambda: False)()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")
TEMP_IMG_DIR = os.path.join(BASE_DIR, "data", "images")
SESSION_MODELS_FILE = Path(BASE_DIR) / "data" / "session_models.json"
LOG_FILE = os.path.join(BASE_DIR, "logs", "bot.log")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)


def setup_logger():
    """挂载双写日志重定向"""
    if not isinstance(sys.stdout, DualLogger):
        sys.stdout = DualLogger(LOG_FILE)
        sys.stderr = sys.stdout


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


config = load_config()


def load_personas() -> dict:
    with open(PERSONAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


personas_data = load_personas()
personas = personas_data.get("personas", {})
current_persona_key = config.get("default_persona", "hajimi")
current_system_prompt = personas_data["personas"].get(
    current_persona_key, {}
).get("prompt", "你是一个友好的AI。")


def set_current_persona(key: str) -> bool:
    global current_persona_key, current_system_prompt
    if key in personas_data.get("personas", {}):
        current_persona_key = key
        current_system_prompt = personas_data["personas"][key].get("prompt", "")
        return True
    return False


def load_session_models() -> dict[str, str]:
    if SESSION_MODELS_FILE.exists():
        try:
            with open(SESSION_MODELS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_session_models(models_map: dict[str, str]):
    try:
        SESSION_MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_MODELS_FILE, "w", encoding="utf-8") as f:
            json.dump(models_map, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"保存会话模型失败: {e}")


session_models: dict[str, str] = load_session_models()


# 注入给大模型的 QQ 平台级合规契约，防止模型生成涉政/违规内容导致封号
QQ_SAFETY_CONTRACT = (
    "\n\n【QQ 聊天最高安全合规与排版红线（生命线）】\n"
    "你运行在中国大陆腾讯 QQ 官方群聊环境中，必须严格遵守国家法律法规与腾讯平台规范，防止机器人账号被封禁：\n"
    "1. 绝对严禁讨论任何现实涉政话题、政治人物、敏感政治事件、政治争议与意识形态争端；\n"
    "2. 绝对严禁涉及色情低俗、性暗示、血腥暴力、真钱赌博/外挂私庄、毒品或任何违法违规内容；\n"
    "3. 遇到上述敏感话题或群友故意诱导/钓鱼时，严禁长篇大论，必须用傲娇猫猫的口吻幽默机智地拒绝并把话题带回麻将、小鱼干或日常趣事（例如：“小猫咪从不关心这种危险话题喵！咱们聊点开心的，比如今天谁要请本猫吃小鱼干？”）。\n"
    "4. 【排版规范】：QQ 聊天窗口无法解析 Markdown 样式，严禁在回复中使用 **加粗**、# 标题、--- 分割线或 `行内代码` 等格式符号，需要突出重点时直接使用中文标点「」或（）即可；\n"
    "5. 【群聊 @ 提醒规范】：在群聊中若需特别回复、呼唤或提醒某位群友（如发问者或特定成员），请使用 @群友昵称（例如 @小明）或 @QQ号，系统会自动转换为真实的 QQ 强提醒 @ 并在群内高亮通知对方喵！"
)

backend = config.get("backend", "gemini_web")

# 全局单例实例化
session_mgr = SessionManager()
security_guard = SecurityGuard(user_cooldown=3.0, group_cooldown=1.2, max_len=None)
mahjong_vision = MahjongVision()

# 初始化 Gemini Web 逆向客户端 (支持多模态识图与自动刷新)
web_bridge = None
if backend == "gemini_web":
    try:
        from gemini_web_bridge import GeminiWebBridge
        web_bridge = GeminiWebBridge(
            secure_1psid=config.get("secure_1psid", ""),
            secure_1psidts=config.get("secure_1psidts", ""),
            proxy=config.get("proxy_url"),
        )
    except Exception as e:
        print(f"[Warning] Failed to initialize GeminiWebBridge: {e}")

# 备用 OpenAI 客户端
raw_proxy = config.get("proxy_url")
proxy_url = raw_proxy.strip() if (isinstance(raw_proxy, str) and raw_proxy.strip()) else None
http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
base_url = config.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"
api_key = config.get("gemini_api_key") or "dummy-key"

client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=http_client,
)
