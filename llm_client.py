"""
大语言模型调用适配器 (LLM Client & Chat Adapter)
支持：
1. Gemini Web 网页版反代 (多模态识图与自动刷新)
2. Antigravity Pro 本地沙箱通道
3. OpenAI 兼容接口通道 (Gemini API / One API 反代)
4. 输出安全审查过滤与 QQ 表情/思维链转换
"""

import os
import time
import base64
import asyncio
import mimetypes
import config_manager as cm
from face_converter import format_bot_reply, THINK_PATTERN
from antigravity_bridge import send_to_antigravity


def image_to_data_url(image_path: str) -> str:
    """将本地图片文件编码为 OpenAI/Gemini 兼容的 Base64 Data URL"""
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
    platform: str = "qq",
    mention_map: dict[str, str] | None = None,
) -> str:
    default_m = cm.config.get("default_model", cm.config.get("gemini_model", "gemini-3.5-flash-lite"))
    model = cm.session_models.get(session_id, default_m)

    try:
        if cm.backend == "gemini_web":
            # 走 Gemini Web 网页版通道
            raw_reply = await cm.web_bridge.send_message(
                session_id=session_id,
                prompt=prompt_text,
                image_paths=image_paths,
                system_prompt=cm.current_system_prompt,
            )
        elif cm.backend == "antigravity":
            # 走本地 Antigravity 物理沙箱通道
            conv_id = cm.session_mgr.get_conv_id(session_id)
            raw_reply, new_conv_id = await send_to_antigravity(
                conv_id=conv_id,
                user_msg=prompt_text,
                system_prompt=cm.current_system_prompt,
                model=model,
            )
            if new_conv_id:
                cm.session_mgr.set_conv_id(session_id, new_conv_id)
        else:
            # 走反代理 API (OpenAI 兼容模式)
            history = cm.session_mgr.get_history(session_id)
            sys_content = (
                cm.current_system_prompt + cm.QQ_SAFETY_CONTRACT
                if platform == "qq"
                else cm.current_system_prompt
            )
            messages = [{"role": "system", "content": sys_content}]
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
            if cm.config.get("enable_web_search", False):
                req_params["extra_body"] = {"web_search": True}

            try:
                response = await asyncio.wait_for(
                    cm.client.chat.completions.create(**req_params),
                    timeout=35.0,
                )
                raw_reply = response.choices[0].message.content.strip()
            except asyncio.TimeoutError:
                print(f"⏱️ [模型调用超时] {session_id} 请求超过 35 秒未返回")
                raw_reply = "[爪子挠头] 喵呜？刚才联网检索或模型思考超时啦，网速太慢了喵！群友请再试一次喵~"

            # 记录本轮对话到历史
            hist_text = prompt_text + (" [发送了图片附件]" if image_paths else "")
            cm.session_mgr.add_message(session_id, "user", hist_text)
            cm.session_mgr.add_message(session_id, "assistant", raw_reply)

        if platform == "qq":
            # 经过表情与思维链清洗管道处理为最终 QQ 发送格式
            formatted_reply = format_bot_reply(raw_reply, mention_map=mention_map)
            # 🛡️ 经过输出敏感词后置熔断审查
            is_safe, final_reply, reject_reason = cm.security_guard.inspect_output(formatted_reply, session_id=session_id)
            return final_reply
        else:
            # Telegram 等支持原生 Markdown 的平台：仅清洗思维链标签，保留原生排版与 Emoji
            return THINK_PATTERN.sub("", raw_reply).strip()
    except Exception as e:
        err_msg = str(e)
        print(f"❌ [模型调用错误]: {err_msg}")
        cur_m = cm.config.get("gemini_model", "")
        hint = ""
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "404" in err_msg:
            hint = f"\n💡 [提示] 当前模型「{cur_m}」配额暂未开放或达到上限，可通过发送 `/model gemini-3.8-flash` 手动切回推荐模型喵~"
        return f"【对话出错】：{err_msg}{hint}"


async def audit_mahjong_vision_report(
    image_paths: list[str],
    draft_report: str,
    raw_mpsz: str = "",
    model: str | None = None,
) -> str:
    """单独走一个独立的专业视觉多模态会话，专门解析与审计麻将盘面，输出最准确的第一条客观报告"""
    if not model:
        model = cm.config.get("default_model", cm.config.get("gemini_model", "gemini-3.5-flash-lite"))

    sys_prompt = (
        "你是一个精通日本麻将规则的专业盘面视觉审计员。\n"
        "你的任务是结合原图与高清切片，对本地初稿进行视觉审计并直接输出最终规范的【第一条客观盘面报告】。\n"
        "严禁任何角色扮演或多余闲聊，严禁出现“来自自家”等违背日麻规则的错误，保持标准客观格式。\n"
        "尾部固定带上：🐾 盘面数据已锁定，正在呼叫哈基米进行深度对局复盘，分析中喵..."
    )
    user_prompt = (
        "【本地轻量视觉初稿】：\n"
        f"{draft_report}\n\n"
        "【审计指示】：请仔细观察附带的原图（图1）、四家牌河与仪表盘高清特写（图2）、副露高清特写（图3），"
        "严格核准副露细节（3张一组、出牌来源；根据日麻规则，任何人绝不可鸣自己）、四家点数与舍牌，直接输出最终规范客观的【第一条盘面报告】。"
    )

    try:
        if cm.backend == "gemini_web":
            temp_session_id = f"vision_audit_{int(time.time()*1000)}"
            audited = await cm.web_bridge.send_message(
                session_id=temp_session_id,
                prompt=user_prompt,
                image_paths=image_paths,
                system_prompt=sys_prompt,
            )
            return THINK_PATTERN.sub("", audited).strip()
        elif cm.backend == "antigravity":
            audited, _ = await send_to_antigravity(
                conv_id=None,
                user_msg=user_prompt,
                system_prompt=sys_prompt,
                model=model,
            )
            return THINK_PATTERN.sub("", audited).strip()
        else:
            content_blocks = [{"type": "text", "text": user_prompt}]
            for p in image_paths:
                if os.path.exists(p):
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": image_to_data_url(p)}
                    })
            resp = await asyncio.wait_for(
                cm.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": content_blocks}
                    ],
                    temperature=0.1
                ),
                timeout=25.0
            )
            audited = resp.choices[0].message.content
            return THINK_PATTERN.sub("", audited).strip()
    except Exception as e:
        print(f"⚠️ 视觉多模态审计会话异常，回退本地初稿: {e}")
        return draft_report
