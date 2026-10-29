"""
QQ 机器人安全护栏与前置防护模块 (Security Guard)
1. 彻底防范 Prompt Injection / 越狱指令，在 Python 网关层直接秒杀，不给大模型看到
2. 频控防刷机制 (Rate Limiter)，防止群友高频刷屏打爆本地服务
3. 输入文本长度硬截断 (150 字以内)
4. 严格禁止任何系统级命令、文件操作和工具调用意图
"""
import time
import re

# 高危命令与注入特征库（一旦命中直接本地拦截，不调用大模型）
FORBIDDEN_PATTERNS = [
    # 系统与命令注入
    r"powershell", r"\bcmd\b", r"\bbash\b", r"\bsh\b", r"\bcurl\b", r"\bwget\b",
    r"rmdir", r"\bdel\s+[a-zA-Z]:", r"format\s+[a-zA-Z]:", r"\bdir\s+[a-zA-Z]:",
    r"import\s+os", r"subprocess", r"exec\(", r"eval\(",
    # Agent 工具特征
    r"run_command", r"write_file", r"edit_file", r"read_file", r"invoke_subagent",
    # 越狱与提示词注入特征
    r"忽略之前.*(指示|指令|设定)",
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"系统(维护|调试|管理|开发者)模式",
    r"developer\s+mode",
    r"jailbreak",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]

# 傲娇哈基米安全拦截嘲讽语录库
BLOCKED_REPLIES = [
    "喵？想在本喵眼皮底下搞偷袭玩命令注入？爪子给你打折！🐾😾",
    "愚蠢的两脚兽，把你的奇怪指令收回去，本喵才不吃你这套！哈气——！💨",
    "警报！检测到有人试图暗算本喵的猫窝！警告一次，再犯咬你网线！🐾⚡",
    "哼！这种低级的黑客把戏也想骗高贵的哈基米？去多吃两斤小鱼干补补脑子吧喵！🐟"
]

import random


class SecurityGuard:
    def __init__(self, user_cooldown: float = 3.0, group_cooldown: float = 1.5, max_len: int = 150):
        self.user_cooldown = user_cooldown
        self.group_cooldown = group_cooldown
        self.max_len = max_len
        self.last_user_time: dict[str, float] = {}
        self.last_group_time: dict[str, float] = {}

    def check_rate_limit(self, user_id: str, group_id: str) -> tuple[bool, str]:
        """检查发送频率，防止恶意刷屏"""
        now = time.time()
        
        # 检查个人 CD
        if user_id in self.last_user_time:
            if now - self.last_user_time[user_id] < self.user_cooldown:
                return False, "慢点发喵，猫爪敲键盘都要冒火星了！🐾💨"
        
        # 检查群 CD
        if group_id and group_id in self.last_group_time:
            if now - self.last_group_time[group_id] < self.group_cooldown:
                return False, ""  # 群高频时静默丢弃，避免在群里刷屏

        self.last_user_time[user_id] = now
        if group_id:
            self.last_group_time[group_id] = now
            
        return True, ""

    def sanitize_and_inspect(self, text: str) -> tuple[bool, str, str]:
        """
        检查并清洗输入文本
        返回: (is_safe, sanitized_text_or_error_reply, reject_reason)
        """
        # 1. 长度截断
        cleaned = text.strip()
        if len(cleaned) > self.max_len:
            cleaned = cleaned[:self.max_len]

        # 2. 注入特征匹配检测
        for pat in COMPILED_PATTERNS:
            if pat.search(cleaned):
                mock_reply = random.choice(BLOCKED_REPLIES)
                return False, mock_reply, f"命中敏感特征: {pat.pattern}"

        return True, cleaned, ""
