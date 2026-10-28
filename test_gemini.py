"""
用于独立测试 Gemini API 连通性与“哈基米”人设效果的轻量测试脚本。
无需启动 NapCatQQ，直接在终端中运行：
    python test_gemini.py
"""
import asyncio
import json
import os
import httpx
from openai import AsyncOpenAI

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

    api_key = config.get("gemini_api_key", "").strip()
    if not api_key or api_key == "YOUR_GEMINI_API_KEY":
        print("⚠️ 提示：你尚未在 config.json 中填入有效的 gemini_api_key！")
        print("请打开 config.json 填入你的 Google AI Studio API Key 后再试。")
        return

    persona_key = config.get("default_persona", "hajimi")
    persona_data = personas.get(persona_key, {})
    system_prompt = persona_data.get("prompt", "你是一个友好的AI。")
    persona_name = persona_data.get("name", persona_key)

    proxy_url = config.get("proxy_url")
    http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        http_client=http_client,
    )

    print("=" * 50)
    print("🐾 [哈基米测试] 正在连接 Gemini Pro API...")
    print(f"🎭 当前人设：{persona_name} ({persona_key})")
    print(f"🧠 模型名称：{config.get('gemini_model', 'gemini-1.5-pro')}")
    print(f"⚡ 代理设置：{proxy_url if proxy_url else '直连'}")
    print("=" * 50)

    test_prompt = "哈基米你好！你是一只什么样的小猫咪呀？你会打麻将吗？"
    print(f"\n🙋 测试提问: {test_prompt}\n")

    try:
        response = await client.chat.completions.create(
            model=config.get("gemini_model", "gemini-1.5-pro"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": test_prompt},
            ],
            temperature=0.8,
        )
        reply = response.choices[0].message.content.strip()
        print("🐱 [哈基米回复]:\n")
        print(reply)
        print("\n" + "=" * 50)
        print("🎉 测试成功！Gemini API 与人设配置完全正常！")
        print("=" * 50)
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("\n💡 排查建议：")
        print("1. 检查 config.json 中的 gemini_api_key 是否正确")
        print("2. 如果在国内网络，请确保 proxy_url 端口开启且能正常科学上网（如 Clash 默认为 http://127.0.0.1:7890）")


if __name__ == "__main__":
    asyncio.run(main())
