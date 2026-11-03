"""
本地终端快速交互测试工具
无需打开 QQ / NapCat，直接在命令行与哈基米连续对话，测试上下文记忆与回复效果！
输入 exit 或 quit 退出，输入 /reset 清空记忆。
"""
import asyncio
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from main import chat_with_llm
from session_manager import SessionManager


async def main():
    session_id = "test_terminal_group"
    mgr = SessionManager()
    print("=" * 55)
    print("🐾 【哈基米终端测试模式】已启动")
    print("• 直接打字回车发送消息")
    print("• 输入 /reset 清空当前会话记忆")
    print("• 输入 exit 或 quit 退出")
    print("=" * 55)

    while True:
        try:
            user_input = input("\n【群友 菠萝吹雪】: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 退出测试。")
            break

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit", "q"]:
            print("👋 退出测试。")
            break

        if user_input == "/reset":
            mgr.reset_session(session_id)
            print("✨ 会话记忆已重置！")
            continue

        prompt_text = f"【群友 菠萝吹雪】: {user_input}"
        reply = await chat_with_llm(session_id, prompt_text, user_input)
        print(f"🐱 哈基米: {reply}")


if __name__ == "__main__":
    asyncio.run(main())
