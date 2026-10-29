import asyncio
import json
import os
import sys
import re
import time
import httpx

# 适配 Windows 控制台输出 UTF-8 / Emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 兼容 Python 3.10 StrEnum
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
    import enum
    enum.StrEnum = StrEnum

try:
    from websockets.asyncio.server import serve
except ImportError:
    from websockets.server import serve

from openai import AsyncOpenAI
from face_converter import format_bot_reply
from antigravity_bridge import send_to_antigravity
from session_manager import SessionManager
from security_guard import SecurityGuard
from gemini_web_bridge import GeminiWebBridge

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")
TEMP_IMG_DIR = os.path.join(BASE_DIR, "data", "images")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)

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

backend = config.get("backend", "gemini_web")

# 初始化多群独立原生会话管理器与安全防护盾
session_mgr = SessionManager()
security_guard = SecurityGuard(user_cooldown=3.0, group_cooldown=1.2, max_len=250)

# 初始化 Gemini Web 逆向客户端 (支持多模态识图与自动刷新)
web_bridge = None
if backend == "gemini_web":
    web_bridge = GeminiWebBridge(
        secure_1psid=config.get("secure_1psid", ""),
        secure_1psidts=config.get("secure_1psidts", ""),
        proxy=config.get("proxy_url"),
    )

# 备用 OpenAI 客户端
proxy_url = config.get("proxy_url")
http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
base_url = config.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"
api_key = config.get("gemini_api_key") or "dummy-key"

client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=http_client,
)


async def download_image(url: str) -> str | None:
    """下载 QQ 群消息中的图片到临时缓存"""
    try:
        import hashlib
        ext = ".jpg"
        fname = f"img_{int(time.time())}_{hashlib.md5(url.encode()).hexdigest()[:8]}{ext}"
        path = os.path.join(TEMP_IMG_DIR, fname)
        async with httpx.AsyncClient() as c:
            resp = await c.get(url, timeout=12.0)
            if resp.status_code == 200:
                with open(path, "wb") as f:
                    f.write(resp.content)
                return path
    except Exception as e:
        print(f"⚠️ 下载群图片异常: {e}")
    return None


