# QQ Gemini (哈基米) & 日麻视觉 AI 助手

基于 **NapCat (Linux Docker / OneBot 11)** + **Google Gemini Pro / Antigravity Bridge** + **高精度开源日麻视觉检测（mahjong-detector + ViT + RapidOCR）** 的全能 QQ 机器人。

---

## 📁 核心架构

- **感知层**：开源专用日麻检测模型（`mahjong-detector`）+ ViT 牌面复核 + RapidOCR 罗盘/点数识别，直接输出标准客观盘面报告。
- **协议层**：支持标准 **MJAI** 协议导出，直连 **Mortal (凡夫)** 日麻引擎进行最优何切与 Q-value 评估。
- **对话人设层**：哈基米多模态萌宠对话，支持动态切换人设与记忆管理。
- **运行环境**：推荐在 **Linux VM (虚拟机) 或 Docker** 中运行，避免 Windows TP 驱动针对桌面客户端的反作弊风控。

---

## 🚀 Linux 虚拟机 / 服务器一键部署流程

### 第一步：克隆仓库 (需支持 Git LFS)
在 Linux 虚拟机中运行：
```bash
# 确保安装了 git 和 git-lfs
sudo apt update && sudo apt install -y git git-lfs
git lfs install

# 克隆仓库
git clone <你的_GITHUB_仓库地址> qq-mahjong-bot
cd qq-mahjong-bot
git lfs pull
```

---

### 第二步：一键初始化 Python 环境
执行随仓库附带的初始化脚本：
```bash
chmod +x setup_linux.sh start_bot.sh
./setup_linux.sh
```
该脚本会自动：
1. 检查并创建 Python 3 虚拟环境 `.venv`；
2. 安装 `requirements.txt` 中的依赖（包括 `opencv-python-headless`, `onnxruntime`, `rapidocr-onnxruntime` 等）；
3. 生成 `config.json` 模板。

---

### 第三步：配置 Clash 代理与 API 密钥 (`config.json`)

由于虚拟机内需要通过宿主机 Windows 的 Clash 科学上网（请求 Gemini API / Antigravity）：

1. **宿主机 Windows Clash 设置**：
   - 打开 Clash，将 **Allow LAN（允许局域网连接）** 开关打开；
   - 查看你宿主机 Windows 的局域网 IP（在 Windows 命令提示符运行 `ipconfig`，例如 `192.168.x.x`）。
2. **编辑虚拟机的 `config.json`**：
   ```json
   {
     "gemini_api_key": "YOUR_GEMINI_API_KEY",
     "proxy_url": "http://192.168.x.x:7890",
     "bot_ws_port": 8080,
     "default_persona": "hajimi"
   }
   ```
   > 注：若虚拟机内已开启全局系统代理（`export http_proxy=...`），可直接将 `proxy_url` 留空 `""`，程序会自动继承系统的环境变量代理。

---

### 第四步：启动 NapCat (Linux Docker)

本项目提供了开箱即用的 `docker-compose.yml`，使用 Linux Host 网络无缝直通宿主机 8080 端口：

```bash
docker compose up -d
```

- **扫码登录**：在浏览器直接打开 `http://<虚拟机IP>:6099/webui`；
- 使用手机 QQ 扫描网页上的二维码授权登录（在 Linux 下会识别为安全、无驱动注入的官方 Linux 终端，永不触发外挂踢线）。

---

### 第五步：启动机器人主进程

```bash
./start_bot.sh
```

控制台提示 `🟢 [NapCat 客户端已连接并建立会话]` 后，机器人即成功上线！可以在 QQ 群或私聊发送麻将牌局截图或与哈基米聊天。
