import asyncio
import json
import os
import sys

# 适配终端 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from face_converter import format_bot_reply
from llm_client import chat_with_llm
from config_manager import config, personas


async def main():
    persona_key = config.get("default_persona", "hajimi")
    persona_data = personas.get(persona_key, {})
    persona_name = persona_data.get("name", persona_key)
    backend = config.get("backend", "api")
    model = config.get("gemini_model") or config.get("default_model", "gemini-3.5-flash-lite")

    print("=" * 55)
    print("🐾 [哈基米测试] 正在启动连通性测试...")
    print(f"⚙️ 当前运行模式: {backend}")
    print(f"🎭 当前人设：{persona_name} ({persona_key})")
    print(f"🧠 模型档位：{model}")
    print("=" * 55)

    test_prompt = "哈基米你好！你是一只什么样的小猫咪呀？你会打麻将吗？"
    print(f"\n🙋 测试提问: {test_prompt}\n")

    raw_reply = await chat_with_llm(
        user_id="test_user",
        user_msg=test_prompt,
        user_name="测试员",
        group_id="test_group",
        persona_key=persona_key,
    )

    formatted_reply = format_bot_reply(raw_reply)
    print("🐱 [哈基米回复]:\n")
    print(formatted_reply)
    print("\n" + "=" * 55)
    print("🎉 测试成功！Gemini 与哈基米人设完全正常！")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
