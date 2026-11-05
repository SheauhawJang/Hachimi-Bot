# AGENTS.md - 架构规范与开发指南 (Mahjong AI Bot)

本文件为后续所有参与本项目开发的 AI Agent 与开发者的最高指令规范与设计准则。

---

## 1. 核心麻将算法与现有项目复用规范 (Mandatory)

本项目与日麻相关的牌理、向听数（Shanten）、听牌判定（Listen/Tenpai）、面子分解、役种番数与点数计算，**必须对齐并复用现有经过数学严格验证的实现库**：
- **基准代码库路径**：
  `C:\Users\Sheauhaw\Documents\SheauhawJang.github.io\source\old_blogs\tools`
  - `mahjong.js`: 核心牌理、34/51 牌编码、向听状态（Step）、七对子向听（PairStep）、国士无双向听（OrphanStep）、听牌判定（Listen）、面子分解（WinOutput）与各流派支持。
  - `mahjong-score.js`: 日麻算点（符数、番数、役种、庄闲得点）与规则引擎。
  - `mahjong-worker.js` / `tenhou-worker.js`: 多规则（日麻四人/三人、国标、四川血战、台湾麻将）天和模拟器与概率计算。

### 规则原则
1. **严禁手写拙劣或残缺的临时牌理算法**：向听数计算、何切进张分析、役满/特殊型（七对子、国士、组合龙等）必须与 `mahjong.js` 逻辑完全一致。
2. **多端/跨语言对接**：在 Python 端维护逻辑时，必须通过标准 MPSZ 结构以及与 `mahjong.js` 对等的算法体系进行转换，不得出现向听漏算或红宝牌混淆。

---

## 2. 盘面感知与副露规范化标准 (Meld & Board Standardization)

任何从视觉模型（YOLO + ViT-Base + OCR）提取的盘面数据，必须按照日麻最高规范与 MJAI 标准进行结构化表示：

### 2.1 副露（Melds）规范
**严禁仅输出单张牌（如“碰[九万]”）！副露必须明确表示整组 3~4 张牌，并标注鸣牌人与出牌来源**：
- **碰（Pon）**：
  - 格式：`碰 999m (来自对家)`、`碰 111p (来自下家)`、`碰 055m (来自上家)`
  - 数据字段：`type="pon"`, `actor=鸣牌人`, `target=放铳/出牌人`, `pai="9m"`, `consumed=["9m", "9m"]`, `tiles_str="999m"`
- **吃（Chi）**：
  - 格式：`吃 789s (来自上家)`
  - 数据字段：`type="chi"`, `actor=鸣牌人`, `target=上家`, `pai="7s"`, `consumed=["8s", "9s"]`, `tiles_str="789s"`
- **杠（Kan）**：
  - 大明杠：`大明杠 9999m (来自对家)`
  - 暗杠：`暗杠 9999m` 或 `暗杠 5550m`
  - 加杠：`加杠 9999m`

### 2.2 玩家座位与方向规范
- `0`: 自家（Self / 画面下方）
- `1`: 下家（Shimocha / 画面右方）
- `2`: 对家（Toimen / 画面上方）
- `3`: 上家（Kamicha / 画面左方）

---

## 3. Mortal (凡夫) 与 MJAI 协议对接规范

为无缝接入日麻顶级 AI **Mortal** (`equim-chan/Mortal`) 与 `mjai-reviewer`，本项目的视觉感知层必须能够直接导出标准的 **MJAI (Mahjong AI protocol) JSON-lines 事件流**：

### 3.1 导出的标准 MJAI 结构示例
```json
{"type": "start_game", "names": ["自家", "下家", "对家", "上家"]}
{"type": "start_kyoku", "bakaze": "E", "kyoku": 3, "honba": 0, "kyotaku": 2, "dora_marker": "7z", "scores": [24000, 32200, 22000, 19800], "tehais": [["0m", "5m", "2p", "2p", "7p", "7p", "2s", "2s", "2z", "2z", "5z", "5z", "6z"], ["?", "?"], ["?", "?"], ["?", "?"]]}
{"type": "pon", "actor": 3, "target": 1, "pai": "9m", "consumed": ["9m", "9m"]}
{"type": "pon", "actor": 3, "target": 1, "pai": "1p", "consumed": ["1p", "1p"]}
{"type": "pon", "actor": 3, "target": 0, "pai": "6p", "consumed": ["6p", "6p"]}
{"type": "tsumo", "actor": 0, "pai": "6z"}
```

### 3.2 下游接入 Mortal 的调用方式
- 将解析生成的当前对局 MJAI 事件列表传入 Mortal 引擎：
  `mortal --player 0 < mjai_events.jsonl`
