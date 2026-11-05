"""
Telegram 通信适配层模块 (由 main.py 统一挂载启动)
100% 复用 main.py 的大模型调用、人设系统、会话记忆、指令处理与安全防护，
仅负责与 Telegram Bot API 进行网络通信（支持本地代理与反代域名）。
"""
import asyncio
import json
import os
import re
import time
import httpx


class TelegramBotClient:
    def __init__(self, token: str, api_base: str, proxy: str | None = None):
        self.token = token
        self.api_base = api_base
        self.proxy = proxy
        self.client = httpx.AsyncClient(
            proxy=proxy,
            timeout=httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=15.0),
        )
        self.bot_info = {}

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{self.api_base}/file/bot{self.token}/{file_path}"

    async def get_me(self) -> dict:
        resp = await self.client.get(self._url("getMe"))
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"获取 Bot 基础信息失败: {data}")
        self.bot_info = data.get("result", {})
        return self.bot_info

    async def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict]:
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["message"]),
        }
        resp = await self.client.post(self._url("getUpdates"), json=params)
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []

    async def send_chat_action(self, chat_id: int | str, action: str = "typing"):
        try:
            await self.client.post(self._url("sendChatAction"), json={"chat_id": chat_id, "action": action})
        except Exception:
            pass

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str = "Markdown",
    ):
        url = self._url("sendMessage")
        payload = {"chat_id": chat_id, "text": text}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = await self.client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return data
            # 若 Markdown 特殊字符未闭合导致 400，自动降级为纯文本发送
            if parse_mode:
                payload.pop("parse_mode", None)
                fallback_resp = await self.client.post(url, json=payload)
                return fallback_resp.json()
        except Exception as e:
            print(f"⚠️ 发送 TG 消息异常: {e}")
        return None

    async def download_file_by_id(self, file_id: str, temp_img_dir: str) -> str | None:
        """通过 TG getFile 接口下载图片到 TEMP_IMG_DIR"""
        try:
            resp = await self.client.post(self._url("getFile"), json={"file_id": file_id})
            data = resp.json()
            if not data.get("ok"):
                return None
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                return None

            ext = os.path.splitext(file_path)[1] or ".jpg"
            local_path = os.path.join(temp_img_dir, f"tg_{int(time.time())}_{file_id[:8]}{ext}")
            dl_resp = await self.client.get(self._file_url(file_path))
            if dl_resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(dl_resp.content)
                return local_path
        except Exception as e:
            print(f"⚠️ 下载 Telegram 图片异常: {e}")
        return None

    async def close(self):
        await self.client.aclose()


