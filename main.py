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
).get("prompt", "你是一个友好的AI小猫咪。")

# 初始化 Gemini 客户端 (通过 Google 官方提供的 OpenAI 兼容接口)
proxy_url = config.get("proxy_url")
http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None

client = AsyncOpenAI(
    api_key=config.get("gemini_api_key"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    http_client=http_client,
)

# 内存会话管理: session_id -> list of messages
sessions = {}


def get_session_history(session_id: str):
    if session_id not in sessions:
        sessions[session_id] = []
    return sessions[session_id]


async def chat_with_gemini(session_id: str, user_text: str) -> str:
    global current_system_prompt
    history = get_session_history(session_id)

    # 组装消息列表
    messages = [{"role": "system", "content": current_system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    try:
        response = await client.chat.completions.create(
            model=config.get("gemini_model", "gemini-1.5-pro"),
            messages=messages,
            temperature=0.75,
        )
        reply = response.choices[0].message.content.strip()

        # 记录到历史
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})

        max_turns = config.get("max_history_turns", 10)
        if len(history) > max_turns * 2:
            history = history[-max_turns * 2 :]
            sessions[session_id] = history

        return reply
    except Exception as e:
        err_msg = str(e)
        print(f"❌ [Gemini API 错误]: {err_msg}")
        if "401" in err_msg or "API_KEY_INVALID" in err_msg:
            return "【配置提示】：Gemini API Key 无效或未填写，请在 config.json 中配置有效的 API Key！"
        return f"【对话出错】：{err_msg}"


def handle_commands(session_id: str, text: str) -> str | None:
    global current_persona_key, current_system_prompt
    cmd = text.strip()

    if cmd in ["/help", "帮助", "菜单"]:
        cur_name = personas_data["personas"].get(current_persona_key, {}).get("name", current_persona_key)
        return (
            f"🐾 【QQ 哈基米 & 麻将助手】\n"
            f"当前人设：{cur_name}\n"
            f"---------------------------\n"
            f"💬 直接发消息或 @我 即可对话\n"
            f"🔄 /reset ：清空当前会话记忆\n"
            f"🎭 /persona ：查看所有可用人设\n"
            f"🎭 /persona [名称] ：切换人设（如 /persona hajimi）\n"
            f"---------------------------"
        )

    if cmd in ["/reset", "重置记忆", "清空上下文"]:
        sessions[session_id] = []
        return "✨ 历史记忆已全部清空，咱们重新开始！"

    if cmd.startswith("/persona"):
        parts = cmd.split()
        if len(parts) > 1 and parts[1] in personas_data["personas"]:
            current_persona_key = parts[1]
            current_system_prompt = personas_data["personas"][current_persona_key][
                "prompt"
            ]
            sessions[session_id] = []  # 切换人设顺便重置会话
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
            sender_id = str(data.get("user_id"))
            group_id = str(data.get("group_id", ""))

            should_reply = False
            user_msg = raw_text

            if msg_type == "private":
                session_id = f"private_{sender_id}"
                should_reply = True
            elif msg_type == "group":
                self_id = str(data.get("self_id"))
                at_me = f"[CQ:at,qq={self_id}]"
                if at_me in raw_text:
                    should_reply = True
                    user_msg = raw_text.replace(at_me, "").strip()
                session_id = f"group_{group_id}"

            if not should_reply or not user_msg:
                continue

            print(f"📩 [{msg_type}] 来自 {sender_id}: {user_msg}")

            # 1. 检查指令
            cmd_reply = handle_commands(session_id, user_msg)
            if cmd_reply:
                reply_text = cmd_reply
            else:
                # 2. 调用大模型
                reply_text = await chat_with_gemini(session_id, user_msg)

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
    print("=" * 55)
    print("🐾 QQ Gemini (哈基米) 机器人服务已就绪")
    print(f"🌐 正在监听反向 WebSocket 端口: ws://127.0.0.1:{port}")
    print(f"🧠 当前模型: {config.get('gemini_model')}")
    print(f"🎭 默认人设: 【{cur_p_name}】 ({current_persona_key})")
    print(f"⚡ 代理设置: {proxy_url if proxy_url else '直连 (无代理)'}")
    print("=" * 55)
    async with serve(ws_handler, "127.0.0.1", port):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 机器人服务已停止。")
