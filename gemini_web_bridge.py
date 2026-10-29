"""
Gemini Web 网页版逆向桥接器 (Gemini Web Bridge)
1. 100% 复用 Google One AI Premium (Gemini Advanced) 会员，零额外按量计费，无账单失控风险！
2. 纯 Web 对话协议，模型完全运行在 Google 云端，本地零 Shell/文件权限，绝对安全！
3. 完美支持多模态识图：直接上传雀魂/天凤/实物麻将截图并由 Gemini 视觉分析！
4. 内置后台自动心跳与 Cookie 定期刷新机制 (auto_refresh)，自动维持会话活性，告别频繁手动更新！
"""
import asyncio
import os
import sys

# 兼容 Python 3.10 StrEnum
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
    import enum
    enum.StrEnum = StrEnum

from gemini_webapi import GeminiClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_IMG_DIR = os.path.join(BASE_DIR, "data", "images")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)


class GeminiWebBridge:
    def __init__(self, secure_1psid: str, secure_1psidts: str, proxy: str | None = None):
        self.secure_1psid = secure_1psid
        self.secure_1psidts = secure_1psidts
        self.proxy = proxy
        self.client: GeminiClient | None = None
        self.sessions: dict[str, any] = {}  # session_id -> chat_session

    async def init_client(self):
        """初始化 Gemini 网页客户端并开启后台自动刷新"""
        if self.client and self.client._running:
            return

        print("🌐 正在连接 Gemini Web 网页端 (Gemini Advanced)...")
        self.client = GeminiClient(
            secure_1psid=self.secure_1psid,
            secure_1psidts=self.secure_1psidts,
            proxy=self.proxy,
        )

        # 核心：auto_refresh=True 每 10 分钟在后台自动向 Google 发起心跳刷新，维持 Cookie 不过期！
        await self.client.init(
            auto_refresh=True,
            refresh_interval=600,
            timeout=120,
        )
        print("✅ Gemini Web 客户端初始化成功！后台 Cookie 定期自动刷新任务已启动。")

    def get_or_create_chat(self, session_id: str):
        """为每一个 QQ 群创建专属的独立 Chat 会话对象"""
        if session_id not in self.sessions:
            self.sessions[session_id] = self.client.start_chat()
        return self.sessions[session_id]

    def reset_chat(self, session_id: str):
        """清空指定群的会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]

    async def send_message(
        self,
        session_id: str,
        prompt: str,
        image_paths: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """
        向群会话发送消息（支持附带麻将截图）
        """
        if not self.client or not self.client._running:
            await self.init_client()

        chat = self.get_or_create_chat(session_id)

        # 如果是该群第 1 轮发言，前置带上哈基米人设
        is_first_turn = len(chat.metadata.history) == 0 if hasattr(chat, "metadata") else True
        if is_first_turn and system_prompt:
            full_prompt = f"【系统人设】\n{system_prompt}\n\n【群友消息】\n{prompt}"
        else:
            full_prompt = prompt

        try:
            if image_paths and len(image_paths) > 0:
                # 附带多模态麻将截图
                response = await chat.send_message(
                    full_prompt,
                    files=image_paths,
                )
            else:
                response = await chat.send_message(full_prompt)

            return response.text.strip()
        except Exception as e:
            err = str(e)
            print(f"❌ Gemini Web 对话异常: {err}")
            # 如果报认证失败，提示刷新
            if "cookie" in err.lower() or "400" in err or "401" in err:
                return "【哈基米掉线喵】：Gemini Web Cookie 可能已失效，请重新提取最新 Cookie 喵！"
            return f"【哈基米打了个嗝】：{err}"
