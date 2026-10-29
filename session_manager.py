"""
群聊与私聊独立会话记忆管理器 (Session Manager)
1. 保证每个群 (group_xxx) 和每个私聊 (private_xxx) 拥有完全独立的记忆隔离空间，绝不串台
2. 自动持久化保存到本地 JSON 文件，机器人重启后记忆不丢失
3. 动态滑动窗口机制：保留最近 N 轮对话，自动清理陈旧记忆，防止上下文臃肿
4. 支持独立重置单个群聊记忆 (/reset)
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


class SessionManager:
    def __init__(self, max_history_turns: int = 10):
        self.max_history_turns = max_history_turns
        self.sessions = {}
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

    def get_history(self, session_id: str) -> list:
        """获取指定群或私聊的对话历史副本"""
        return self.sessions.get(session_id, [])

    def add_interaction(self, session_id: str, user_text: str, bot_reply: str):
        """向指定会话追加一轮问答，并自动截断超限记忆与持久化"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append({"role": "user", "content": user_text})
        self.sessions[session_id].append({"role": "assistant", "content": bot_reply})

        # 滑动窗口截断：保留最近 max_history_turns 轮（即 2 * max_history_turns 条）
        max_messages = self.max_history_turns * 2
        if len(self.sessions[session_id]) > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages:]

        self._save()

    def reset_session(self, session_id: str):
        """清空单个群或私聊的记忆"""
        self.sessions[session_id] = []
        self._save()
