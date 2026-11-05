"""
OneBot 11 (QQ) 协议通信与消息分发管道 (OneBot Client & Message Pipeline)
负责：
1. OneBot 11 WebSocket 消息接收与 JSON-RPC API 调用 (call_onebot_api)
2. CQ 码解析、图片提取下载与群图片短期上下文回溯
3. 引用消息 (reply) 详情递归解析
4. 群成员名片缓存与 @强提醒 自动映射
5. 消息安全过滤、内置指令拦截、两阶段麻将客观报告与哈基米复盘发送
"""

import os
import re
import json
import time
import httpx
import asyncio
from websockets.exceptions import ConnectionClosed

import config_manager as cm
from command_handler import handle_commands
from llm_client import chat_with_llm

# 全局活跃 WebSocket 连接
active_ws = None

# 群内最近图片缓存字典 (group_id -> [{"time": timestamp, "path": local_img}])
recent_group_images: dict[str, list[dict]] = {}

# 存放等待 OneBot API 返回的 Future (echo -> asyncio.Future)
pending_api_futures: dict[str, asyncio.Future] = {}

# 群成员名片/昵称缓存: { group_id: { "update_time": float, "members": { name_or_card: user_id_str } } }
group_members_cache: dict[str, dict] = {}


async def download_image(url: str) -> str | None:
    """下载 QQ 群消息中的图片到临时缓存"""
    try:
        import hashlib
        ext = ".jpg"
        fname = f"img_{int(time.time())}_{hashlib.md5(url.encode()).hexdigest()[:8]}{ext}"
        path = os.path.join(cm.TEMP_IMG_DIR, fname)
        async with httpx.AsyncClient() as c:
            resp = await c.get(url, timeout=12.0)
            if resp.status_code == 200:
                with open(path, "wb") as f:
                    f.write(resp.content)
                return path
    except Exception as e:
        print(f"⚠️ 下载群图片异常: {e}")
    return None


async def call_onebot_api(websocket, action: str, params: dict, timeout: float = 3.5) -> dict | None:
    """异步调用 OneBot 11 API 并等待带 echo 的响应结果"""
    global active_ws
    target_ws = active_ws if active_ws is not None else websocket
    if target_ws is None:
        return None
    import uuid
    echo = f"echo_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    pending_api_futures[echo] = future

    payload = {
        "action": action,
        "params": params,
        "echo": echo,
    }
    try:
        await target_ws.send(json.dumps(payload))
        resp = await asyncio.wait_for(future, timeout=timeout)
        return resp
    except asyncio.TimeoutError:
        print(f"⏱️ [OneBot API 超时] 调用 {action} 超过 {timeout}s 未收到响应 (echo={echo})")
        return None
    except Exception as e:
        print(f"⚠️ [OneBot API 异常] {action}: {e}")
        return None
    finally:
        pending_api_futures.pop(echo, None)


async def fetch_group_members(websocket, group_id: str):
    """异步拉取群成员列表并更新缓存，避免频繁调用 OneBot API"""
    if not group_id or not websocket:
        return
    try:
        resp = await call_onebot_api(websocket, "get_group_member_list", {"group_id": int(group_id)}, timeout=5.0)
        if resp and resp.get("status") == "ok" and isinstance(resp.get("data"), list):
            members_data = resp["data"]
            m_map = {}
            for m in members_data:
                uid = str(m.get("user_id", "")).strip()
                if not uid:
                    continue
                card = (m.get("card") or "").strip()
                nick = (m.get("nickname") or "").strip()
                if card:
                    m_map[card] = uid
                if nick:
                    m_map[nick] = uid
            group_members_cache[group_id] = {
                "update_time": time.time(),
                "members": m_map,
            }
            print(f"👥 [群成员缓存] 已更新群 {group_id} 的成员列表（共 {len(m_map)} 个名片/昵称项）")
    except Exception as e:
        print(f"⚠️ [群成员缓存] 获取群 {group_id} 成员失败: {e}")


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


