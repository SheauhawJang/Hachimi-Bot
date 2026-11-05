"""
指令解析与分发处理模块 (Command Handler)
支持：
1. /help, 菜单, 帮助
2. /reset, 重置记忆
3. /persona 人设查看与切换
4. /model 会话/全局模型查看与切换 (管理员鉴权)
"""

import config_manager as cm


def handle_commands(session_id: str, text: str, sender_id: str = "") -> str | None:
    cmd = text.strip()

    if cmd in ["/start", "/help", "帮助", "菜单"]:
        cur_name = cm.personas_data["personas"].get(cm.current_persona_key, {}).get("name", cm.current_persona_key)
        mode_desc = "Gemini Web (多模态识图 / 自动Cookie刷新)" if cm.backend == "gemini_web" else "Antigravity Pro 沙箱"
        default_m = cm.config.get("default_model", "gemini-3.5-flash-lite")
        cur_session_m = cm.session_models.get(session_id, default_m)
        return (
            f"🐾 【哈基米 & 麻将多模态助手】\n"
            f"当前人设：{cur_name}\n"
            f"当前模型：{cur_session_m}（会话独立）\n"
            f"驱动核心：{mode_desc}\n"
            f"---------------------------\n"
            f"💬 @我 发送文字或麻将截图即可对话/分析何切\n"
            f"🔄 /reset ：清空本群当前的上下文记忆，开启新话题\n"
            f"🎭 /persona ：查看或切换人设（如 /persona hajimi）\n"
            f"🤖 /model ：查看或切换当前群/会话的大模型（管理员指令）\n"
            f"---------------------------"
        )

    if cmd in ["/reset", "重置记忆", "清空上下文", "新会话"]:
        if cm.backend == "gemini_web" and cm.web_bridge:
            cm.web_bridge.reset_chat(session_id)
        cm.session_mgr.reset_session(session_id)
        return "✨ 本群的原生会话记忆已全部清空，开启全新对话喵！"

    if cmd.startswith("/persona"):
        parts = cmd.split()
        if len(parts) > 1 and parts[1] in cm.personas_data["personas"]:
            cm.set_current_persona(parts[1])
            if cm.backend == "gemini_web" and cm.web_bridge:
                cm.web_bridge.reset_chat(session_id)
            cm.session_mgr.reset_session(session_id)
            p_name = cm.personas_data["personas"][cm.current_persona_key]["name"]
            return f"🎭 人设已成功切换为：【{p_name}】！本群会话已自动重置以应用新人设。"
        else:
            cur_name = cm.personas_data["personas"].get(cm.current_persona_key, {}).get("name", "默认")
            lines = [f"当前人设：【{cur_name}】", "可用人设列表："]
            for k, v in cm.personas_data["personas"].items():
                lines.append(f"  • `{k}` : {v['name']}")
            lines.append("\n切换指令示例：/persona hajimi")
            return "\n".join(lines)

    if cmd.startswith("/model"):
        parts = cmd.split()
        supported_models = {
            "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite（系统默认主力，超低延迟、极度省额度）",
            "gemini-3.8-flash": "Gemini 3.8 Flash（高阶联网推理，查比赛查资讯最准，推荐）",
            "gemini-3.8-flash-high": "Gemini 3.8 Flash 深度思考（高阶 Thinking 展开，逻辑推导极强）",
            "gemini-3.8-flash-medium": "Gemini 3.8 Flash 标准思考（中度 Thinking 思考链）",
            "claude-opus": "Claude Opus 5.5 High（顶尖复杂推理与长文本思维链，实测可用）",
            "claude-sonnet": "Claude Sonnet 5.5 Medium（极佳代码逻辑与分析能力，实测可用）",
            "gpt-oss-120b": "GPT-OSS 120B Medium（开源大模型专项）",
            "gemini-3-flash": "Gemini 3 Flash（标准 Flash）",
        }
        model_aliases = {
            "opus": "claude-opus",
            "sonnet": "claude-sonnet",
            "flash": "gemini-3.8-flash",
            "lite": "gemini-3.5-flash-lite",
            "3.5": "gemini-3.5-flash-lite",
            "3.8": "gemini-3.8-flash",
            "think": "gemini-3.8-flash-high",
            "thinking": "gemini-3.8-flash-high",
            "3.8-high": "gemini-3.8-flash-high",
            "3.8-think": "gemini-3.8-flash-high",
            "3.8-medium": "gemini-3.8-flash-medium",
            "oss": "gpt-oss-120b",
        }
        default_m = cm.config.get("default_model", "gemini-3.5-flash-lite")
        cur_session_m = cm.session_models.get(session_id, default_m)

        # 1. 仅查看指令 (无参数)
        if len(parts) == 1:
            lines = [
                f"当前会话运行模型：【{cur_session_m}】（会话独立）",
                f"系统全局默认模型：【{default_m}】",
                "\n可用模型列表："
            ]
            for m_id, m_desc in supported_models.items():
                lines.append(f"  • `{m_id}`\n    └ {m_desc}")
            lines.append("\n💡 提示：管理员发送 `/model <模型名>` 可切换本群模型；发送 `/model global <模型名>` 可切换全局默认。")
            return "\n".join(lines)

        # 2. 权限审查：只有管理员白名单才允许变更模型
        admin_users = [str(u) for u in cm.config.get("admin_users", []) + cm.config.get("telegram_admin_users", [])]
        owner_id = str(cm.config.get("owner_id", ""))
        is_admin = (not sender_id) or (sender_id in admin_users) or (sender_id == owner_id)
        if not is_admin:
            return "喵？只有主人/管理员才可以调整本猫的大模型核心喵！爪子拍开你的手.jpg 🐾😼"

        # 3. 管理员切换模型
        is_global = False
        target_arg = parts[1].lower()
        if target_arg in ["global", "全局"] and len(parts) > 2:
            is_global = True
            target_arg = parts[2].lower()

        target = model_aliases.get(target_arg, target_arg)
        if target in supported_models:
            if is_global:
                cm.config["default_model"] = target
                cm.config["gemini_model"] = target
                try:
                    cm.save_config(cm.config)
                except Exception:
                    pass
                return f"🌐 [全局切换成功] 默认基础模型已变更为：【{target}】！\n说明：{supported_models[target]}"
            else:
                cm.session_models[session_id] = target
                cm.save_session_models(cm.session_models)
                return (
                    f"🤖 [会话模型已切换] 当前会话（群/私聊）已绑定模型：【{target}】！\n"
                    f"说明：{supported_models[target]}\n"
                    f"💡 本次设置仅对本会话生效，其他群保持默认独立，完全不冲突喵~"
                )
        else:
            return f"⚠️ 未识别的模型名称「{target_arg}」。发送 `/model` 可查看支持的模型列表喵~"

    return None
