"""
用于独立测试哈基米机器人连通性与人设效果的测试脚本。
支持：
1. Antigravity Pro 会员通道 (backend="antigravity", 0额外扣费，无RPD限制)
2. 外部 API 模式 (backend="api")

终端直接运行：
    python test_gemini.py
"""
import asyncio
import json
import os
import sys
import httpx
from openai import AsyncOpenAI
from face_converter import format_bot_reply
from antigravity_bridge import chat_via_antigravity

# 适配 Windows 控制台输出 UTF-8 / Emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PERSONAS_FILE = os.path.join(BASE_DIR, "personas.json")


async def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 找不到配置文件: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    with open(PERSONAS_FILE, "r", encoding="utf-8") as f:
        personas = json.load(f)["personas"]

    backend = config.get("backend", "antigravity")
    persona_key = config.get("default_persona", "hajimi")
    persona_data = personas.get(persona_key, {})
    system_prompt = persona_data.get("prompt", "你是一个友好的AI。")
    persona_name = persona_data.get("name", persona_key)
    model = config.get("gemini_model", "flash")

    print("=" * 55)
    print("🐾 [哈基米测试] 正在启动连通性测试...")
    mode_desc = "🚀 Antigravity Pro 会员本地直通车 (0扣费·无RPD限制)" if backend == "antigravity" else "🌐 外部 API 模式"
    print(f"⚙️ 当前运行模式: {mode_desc}")
    print(f"🎭 当前人设：{persona_name} ({persona_key})")
    print(f"🧠 模型档位：{model}")
    print("=" * 55)

    test_prompt = "哈基米你好！你是一只什么样的小猫咪呀？你会打麻将吗？"
    print(f"\n🙋 测试提问: {test_prompt}\n")

    if backend == "antigravity":
        # 走本地 Antigravity 会员通道
        print("⏳ 正在通过本地 Antigravity 语言服务器生成回复...")
        raw_reply = await chat_via_antigravity(
            system_prompt=system_prompt,
            history=[],
            user_msg=test_prompt,
            model=model,
        )
    else:
        # 走外部 API
        api_key = config.get("gemini_api_key", "").strip()
        proxy_url = config.get("proxy_url")
        http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
        base_url = config.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai/"

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": test_prompt},
            ],
            temperature=0.8,
        )
        raw_reply = response.choices[0].message.content.strip()

    formatted_reply = format_bot_reply(raw_reply)
    print("🐱 [哈基米回复]:\n")
    print(formatted_reply)
    print("\n" + "=" * 55)
    print("🎉 测试成功！Antigravity Pro 会员通道与哈基米人设完全正常！")
    print("=" * 55)


if __name__ == "__main__":
    asyncio.run(main())