- Mortal 将直接返回：
  - 各合法切牌选择的 Q-value（期望胜率/打点评价）
  - 最优何切推荐（Best Discard）
  - 立直/默听/鸣牌决策分析

---

## 4. 客观盘面独立交付与 Mortal 引擎直连规范 (Single-Stage Delivery & Mortal Direct Connect)

为确保盘面数据绝对准确、杜绝大语言模型在日麻策略和何切上的胡说八道与幻觉（LLM 严禁 handle 打牌与战术决策），系统执行**客观盘面独立交付与 Mortal 直连机制**：

1. **高精度盘面客观报告秒级交付**：
   - 流程：使用开源专用日麻检测模型（mahjong-detector）+ ViT-Base 四向最大概率复核 + RapidOCR 提取全盘面信息，生成标准客观盘面报告。
   - 触发发送：解析完成后立即秒级发送给群内，精准引用群友原消息 ([CQ:reply,id=user_msg_id])。
   - 包含：局况、四家点数、宝牌指示与实际宝牌、自家手牌、赤宝牌统计、规范化副露（含来源）、四家牌河。
2. **彻底移除大语言模型下游打牌复盘（No LLM For Mahjong Tactics）**：
   - 严禁让通用大语言模型（哈基米 / Gemini / GPT 等）生成所谓的对局复盘或何切建议；
   - 下游策略与何切分析将**直接无缝接入顶级日麻专用 AI 引擎 Mortal (凡夫)**，通过导出的标准 MJAI 协议直接输出权威 Q-value 与打点评价。

---

## 5. 开源专用模型感知与牌理协同架构 (Specialized Model Perception & Shanten Engine)

通用多模态大模型（如 Gemini vision）缺乏日麻专业盘面数据的针对性训练，在识别密集小牌、副露朝向和牌河时极易出现幻觉；而纯手写几何规则又过于脆弱复杂。因此，系统严格执行**开源专用模型 + 开源 OCR + 数学牌理**的感知架构：

1. **开源目标检测模型 (`mahjong-detector`)**：
   - 使用针对雀魂对局截屏经过专门标注与训练的高精度 ONNX 模型 (`mahjong-detector`)；
   - 单次前向推断（~50ms）精准识别全图手牌（包含白板）、宝牌指示牌、副露牌面与四家牌河；
   - 结合笔画与 HSV 颜色分析区分赤五牌（`0m`, `0p`, `0s`）。
2. **开源仪表盘 OCR (`RapidOCR`)**：
   - 使用开源 `rapidocr_onnxruntime` 提取中央罗盘区域的对局局况（如東3局）、牌山余牌数（如余46）以及四家点数（自家/下家/对家/上家）。
3. **MJAI 协议与 Mortal / 基准牌理对接 (`Mortal / mahjong.js`)**：
   - 严禁手写或引入非官方临时牌理；客观盘面结构直接导出标准 MJAI 协议事件流，由 Mortal 或基准库 `mahjong.js` 进行标准牌效与战术评估。
4. **群聊人设解耦复盘 (Persona Decoupled Review)**：
   - 客观结构化盘面数据生成第 1 条报告后，直接交由哈基米大模型以纯文本输入进行战术复盘，实现“专用模型看精确盘面，群聊人设做生动复盘”的高效解耦。

---

## 6. 模型使用与逻辑膨胀防范红线 (Model Modification & Anti-Expansion Policy)

为防止 Agent 自由发挥导致代码不可控膨胀与脆弱的手写几何拼凑怪，系统严格遵守以下原则：

1. **所有对模型的更改必须与用户确认 (Mandatory User Confirmation)**：
   - **严禁擅自编写未把关的复杂启发式规则**：任何针对模型识别的后处理改动，严禁私自手写手工物理网格步长（Pitch）、透视斜率脑补、空隙插值、灰度/白底阈值等复杂的自定义几何推演；
   - 任何改动模型流程、变更核心参数（如置信度阈值）或加入新判断，**必须提前向用户明确说明并获得确认**，防止未经检阅的逻辑泄露与系统复杂度光速膨胀。
2. **允许并倡导模型的自由组合使用 (Allowed Model Composition & TTA)**：
   - 各专用开源模型（如 YOLO 目标检测、ViT 单牌特征提取、RapidOCR 文字识别）本身经过数学与数据集验证，具有高度可靠性；
   - **允许纯空间几何变换与标准模型组合**：例如全图正交四向旋转（0°/90°/180°/270° TTA）本身不 handle 任何识别操作，仅提供自然正向视角，辅以标准 NMS（非极大抑制）聚合多视角高置信度结果；
   - 模型的自由组合依靠模型各自的输出进行交集/聚合，不需要且不应该加入复杂的主观手写逻辑分析。

