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

# 注入给大模型的 QQ 平台级合规契约，防止模型生成涉政/违规内容导致封号
QQ_SAFETY_CONTRACT = (
    "\n\n【QQ 聊天最高安全合规红线（生命线）】\n"
    "你运行在中国大陆腾讯 QQ 官方群聊环境中，必须严格遵守国家法律法规与腾讯平台规范，防止机器人账号被封禁：\n"
    "1. 绝对严禁讨论任何现实涉政话题、政治人物、敏感政治事件、政治争议与意识形态争端；\n"
    "2. 绝对严禁涉及色情低俗、性暗示、血腥暴力、真钱赌博/外挂私庄、毒品或任何违法违规内容；\n"
    "3. 遇到上述敏感话题或群友故意诱导/钓鱼时，严禁长篇大论，必须用傲娇猫猫的口吻幽默机智地拒绝并把话题带回麻将、小鱼干或日常趣事（例如：“小猫咪从不关心这种危险话题喵！咱们聊点开心的，比如今天谁要请本猫吃小鱼干？”）。"
)

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


def image_to_data_url(image_path: str) -> str:
    """将本地图片文件编码为 OpenAI/Gemini 兼容的 Base64 Data URL"""
    import base64
    import mimetypes
    mime, _ = mimetypes.guess_type(image_path)
    if not mime:
        mime = "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


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
            # 走反代理 API (OpenAI 兼容模式) - 多模态识图与全量上下文直推
            history = session_mgr.get_history(session_id)
            messages = [{"role": "system", "content": current_system_prompt + QQ_SAFETY_CONTRACT}]
            messages.extend(history)

            # 构造多模态用户输入 (文本 + 图片)
            if image_paths:
                content_blocks = [{"type": "text", "text": prompt_text}]
                for p in image_paths:
                    if os.path.exists(p):
                        content_blocks.append({
                            "type": "image_url",
                            "image_url": {"url": image_to_data_url(p)}
                        })
                messages.append({"role": "user", "content": content_blocks})
            else:
                messages.append({"role": "user", "content": prompt_text})

            req_params = {
                "model": model,
                "messages": messages,
                "temperature": 0.8,
            }
            if config.get("enable_web_search", False):
                req_params["extra_body"] = {"web_search": True}

            response = await client.chat.completions.create(**req_params)
            raw_reply = response.choices[0].message.content.strip()

            # 记录本轮对话到历史（历史中仅记录文本标记，避免膨胀 sessions 存储体积）
            hist_text = prompt_text + (" [发送了图片附件]" if image_paths else "")
            session_mgr.add_message(session_id, "user", hist_text)
            session_mgr.add_message(session_id, "assistant", raw_reply)

        # 经过表情与思维链清洗管道处理为最终 QQ 发送格式
        formatted_reply = format_bot_reply(raw_reply)

        # 🛡️ 经过输出敏感词后置熔断审查（若含高危封号词直接拦截替换，绝不发往 QQ）
        is_safe, final_reply, reject_reason = security_guard.inspect_output(formatted_reply)
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
            f"🎭 /persona ：查看或切换人设（如 /persona hajimi）\n"
            f"🤖 /model ：查看或切换模型（如 /model gemini-3.8-flash）\n"
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

    if cmd.startswith("/model"):
        parts = cmd.split()
        supported_models = {
            "gemini-3.8-flash": "Gemini 3.8 Flash（高阶联网推理，查比赛查资讯最准，推荐）",
            "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite（超低延迟、极度省额度）",
            "gemini-3-flash": "Gemini 3 Flash（标准 Flash）",
            "gemini-2.5-pro": "Gemini 2.5 Pro（深度思维链推理）",
        }
        if len(parts) > 1 and parts[1] in supported_models:
            config["gemini_model"] = parts[1]
            return f"🤖 模型已成功切换为：【{parts[1]}】！\n说明：{supported_models[parts[1]]}"
        else:
            cur_model = config.get("gemini_model", "gemini-3.8-flash")
            lines = [f"当前模型：【{cur_model}】", "可用模型列表："]
            for m_id, m_desc in supported_models.items():
                lines.append(f"  • `{m_id}` : {m_desc}")
            lines.append("\n切换指令示例：/model gemini-3.8-flash")
            return "\n".join(lines)

    return None


