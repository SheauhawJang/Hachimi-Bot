import asyncio
import os
import sys

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from antigravity_bridge import send_to_antigravity

async def main():
    print("=== 测试 Antigravity 群原生会话机制 ===")
    system_prompt = "你是QQ群宠物哈基米，一只毒舌傲娇的表情包猫猫。懂麻将，喜欢小鱼干。"
    
    # 第 1 轮：新建会话
    print("\n--- 第 1 轮 ---")
    msg1 = "【群友 菠萝吹雪】: 哈基米，本大侠今天打四川麻将胡了一把清一色极品大对子！"
    reply1, conv_id = await send_to_antigravity(None, msg1, system_prompt)
    print(f"会话 ID: {conv_id}")
    print(f"哈基米回复: {reply1}")

    # 第 2 轮：在同一个会话中继续（测试上下文记忆）
    print("\n--- 第 2 轮（同一个会话继续） ---")
    msg2 = "【群友 菠萝吹雪】: 我刚才说我胡了什么牌型来着？你复述一下！"
    reply2, conv_id = await send_to_antigravity(conv_id, msg2, system_prompt)
    print(f"会话 ID: {conv_id}")
    print(f"哈基米回复: {reply2}")

if __name__ == "__main__":
    asyncio.run(main())
