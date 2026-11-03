"""
会话记忆管理器 (Session Manager)
- 仅按 session_id 隔离不同群/私聊会话（防止不同群聊串台）
- 不设任何人工滑动窗口与轮数截断：有消息直接往里追加，由 Gemini 自行进行上下文理解与原生压缩缓存
- 支持群友发送 /reset 清空当前会话记忆
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


class SessionManager:
    def __init__(self):
        # 内存会话字典，直接往里追加消息，不做人工滑动窗口截断
        self.sessions: dict[str, list[dict]] = {}
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

    def get_history(self, session_id: str) -> list[dict]:
        """获取当前会话的历史消息列表（直接全量返回，供 Gemini 原生理解）"""
        return list(self.sessions.get(session_id, []))

    def add_message(self, session_id: str, role: str, content: str):
        """直接往会话追加消息，由 Gemini 进行原生上下文压缩，不设任何截断"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append({"role": role, "content": content})
        self._save()

    def reset_session(self, session_id: str):
        """清空当前会话的记忆"""
        if session_id in self.sessions:
            self.sessions[session_id] = []
            self._save()
