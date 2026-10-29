import asyncio
import json
import os
import sys
import httpx

# 适配 Windows 控制台输出 UTF-8 / Emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from websockets.asyncio.server import serve
except ImportError:
    from websockets.server import serve

from openai import AsyncOpenAI
from face_converter import format_bot_reply
from antigravity_bridge import chat_via_antigravity
from session_manager import SessionManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")

# 加载配置
with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

# 加载人设
with open(PERSONAS_FILE, "r", encoding="utf-8") as f:
    personas_data = json.load(f)

current_persona_key = config.get("default_persona", "hajimi")
current_system_prompt = personas_data["personas"].get(
    current_persona_key, {}
).get("prompt", "你是一个友好的AI。")

backend = config.get("backend", "antigravity")

# 初始化多群独立持久化会话管理器
max_turns = config.get("max_history_turns", 10)
session_mgr = SessionManager(max_history_turns=max_turns)

# 备用 OpenAI 客户端 (当 backend == "api" 时启用)
proxy_url = config.get("proxy_url")
http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
base_url = config.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"
api_key = config.get("gemini_api_key") or "dummy-key"

client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=http_client,
)


async def chat_with_llm(session_id: str, prompt_text: str, raw_user_msg: str) -> str:
    global current_system_prompt
    history = session_mgr.get_history(session_id)
    model = config.get("gemini_model", "flash")

    try:
        if backend == "antigravity":
            # 走本地 Antigravity 会员直通车
            raw_reply = await chat_via_antigravity(
                system_prompt=current_system_prompt,
                history=history,
                user_msg=prompt_text,
                model=model,
            )
        else:
            # 走外部 API
            messages = [{"role": "system", "content": current_system_prompt}]
            messages.extend(history)
            messages.append({"role": "user", "content": prompt_text})

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.8,
            )
            raw_reply = response.choices[0].message.content.strip()

        # 记录到当前群/用户的持久化独立记忆中
        session_mgr.add_interaction(session_id, prompt_text, raw_reply)

        # 经过表情与思维链清洗管道处理为最终 QQ 发送格式
        final_reply = format_bot_reply(raw_reply)
        return final_reply
    except Exception as e:
        err_msg = str(e)
        print(f"❌ [模型调用错误]: {err_msg}")
        return f"【对话出错】：{err_msg}"


def handle_commands(session_id: str, text: str) -> str | None:
    global current_persona_key, current_system_prompt
    cmd = text.strip()

    if cmd in ["/help", "帮助", "菜单"]:
        cur_name = personas_data["personas"].get(current_persona_key, {}).get("name", current_persona_key)
        mode_str = "Antigravity Pro 会员通道 (0额度限制)" if backend == "antigravity" else "外部 API 通道"
        return (
            f"🐾 【QQ 哈基米 & 麻将助手】\n"
            f"当前人设：{cur_name}\n"
            f"运行后端：{mode_str}\n"
            f"---------------------------\n"
            f"💬 直接发消息或 @我 即可对话\n"
            f"🔄 /reset ：清空本群当前的上下文记忆\n"
            f"🎭 /persona ：查看所有可用人设\n"
            f"🎭 /persona [名称] ：切换人设（如 /persona hajimi）\n"
            f"---------------------------"
        )

    if cmd in ["/reset", "重置记忆", "清空上下文"]:
        session_mgr.reset_session(session_id)
        return "✨ 本群的历史记忆已全部清空，咱们重新开始吧！"

    if cmd.startswith("/persona"):
        parts = cmd.split()
        if len(parts) > 1 and parts[1] in personas_data["personas"]:
            current_persona_key = parts[1]
            current_system_prompt = personas_data["personas"][current_persona_key][
                "prompt"
            ]
            session_mgr.reset_session(session_id)  # 切换人设顺便重置本群会话
            p_name = personas_data["personas"][current_persona_key]["name"]
            return f"🎭 人设已成功切换为：【{p_name}】！"
        else:
            cur_name = personas_data["personas"].get(current_persona_key, {}).get("name", "默认")
            lines = [f"当前人设：【{cur_name}】", "可用人设列表："]
            for k, v in personas_data["personas"].items():
                lines.append(f"  • `{k}` : {v['name']}")
            lines.append("\n切换指令示例：/persona hajimi")
            return "\n".join(lines)

    return None


async def ws_handler(websocket):
    print("🟢 [NapCatQQ 已建立连接] 开始监听消息...")
    async for message in websocket:
        try:
            data = json.loads(message)
            if data.get("post_type") != "message":
                continue

            msg_type = data.get("message_type")  # "private" 或 "group"
            raw_text = data.get("raw_message", "").strip()
            sender_info = data.get("sender", {})
            sender_id = str(data.get("user_id"))
            group_id = str(data.get("group_id", ""))

            # 提取发送者昵称（群名片优先）
            sender_name = sender_info.get("card") or sender_info.get("nickname") or f"用户_{sender_id}"

            should_reply = False
            user_msg = raw_text

            if msg_type == "private":
                session_id = f"private_{sender_id}"
                should_reply = True
                prompt_text = user_msg
            elif msg_type == "group":
                self_id = str(data.get("self_id"))
                at_me = f"[CQ:at,qq={self_id}]"
                if at_me in raw_text:
                    should_reply = True
                    user_msg = raw_text.replace(at_me, "").strip()
                session_id = f"group_{group_id}"
                # 群聊注入发信人昵称，赋予哈基米真正的认人与称呼能力
                prompt_text = f"【群友 {sender_name}】: {user_msg}"

            if not should_reply or not user_msg:
                continue

            print(f"📩 [{msg_type}] 来自 {sender_name}({sender_id}): {user_msg}")

            # 1. 检查指令
            cmd_reply = handle_commands(session_id, user_msg)
            if cmd_reply:
                reply_text = cmd_reply
            else:
                # 2. 调用模型 (走 Antigravity 会员或 API)
                reply_text = await chat_with_llm(session_id, prompt_text, user_msg)

            print(f"📤 回复: {reply_text[:60]}...")

            # 3. 发送回 QQ
            send_payload = {
                "action": "send_msg",
                "params": {
                    "message_type": msg_type,
                    "user_id": int(sender_id) if msg_type == "private" else None,
                    "group_id": int(group_id) if msg_type == "group" else None,
                    "message": reply_text,
                },
            }
            await websocket.send(json.dumps(send_payload))

        except Exception as e:
            print(f"⚠️ 处理消息出错: {e}")


async def main():
    port = config.get("bot_ws_port", 8080)
    cur_p_name = personas_data["personas"].get(current_persona_key, {}).get("name", current_persona_key)
    mode_str = "Antigravity Pro 会员通道 (直调本地客户端，0额外扣费，无RPD限制)" if backend == "antigravity" else "外部 API 通道"
    print("=" * 65)
    print("🐾 QQ Gemini (哈基米) 机器人服务已就绪")
    print(f"🌐 正在监听反向 WebSocket 端口: ws://127.0.0.1:{port}")
    print(f"🚀 运行后端模式: 【{mode_str}】")
    print(f"🧠 模型档位: {config.get('gemini_model', 'flash')}")
    print(f"🎭 默认人设: 【{cur_p_name}】 ({current_persona_key})")
    print(f"💾 会话记忆模式: 【单群独立隔离 + 本地自动持久化 (最近{max_turns}轮)】")
    print(f"✨ 核心特性: 326种真QQ表情转换 + 群友昵称感知注入 + 短句节奏控制")
    print("=" * 65)
    async with serve(ws_handler, "127.0.0.1", port):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 机器人服务已停止。")
