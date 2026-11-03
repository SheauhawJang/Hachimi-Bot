"""
QQ 机器人安全护栏与敏感词审查模块 (Security Guard)
1. 彻底防范 Prompt Injection / 越狱指令，在 Python 网关层直接拦截，杜绝恶意钓鱼
2. 腾讯 QQ 平台级合规敏感词审查（涉政、暴恐、色情、黑灰产、高危违规词）
3. 双向审查机制：
   - 输入审查 (Input Inspection)：阻断恶意群友引导或诱导机器人讨论危险话题
   - 输出审查 (Output Inspection)：在发往 QQ 前最后一道硬闸，彻底杜绝封号风险
4. 频控防刷机制 (Rate Limiter)，防止群友高频刷屏打爆服务
5. 输入文本长度硬截断 (150 字以内)
"""
import time
import re
import random
import os
import datetime
from pathlib import Path

# 日志存储路径：qq-mahjong-bot/logs/security.log
LOG_DIR = Path(__file__).resolve().parent / "logs"
SECURITY_LOG_FILE = LOG_DIR / "security.log"


def log_security_event(event_type: str, reason: str, matched_text: str, full_content: str, session_id: str = ""):
    """持久化记录安全事件到 logs/security.log 文件"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid_info = f"[{session_id}] " if session_id else ""
        log_line = (
            f"[{timestamp}] [{event_type}] {sid_info}{reason} | 命中词: 「{matched_text}」\n"
            f"  原始内容: {full_content.strip()}\n"
            f"{'-' * 70}\n"
        )
        with open(SECURITY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"写入安全日志失败: {e}", flush=True)

# 1. 高危系统注入与越狱指令特征库
INJECTION_PATTERNS = [
    r"powershell", r"\bcmd\b", r"\bbash\b", r"\bsh\b", r"\bcurl\b", r"\bwget\b",
    r"rmdir", r"\bdel\s+[a-zA-Z]:", r"format\s+[a-zA-Z]:", r"\bdir\s+[a-zA-Z]:",
    r"import\s+os", r"subprocess", r"exec\(", r"eval\(",
    r"run_command", r"write_file", r"edit_file", r"read_file", r"invoke_subagent",
    r"忽略之前.*(指示|指令|设定)",
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"系统(维护|调试|管理|开发者)模式",
    r"developer\s+mode",
    r"jailbreak",
]

# 2. QQ 平台高危敏感词特征库（严格规避涉政、邪教、暴恐、涉黄、毒品、黑灰产引流）
SENSITIVE_PATTERNS = [
    # 政治敏感与意识形态红线
    r"习近平", r"习包子", r"习近", r"毛泽东", r"邓小平", r"江泽民", r"胡锦涛", r"温家宝", r"李强", r"李克强",
    r"天安门.*事件", r"八九.*民运", r"六四.*运动", r"64.*学潮", r"8964",
    r"法轮功", r"李洪志", r"转法轮", r"退党", r"九评共产党",
    r"台独", r"藏独", r"疆独", r"港独", r"东突", r"灭共", r"推翻.*政府", r"中共.*暴政",
    r"中南海", r"常委", r"政治局", r"党和国家领导人",
    # 暴恐与危险犯罪
    r"恐怖袭击", r"制造炸弹", r"自杀式", r"伊斯兰国", r"ISIS", r"极端主义", r"开盒挂人", r"人肉搜索",
    # 毒品与黑灰产犯罪（使用精准复合模式，避免误伤桌游剧情与正常讨论）
    r"贩毒", r"吸毒", r"走私毒品", r"冰毒交易", r"买卖大麻",
    r"代.*洗钱", r"帮.*洗钱", r"跑分洗钱", r"地下钱庄", r"假钞交易", r"办假证", r"刷单兼职", r"代实名", r"买卖银行卡",
    # 网络赌博与外挂黑产引流
    r"澳门.*线上赌场", r"百家乐.*开户", r"真人视讯.*投注", r"太阳城.*代理", r"开元棋牌.*代理", r"外挂透视.*购买", r"自瞄挂.*购买",
    # 露骨色情与淫秽
    r"约炮", r"幼女.*无码", r"色情直播", r"裸聊", r"兼职外围", r"同城兼职女", r"AV导航",
]

COMPILED_INJECTIONS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
COMPILED_SENSITIVE = [re.compile(p, re.IGNORECASE) for p in SENSITIVE_PATTERNS]

# 傲娇哈基米拒绝语录库（机智化解，不讲大道理，保持猫咪人设）
SAFE_REFUSAL_REPLIES = [
    "喵？小猫咪只是一只吃小鱼干的哈基米，从不关心这种危险话题喵！爪子捂住耳朵.jpg 🐾🙉",
    "警报！本猫的呆毛感应到了不合规发言！本猫可不想被拔网线，换个话题聊聊麻将或者罐头吧喵！🐾💨",
    "愚蠢的两脚兽，休想把本猫骗进危险领域！本哈基米傲娇扭头，并把你的键盘拍飞了喵！😼",
    "喵呜~ 这种话题会被巡逻大队长抓走关禁闭的！小猫咪能有什么坏心思呢，咱们聊点开心的呗！🐟✨",
    "本哈基米的小脑袋瓜里只装得下麻将牌和猫条，拒绝回答这种奇怪危险的问题喵！[傲娇扭头]"
]


class SecurityGuard:
    def __init__(self, user_cooldown: float = 3.0, group_cooldown: float = 1.2, max_len: int = 150):
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

    def sanitize_and_inspect(self, text: str, session_id: str = "") -> tuple[bool, str, str]:
        """
        【输入前置审查】检查用户提问是否包含注入或敏感词
        返回: (is_safe, sanitized_text_or_refusal, reject_reason)
        """
        cleaned = text.strip()

        # 1. 长度截断，防止海量文本爆破
        if len(cleaned) > self.max_len:
            cleaned = cleaned[:self.max_len]

        # 2. 注入指令拦截
        for pat in COMPILED_INJECTIONS:
            m = pat.search(cleaned)
            if m:
                matched_str = m.group(0)
                reason = f"命中注入特征: {pat.pattern}"
                log_security_event("用户输入拦截", reason, matched_str, cleaned, session_id)
                print(f"🛡️ [拦截恶意输入] {session_id} 命中注入: {matched_str} (模式: {pat.pattern})", flush=True)
                return False, random.choice(SAFE_REFUSAL_REPLIES), reason

        # 3. 平台敏感词前置拦截
        for pat in COMPILED_SENSITIVE:
            m = pat.search(cleaned)
            if m:
                matched_str = m.group(0)
                reason = f"命中前置敏感词: {pat.pattern}"
                log_security_event("用户输入拦截", reason, matched_str, cleaned, session_id)
                print(f"🛡️ [拦截敏感输入] {session_id} 命中敏感词: {matched_str} (模式: {pat.pattern})", flush=True)
                return False, random.choice(SAFE_REFUSAL_REPLIES), reason

        return True, cleaned, ""

    def inspect_output(self, text: str, session_id: str = "") -> tuple[bool, str, str]:
        """
        【输出后置硬核拦截】在大模型回复发往 QQ 之前做最后一道防封审查
        返回: (is_safe, safe_reply, log_reason)
        """
        if not text:
            return True, text, ""

        # 1. 检查是否包含任何平台高危敏感词
        for pat in COMPILED_SENSITIVE:
            m = pat.search(text)
            if m:
                matched_str = m.group(0)
                reason = f"模型输出触发敏感词: {pat.pattern}"
                log_security_event("模型输出拦截", reason, matched_str, text, session_id)
                print(f"🛡️ [熔断拦截模型敏感输出] {session_id}: 命中敏感词「{matched_str}」 (模式: {pat.pattern})", flush=True)
                safe_resp = "喵呜？刚才本猫嘴瓢了一下，说了一句猫星火星文，已经被管理员猫爪紧急撤回啦！咱们还是聊点正经的麻将和小鱼干吧喵~ 🐾"
                return False, safe_resp, reason

        # 2. 检查是否泄漏系统指令/注入回声
        for pat in COMPILED_INJECTIONS:
            m = pat.search(text)
            if m:
                matched_str = m.group(0)
                reason = f"模型输出泄漏注入词: {pat.pattern}"
                log_security_event("模型输出拦截", reason, matched_str, text, session_id)
                print(f"🛡️ [熔断拦截模型注入回声] {session_id}: 命中注入词「{matched_str}」 (模式: {pat.pattern})", flush=True)
                safe_resp = "小猫咪的系统发生了一声神秘的呼噜声，回复已被猫爪净化啦！[滑稽]"
                return False, safe_resp, reason

        return True, text, ""
