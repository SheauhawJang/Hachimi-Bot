"""
Antigravity 本地会员桥接器 (Antigravity Bridge)
直接基于 Antigravity 原生会话上下文机制：
每个 QQ 群/私聊绑定一个持久的 Antigravity 会话 (Conversation)，由模型上下文机制自动维系记忆。
完全零额外扣费，无 5 RPM / 500 RPD 限制！
"""
import asyncio
import json
import os
import time

EXE = r"C:\Users\Sheauhaw\AppData\Local\Programs\antigravity\resources\bin\language_server.exe"
BRAIN_DIR = r"C:\Users\Sheauhaw\.gemini\antigravity\brain"


def _get_max_step(transcript_path: str) -> int:
    """获取当前 transcript 的最大 step_index"""
    max_step = -1
    if not os.path.exists(transcript_path):
        return max_step
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    idx = obj.get("step_index", -1)
                    if idx > max_step:
                        max_step = idx
                except Exception:
                    pass
    except Exception:
        pass
    return max_step


async def send_to_antigravity(
    conv_id: str | None,
    user_msg: str,
    system_prompt: str,
    model: str = "flash",
    timeout: float = 25.0,
) -> tuple[str, str]:
    """
    发送消息到 Antigravity。
    如果 conv_id 为空或不存在，自动开启新会话 (new-conversation)。
    如果 conv_id 存在，直接在现有会话中追加消息 (send-message)，由底层原生上下文机制自动维护记忆。
    返回: (reply_text, active_conv_id)
    """
    transcript_path = None
    if conv_id:
        transcript_path = os.path.join(
            BRAIN_DIR, conv_id, ".system_generated", "logs", "transcript.jsonl"
        )
        if not os.path.exists(transcript_path):
            conv_id = None  # 原会话文件不存在，自动重建

    if not conv_id:
        # 开启新会话
        full_prompt = (
            f"【系统设定】\n{system_prompt}\n\n"
            f"【群消息】\n{user_msg}\n\n"
            f"请保持哈基米设定直接回复群友："
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                EXE,
                "agentapi",
                "new-conversation",
                f"--model={model}",
                full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode("utf-8", errors="ignore").strip())
            conv_id = data["response"]["newConversation"]["conversationId"]
            transcript_path = os.path.join(
                BRAIN_DIR, conv_id, ".system_generated", "logs", "transcript.jsonl"
            )
            target_min_step = 1
        except Exception as e:
            return f"【Antigravity 启动会话失败】: {e}", ""
    else:
        # 在已有会话中继续对话
        last_step = _get_max_step(transcript_path)
        target_min_step = last_step + 1

        try:
            proc = await asyncio.create_subprocess_exec(
                EXE,
                "agentapi",
                "send-message",
                conv_id,
                user_msg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            return f"【Antigravity 发送消息失败】: {e}", conv_id

    # 轮询等待模型回复生成
    start_time = time.time()
    while time.time() - start_time < timeout:
        await asyncio.sleep(0.4)
        if not os.path.exists(transcript_path):
            continue

        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    step_index = obj.get("step_index", -1)
                    step_type = obj.get("type")
                    status = obj.get("status")

                    if step_index >= target_min_step and step_type == "PLANNER_RESPONSE":
                        # 当状态完成或已有内容时提取
                        content = obj.get("content")
                        if content and content.strip():
                            return content.strip(), conv_id

                        # 如果模型通过 inter-agent send_message 工具回复
                        tool_calls = obj.get("tool_calls", [])
                        for tc in tool_calls:
                            if tc.get("name") == "send_message":
                                msg = tc.get("args", {}).get("Message")
                                if msg:
                                    if msg.startswith('"') and msg.endswith('"'):
                                        msg = msg[1:-1]
                                    return msg.strip(), conv_id
        except Exception:
            pass

    return "【哈基米打了个盹】：等待 Antigravity 响应超时喵~", conv_id
