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
from antigravity_bridge import send_to_antigravity
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

# 初始化多群独立原生会话管理器
session_mgr = SessionManager()

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
    model = config.get("gemini_model", "flash")

    try:
        if backend == "antigravity":
            # 走本地 Antigravity 原生群会话通道 (自动维护长上下文记忆，100% 消耗 Pro 会员，无 500 RPD 限制)
            conv_id = session_mgr.get_conv_id(session_id)
            raw_reply, new_conv_id = await send_to_antigravity(
                conv_id=conv_id,
                user_msg=prompt_text,
                system_prompt=current_system_prompt,
                model=model,
            )
            if new_conv_id:
                session_mgr.set_conv_id(session_id, new_conv_id)
        else:
            # 备用 API Key 通道
            messages = [
                {"role": "system", "content": current_system_prompt},
                {"role": "user", "content": prompt_text},
            ]
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.8,
            )
            raw_reply = response.choices[0].message.content.strip()

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
        mode_str = "Antigravity Pro 原生群会话 (0额度限制/自动上下文)" if backend == "antigravity" else "外部 API 通道"
        return (
            f"🐾 【QQ 哈基米 & 麻将助手】\n"
            f"当前人设：{cur_name}\n"
            f"运行后端：{mode_str}\n"
            f"---------------------------\n"
            f"💬 直接发消息或 @我 即可对话\n"
            f"🔄 /reset ：清空本群当前的上下文记忆，开启新会话\n"
            f"🎭 /persona ：查看所有可用人设\n"
            f"🎭 /persona [名称] ：切换人设（如 /persona hajimi）\n"
            f"---------------------------"
        )

    if cmd in ["/reset", "重置记忆", "清空上下文", "新会话"]:
        session_mgr.reset_session(session_id)
        return "✨ 本群的原生会话记忆已全部清空，开启全新对话喵！"

    if cmd.startswith("/persona"):
        parts = cmd.split()
        if len(parts) > 1 and parts[1] in personas_data["personas"]:
            current_persona_key = parts[1]
            current_system_prompt = personas_data["personas"][current_persona_key][
                "prompt"
            ]
            session_mgr.reset_session(session_id)  # 切换人设顺便重置本群会话
            p_name = personas_data["personas"][current_persona_key]["name"]
            return f"🎭 人设已成功切换为：【{p_name}】！本群会话已自动重置以应用新人设。"
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

            print(f"📩 [{session_id}] 收到来自【{sender_name}】的消息: {user_msg}")

            # 优先处理内置快捷指令
            cmd_reply = handle_commands(session_id, user_msg)
            if cmd_reply:
                reply_payload = {
                    "action": "send_msg",
                    "params": {
                        "message_type": msg_type,
                        "message": cmd_reply,
                    },
                }
                if msg_type == "group":
                    reply_payload["params"]["group_id"] = int(group_id)
                else:
                    reply_payload["params"]["user_id"] = int(sender_id)

                await websocket.send(json.dumps(reply_payload))
                continue

            # 调用大模型生成哈基米回复
            bot_reply = await chat_with_llm(session_id, prompt_text, user_msg)
            print(f"🐱 [{session_id}] 哈基米回复: {bot_reply}")

            # 构造 NapCat 发送消息负载 (CQ:face 会被 NapCat 自动解析为原生 QQ 大表情)
            reply_payload = {
                "action": "send_msg",
                "params": {
                    "message_type": msg_type,
                    "message": bot_reply,
                },
            }
            if msg_type == "group":
                reply_payload["params"]["group_id"] = int(group_id)
            else:
                reply_payload["params"]["user_id"] = int(sender_id)

            await websocket.send(json.dumps(reply_payload))

        except Exception as e:
            print(f"❌ 处理消息异常: {e}")


async def main():
    host = "0.0.0.0"
    port = config.get("bot_ws_port", 8080)
    print("=" * 60)
    print("🚀 QQ 哈基米 & 麻将小助手 (QQ-Mahjong-Bot) 正在启动...")
    print(f"📡 正在监听 NapCatQQ 正向/反向 WebSocket: ws://{host}:{port}/ws")
    print(f"🎭 默认激活人设: 【{current_persona_key}】")
    mode_desc = "Antigravity Pro 本地会话机制 (0额度扣费 / 自动长上下文)" if backend == "antigravity" else "外部 API 模式"
    print(f"⚡ 驱动核心: {mode_desc}")
    print("=" * 60)

    server = await serve(ws_handler, host, port)
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 机器人已优雅停止。")
