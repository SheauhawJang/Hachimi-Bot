"""
哈基米 & 麻将多模态助手 - 主服务启动入口 (Main Entrypoint)
支持 QQ (NapCat OneBot 11) + Telegram 双端并发挂载
"""

import sys
import asyncio

# 兼容 Python 3.10 StrEnum
try:
    from enum import StrEnum
except ImportError:
    from strenum import StrEnum
    import enum
    enum.StrEnum = StrEnum

try:
    from websockets.asyncio.server import serve
except ImportError:
    from websockets.server import serve

# 导入配置、日志与单例服务
import config_manager as cm
from config_manager import (
    config,
    personas_data,
    current_persona_key,
    session_mgr,
    security_guard,
    mahjong_vision,
    TEMP_IMG_DIR,
    setup_logger,
)

# 挂载双写日志重定向
setup_logger()

# 导入指令、大模型与 OneBot 协议组件（并对外 re-export 保持多端兼容）
from command_handler import handle_commands
from llm_client import chat_with_llm, audit_mahjong_vision_report, image_to_data_url
from onebot_client import ws_handler, recent_group_images, call_onebot_api
from tg_bot import start_telegram_service


async def main():
    host = "0.0.0.0"
    port = cm.config.get("bot_ws_port", 8080)
    print("=" * 60)
    print("🚀 哈基米 & 麻将多模态助手 (QQ + Telegram 双端引擎) 正在启动...")
    print(f"📡 QQ 监听 WebSocket 端口: ws://{host}:{port}/ws")
    print(f"🎭 默认激活人设: 【{cm.current_persona_key}】")

    if cm.backend == "gemini_web":
        print("🌐 运行后端: Gemini Web 网页版 (支持多模态麻将截图何切 / 后台自动心跳刷新Cookie)")
        print("💰 计费模式: 100% 消耗已付 Google One AI Premium (Gemini Advanced) 会员，零额外扣费！")
        if cm.web_bridge and cm.web_bridge.secure_1psid and "YOUR_" not in cm.web_bridge.secure_1psid:
            try:
                await cm.web_bridge.init_client()
            except Exception as e:
                print(f"⚠️ Gemini Web 初始化提示: {e} (请检查 config.json 中的 Cookie 是否有效)")
    elif cm.backend == "antigravity":
        print("🛡️ 运行后端: Antigravity Pro 本地沙箱隔离通道")
    else:
        print(f"🔌 运行后端: API 模式 (模型: {cm.config.get('default_model', 'gemini-3.5-flash-lite')})")
    print("=" * 60)

    # 并发启动 Telegram 轮询服务 (若已配置 telegram_bot_token)
    tg_task = asyncio.create_task(start_telegram_service(sys.modules[__name__]))

    server = await serve(ws_handler, host, port, ping_interval=30, ping_timeout=120)
    try:
        await server.wait_closed()
    finally:
        tg_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 机器人已优雅停止。")