def extract_reply_id(data: dict) -> int | str | None:
    """从 OneBot 消息中提取被引用的 message_id"""
    # 1. 从 message 数组段提取
    msg = data.get("message")
    if isinstance(msg, list):
        for seg in msg:
            if isinstance(seg, dict) and seg.get("type") == "reply":
                r_id = seg.get("data", {}).get("id")
                if r_id is not None:
                    try:
                        return int(r_id)
                    except (ValueError, TypeError):
                        return str(r_id)
    # 2. 从 raw_message 中正则提取 [CQ:reply,id=xxx]
    raw_text = data.get("raw_message", "")
    m = re.search(r"\[CQ:reply,id=([^,\]]+)\]", raw_text)
    if m:
        val = m.group(1)
        try:
            return int(val)
        except ValueError:
            return val
    return None


async def get_reply_detail(websocket, data: dict) -> dict | None:
    """获取当前消息引用的上一条消息详情（优先复用事件内嵌 reply，无则通过 get_msg 接口拉取）"""
    if isinstance(data.get("reply"), dict):
        return data["reply"]

    reply_id = extract_reply_id(data)
    if reply_id is None:
        return None

    resp = await call_onebot_api(websocket, "get_msg", {"message_id": reply_id}, timeout=3.5)
    if resp and resp.get("status") == "ok" and isinstance(resp.get("data"), dict):
        return resp["data"]
    return None


def extract_quote_context(reply_detail: dict | None, self_id: str = "") -> tuple[str, list[str]]:
    """从引用的消息详情中提取被引用人、文本描述与可能附带的图片 URL 列表"""
    if not reply_detail:
        return "", []

    sender = reply_detail.get("sender", {})
    uid = str(sender.get("user_id", ""))
    name = sender.get("card") or sender.get("nickname") or (f"用户_{uid}" if uid else "某群友")

    bot_display_name = cm.personas_data.get("personas", {}).get(cm.current_persona_key, {}).get("name", "哈基米")
    if self_id and uid == self_id:
        name = f"{bot_display_name}(我)"

    img_urls = extract_image_urls(reply_detail)

    raw_msg = reply_detail.get("raw_message") or ""
    if not raw_msg:
        msg_list = reply_detail.get("message")
        if isinstance(msg_list, list):
            raw_msg = "".join(
                s.get("data", {}).get("text", "")
                for s in msg_list
                if isinstance(s, dict) and s.get("type") == "text"
            )

    clean_ref = re.sub(r"\[CQ:image,[^\]]*\]", "[图片]", raw_msg)
    clean_ref = re.sub(r"\[CQ:face,[^\]]*\]", "[表情]", clean_ref)
    clean_ref = re.sub(r"\[CQ:reply,[^\]]*\]", "", clean_ref)
    clean_ref = re.sub(r"\[CQ:at,qq=([^,\]]+)\]", r"@\1", clean_ref).strip()

    if len(clean_ref) > 180:
        clean_ref = clean_ref[:180] + "..."

    img_tag = " [含图片]" if img_urls else ""
    if clean_ref:
        ref_desc = f"（引用了 {name} 的消息：“{clean_ref}”{img_tag}）"
    elif img_urls:
        ref_desc = f"（引用了 {name} 发送的图片）"
    else:
        ref_desc = f"（引用了 {name} 的消息）"

    return ref_desc, img_urls


