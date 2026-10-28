# QQ Mahjong & Gemini Bot (本地机器人项目)

基于 NapCatQQ (OneBot 11) 与 Google Gemini Pro 的 QQ 智能对话机器人，预留麻将牌效与 AI 分析扩展能力。

---

## 📁 目录结构

```
qq-mahjong-bot/
├── config.json         # 机器人核心配置（API Key、模型、端口、代理）
├── personas.json       # 人设列表与提示词（支持动态切换）
├── main.py             # 机器人主服务（OneBot 11 反向 WebSocket + 会话管理）
├── requirements.txt    # Python 依赖项
└── README.md           # 说明文档
```

---

## 🚀 快速启动步骤

### 1. 安装依赖
在项目目录下打开终端运行：
```bash
pip install -r requirements.txt
```

### 2. 填写配置 (`config.json`)
打开 `config.json`，至少填入你的 Gemini API Key：
```json
{
  "gemini_api_key": "在这里填入你的 Google AI Studio API Key",
  "gemini_model": "gemini-1.5-pro",
  "proxy_url": "http://127.0.0.1:7890",
  "bot_ws_port": 8080
}
```
> **注意**：如果在国内网络，请确保 `proxy_url` 端口与你的代理客户端（如 Clash、v2rayN）一致；如果不需要代理，将其设为 `null` 即可。

### 3. 配置 NapCatQQ (QQ 协议端)
在 NapCatQQ 的网络配置（WebUI 或 `napcat/config/onebot11.json`）中设置：
* **模式**：反向 WebSocket（`ws_reverse`）
* **地址**：`ws://127.0.0.1:8080/ws`
* **启用**：打开

### 4. 运行机器人
```bash
python main.py
```
当控制台提示 `🟢 [NapCatQQ 已建立连接]` 时，即可在 QQ 中私聊或在群里 @机器人 开始对话！

---

## 🎮 内置指令

* `/help`：查看帮助菜单
* `/reset` 或 `重置记忆`：清空当前上下文历史
* `/persona`：查看可用人设列表
* `/persona [名称]`：切换人设（例如 `/persona sichuan_spicy` 切换为川麻老油条）

---

## 🔜 下一步计划（麻将与视觉模块）
- [ ] 接入本地 `mahjong` 目录的 JS 牌效模块（计算向听数与何切）
- [ ] 接入 Gemini 2.5 Flash 视觉识别（手牌拍照/截图直读）
- [ ] 接入 Mortal 牌谱检讨 Web API
- [ ] 接入四川麻将（血战到底）期望决策算法
