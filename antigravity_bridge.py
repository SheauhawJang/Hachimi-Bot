"""
Antigravity 本地会员桥接器 (Antigravity Bridge)
直接调用本地正在运行的 Antigravity 语言服务器，100% 消耗用户的 Google AI Pro 会员额度。
完全零额外扣费，无 5 RPM / 500 RPD 限制！
"""
import asyncio
import json
import os
import time

EXE = r"C:\Users\Sheauhaw\AppData\Local\Programs\antigravity\resources\bin\language_server.exe"
BRAIN_DIR = r"C:\Users\Sheauhaw\.gemini\antigravity\brain"


async def chat_via_antigravity(
    system_prompt: str,
    history: list,
    user_msg: str,
    model: str = "flash",
    timeout: float = 12.0,
) -> str:
    # 组装上下文
    prompt_parts = [
        f"【角色设定】\n{system_prompt}\n",
    ]
    if history:
        prompt_parts.append("【近期对话历史】")
        for turn in history[-6:]:
            role = "群友" if turn.get("role") == "user" else "哈基米"
            prompt_parts.append(f"{role}: {turn.get('content')}")
        prompt_parts.append("")

    prompt_parts.append(f"【当前群友消息】\n{user_msg}\n")
    prompt_parts.append("请保持哈基米设定直接回复，无需输出多余客套：")

    full_prompt = "\n".join(prompt_parts)

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
        stdout, stderr = await proc.communicate()
        out_str = stdout.decode("utf-8", errors="ignore").strip()

        data = json.loads(out_str)
        conv_id = data["response"]["newConversation"]["conversationId"]
    except Exception as e:
        return f"【Antigravity 本地桥接异常】: {e}"

    transcript_path = os.path.join(
        BRAIN_DIR, conv_id, ".system_generated", "logs", "transcript.jsonl"
    )

    start_time = time.time()
    while time.time() - start_time < timeout:
        await asyncio.sleep(0.4)
        if os.path.exists(transcript_path):
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line in f:
                        obj = json.loads(line)
                        if (
                            obj.get("step_index") == 1
                            and obj.get("type") == "PLANNER_RESPONSE"
                        ):
                            content = obj.get("content")
                            if content:
                                return content.strip()
            except Exception:
                pass

    return "【哈基米打了个盹】：等待 Antigravity 响应超时，请重试喵~"