async def chat_with_llm(
    session_id: str,
    prompt_text: str,
    raw_user_msg: str,
    image_paths: list[str] | None = None,
) -> str:
    global current_system_prompt
    model = config.get("gemini_model", "flash")

    try:
        if backend == "gemini_web":
            # 走 Gemini Web 网页版通道（完美支持多模态截图、自动后台刷新 Cookie、零额外扣费）
            raw_reply = await web_bridge.send_message(
                session_id=session_id,
                prompt=prompt_text,
                image_paths=image_paths,
                system_prompt=current_system_prompt,
            )
        elif backend == "antigravity":
            # 走本地 Antigravity 物理沙箱通道
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
        mode_desc = "Gemini Web (多模态识图 / 自动Cookie刷新)" if backend == "gemini_web" else "Antigravity Pro 沙箱"
        return (
            f"🐾 【QQ 哈基米 & 麻将多模态助手】\n"
            f"当前人设：{cur_name}\n"
            f"驱动核心：{mode_desc}\n"
            f"---------------------------\n"
            f"💬 @我 发送文字或麻将截图即可对话/分析何切\n"
            f"🔄 /reset ：清空本群当前的上下文记忆，开启新话题\n"
            f"🎭 /persona ：查看所有可用人设\n"
            f"🎭 /persona [名称] ：切换人设（如 /persona hajimi）\n"
            f"---------------------------"
        )

    if cmd in ["/reset", "重置记忆", "清空上下文", "新会话"]:
        if backend == "gemini_web" and web_bridge:
            web_bridge.reset_chat(session_id)
        session_mgr.reset_session(session_id)
        return "✨ 本群的原生会话记忆已全部清空，开启全新对话喵！"

    if cmd.startswith("/persona"):
        parts = cmd.split()
        if len(parts) > 1 and parts[1] in personas_data["personas"]:
            current_persona_key = parts[1]
            current_system_prompt = personas_data["personas"][current_persona_key][
                "prompt"
            ]
            if backend == "gemini_web" and web_bridge:
                web_bridge.reset_chat(session_id)
            session_mgr.reset_session(session_id)
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
            elif msg_type == "group":
                self_id = str(data.get("self_id"))
                at_me = f"[CQ:at,qq={self_id}]"
                if at_me in raw_text:
                    should_reply = True
                    user_msg = raw_text.replace(at_me, "").strip()
                session_id = f"group_{group_id}"

            if not should_reply or not user_msg:
                continue

            # 🖼️ 提取并下载群消息中的图片附件（麻将手牌截图、雀魂战局等）
            image_paths = []
            img_urls = re.findall(r"\[CQ:image,[^\]]*url=([^,\]]+)[^\]]*\]", user_msg)
            if img_urls:
                print(f"📸 检测到群友发送了 {len(img_urls)} 张图片，正在下载...")
                for u in img_urls[:2]:  # 一次最多处理 2 张图片
                    local_img = await download_image(u)
                    if local_img:
                        image_paths.append(local_img)

            # 清理消息中的 CQ 码，保留纯文本提问
            clean_text = re.sub(r"\[CQ:image,[^\]]+\]", "", user_msg).strip()
            if not clean_text and image_paths:
                clean_text = "哈基米，帮我看下这把麻将牌局/手牌，我应该怎么打？打哪张最好？"

            # 🛡️ 1. 频率与刷屏防护 (Rate Limiting)
            allowed, cd_reason = security_guard.check_rate_limit(sender_id, group_id)
            if not allowed:
                if cd_reason:
                    payload = {
                        "action": "send_msg",
                        "params": {
                            "message_type": msg_type,
                            "message": cd_reason,
                            ("group_id" if msg_type == "group" else "user_id"): (
                                int(group_id) if msg_type == "group" else int(sender_id)
                            ),
                        },
                    }
                    await websocket.send(json.dumps(payload))
                continue

            # 🛡️ 2. 前置安全检测与注入过滤
            is_safe, sanitized_text, reject_reason = security_guard.sanitize_and_inspect(clean_text)
            if not is_safe:
                print(f"🛡️ [拦截恶意输入] 来自【{sender_name}】({sender_id}): {reject_reason}")
                payload = {
                    "action": "send_msg",
                    "params": {
                        "message_type": msg_type,
                        "message": sanitized_text,
                        ("group_id" if msg_type == "group" else "user_id"): (
                            int(group_id) if msg_type == "group" else int(sender_id)
                        ),
                    },
                }
                await websocket.send(json.dumps(payload))
                continue

            user_msg = sanitized_text
            prompt_text = (
                f"【群友 {sender_name}】: {user_msg}"
                if msg_type == "group"
                else user_msg
            )

            print(f"📩 [{session_id}] 收到来自【{sender_name}】的消息: {user_msg} (附图: {len(image_paths)})")

            # 优先处理内置快捷指令
            cmd_reply = handle_commands(session_id, user_msg)
            if cmd_reply:
                reply_payload = {
                    "action": "send_msg",
                    "params": {
                        "message_type": msg_type,
                        "message": cmd_reply,
                        ("group_id" if msg_type == "group" else "user_id"): (
                            int(group_id) if msg_type == "group" else int(sender_id)
                        ),
                    },
                }
                await websocket.send(json.dumps(reply_payload))
                continue

            # 调用大模型生成哈基米回复（支持多模态识图分析）
            bot_reply = await chat_with_llm(
                session_id=session_id,
                prompt_text=prompt_text,
                raw_user_msg=user_msg,
                image_paths=image_paths,
            )
            print(f"🐱 [{session_id}] 哈基米回复: {bot_reply}")

            # 构造 NapCat 发送消息负载 (CQ:face 会被 NapCat 自动解析为原生 QQ 大表情)
            reply_payload = {
                "action": "send_msg",
                "params": {
                    "message_type": msg_type,
                    "message": bot_reply,
                    ("group_id" if msg_type == "group" else "user_id"): (
                        int(group_id) if msg_type == "group" else int(sender_id)
                    ),
                },
            }
            await websocket.send(json.dumps(reply_payload))

            # 清理临时下载的图片文件
            for p in image_paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

        except Exception as e:
            print(f"❌ 处理消息异常: {e}")


async def main():
    host = "0.0.0.0"
    port = config.get("bot_ws_port", 8080)
    print("=" * 60)
    print("🚀 QQ 哈基米 & 麻将多模态助手 (QQ-Mahjong-Bot) 正在启动...")
    print(f"📡 监听 WebSocket 端口: ws://{host}:{port}/ws")
    print(f"🎭 默认激活人设: 【{current_persona_key}】")
    if backend == "gemini_web":
        print("🌐 运行后端: Gemini Web 网页版 (支持多模态麻将截图何切 / 后台自动心跳刷新Cookie)")
        print("💰 计费模式: 100% 消耗已付 Google One AI Premium (Gemini Advanced) 会员，零额外扣费！")
        # 预热并初始化 Gemini Web 客户端
        if web_bridge and web_bridge.secure_1psid and "YOUR_" not in web_bridge.secure_1psid:
            try:
                await web_bridge.init_client()
            except Exception as e:
                print(f"⚠️ Gemini Web 初始化提示: {e} (请检查 config.json 中的 Cookie 是否有效)")
    else:
        print("🛡️ 运行后端: Antigravity Pro 本地沙箱隔离通道")
    print("=" * 60)

    server = await serve(ws_handler, host, port)
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 机器人已优雅停止。")