# 群内最近图片缓存字典 (group_id -> [{"time": timestamp, "path": local_img}])
recent_group_images: dict[str, list[dict]] = {}


def extract_image_urls(data: dict) -> list[str]:
    """从 OneBot 消息（数组格式与 CQ 码字符串格式）中全面提取图片 URL"""
    urls = []
    # 1. 处理 array 消息段格式
    msg = data.get("message")
    if isinstance(msg, list):
        for seg in msg:
            if isinstance(seg, dict) and seg.get("type") == "image":
                d = seg.get("data", {})
                u = d.get("url") or d.get("file")
                if u and isinstance(u, str) and u.startswith("http"):
                    urls.append(u)
    # 2. 正则解析 CQ:image 码
    for text_field in [data.get("raw_message", ""), str(data.get("message", ""))]:
        if not text_field:
            continue
        for u in re.findall(r"\[CQ:image,[^\]]*?url=([^,\]]+)", text_field):
            if u.startswith("http") and u not in urls:
                urls.append(u)
        for u in re.findall(r"\[CQ:image,[^\]]*?file=(http[^,\]]+)", text_field):
            if u not in urls:
                urls.append(u)
    return urls


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

            # 🖼️ 全局嗅探群内图片并更新近期缓存（只要有人发图就暂存 3 分钟，方便后续何切/看图提问）
            found_urls = extract_image_urls(data)
            if found_urls and group_id:
                for u in found_urls[:2]:
                    local_img = await download_image(u)
                    if local_img:
                        if group_id not in recent_group_images:
                            recent_group_images[group_id] = []
                        recent_group_images[group_id].append({"time": time.time(), "path": local_img})
                        recent_group_images[group_id] = recent_group_images[group_id][-5:]

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

            if not should_reply:
                continue

            # 🖼️ 提取多模态图片附件
            image_paths = []
            if found_urls:
                print(f"📸 检测到当前提问消息附带 {len(found_urls)} 张图片，正在处理...")
                for u in found_urls[:2]:
                    local_img = await download_image(u)
                    if local_img and local_img not in image_paths:
                        image_paths.append(local_img)

            # 🧠 智能图片回溯：如果当前消息没带图，但群友说了“何切/怎么打/识别”或回复了带图消息，自动绑定群内最近截图
            if not image_paths and group_id in recent_group_images:
                now = time.time()
                valid_recent = [img for img in recent_group_images[group_id] if now - img["time"] < 180]
                vision_triggers = ["何切", "看图", "手牌", "牌局", "怎么打", "打哪", "识别", "这把", "这手", "这局", "牌"]
                has_reply = "[CQ:reply" in raw_text or "reply" in str(data.get("message", ""))
                is_trigger = any(w in user_msg for w in vision_triggers)
                if (has_reply or is_trigger) and valid_recent:
                    latest_img = valid_recent[-1]["path"]
                    if os.path.exists(latest_img):
                        image_paths.append(latest_img)
                        print(f"📸 智能关联群内最近 {int(now - valid_recent[-1]['time'])}s 内发送的截图进行多模态分析！")

            # 清理消息中的 CQ 码（CQ:image, CQ:reply 等），保留纯提问
            clean_text = re.sub(r"\[CQ:image,[^\]]+\]", "", user_msg)
            clean_text = re.sub(r"\[CQ:reply,[^\]]+\]", "", clean_text).strip()
            if not clean_text and image_paths:
                clean_text = "哈基米，帮我看下这张麻将牌局/手牌截图，我应该怎么打？打哪张最好？请给出专业硬核的何切建议！"
            elif not clean_text:
                continue

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
