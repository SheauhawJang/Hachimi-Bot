"""
多群与私聊独立会话记忆管理器 (Session Manager)
1. 保证每个群 (group_xxx) 与私聊 (private_xxx) 1:1 独立记忆隔离，绝不串台
2. 精简滑动窗口机制 (默认保留最近 4 轮/8 条消息)：
   - 保持群内自然接梗与短期记忆
   - 严格压制上下文体积，防止重复浪费 token，为你日常正事保留最大额度！
3. 本地 JSON 自动持久化存储，重启机器人记忆不丢失
4. 支持群友发送 /reset 独立清空当前群记忆
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


class SessionManager:
    def __init__(self, max_history_turns: int = 4):
        # 默认只保留最近 4 轮问答（8 条消息），既能接梗，又几乎不烧 token！
        self.max_history_turns = max_history_turns
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
        """获取指定群或私聊的独立历史消息列表"""
        return list(self.sessions.get(session_id, []))

    def add_message(self, session_id: str, role: str, content: str):
        """向指定会话追加单条消息并执行滑动截断"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append({"role": role, "content": content})

        # 严格限制最大消息条数，防止 token 越滚越大
        max_msgs = self.max_history_turns * 2
        if len(self.sessions[session_id]) > max_msgs:
            self.sessions[session_id] = self.sessions[session_id][-max_msgs:]

        self._save()

    def reset_session(self, session_id: str):
        """清空单个群或私聊的记忆"""
        if session_id in self.sessions:
            self.sessions[session_id] = []
            self._save()