async def keep_typing(tg: TelegramBotClient, chat_id: int | str, stop_event: asyncio.Event):
    while not stop_event.is_set():
        await tg.send_chat_action(chat_id, "typing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.5)
        except asyncio.TimeoutError:
            pass


async def handle_tg_message(tg: TelegramBotClient, msg: dict, core):
    """处理单条 Telegram 消息并复用 main.py 的核心管道"""
    try:
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = chat.get("type")  # "private", "group", "supergroup"
        sender = msg.get("from", {})
        sender_id = str(sender.get("id", ""))
        sender_name = sender.get("first_name") or sender.get("username") or f"用户_{sender_id}"
        message_id = msg.get("message_id")

        raw_text = (msg.get("text") or msg.get("caption") or "").strip()
        photos = msg.get("photo")
        is_private = (chat_type == "private")
        group_key = f"tg_{chat_id}" if not is_private else ""

        # 下载图片并缓存（复用 main.py 的 recent_group_images 3分钟上下文看图机制）
        image_paths = []
        if photos and isinstance(photos, list):
            file_id = photos[-1].get("file_id")
            if file_id:
                local_img = await tg.download_file_by_id(file_id, core.TEMP_IMG_DIR)
                if local_img:
                    image_paths.append(local_img)
                    if group_key:
                        core.recent_group_images.setdefault(group_key, []).append(
                            {"time": time.time(), "path": local_img}
                        )
                        core.recent_group_images[group_key] = core.recent_group_images[group_key][-5:]

        # 判断触发条件（私聊直回；群聊需 @机器人 或 回复机器人消息）
        bot_username = tg.bot_info.get("username", "")
        bot_id = tg.bot_info.get("id")
        should_reply = False
        user_msg = raw_text

        if is_private:
            session_id = f"tg_private_{chat_id}"
            should_reply = True
        else:
            session_id = f"tg_group_{chat_id}"
            mention_token = f"@{bot_username}"
            reply_to = msg.get("reply_to_message", {})
            if mention_token and mention_token.lower() in user_msg.lower():
                should_reply = True
                user_msg = re.sub(re.escape(mention_token), "", user_msg, flags=re.IGNORECASE).strip()
            elif reply_to.get("from", {}).get("id") == bot_id:
                should_reply = True

        if not should_reply:
            return

        # 提取 Telegram 引用详情（被引用人、文本及图片）
        ref_desc = ""
        if reply_to:
            ref_sender = reply_to.get("from", {})
            ref_uid = str(ref_sender.get("id", ""))
            ref_name = ref_sender.get("first_name") or ref_sender.get("username") or f"用户_{ref_uid}"
            if str(bot_id) and ref_uid == str(bot_id):
                bot_display_name = core.personas_data.get("personas", {}).get(core.current_persona_key, {}).get("name", "哈基米")
                ref_name = f"{bot_display_name}(我)"
            ref_text = (reply_to.get("text") or reply_to.get("caption") or "").strip()
            ref_photos = reply_to.get("photo")

            # 若提问自身未带图，但引用的消息带有图片，自动下载引用的图片
            if not image_paths and ref_photos and isinstance(ref_photos, list):
                rf_id = ref_photos[-1].get("file_id")
                if rf_id:
                    local_img = await tg.download_file_by_id(rf_id, core.TEMP_IMG_DIR)
                    if local_img and local_img not in image_paths:
                        image_paths.append(local_img)

            if len(ref_text) > 180:
                ref_text = ref_text[:180] + "..."
            img_tag = " [含图片]" if ref_photos else ""
            if ref_text:
                ref_desc = f"（引用了 {ref_name} 的消息：“{ref_text}”{img_tag}）"
            elif ref_photos:
                ref_desc = f"（引用了 {ref_name} 发送的图片）"
            else:
                ref_desc = f"（引用了 {ref_name} 的消息）"

        # 智能图片回溯（与 QQ 群一致：如果没直接带图，但明确说了“何切/怎么打”等看图词，自动关联群内最近图片）
        if not image_paths and group_key in core.recent_group_images:
            now = time.time()
            valid_recent = [img for img in core.recent_group_images[group_key] if now - img["time"] < 180]
            vision_triggers = ["何切", "看图", "手牌", "牌局", "怎么打", "打哪", "识别", "这把", "这手", "这局", "牌"]
            if any(w in user_msg for w in vision_triggers) and valid_recent:
                latest_img = valid_recent[-1]["path"]
                if os.path.exists(latest_img):
                    image_paths.append(latest_img)

        # 如果没有输入文字，但发送了图片或引用了发言，交由模型通用多模态能力自然解析
        if not user_msg and image_paths:
            user_msg = "看看这张图"
        elif not user_msg and ref_desc:
            user_msg = "你怎么看这条消息喵？"
        elif not user_msg:
            return

        # 复用 main.py 的频率限制与安全过滤
        allowed, cd_reason = core.security_guard.check_rate_limit(sender_id, group_key)
        if not allowed:
            if cd_reason:
                await tg.send_message(chat_id, cd_reason, reply_to_message_id=message_id)
            return

        is_safe, sanitized_text, reject_reason = core.security_guard.sanitize_and_inspect(user_msg, session_id=session_id)
        if not is_safe:
            print(f"🛡️ [TG 拦截输入] 来自【{sender_name}】({sender_id}): {reject_reason}")
            await tg.send_message(chat_id, sanitized_text, reply_to_message_id=message_id)
            return

        user_msg = sanitized_text
        prompt_text = (
            f"【群友 {sender_name}{ref_desc}】: {user_msg}"
            if not is_private
            else (f"{ref_desc} {user_msg}".strip() if ref_desc else user_msg)
        )
        print(f"📩 [{session_id}] 收到来自【{sender_name}】的消息: {prompt_text} (附图: {len(image_paths)})")

        # 复用 main.py 的内置快捷指令
        cmd_reply = core.handle_commands(session_id, user_msg, sender_id=sender_id)
        if cmd_reply:
            await tg.send_message(chat_id, cmd_reply, reply_to_message_id=message_id)
            return

        # 🀄 专业日麻盘面多阶段视觉识别与牌理分析
        perception_report = None
        vision_msg_id = None
        extra_crops = []

        if image_paths and getattr(core, "mahjong_vision", None):
            try:
                loop = asyncio.get_running_loop()
                # 1. 开源专业模型 (mahjong-detector + RapidOCR) 识别盘面 + 牌理分析
                v_res = await loop.run_in_executor(None, core.mahjong_vision.recognize, image_paths[0])
                if v_res and v_res.get("success") and v_res.get("count", 0) >= 4:
                    perception_report = core.mahjong_vision.build_report(v_res)

                    # 2. 🚀 发送【第 1 条消息】：开源模型高精度解析完成后，立即发送规范客观报告（引用群友原提问）
                    print("📤 [TG 两阶段发送] 正在推送第 1 条开源模型高精度盘面客观报告...")
                    first_tg_res = await tg.send_message(
                        chat_id,
                        perception_report,
                        reply_to_message_id=message_id,
                        parse_mode=None  # 纯文本避免特殊字符报错
                    )
                    if first_tg_res and first_tg_res.get("ok"):
                        vision_msg_id = first_tg_res.get("result", {}).get("message_id")
                        print(f"✅ TG 第 1 条客观盘面分析已成功发送！message_id={vision_msg_id}")
            except Exception as e:
                print(f"⚠️ TG 麻将视觉分析执行异常: {e}")

        # 若识别到了麻将对局盘面，客观报告已成功发送，直接在此拦截返回
        # 绝不让大语言模型处理日麻战术或打牌决策，后续直接接入 Mortal
        if perception_report:
            print("✅ [TG 盘面解析完成] 客观报告已送达，已停用大模型第 2 条复盘消息（后续对接 Mortal）")
            for cp in extra_crops:
                try:
                    if os.path.exists(cp):
                        os.remove(cp)
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
                f"【第二条消息输出要求】：\n"
                f"现在请你以你的专属人设（哈基米喵~）发送【第二条消息】：针对这个手牌局况进行生动、专业、幽默或可爱的深度对局复盘评论。\n"
                f"重点分析：最优切牌推荐、攻守兼备理由、向听与改良进张、防守安牌注意点、点差攻防策略；\n"
                f"生动幽默，切记不要重复机械罗列第一条已有的手牌和点数喵！"
            )

        # 后台显示“正在输入...”并复用 main.py 的 chat_with_llm (若已有盘面报告，无需再传原图，彻底杜绝多模态幻觉)
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(tg, chat_id, stop_typing))
        try:
            bot_reply = await core.chat_with_llm(
                session_id=session_id,
                prompt_text=llm_prompt,
                raw_user_msg=user_msg,
                image_paths=[] if perception_report else image_paths,
                platform="telegram",
            )
        finally:
            stop_typing.set()
            await typing_task
            # 清理切片
            for cp in extra_crops:
                try:
                    if os.path.exists(cp):
                        os.remove(cp)
                except Exception:
                    pass

        print(f"🐱 [{session_id}] 哈基米回复: {bot_reply[:80]}...")
        # 🔗 消息互相引用：第二条评论精准引用第一条盘面分析消息！
        target_reply_id = vision_msg_id if vision_msg_id else message_id
        await tg.send_message(chat_id, bot_reply, reply_to_message_id=target_reply_id)

    except Exception as e:
        print(f"❌ 处理 TG 消息异常: {e}")


