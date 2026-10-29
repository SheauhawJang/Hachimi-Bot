"""
群聊与私聊独立会话管理器 (Session Manager)
1. 每一个 QQ 群 (group_xxx) 和私聊 (private_xxx) 1:1 绑定一个持久的 Gemini / Antigravity 原生会话
2. 利用大模型原生上下文机制自动维护历史记忆，无需手动切片历史
3. 记忆自动持久化到 data/sessions.json，重启机器人不丢失
4. 支持独立重置单个群聊的上下文记忆 (/reset 或 /重置)
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self._load()

    def _load(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception as e:
                print(f"⚠️ 加载 sessions.json 失败: {e}")
                self.sessions = {}

    def _save(self):
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存 sessions.json 失败: {e}")

    def get_conv_id(self, session_id: str) -> str | None:
        """获取指定群或私聊绑定的会话 ID"""
        session_info = self.sessions.get(session_id)
        if isinstance(session_info, dict):
            return session_info.get("conv_id")
        return None

    def set_conv_id(self, session_id: str, conv_id: str):
        """记录群或私聊当前活跃的会话 ID 并持久化"""
        self.sessions[session_id] = {
            "conv_id": conv_id,
            "updated_at": int(time.time()),
        }
        self._save()

    def reset_session(self, session_id: str):
        """重置指定群的会话，下次说话将自动开启全新的会话上下文"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._save()
