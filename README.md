# QQ Gemini (哈基米) & 麻将智能助手

基于 NapCatQQ (OneBot 11) 与 Google Gemini Pro 的 QQ 智能对话机器人。默认预置超可爱的**“哈基米（全能萌猫）”**人设，并预留麻将牌效与视觉识别扩展接口。

---

## 📁 目录结构

```
qq-mahjong-bot/
├── config.json         # 本地实际配置文件 (包含 API Key，已被 .gitignore 保护)
├── config.example.json # 配置文件模板
├── personas.json       # 人设列表与提示词（默认：哈基米，支持动态热切换）
├── main.py             # 机器人主服务（OneBot 11 反向 WebSocket + 会话管理）
├── test_gemini.py      # 独立连通性测试脚本（无需启动 NapCatQQ 即可验证 Gemini 与人设）
├── requirements.txt    # Python 依赖项
├── .gitignore          # Git 忽略配置
└── README.md           # 说明文档
```

---

## 🚀 快速启动指南

### 1. 填写配置 (`config.json`)
打开 [`config.json`](./config.json)，填入你的 Gemini API Key：
```json
{
  "gemini_api_key": "在这里填入你的 Google AI Studio API Key",
  "gemini_model": "gemini-1.5-pro",
  "proxy_url": "http://127.0.0.1:7890",
  "bot_ws_port": 8080,
  "max_history_turns": 10,
  "default_persona": "hajimi"
}
```
* **注意**：如果在国内网络，请确保 `proxy_url` 端口与你的代理客户端（如 Clash 默认为 `7890`，v2rayN 为 `10809`）一致；若直连可设为 `null`。

---

### 2. 独立验证 Gemini 与人设效果（推荐）
在不需要打开 NapCatQQ 的情况下，先跑一个单次测试：
```bash
python test_gemini.py
```
若提示测试成功且收到哈基米的小猫咪回复，说明 API Key 与网络完全通畅！

---

### 3. 配置 NapCatQQ (QQ 协议端)
在 NapCatQQ 的网络配置（WebUI 或 `napcat/config/onebot11.json`）中设置：
* **通信方式**：反向 WebSocket（`ws_reverse`）
* **连接地址**：`ws://127.0.0.1:8080/ws`
* **状态**：启用

---

### 4. 运行机器人服务
```bash
python main.py
```
控制台提示 `🟢 [NapCatQQ 已建立连接]` 后，即可在 QQ 中私聊或在群里 @机器人 开始对话！

---

## 🎭 可用人设与指令

* `/help`：查看指令菜单
* `/reset` 或 `重置记忆`：清空当前上下文历史
* `/persona`：查看所有可用人设列表
* `/persona [名称]`：切换人设，支持：
  * `hajimi`：**哈基米（全能萌猫）**（默认，软萌机灵、带生动猫咪动作与口癖）
  * `hajimi_tsundere`：**哈基米（傲娇猫主子）**（口嫌体正直的高贵布偶猫）
  * `mahjong_coach`：**麻将教练（毒舌专业）**（南彦）
  * `sichuan_spicy`：**川麻老手（地道豪爽）**（地道茶馆血战到底）
  * `friendly_assistant`：**温柔管家**

---

## 🔜 后续拓展计划
- [ ] 接入本地 `Codes/mahjong` 目录的 JS 牌效模块（计算向听数与何切）
- [ ] 接入 Gemini 视觉手牌识别（照片/截图直读手牌）
- [ ] 接入 Mortal 牌谱检讨 Web API