async def start_telegram_service(core):
    """由 main.py 调用的 Telegram 异步后台服务"""
    bot_token = core.config.get("telegram_bot_token", "").strip()
    api_base_url = core.config.get("telegram_api_base_url", "https://api.telegram.org").rstrip("/")
    proxy_url = core.config.get("proxy_url")

    if not bot_token or "YOUR_" in bot_token:
        print("⚪ [Telegram 通道未启用] (如需同时启用 TG 机器人，请在 config.json 填写 telegram_bot_token)")
        return

    tg = TelegramBotClient(token=bot_token, api_base=api_base_url, proxy=proxy_url)
    try:
        bot_info = await tg.get_me()
        print(
            f"🟢 [Telegram 已建立连接] Bot: @{bot_info.get('username')} "
            f"(API: {api_base_url}, 代理: {proxy_url or '直连'})"
        )
    except Exception as e:
        print(f"❌ [Telegram 连接失败] {e} (请检查 proxy_url 或 telegram_api_base_url)")
        await tg.close()
        return

    offset = 0
    try:
        while True:
            try:
                updates = await tg.get_updates(offset=offset, timeout=30)
                for u in updates:
                    offset = max(offset, u.get("update_id", 0) + 1)
                    if "message" in u:
                        asyncio.create_task(handle_tg_message(tg, u["message"], core))
            except httpx.ReadTimeout:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [TG 轮询异常] {e}，3 秒后重试...")
                await asyncio.sleep(3)
    finally:
        await tg.close()