async def handle_single_message(websocket, data: dict):
    """异步并发处理单条 QQ 消息，彻底避免耗时查询阻塞 WebSocket 接收循环"""
    global active_ws
    try:
        msg_type = data.get("message_type")  # "private" 或 "group"
        raw_text = data.get("raw_message", "").strip()
        sender_info = data.get("sender", {})
        sender_id = str(data.get("user_id"))
        group_id = str(data.get("group_id", ""))
        self_id = str(data.get("self_id") or "")

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
        sender_card = (sender_info.get("card") or "").strip()
        sender_nick = (sender_info.get("nickname") or "").strip()
        sender_name = sender_card or sender_nick or f"用户_{sender_id}"

        # 构建当前消息上下文中的 @提及 映射字典（提问者优先）
        mention_map: dict[str, str] = {}
        if sender_id:
            if sender_name:
                mention_map[sender_name] = sender_id
            if sender_card:
                mention_map[sender_card] = sender_id
            if sender_nick:
                mention_map[sender_nick] = sender_id

        # 异步拉取/刷新群成员列表（若尚未拉取或超过 10 分钟未更新）
        if msg_type == "group" and group_id and websocket:
            cache_entry = group_members_cache.get(group_id)
            if not cache_entry or (time.time() - cache_entry.get("update_time", 0) > 600):
                asyncio.create_task(fetch_group_members(websocket, group_id))

        # 🔍 检测引用消息
        has_reply_seg = "[CQ:reply" in raw_text or any(
            isinstance(s, dict) and s.get("type") == "reply"
            for s in (data.get("message") if isinstance(data.get("message"), list) else [])
        ) or ("reply" in data)

        reply_detail = None
        if has_reply_seg:
            reply_detail = await get_reply_detail(websocket, data)
            if reply_detail:
                ref_sender = reply_detail.get("sender", {})
                ref_uid = str(ref_sender.get("user_id", "")).strip()
                ref_c = (ref_sender.get("card") or "").strip()
                ref_n = (ref_sender.get("nickname") or "").strip()
                if ref_uid:
                    if ref_c:
                        mention_map[ref_c] = ref_uid
                    if ref_n:
                        mention_map[ref_n] = ref_uid

        # 合并群成员缓存中的群成员映射表（提问者与被引用者权重更高覆盖）
        if msg_type == "group" and group_id in group_members_cache:
            merged_map = dict(group_members_cache[group_id].get("members", {}))
            merged_map.update(mention_map)
            mention_map = merged_map

        should_reply = False
        user_msg = raw_text

        if msg_type == "private":
            session_id = f"private_{sender_id}"
            should_reply = True
        elif msg_type == "group":
            at_me = f"[CQ:at,qq={self_id}]" if self_id else ""
            if at_me and at_me in raw_text:
                should_reply = True
                user_msg = raw_text.replace(at_me, "").strip()
            elif reply_detail:
                ref_sender_id = str(reply_detail.get("sender", {}).get("user_id", ""))
                if self_id and ref_sender_id == self_id:
                    should_reply = True
                    user_msg = raw_text.strip()
                    print(f"🎯 检测到群友【{sender_name}】直接引用了机器人的历史发言，自动唤醒！")
            session_id = f"group_{group_id}"

        if not should_reply:
            return

        ref_desc, ref_img_urls = extract_quote_context(reply_detail, self_id=self_id)

        # 🖼️ 提取多模态图片附件
        image_paths = []
        if found_urls:
            print(f"📸 检测到当前提问消息附带 {len(found_urls)} 张图片，正在处理...")
            for u in found_urls[:2]:
                local_img = await download_image(u)
                if local_img and local_img not in image_paths:
                    image_paths.append(local_img)
        elif ref_img_urls:
            print(f"📸 检测到引用的原消息附带 {len(ref_img_urls)} 张图片，正在提取...")
            for u in ref_img_urls[:2]:
                local_img = await download_image(u)
                if local_img and local_img not in image_paths:
                    image_paths.append(local_img)

        # 🧠 智能图片回溯：如果当前消息及引用均未带图，但群友明确触发了看图/何切等关键词，自动兜底绑定群内最近截图
        if not image_paths and group_id in recent_group_images:
            now = time.time()
            valid_recent = [img for img in recent_group_images[group_id] if now - img["time"] < 180]
            vision_triggers = ["何切", "看图", "手牌", "牌局", "怎么打", "打哪", "识别", "这把", "这手", "这局", "牌"]
            is_trigger = any(w in user_msg for w in vision_triggers)
            if is_trigger and valid_recent:
                latest_img = valid_recent[-1]["path"]
                if os.path.exists(latest_img):
                    image_paths.append(latest_img)
                    print(f"📸 智能关联群内最近 {int(now - valid_recent[-1]['time'])}s 内发送的截图进行多模态分析！")

        # 清理消息中的 CQ 码，保留纯提问
        clean_text = re.sub(r"\[CQ:image,[^\]]+\]", "", user_msg)
        clean_text = re.sub(r"\[CQ:reply,[^\]]+\]", "", clean_text)
        clean_text = re.sub(r"\[CQ:at,qq=[^\]]+\]", "", clean_text).strip()

        if not clean_text and image_paths:
            clean_text = "看看这张图"
        elif not clean_text and ref_desc:
            clean_text = "你怎么看这条消息喵？"
        elif not clean_text:
            return

        # 🛡️ 1. 频率与刷屏防护 (Rate Limiting)
        allowed, cd_reason = cm.security_guard.check_rate_limit(sender_id, group_id)
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
            return

        # 🛡️ 2. 前置安全检测与注入过滤
        is_safe, sanitized_text, reject_reason = cm.security_guard.sanitize_and_inspect(clean_text, session_id=session_id)
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
            return

        user_msg = sanitized_text
        if msg_type == "group":
            prompt_text = f"【群友 {sender_name}{ref_desc}】: {user_msg}"
        else:
            prompt_text = f"{ref_desc} {user_msg}".strip() if ref_desc else user_msg

        print(f"📩 [{session_id}] 收到来自【{sender_name}】的消息: {prompt_text} (附图: {len(image_paths)})")

        # 优先处理内置快捷指令
        cmd_reply = handle_commands(session_id, user_msg, sender_id=sender_id)
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
            return

        # 🀄 专业日麻盘面多阶段视觉识别与牌理分析
        perception_report = None
        vision_msg_id = None
        extra_crops = []

        if image_paths and cm.mahjong_vision:
            try:
                loop = asyncio.get_running_loop()
                # 1. 开源专业模型 (mahjong-detector + RapidOCR) 识别盘面 + 牌理分析
                v_res = await loop.run_in_executor(None, cm.mahjong_vision.recognize, image_paths[0])
                if v_res and v_res.get("success") and v_res.get("count", 0) >= 4:
                    perception_report = cm.mahjong_vision.build_report(v_res)

                    # 2. 🚀 发送【第 1 条消息】：开源模型高精度解析完成后，立即发送规范客观报告（引用群友原提问）
                    first_msg = perception_report
                    if data.get("message_id"):
                        first_msg = f"[CQ:reply,id={data['message_id']}]{first_msg}"

                    first_payload = {
                        "message_type": msg_type,
                        "message": first_msg,
                        ("group_id" if msg_type == "group" else "user_id"): (
                            int(group_id) if msg_type == "group" else int(sender_id)
                        ),
                    }
                    print("📤 [两阶段发送] 正在推送第 1 条开源模型高精度盘面客观报告...")
                    first_resp = await call_onebot_api(
                        websocket,
                        "send_msg",
                        first_payload,
                        timeout=5.0
                    )
                    if first_resp and first_resp.get("status") == "ok":
                        vision_msg_id = (first_resp.get("data") or {}).get("message_id")
                        print(f"✅ 第 1 条客观盘面分析已成功发送！message_id={vision_msg_id}")
                    else:
                        print("⚠️ 第 1 条客观报告已发送但未收到回执 message_id")
            except Exception as e:
                print(f"⚠️ 麻将视觉分析执行异常: {e}")

        # 若识别到了麻将对局盘面，客观报告已成功发送，直接在此拦截返回
        # 绝不让大语言模型处理日麻战术或打牌决策，后续直接接入 Mortal
        if perception_report:
            print("✅ [盘面解析完成] 客观报告已送达，已停用大模型第 2 条复盘消息（后续对接 Mortal）")
            for p in list(image_paths) + extra_crops:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            return

        # 3. 🚀 准备【第 2 条消息】：把解析结果喂给群里的哈基米进行深度对局复盘评论
        llm_prompt = prompt_text
        if perception_report:
            llm_prompt = (
                f"{prompt_text}\n\n"
                f"【雀魂盘面客观数据已锁定（已作为第1条消息发送至群内）】：\n"
                f"{perception_report}\n\n"
                f"【重要提示】：第一条客观盘面报告已经发送至群内。现在请你以你的专属人设（哈基米喵~）发送【第二条消息】：针对这个手牌局况进行生动、专业、幽默或可爱的深度对局复盘评论。\n"
                f"重点分析：最优切牌推荐、攻守兼备理由、向听与改良进张、防守安牌注意点、点差攻防策略；\n"
                f"生动幽默，切记不要重复机械罗列第一条已有的手牌和点数喵！"
            )

        # 调用群聊会话大模型（哈基米），传入解析结果与原始提问
        bot_reply = await chat_with_llm(
            session_id=session_id,
            prompt_text=llm_prompt,
            raw_user_msg=user_msg,
            image_paths=[] if perception_report else image_paths,
            mention_map=mention_map,
        )
        print(f"🐱 [{session_id}] 哈基米第 2 条评论回复: {bot_reply}")

        # 5. 发送第 2 条消息：精准引用第 1 条客观分析消息！
        outgoing_msg = bot_reply
        if vision_msg_id:
            outgoing_msg = f"[CQ:reply,id={vision_msg_id}]{outgoing_msg}"
        elif cm.config.get("quote_reply", False) and data.get("message_id"):
            outgoing_msg = f"[CQ:reply,id={data['message_id']}]{outgoing_msg}"

        reply_payload = {
            "action": "send_msg",
            "params": {
                "message_type": msg_type,
                "message": outgoing_msg,
                ("group_id" if msg_type == "group" else "user_id"): (
                    int(group_id) if msg_type == "group" else int(sender_id)
                ),
            },
        }
        target_ws = active_ws if active_ws is not None else websocket
        await target_ws.send(json.dumps(reply_payload))

        # 清理临时下载的图片文件与高清放大切片
        for p in list(image_paths) + extra_crops:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    except Exception as e:
        print(f"❌ 处理消息异常: {e}")


async def ws_handler(websocket):
    global active_ws
    active_ws = websocket
    print("🟢 [NapCatQQ 已建立连接] 开始监听消息...")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if not isinstance(data, dict):
                    continue

                # 1. 响应 API 调用回调 (通过 echo 匹配 Future)
                if "echo" in data:
                    echo_key = str(data["echo"])
                    if echo_key in pending_api_futures:
                        fut = pending_api_futures[echo_key]
                        if not fut.done():
                            fut.set_result(data)
                        continue

                # 2. 忽略非聊天消息事件 (如 notice, request, meta_event 等)
                if data.get("post_type") != "message":
                    continue

                # 异步并发执行，避免单个耗时查询阻塞整个接收主循环
                asyncio.create_task(handle_single_message(websocket, data))
            except Exception as e:
                print(f"❌ 接收消息异常: {e}")
    except (ConnectionClosed, ConnectionResetError, OSError) as e:
        print(f"🟡 [NapCatQQ 连接已断开] ({e})，等待客户端自动重连...")
    finally:
        if active_ws is websocket:
            active_ws = None
        for echo_key, fut in list(pending_api_futures.items()):
            if not fut.done():
                fut.cancel()
        pending_api_futures.clear()
