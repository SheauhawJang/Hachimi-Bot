"""
专业日麻全盘面高精度感知引擎 (Full Board Mahjong Vision Engine)
支持：
1. 局况与点数（从中央仪表盘提取自家/下家/对家/上家点数与本场局况）
2. 宝牌指示牌提取（从左上角王牌区识别）
3. 自家手牌（YOLO + ViT-Base + 等距栅格补齐 + 笔画级赤五判定）
4. 他家副露（屏幕四角吃碰杠副露提取）
5. 四家牌河（上家、对家、下家、自家弃牌流）
"""

import os
import cv2
import json
import numpy as np
import onnxruntime as ort
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image

try:
    import mahjong_detector
    from mahjong_detector.preprocess import preprocess_image
    from mahjong_detector.predict import Detection
    from mahjong_detector import CLASS_NAMES as MD_CLASS_NAMES, predict as md_predict
    HAS_MAHJONG_DETECTOR = True
except Exception as _e:
    HAS_MAHJONG_DETECTOR = False
    HAS_MAHJONG_DETECTOR = False

DETECTOR_MAP = {
    "chun": "7z", "haku": "5z", "hatsu": "6z",
    "nan": "2z", "pe": "4z", "sha": "3z", "tou": "1z",
}

MPSZ_TO_CN = {
    "1m": "一万", "2m": "二万", "3m": "三万", "4m": "四万", "5m": "五万", "0m": "赤五万",
    "6m": "六万", "7m": "七万", "8m": "八万", "9m": "九万",
    "1p": "一筒", "2p": "二筒", "3p": "三筒", "4p": "四筒", "5p": "五筒", "0p": "赤五筒",
    "6p": "六筒", "7p": "七筒", "8p": "八筒", "9p": "九筒",
    "1s": "一条", "2s": "二条", "3s": "三条", "4s": "四条", "5s": "五条", "0s": "赤五条",
    "6s": "六条", "7s": "七条", "8s": "八条", "9s": "九条",
    "1z": "东风", "2z": "南风", "3z": "西风", "4z": "北风",
    "5z": "白板", "6z": "发财", "7z": "红中"
}

VIT_LABEL_TO_MPSZ = {
    "1b": "1s", "2b": "2s", "3b": "3s", "4b": "4s", "5b": "5s", "6b": "6s", "7b": "7s", "8b": "8s", "9b": "9s",
    "1n": "1m", "2n": "2m", "3n": "3m", "4n": "4m", "5n": "5m", "6n": "6m", "7n": "7m", "8n": "8m", "9n": "9m",
    "1p": "1p", "2p": "2p", "3p": "3p", "4p": "4p", "5p": "5p", "6p": "6p", "7p": "7p", "8p": "8p", "9p": "9p",
    "ew": "1z", "sw": "2z", "ww": "3z", "nw": "4z", "wd": "5z", "gd": "6z", "rd": "7z"
}

DORA_NEXT = {
    "1m": "2m", "2m": "3m", "3m": "4m", "4m": "5m", "5m": "6m", "6m": "7m", "7m": "8m", "8m": "9m", "9m": "1m",
    "1p": "2p", "2p": "3p", "3p": "4p", "4p": "5p", "5p": "6p", "6p": "7p", "7p": "8p", "8p": "9p", "9p": "1p",
    "1s": "2s", "2s": "3s", "3s": "4s", "4s": "5s", "5s": "6s", "6s": "7s", "7s": "8s", "8s": "9s", "9s": "1s",
    "1z": "2z", "2z": "3z", "3z": "4z", "4z": "1z",
    "5z": "6z", "6z": "7z", "7z": "5z"
}


class MahjongVision:
    def __init__(
        self,
        yolo_path: str = "models/yolo/weights.onnx",
        vit_model_path: str = "models/vit/model.onnx",
        vit_config_path: str = "models/vit/config.json",
    ):
        self.yolo_path = Path(yolo_path)
        self.vit_model_path = Path(vit_model_path)
        self.vit_config_path = Path(vit_config_path)

        self.yolo_session = None
        self.vit_session = None
        self.vit_id2label = {}
        self.ocr = None

        self._load_models()

    def _get_ocr(self):
        if self.ocr is None:
            try:
                from rapidocr import RapidOCR
                self.ocr = RapidOCR()
            except ImportError:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    self.ocr = RapidOCR()
                except Exception as e:
                    print(f"[MahjongVision] OCR 初始化失败: {e}")
            except Exception as e:
                print(f"[MahjongVision] OCR 初始化失败: {e}")
        return self.ocr

    def _parse_center(self, img: np.ndarray) -> Dict[str, Any]:
        """通过 RapidOCR 识别中央仪表盘对局局况与四家点数"""
        res = {
            "round": "",
            "remaining": "",
            "scores": {"self": "", "shimocha": "", "toimen": "", "kamicha": ""},
        }
        ocr = self._get_ocr()
        if not ocr:
            return res
        try:
            h, w = img.shape[:2]
            center_crop = img[int(h * 0.25):int(h * 0.55), int(w * 0.35):int(w * 0.65)]
            ocr_res, _ = ocr(center_crop)
            if not ocr_res:
                return res

            ch, cw = center_crop.shape[:2]
            for box, txt, score in ocr_res:
                txt = txt.strip()
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)

                if "局" in txt:
                    res["round"] = txt
                elif "余" in txt:
                    res["remaining"] = txt
                elif txt.isdigit() and len(txt) in [4, 5]:
                    if cy < ch * 0.35:
                        res["scores"]["toimen"] = txt
                    elif cy > ch * 0.65:
                        res["scores"]["self"] = txt
                    elif cx < cw * 0.40:
                        res["scores"]["kamicha"] = txt
                    elif cx > cw * 0.60:
                        res["scores"]["shimocha"] = txt
        except Exception as e:
            print(f"[MahjongVision] Center OCR error: {e}")
        return res

    def _load_models(self):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        if self.yolo_path.exists():
            try:
                self.yolo_session = ort.InferenceSession(
                    str(self.yolo_path), sess_options=opts, providers=["CPUExecutionProvider"]
                )
                self.yolo_in_name = self.yolo_session.get_inputs()[0].name
                self.yolo_out_name = self.yolo_session.get_outputs()[0].name
                print("[MahjongVision] Stage 1: YOLOv8 空间锚定模型加载成功")
            except Exception as e:
                print(f"[MahjongVision] YOLO 加载失败: {e}")

        if self.vit_model_path.exists() and self.vit_config_path.exists():
            try:
                with open(self.vit_config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.vit_id2label = cfg.get("id2label", {})

                self.vit_session = ort.InferenceSession(
                    str(self.vit_model_path), sess_options=opts, providers=["CPUExecutionProvider"]
                )
                self.vit_in_name = self.vit_session.get_inputs()[0].name
                print(f"[MahjongVision] Stage 2: ViT-Base 雀魂视觉大模型加载成功 (344MB / 34日麻分类)")
            except Exception as e:
                print(f"[MahjongVision] ViT 加载失败: {e}")

    def _predict_tile(self, crop: np.ndarray) -> str:
        """单张牌 ViT 快速推断"""
        t, _ = self._predict_tile_with_conf(crop)
        return t

    def _predict_tile_with_conf(self, crop: np.ndarray) -> tuple[str, float]:
        """单张牌 ViT 快速推断并返回置信度"""
        if not self.vit_session or crop.size == 0:
            return "", 0.0
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_LINEAR)
        norm = (resized.astype(np.float32) / 127.5) - 1.0
        logits = self.vit_session.run(None, {self.vit_in_name: norm.transpose(2, 0, 1)[None]})[0][0]
        exp = np.exp(logits - np.max(logits))
        probs = exp / np.sum(exp)
        top_idx = int(np.argmax(probs))
        conf = float(probs[top_idx])
        raw = self.vit_id2label.get(str(top_idx), "1n")
        return VIT_LABEL_TO_MPSZ.get(raw, "1m"), conf

    def _detect_all_yolo_boxes(self, img: np.ndarray) -> List[Dict[str, Any]]:
        """全图单次运行 YOLOv8 并执行 NMS，提取全盘所有麻将牌候选框"""
        if not self.yolo_session:
            return []
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, (640, 640), swapRB=True, crop=False)
        out = self.yolo_session.run([self.yolo_out_name], {self.yolo_in_name: blob})[0]
        preds = np.transpose(out, (0, 2, 1))[0]
        boxes = preds[:, :4]
        scores = preds[:, 4:]
        max_scores = np.max(scores, axis=1)

        scale_x = w / 640.0
        scale_y = h / 640.0

        nms_boxes, nms_confs, meta = [], [], []
        for i, row in enumerate(boxes):
            conf = float(max_scores[i])
            if conf > 0.25:
                cx, cy, bw, bh = row
                x1 = int((cx - bw / 2) * scale_x)
                y1 = int((cy - bh / 2) * scale_y)
                bw_pix = int(bw * scale_x)
                bh_pix = int(bh * scale_y)
                nms_boxes.append([x1, y1, bw_pix, bh_pix])
                nms_confs.append(conf)
                meta.append({
                    "cx": float(cx * scale_x),
                    "cy": float(cy * scale_y),
                    "w": bw_pix,
                    "h": bh_pix,
                    "conf": conf
                })

        indices = cv2.dnn.NMSBoxes(nms_boxes, nms_confs, 0.25, 0.45)
        res = []
        for idx in indices:
            i = idx if isinstance(idx, (int, np.integer)) else idx[0]
            m = meta[i]
            m["box"] = nms_boxes[i]
            res.append(m)
        return res

    def _locate_hand_tiles(self, img: np.ndarray, all_boxes: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """利用 YOLO 提取手牌并按间距补齐白板与自摸牌"""
        if not self.yolo_session:
            return []

        h, w = img.shape[:2]
        if all_boxes is None:
            all_boxes = self._detect_all_yolo_boxes(img)

        # 锁定真正的玩家手牌行 (位于画面底部 78% 以下)
        hand_y_min = h * 0.78
        hand_cands = [b for b in all_boxes if b["cy"] > hand_y_min and b["conf"] > 0.35]
        if not hand_cands:
            return []

        candidates = sorted(hand_cands, key=lambda x: x["cx"])

        clusters = []
        for c in candidates:
            if not clusters or abs(c["cx"] - clusters[-1]["cx"]) > 22:
                clusters.append(c)
            else:
                if c["conf"] > clusters[-1]["conf"]:
                    clusters[-1] = c

        base_cy = float(np.median([c["cy"] for c in clusters]))
        valid_hand = [c for c in clusters if abs(c["cy"] - base_cy) < 25]
        if not valid_hand:
            return []

        avg_w = float(np.median([c["w"] for c in valid_hand]))
        avg_h = float(np.median([c["h"] for c in valid_hand]))
        tile_w = max(38.0, avg_w)
        tile_h = max(56.0, avg_h)

        cxs = [c["cx"] for c in valid_hand]
        diffs = [cxs[i+1] - cxs[i] for i in range(len(cxs)-1)]
        valid_pitches = [d for d in diffs if 35.0 < d < 65.0]
        tile_pitch = float(np.median(valid_pitches)) if valid_pitches else 50.0

        # 网格插值补全白板
        filled_centers = [cxs[0]]
        for i in range(len(cxs) - 1):
            curr_x = cxs[i]
            next_x = cxs[i + 1]
            dist = next_x - curr_x
            gap_count = int(round(dist / tile_pitch)) - 1
            if 0 < gap_count <= 3:
                for step in range(1, gap_count + 1):
                    filled_centers.append(curr_x + step * (dist / (gap_count + 1)))
            filled_centers.append(next_x)

        tile_boxes = []
        for cx in filled_centers:
            x1 = max(0, int(round(cx - tile_w / 2)))
            x2 = min(w, int(round(cx + tile_w / 2)))
            y1 = max(0, int(round(base_cy - tile_h / 2)))
            y2 = min(h, int(round(base_cy + tile_h / 2)))
            tile_boxes.append({
                "cx": float(cx),
                "cy": float(base_cy),
                "box": [x1, y1, x2, y2],
                "crop": img[y1:y2, x1:x2]
            })

        return tile_boxes

    def _check_red_dora(self, crop: np.ndarray, base_tile: str) -> str:
        """赤宝牌笔画与色彩精确判定"""
        if base_tile not in ["5m", "5p", "5s"]:
            return base_tile

        h, w = crop.shape[:2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        if base_tile == "5m":
            upper = crop[int(h * 0.1):int(h * 0.48), :]
            uhsv = cv2.cvtColor(upper, cv2.COLOR_BGR2HSV)
            black_cnt = np.sum(uhsv[:, :, 2] < 90)
            red_cnt = np.sum(((uhsv[:, :, 0] < 15) | (uhsv[:, :, 0] > 165)) & (uhsv[:, :, 1] > 80) & (uhsv[:, :, 2] > 80))
            if red_cnt > 100 and black_cnt < 60:
                return "0m"
            return "5m"

        if base_tile == "5p":
            red_cnt = np.sum(((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 168)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80))
            dark_cnt = np.sum(hsv[:, :, 2] < 90)
            if red_cnt > 1000 and dark_cnt < 300:
                return "0p"
            return "5p"

        if base_tile == "5s":
            red_cnt = np.sum(((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 168)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80))
            green_cnt = np.sum((hsv[:, :, 0] > 35) & (hsv[:, :, 0] < 85) & (hsv[:, :, 1] > 60))
            if red_cnt > 800 and green_cnt < 300:
                return "0s"
            return "5s"

        return base_tile

    def _parse_dora(self, img: np.ndarray) -> List[str]:
        """从左上角王牌区识别宝牌指示牌"""
        h, w = img.shape[:2]
        dora_roi = img[int(h * 0.02):int(h * 0.18), int(w * 0.01):int(w * 0.17)]
        if dora_roi.size == 0:
            return []
        dh, dw = dora_roi.shape[:2]
        tile_crop = dora_roi[int(dh * 0.08):int(dh * 0.62), int(dw * 0.02):int(dw * 0.22)]
        t = self._predict_tile(tile_crop)
        return [t] if t else []

    def _parse_rivers(self, img: np.ndarray) -> Dict[str, List[str]]:
        """从中央牌河区域解析四家舍牌流"""
        h, w = img.shape[:2]
        rivers = {"self": [], "shimocha": [], "toimen": [], "kamicha": []}

        # 1. 自家牌河 (Self)
        y_s1, y_s2 = int(h * 0.49), int(h * 0.66)
        x_s1, x_s2 = int(w * 0.39), int(w * 0.60)
        self_area = img[y_s1:y_s2, x_s1:x_s2]
        if self_area.size > 0:
            rh, rw = self_area.shape[:2]
            for r in range(2):
                r_y1 = int(r * (rh / 2))
                r_y2 = int((r + 1) * (rh / 2))
                for c in range(6):
                    c_x1 = int(c * (rw / 6))
                    c_x2 = int((c + 1) * (rw / 6))
                    crop = self_area[r_y1:r_y2, c_x1:c_x2]
                    if crop.size > 0 and np.sum(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) > 160) > 120:
                        t = self._predict_tile(crop)
                        if t:
                            rivers["self"].append(t)

        # 2. 对家牌河 (Toimen)
        y_t1, y_t2 = int(h * 0.22), int(h * 0.40)
        x_t1, x_t2 = int(w * 0.40), int(w * 0.60)
        toimen_area = img[y_t1:y_t2, x_t1:x_t2]
        if toimen_area.size > 0:
            toimen_rot = cv2.rotate(toimen_area, cv2.ROTATE_180)
            rh, rw = toimen_rot.shape[:2]
            for r in range(2):
                r_y1 = int(r * (rh / 2))
                r_y2 = int((r + 1) * (rh / 2))
                for c in range(6):
                    c_x1 = int(c * (rw / 6))
                    c_x2 = int((c + 1) * (rw / 6))
                    crop = toimen_rot[r_y1:r_y2, c_x1:c_x2]
                    if crop.size > 0 and np.sum(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) > 160) > 120:
                        t = self._predict_tile(crop)
                        if t:
                            rivers["toimen"].append(t)

        # 3. 下家牌河 (Shimocha)
        shimo_area = img[int(h * 0.38):int(h * 0.65), int(w * 0.57):int(w * 0.67)]
        if shimo_area.size > 0:
            shimo_rot = cv2.rotate(shimo_area, cv2.ROTATE_90_COUNTERCLOCKWISE)
            rh, rw = shimo_rot.shape[:2]
            for c in range(6):
                c_x1 = int(c * (rw / 6))
                c_x2 = int((c + 1) * (rw / 6))
                crop = shimo_rot[10:rh - 10, c_x1:c_x2]
                if crop.size > 0 and np.sum(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) > 160) > 120:
                    t = self._predict_tile(crop)
                    if t:
                        rivers["shimocha"].append(t)

        # 4. 上家牌河 (Kamicha)
        kami_area = img[int(h * 0.38):int(h * 0.65), int(w * 0.33):int(w * 0.43)]
        if kami_area.size > 0:
            kami_rot = cv2.rotate(kami_area, cv2.ROTATE_90_CLOCKWISE)
            rh, rw = kami_rot.shape[:2]
            for c in range(6):
                c_x1 = int(c * (rw / 6))
                c_x2 = int((c + 1) * (rw / 6))
                crop = kami_rot[10:rh - 10, c_x1:c_x2]
                if crop.size > 0 and np.sum(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) > 160) > 120:
                    t = self._predict_tile(crop)
                    if t:
                        rivers["kamicha"].append(t)

        return rivers

    def _parse_melds(self, img: np.ndarray, all_boxes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, Any]]]:
        """从屏幕提取四家副露，明确识别 3~4 张一组的牌面、鸣牌类型与来源 (MJAI 兼容)"""
        h, w = img.shape[:2]
        melds = {"self": [], "shimocha": [], "toimen": [], "kamicha": []}
        if all_boxes is None:
            all_boxes = self._detect_all_yolo_boxes(img)
        if not all_boxes or not self.vit_session:
            return melds

        def process_player_boxes(p_id: int, p_boxes: List[Dict[str, Any]], is_vertical: bool = True) -> List[Dict[str, Any]]:
            p_names = {0: "自家(東)", 1: "下家(南)", 2: "对家(西)", 3: "上家(北)"}
            actor_name = p_names[p_id]
            if is_vertical:
                p_boxes.sort(key=lambda b: b["box"][1])
            else:
                p_boxes.sort(key=lambda b: b["box"][0])

            res_melds = []
            for i in range(0, len(p_boxes), 3):
                group = p_boxes[i:i+3]
                if len(group) == 3:
                    tiles = []
                    for item in group:
                        b = item["box"]
                        crop = img[b[1]:b[1]+b[3], b[0]:b[0]+b[2]]
                        rot = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE) if b[2] > b[3] else crop
                        t = self._predict_tile(rot)
                        t = self._check_red_dora(rot, t)
                        tiles.append(t)

                    asps = [item["box"][2] / float(max(1, item["box"][3])) for item in group]
                    min_asp_idx = int(np.argmin(asps))

                    # 根据横向偏转牌所在索引推导从何家副露 (绝不允许出现“碰自家/自己”的荒谬逻辑)
                    # 统一使用“我方”代指 0 号底端玩家，避免出现歧义
                    if p_id == 3:  # 上家(左侧)视角: 0:我方, 1:下家, 2:对家
                        t_map = {0: (0, "我方"), 1: (1, "下家"), 2: (2, "对家")}
                    elif p_id == 1:  # 下家(右侧)视角: 0:对家, 1:上家, 2:我方
                        t_map = {0: (2, "对家"), 1: (3, "上家"), 2: (0, "我方")}
                    elif p_id == 2:  # 对家(顶端)视角: 0:上家, 1:我方, 2:下家
                        t_map = {0: (3, "上家"), 1: (0, "我方"), 2: (1, "下家")}
                    else:  # 自家视角: 0:上家, 1:对家, 2:下家
                        t_map = {0: (3, "上家"), 1: (2, "对家"), 2: (1, "下家")}

                    target_id, target_name = t_map.get(min_asp_idx, (None, "他家"))
                    if target_id == p_id:
                        # 兜底规则防御：绝不可鸣自己
                        target_id, target_name = (p_id - 1) % 4, "上家"

                    # 判断副露形态 (碰 vs 吃)
                    norm_tiles = [t.replace("0", "5") for t in tiles]
                    if norm_tiles[0] == norm_tiles[1] == norm_tiles[2]:
                        m_type = "pon"
                        m_type_cn = "碰"
                        suit = tiles[0][1] if len(tiles[0]) == 2 else "m"
                        nums = "".join([t[0] for t in tiles])
                        tiles_str = f"{nums}{suit}"
                        pai = tiles[min_asp_idx]
                        consumed = [t for idx, t in enumerate(tiles) if idx != min_asp_idx]
                    else:
                        m_type = "chi"
                        m_type_cn = "吃"
                        suit = tiles[0][1] if len(tiles[0]) == 2 else "m"
                        nums = sorted([int(t[0]) for t in tiles if t[0].isdigit()])
                        tiles_str = f"{nums[0]}{nums[1]}{nums[2]}{suit}" if len(nums) == 3 else "".join(tiles)
                        pai = tiles[0]
                        consumed = tiles[1:]
                        # 吃牌永远来自该玩家的上家
                        kami_rel = {3: (2, "对家"), 2: (1, "下家"), 1: (0, "我方"), 0: (3, "上家")}
                        target_id, target_name = kami_rel.get(p_id, ((p_id - 1) % 4, "上家"))

                    desc = f"{m_type_cn} {tiles_str} (来自{target_name})"
                    res_melds.append({
                        "type": m_type,
                        "actor": p_id,
                        "actor_name": actor_name,
                        "target": target_id,
                        "target_name": target_name,
                        "pai": pai,
                        "consumed": consumed,
                        "tiles": tiles,
                        "tiles_str": tiles_str,
                        "desc": desc
                    })
            return res_melds

        # 1. 上家副露 (左侧区域)
        kami_b = [b for b in all_boxes if b["box"][0] < w * 0.18 and h * 0.35 <= b["box"][1] <= h * 0.82 and b["w"] >= 28 and b["h"] >= 18]
        melds["kamicha"] = process_player_boxes(3, kami_b, is_vertical=True)

        # 2. 下家副露 (右侧区域)
        shimo_b = [b for b in all_boxes if b["box"][0] > w * 0.82 and h * 0.15 <= b["box"][1] <= h * 0.65 and b["w"] >= 28 and b["h"] >= 18]
        melds["shimocha"] = process_player_boxes(1, shimo_b, is_vertical=True)

        # 3. 对家副露 (上方区域)
        toimen_b = [b for b in all_boxes if b["box"][1] < h * 0.22 and w * 0.55 <= b["box"][0] <= w * 0.85 and b["w"] >= 20 and b["h"] >= 20]
        melds["toimen"] = process_player_boxes(2, toimen_b, is_vertical=False)

        # 4. 自家副露 (右下角手牌右侧)
        self_b = [b for b in all_boxes if b["box"][1] > h * 0.80 and b["box"][0] > w * 0.72 and b["w"] >= 28]
        melds["self"] = process_player_boxes(0, self_b, is_vertical=False)

        return melds

    def _generate_zoom_crops(
        self, img: np.ndarray, base_path: str, melds: Dict[str, Any]
    ) -> List[str]:
        """为多模态大模型生成关键区域（四家牌河特写、副露特写）高清切片，解决大图压缩看不清细节的问题"""
        h, w = img.shape[:2]
        crop_paths = []
        base_dir = Path(base_path).parent
        stem = Path(base_path).stem

        # 1. 四家牌河与仪表盘高清特写 (Center Pond Zoom)
        py1, py2 = max(0, int(h * 0.18)), min(h, int(h * 0.72))
        px1, px2 = max(0, int(w * 0.28)), min(w, int(w * 0.72))
        pond_crop = img[py1:py2, px1:px2]
        if pond_crop.size > 0:
            pond_p = base_dir / f"{stem}_zoom_pond.jpg"
            cv2.imwrite(str(pond_p), pond_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            crop_paths.append(str(pond_p))

        # 2. 上家副露特写 (如果有副露)
        if melds.get("kamicha"):
            ky1, ky2 = max(0, int(h * 0.22)), min(h, int(h * 0.75))
            kx1, kx2 = 0, min(w, int(w * 0.18))
            kami_crop = img[ky1:ky2, kx1:kx2]
            if kami_crop.size > 0:
                kami_p = base_dir / f"{stem}_zoom_kami_melds.jpg"
                cv2.imwrite(str(kami_p), kami_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                crop_paths.append(str(kami_p))

        # 3. 下家副露特写 (如果有副露)
        if melds.get("shimocha"):
            sy1, sy2 = max(0, int(h * 0.15)), min(h, int(h * 0.65))
            sx1, sx2 = max(0, int(w * 0.82)), w
            shimo_crop = img[sy1:sy2, sx1:sx2]
            if shimo_crop.size > 0:
                shimo_p = base_dir / f"{stem}_zoom_shimo_melds.jpg"
                cv2.imwrite(str(shimo_p), shimo_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                crop_paths.append(str(shimo_p))

        # 4. 对家副露特写 (如果有副露)
        if melds.get("toimen"):
            ty1, ty2 = 0, min(h, int(h * 0.25))
            tx1, tx2 = max(0, int(w * 0.50)), min(w, int(w * 0.85))
            toi_crop = img[ty1:ty2, tx1:tx2]
            if toi_crop.size > 0:
                toi_p = base_dir / f"{stem}_zoom_toi_melds.jpg"
                cv2.imwrite(str(toi_p), toi_crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                crop_paths.append(str(toi_p))

        return crop_paths

    @staticmethod
    def _rotate_box_back(box: List[int], rot_type: str, orig_w: int, orig_h: int) -> List[int]:
        """将旋转图像中的目标检测框逆映射回原始图像坐标系"""
        x1, y1, x2, y2 = box
        if rot_type == "none":
            return [x1, y1, x2, y2]
        elif rot_type == "cw":  # 顺时针 90°: 对应原图 x = y_rot, y = orig_h - 1 - x_rot
            ox1, ox2 = y1, y2
            oy1, oy2 = orig_h - 1 - x2, orig_h - 1 - x1
            return [min(ox1, ox2), min(oy1, oy2), max(ox1, ox2), max(oy1, oy2)]
        elif rot_type == "180":  # 180°: 对应原图 x = orig_w - 1 - x_rot, y = orig_h - 1 - y_rot
            ox1, ox2 = orig_w - 1 - x2, orig_w - 1 - x1
            oy1, oy2 = orig_h - 1 - y2, orig_h - 1 - y1
            return [min(ox1, ox2), min(oy1, oy2), max(ox1, ox2), max(oy1, oy2)]
        elif rot_type == "ccw":  # 逆时针 90°: 对应原图 x = orig_w - 1 - y_rot, y = x_rot
            ox1, ox2 = orig_w - 1 - y2, orig_w - 1 - y1
            oy1, oy2 = x1, x2
            return [min(ox1, ox2), min(oy1, oy2), max(ox1, ox2), max(oy1, oy2)]
        return [x1, y1, x2, y2]

    def _detect_with_full_rotations(
        self, frame: np.ndarray, conf_threshold: float = 0.50
    ) -> List[Any]:
        """
        全图正交四向推断 (4-way Full-Image Rotation TTA)
        利用日麻四家各偏转 90 度的物理对称性，将全图分别在 0°, 90°CW, 180°, 90°CCW 运行 YOLO 检测，
        并将检测结果通过坐标逆变换映射回原图坐标系，经标准 NMS 合并。
        在每个视角下，对应座次的瓦片均以自然正向呈现，使轻量模型在 conf >= 0.50 下即可高置信度召回，
        彻底消除手写物理步长、缝隙插值与微观切片旋转等脆弱启发式规则。
        """
        orig_h, orig_w = frame.shape[:2]
        rotations = [
            ("none", frame),
            ("cw", cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)),
            ("180", cv2.rotate(frame, cv2.ROTATE_180)),
            ("ccw", cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        ]

        session = md_predict.__globals__["get_inference_session"]()
        input_name = session.get_inputs()[0].name
        create_input_tensor = md_predict.__globals__["create_input_tensor"]
        postprocess = md_predict.__globals__["postprocess"]
        nms = md_predict.__globals__["nms"]

        all_dets: List[Detection] = []
        for rot_type, r_frame in rotations:
            pil_r = Image.fromarray(cv2.cvtColor(r_frame, cv2.COLOR_BGR2RGB))
            p_img, p_info = preprocess_image(pil_r)
            input_data = create_input_tensor(p_img)
            outputs = session.run(None, {input_name: input_data})
            dets = postprocess(
                outputs[0][0, ...], p_info, num_classes=len(MD_CLASS_NAMES), conf_threshold=conf_threshold
            )
            for d in dets:
                box_orig = self._rotate_box_back([d.x1, d.y1, d.x2, d.y2], rot_type, orig_w, orig_h)
                all_dets.append(
                    Detection(
                        x1=int(box_orig[0]),
                        y1=int(box_orig[1]),
                        x2=int(box_orig[2]),
                        y2=int(box_orig[3]),
                        class_id=int(d.class_id),
                        confidence=float(d.confidence),
                    )
                )

        if not all_dets:
            return []

        boxes = np.array([[d.x1, d.y1, d.x2, d.y2] for d in all_dets])
        scores = np.array([d.confidence for d in all_dets])
        keep = nms(boxes, scores, iou_threshold=0.45)
        return [all_dets[i] for i in keep]

    def _classify_crops_with_vit_4rot(self, crops: List[np.ndarray]) -> List[Tuple[str, float]]:
        """
        纯模型自由组合：对裁剪出的麻将牌，执行 4 向正交旋转并使用 ViT-Base 预测，
        取各向最大概率值对应的类别，彻底消除单阶段目标检测器的分类幻觉与视角盲区。
        """
        if not crops or not self.vit_session:
            return []
        batch = []
        for c in crops:
            if c.size == 0 or c.shape[0] < 5 or c.shape[1] < 5:
                c = np.zeros((20, 20, 3), dtype=np.uint8)
            rot_imgs = [
                c,
                cv2.rotate(c, cv2.ROTATE_90_CLOCKWISE),
                cv2.rotate(c, cv2.ROTATE_180),
                cv2.rotate(c, cv2.ROTATE_90_COUNTERCLOCKWISE),
            ]
            for r_img in rot_imgs:
                rgb = cv2.cvtColor(r_img, cv2.COLOR_BGR2RGB)
                resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_LINEAR)
                norm = (resized.astype(np.float32) / 127.5) - 1.0
                batch.append(norm.transpose(2, 0, 1))

        inp = np.array(batch, dtype=np.float32)
        logits = self.vit_session.run(None, {self.vit_in_name: inp})[0]
        exp_l = np.exp(logits - np.max(logits, axis=1, keepdims=True))
        probs = exp_l / np.sum(exp_l, axis=1, keepdims=True)

        probs = probs.reshape(len(crops), 4, -1)
        results = []
        for i in range(len(crops)):
            p_crop = probs[i]
            max_idx = np.argmax(p_crop)
            best_rot, best_cls = divmod(max_idx, p_crop.shape[1])
            prob = float(p_crop[best_rot, best_cls])
            lbl = self.vit_id2label.get(str(best_cls), "1n")
            mpsz = VIT_LABEL_TO_MPSZ.get(lbl, "1m")
            results.append((mpsz, prob))
        return results

    def _recognize_with_mahjong_detector(self, image_path: str, frame: np.ndarray) -> dict:
        """使用雀魂对局截屏专门训练的开源大模型 (mahjong-detector) 全图正交四向 TTA 严谨感知"""
        h, w = frame.shape[:2]
        # 严格执行全图正交四向 TTA 推断，阈值锁死在官方推荐的高置信度 0.50
        dets = self._detect_with_full_rotations(frame, conf_threshold=0.50)

        def to_mpsz(name: str) -> str:
            return DETECTOR_MAP.get(name, name)

        # 1. 宝牌指示牌提取 (左上角区域，经 ViT 4向旋转复核)
        dora_list = []
        dora_crops = []
        for d in dets:
            cx, cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
            if cx < w * 0.15 and cy < h * 0.18:
                crop = frame[max(0, int(d.y1)):min(h, int(d.y2)), max(0, int(d.x1)):min(w, int(d.x2))]
                dora_crops.append(crop)
        if dora_crops and self.vit_session:
            v_res = self._classify_crops_with_vit_4rot(dora_crops)
            dora_list = [m for m, p in v_res]
        else:
            for d in dets:
                cx, cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
                if cx < w * 0.15 and cy < h * 0.18:
                    dora_list.append(to_mpsz(MD_CLASS_NAMES[d.class_id]))
        dora_cn = [MPSZ_TO_CN.get(d, d) for d in dora_list]
        actual_dora_list = [DORA_NEXT.get(d, "") for d in dora_list if d in DORA_NEXT]
        actual_dora_cn = [MPSZ_TO_CN.get(d, d) for d in actual_dora_list]

        # 2. 自家手牌 (底部区域)
        # 2. 自家手牌提取 (最下方且尺寸最大的一组牌)
        max_h = max((d.y2 - d.y1 for d in dets), default=0)
        hand_tiles = []
        for d in dets:
            cx, cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
            bh = d.y2 - d.y1
            # 保留原有位置与尺寸门限，仅需附加尺寸最大过滤即可排除副露小牌
            if cy > h * 0.70 and bh > 40 and cx > w * 0.08 and bh >= 0.75 * max_h:
                crop = frame[max(0, int(d.y1)):min(h, int(d.y2)), max(0, int(d.x1)):min(w, int(d.x2))]
                tile = to_mpsz(MD_CLASS_NAMES[d.class_id])
                tile = self._check_red_dora(crop, tile)
                hand_tiles.append({
                    "raw_class": MD_CLASS_NAMES[d.class_id],
                    "mpsz": tile,
                    "cx": cx,
                    "cy": cy,
                    "box": [int(d.x1), int(d.y1), int(d.x2), int(d.y2)],
                    "confidence": float(d.confidence)
                })

        hand_tiles.sort(key=lambda item: item["cx"])
        mpsz_list = [r["mpsz"] for r in hand_tiles]
        cn_list = [MPSZ_TO_CN.get(m, m) for m in mpsz_list]
        tiles_mpsz_str = self.format_mpsz(mpsz_list)

        # 持宝牌数统计
        hand_dora_count = 0
        hand_dora_details = []
        for red_t in ["0m", "0p", "0s"]:
            rc = mpsz_list.count(red_t)
            if rc > 0:
                hand_dora_count += rc
                hand_dora_details.append(f"{MPSZ_TO_CN.get(red_t, red_t)} ×{rc}")
        for act in actual_dora_list:
            cnt = 0
            if act == "5m": cnt = mpsz_list.count("5m") + mpsz_list.count("0m")
            elif act == "5p": cnt = mpsz_list.count("5p") + mpsz_list.count("0p")
            elif act == "5s": cnt = mpsz_list.count("5s") + mpsz_list.count("0s")
            else: cnt = mpsz_list.count(act)
            if cnt > 0:
                hand_dora_count += cnt
                hand_dora_details.append(f"{MPSZ_TO_CN.get(act, act)} ×{cnt}")

        # 3. 四家副露提取与标准化
        melds = {"self": [], "shimocha": [], "toimen": [], "kamicha": []}
        kami_cands, shimo_cands, toi_cands, self_cands = [], [], [], []

        for d in dets:
            cx, cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
            crop = frame[max(0, int(d.y1)):min(h, int(d.y2)), max(0, int(d.x1)):min(w, int(d.x2))]
            t = to_mpsz(MD_CLASS_NAMES[d.class_id])
            t = self._check_red_dora(crop, t)
            bw = d.x2 - d.x1
            bh = d.y2 - d.y1
            aspect = bw / max(1.0, bh)
            cand = {"tile": t, "d": d, "cx": cx, "cy": cy, "aspect": aspect, "conf": float(d.confidence)}

            if cx < w * 0.20 and h * 0.25 <= cy <= h * 0.90:
                kami_cands.append(cand)
            elif cx > w * 0.80 and h * 0.15 <= cy <= h * 0.70:
                shimo_cands.append(cand)
            elif cy < h * 0.22 and w * 0.50 <= cx <= w * 0.85:
                toi_cands.append(cand)
            elif cy > h * 0.75 and cx > w * 0.75:
                self_cands.append(cand)

        def parse_player_melds(p_id: int, cands: List[Dict[str, Any]], is_vertical: bool) -> List[Dict[str, Any]]:
            p_names = {0: "自家(東)", 1: "下家(南)", 2: "对家(西)", 3: "上家(北)"}
            actor_name = p_names[p_id]
            if is_vertical:
                cands.sort(key=lambda x: x["cy"])
            else:
                cands.sort(key=lambda x: x["cx"])

            res = []
            for i in range(0, len(cands), 3):
                grp = cands[i:i+3]
                if len(grp) == 3:
                    tiles = [g["tile"] for g in grp]
                    asps = [g["aspect"] for g in grp]
                    min_idx = int(np.argmin(asps))

                    # 偏转牌来源推导 (MJAI 兼容)
                    if p_id == 3:  # 上家视角: 0:对家, 1:下家, 2:我方
                        t_map = {0: (2, "对家"), 1: (1, "下家"), 2: (0, "我方")}
                    elif p_id == 1:  # 下家视角: 0:对家, 1:上家, 2:我方
                        t_map = {0: (2, "对家"), 1: (3, "上家"), 2: (0, "我方")}
                    elif p_id == 2:  # 对家视角: 0:上家, 1:我方, 2:下家
                        t_map = {0: (3, "上家"), 1: (0, "我方"), 2: (1, "下家")}
                    else:  # 自家视角: 0:上家, 1:对家, 2:下家
                        t_map = {0: (3, "上家"), 1: (2, "对家"), 2: (1, "下家")}

                    target_id, target_name = t_map.get(min_idx, ((p_id - 1) % 4, "上家"))
                    if target_id == p_id:
                        target_id, target_name = (p_id - 1) % 4, "上家"

                    # 容错纠错：若 3 张牌中 2 张相同，第 3 张误判时自动修正为碰牌
                    norm = [t.replace("0", "5") for t in tiles]
                    if norm[0] == norm[2] and norm[0] != norm[1]:
                        tiles[1] = tiles[0]
                        norm[1] = norm[0]
                    elif norm[0] == norm[1] and norm[0] != norm[2]:
                        tiles[2] = tiles[0]
                        norm[2] = norm[0]
                    elif norm[1] == norm[2] and norm[1] != norm[0]:
                        tiles[0] = tiles[1]
                        norm[0] = norm[1]

                    if norm[0] == norm[1] == norm[2]:
                        m_type = "pon"
                        m_type_cn = "碰"
                        suit = tiles[0][1] if len(tiles[0]) == 2 else "m"
                        nums = "".join([t[0] for t in tiles])
                        tiles_str = f"{nums}{suit}"
                        tile_name_cn = f" ({MPSZ_TO_CN.get(tiles[0], '')})" if suit == "z" else ""
                        pai = tiles[min_idx]
                        consumed = [t for idx, t in enumerate(tiles) if idx != min_idx]
                        desc = f"{m_type_cn} {tiles_str}{tile_name_cn} (来自{target_name})"
                    else:
                        m_type = "chi"
                        m_type_cn = "吃"
                        suit = tiles[0][1] if len(tiles[0]) == 2 else "m"
                        nums = sorted([int(t[0]) for t in tiles if t[0].isdigit()])
                        tiles_str = f"{nums[0]}{nums[1]}{nums[2]}{suit}" if len(nums) == 3 else "".join(tiles)
                        pai = tiles[0]
                        consumed = tiles[1:]
                        kami_rel = {3: (2, "对家"), 2: (1, "下家"), 1: (0, "我方"), 0: (3, "上家")}
                        target_id, target_name = kami_rel.get(p_id, ((p_id - 1) % 4, "上家"))
                        desc = f"{m_type_cn} {tiles_str} (来自{target_name})"
                    res.append({
                        "type": m_type,
                        "actor": p_id,
                        "actor_name": actor_name,
                        "target": target_id,
                        "target_name": target_name,
                        "pai": pai,
                        "consumed": consumed,
                        "tiles": tiles,
                        "tiles_str": tiles_str,
                        "desc": desc
                    })
            return res

        melds["kamicha"] = parse_player_melds(3, kami_cands, is_vertical=True)
        melds["shimocha"] = parse_player_melds(1, shimo_cands, is_vertical=True)
        melds["toimen"] = parse_player_melds(2, toi_cands, is_vertical=False)
        melds["self"] = parse_player_melds(0, self_cands, is_vertical=False)

        # 4. 四家牌河解析（纯天然四象限分类与行序号自然排序，经 ViT 4向旋转复核，杜绝手写步长与插值）
        river_cands = []
        for d in dets:
            cx, cy = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
            if cx < w * 0.15 and cy < h * 0.20: continue
            if cy > h * 0.70 and (d.y2 - d.y1) > 40: continue
            if cx < w * 0.20 and cy > h * 0.25: continue
            if cx > w * 0.80 and cy > h * 0.15: continue
            if cy < h * 0.20 and cx > w * 0.55: continue
            if cy > h * 0.75 and cx > w * 0.75: continue

            seat = None
            if cy >= h * 0.48: seat = "self"
            elif cy <= h * 0.30 and cx >= w * 0.40: seat = "toimen"
            elif cx <= w * 0.41 and cy >= h * 0.22: seat = "kamicha"
            elif cx >= w * 0.59 and cy >= h * 0.28: seat = "shimocha"

            if seat:
                crop = frame[max(0, int(d.y1)):min(h, int(d.y2)), max(0, int(d.x1)):min(w, int(d.x2))]
                river_cands.append((seat, cx, cy, d, crop))

        r_crops = [it[4] for it in river_cands]
        if r_crops and self.vit_session:
            r_preds = self._classify_crops_with_vit_4rot(r_crops)
        else:
            r_preds = [(to_mpsz(MD_CLASS_NAMES[it[3].class_id]), float(it[3].confidence)) for it in river_cands]

        river_items = {"self": [], "shimocha": [], "toimen": [], "kamicha": []}
        for (seat, cx, cy, d, crop), (mpsz, prob) in zip(river_cands, r_preds):
            t = self._check_red_dora(crop, mpsz)
            item = {
                "tile": t,
                "cx": cx,
                "cy": cy,
                "box": [int(d.x1), int(d.y1), int(d.x2), int(d.y2)],
                "conf": float(prob)
            }
            if seat == "self":
                lid = 0 if cy < h * 0.55 else (1 if cy < h * 0.62 else 2)
                river_items["self"].append((lid, cx, item))
            elif seat == "toimen":
                lid = 0 if cy > h * 0.22 else (1 if cy > h * 0.16 else 2)
                river_items["toimen"].append((lid, -cx, item))
            elif seat == "kamicha":
                lid = 0 if cx > w * 0.35 else (1 if cx > w * 0.30 else 2)
                river_items["kamicha"].append((lid, cy, item))
            elif seat == "shimocha":
                lid = 0 if cx < w * 0.65 else (1 if cx < w * 0.70 else 2)
                river_items["shimocha"].append((lid, cy, item))

        rivers = {}
        for player in ["self", "shimocha", "toimen", "kamicha"]:
            p_items = river_items[player]
            p_items.sort(key=lambda it: (it[0], it[1]))
            rivers[player] = [it[2]["tile"] for it in p_items]

        # 5. 中央仪表盘 (RapidOCR)
        center_info = self._parse_center(frame)

        # 6. 巡目与牌山余牌数学守恒闭环 (Game State Parity Check)
        remain_txt = center_info.get("remaining", "")
        for token in ["余", " ", "牌"]:
            remain_txt = remain_txt.replace(token, "")
        remain_num = int(remain_txt) if remain_txt.isdigit() else None

        total_river_tiles = sum(len(rivers[k]) for k in rivers)
        melded_discards_count = 0
        total_kans = 0
        for seat, m_list in melds.items():
            for m in m_list:
                m_type = m.get("type", "")
                if m_type in ["pon", "chi", "daiminkan"]:
                    melded_discards_count += 1
                if "kan" in m_type:
                    total_kans += 1

        actual_completed_discards = total_river_tiles + melded_discards_count
        parity_info = {"status": "skipped"}
        if remain_num is not None:
            is_self_tsumo = 1 if len(mpsz_list) % 3 == 2 else 0
            expected_discards = 70 - remain_num - is_self_tsumo - total_kans
            diff = expected_discards - actual_completed_discards
            parity_info = {
                "remaining_wall": remain_num,
                "expected_discards": expected_discards,
                "actual_discards": actual_completed_discards,
                "river_tiles": total_river_tiles,
                "melded_discards": melded_discards_count,
                "diff": diff,
                "balanced": (diff == 0),
                "status": "balanced" if diff == 0 else f"discrepancy_{diff}"
            }

        # 7. 构造规范化 StandardMahjongState
        tsumo_tile = mpsz_list[-1] if len(mpsz_list) % 3 == 2 else None
        scores_map = center_info.get("scores", {})
        standard_state = StandardMahjongState(
            round_info=center_info,
            scores=scores_map,
            dora_indicators=dora_list,
            actual_dora=actual_dora_list,
            tehai=mpsz_list,
            tehai_mpsz=tiles_mpsz_str,
            fulou=melds,
            kawa=rivers,
            shanten_res={},
            hand_dora_count=hand_dora_count,
            hand_dora_details=hand_dora_details,
            tsumo_tile=tsumo_tile,
            parity_info=parity_info,
        )

        return {
            "success": True,
            "count": len(hand_tiles),
            "tiles": hand_tiles,
            "tiles_mpsz": tiles_mpsz_str,
            "raw_mpsz_list": mpsz_list,
            "tiles_cn": " ".join(cn_list),
            "dora_indicators": dora_list,
            "dora_cn": dora_cn,
            "actual_dora": actual_dora_list,
            "actual_dora_cn": actual_dora_cn,
            "hand_dora_count": hand_dora_count,
            "hand_dora_details": hand_dora_details,
            "rivers": rivers,
            "melds": melds,
            "center": center_info,
            "parity": parity_info,
            "state": standard_state,
            "extra_crop_paths": [],
        }

    def recognize(self, image_path: str) -> dict:
        """全量日麻盘面感知主入口"""
        if not os.path.exists(image_path):
            return {"success": False, "error": f"图片不存在: {image_path}"}

        frame = cv2.imread(image_path)
        if frame is None:
            return {"success": False, "error": "无法解码图片数据"}

        # 优先使用针对雀魂专门训练的高精度开源目标检测模型 mahjong-detector
        if HAS_MAHJONG_DETECTOR:
            try:
                res = self._recognize_with_mahjong_detector(image_path, frame)
                if res and res.get("success") and res.get("count", 0) >= 4:
                    return res
            except Exception as e:
                print(f"[MahjongVision] mahjong-detector 推断异常，自动降级回退: {e}")

        # 降级回退：全盘 YOLO + ViT 识别
        all_boxes = self._detect_all_yolo_boxes(frame)

        # 1. 自家手牌识别
        tile_boxes = self._locate_hand_tiles(frame, all_boxes=all_boxes)
        hand_tiles = []
        if self.vit_session and tile_boxes:
            batch = []
            for item in tile_boxes:
                rgb = cv2.cvtColor(item["crop"], cv2.COLOR_BGR2RGB)
                resized = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_LINEAR)
                norm = (resized.astype(np.float32) / 127.5) - 1.0
                batch.append(norm.transpose(2, 0, 1))

            input_tensor = np.array(batch, dtype=np.float32)
            logits = self.vit_session.run(None, {self.vit_in_name: input_tensor})[0]
            preds = np.argmax(logits, axis=1)

            for i, item in enumerate(tile_boxes):
                raw_lbl = self.vit_id2label.get(str(preds[i]), "1n")
                mpsz = VIT_LABEL_TO_MPSZ.get(raw_lbl, "1m")
                final_mpsz = self._check_red_dora(item["crop"], mpsz)
                hand_tiles.append({
                    "raw_class": raw_lbl,
                    "mpsz": final_mpsz,
                    "cx": item["cx"],
                    "cy": item["cy"],
                    "box": item["box"]
                })

        mpsz_list = [r["mpsz"] for r in hand_tiles]
        cn_list = [MPSZ_TO_CN.get(m, m) for m in mpsz_list]
        tiles_mpsz_str = self.format_mpsz(mpsz_list)

        # 2. 宝牌指示牌与实际宝牌推导
        dora_list = self._parse_dora(frame)
        dora_cn = [MPSZ_TO_CN.get(d, d) for d in dora_list]
        actual_dora_list = [DORA_NEXT.get(d, "") for d in dora_list if d in DORA_NEXT]
        actual_dora_cn = [MPSZ_TO_CN.get(d, d) for d in actual_dora_list]

        # 统计自家手牌持有的宝牌数量
        hand_dora_count = 0
        hand_dora_details = []
        for red_t in ["0m", "0p", "0s"]:
            rc = mpsz_list.count(red_t)
            if rc > 0:
                hand_dora_count += rc
                hand_dora_details.append(f"{MPSZ_TO_CN.get(red_t, red_t)} ×{rc}")
        for act in actual_dora_list:
            cnt = 0
            if act == "5m":
                cnt = mpsz_list.count("5m") + mpsz_list.count("0m")
            elif act == "5p":
                cnt = mpsz_list.count("5p") + mpsz_list.count("0p")
            elif act == "5s":
                cnt = mpsz_list.count("5s") + mpsz_list.count("0s")
            else:
                cnt = mpsz_list.count(act)
            if cnt > 0:
                hand_dora_count += cnt
                hand_dora_details.append(f"{MPSZ_TO_CN.get(act, act)} ×{cnt}")

        # 3. 四家牌河
        rivers = self._parse_rivers(frame)

        # 4. 规范化四家副露
        melds = self._parse_melds(frame, all_boxes=all_boxes)

        # 5. 中央仪表盘（局况与四家点数）
        center_info = self._parse_center(frame)

        # 6. 生成关键区域高清放大切片（牌河特写、副露特写），供多模态大模型双向校验与无损识图
        extra_crops = self._generate_zoom_crops(frame, image_path, melds)

        # 构造规范化 StandardMahjongState 对象
        scores_map = center_info.get("scores", {})
        standard_state = StandardMahjongState(
            round_info=center_info,
            scores=scores_map,
            dora_indicators=dora_list,
            actual_dora=actual_dora_list,
            tehai=mpsz_list,
            tehai_mpsz=tiles_mpsz_str,
            fulou=melds,
            kawa=rivers,
            shanten_res={},
            hand_dora_count=hand_dora_count,
            hand_dora_details=hand_dora_details,
        )

        return {
            "success": True,
            "count": len(hand_tiles),
            "tiles": hand_tiles,
            "tiles_mpsz": tiles_mpsz_str,
            "raw_mpsz_list": mpsz_list,
            "tiles_cn": " ".join(cn_list),
            "dora_indicators": dora_list,
            "dora_cn": dora_cn,
            "actual_dora": actual_dora_list,
            "actual_dora_cn": actual_dora_cn,
            "hand_dora_count": hand_dora_count,
            "hand_dora_details": hand_dora_details,
            "rivers": rivers,
            "melds": melds,
            "center": center_info,
            "state": standard_state,
            "extra_crop_paths": extra_crops,
        }

    def build_report(self, vision_res: dict, shanten_res: Optional[dict] = None) -> str:
        """生成格式化日麻全盘面视觉感知客观报告 (支持 StandardMahjongState 与 MJAI)"""
        state: Optional[StandardMahjongState] = vision_res.get("state")
        if state:
            if shanten_res:
                state.shanten_res = shanten_res
            return state.format_chat_report()

        # 兜底格式化
        lines = [
            "🀄【雀魂盘面视觉感知识别结果】",
            "━━━━━━━━━━━━━━━━━━"
        ]
        center = vision_res.get("center", {})
        round_str = center.get("round") or "东风战"
        remain_str = center.get("remaining") or ""
        lines.append(f"【对局局况】：{round_str}" + (f" | 牌山{remain_str}" if remain_str else ""))
        lines.append(f"【自家手牌】：{vision_res.get('tiles_mpsz', '')}")
        lines.append(f"【牌名对照】：{vision_res.get('tiles_cn', '')}")
        lines.append("━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    @staticmethod
    def format_mpsz(mpsz_list: List[str]) -> str:
        groups: Dict[str, List[str]] = {"m": [], "p": [], "s": [], "z": []}
        others = []
        for tile in mpsz_list:
            if len(tile) == 2 and tile[1] in groups:
                groups[tile[1]].append(tile[0])
            else:
                others.append(tile)
        res = ""
        for suit in ["m", "p", "s", "z"]:
            if groups[suit]:
                res += "".join(groups[suit]) + suit
        if others:
            res += " " + "".join(others)
        return res.strip()


class StandardMahjongState:
    """
    标准化日麻对局全盘面状态数据结构
    完全兼容 MJAI (Mahjong AI) 协议与 Mortal (凡夫) 对局输入格式
    """
    def __init__(
        self,
        round_info: Dict[str, Any],
        scores: Dict[str, Any],
        dora_indicators: List[str],
        actual_dora: List[str],
        tehai: List[str],
        tehai_mpsz: str,
        fulou: Dict[str, List[Dict[str, Any]]],
        kawa: Dict[str, List[str]],
        shanten_res: Dict[str, Any],
        hand_dora_count: int,
        hand_dora_details: List[str],
        tsumo_tile: Optional[str] = None,
        parity_info: Optional[Dict[str, Any]] = None,
    ):
        self.round_info = round_info
        self.scores = scores
        self.dora_indicators = dora_indicators
        self.actual_dora = actual_dora
        self.tehai = tehai
        self.tehai_mpsz = tehai_mpsz
        self.fulou = fulou
        self.kawa = kawa
        self.shanten_res = shanten_res
        self.hand_dora_count = hand_dora_count
        self.hand_dora_details = hand_dora_details
        self.tsumo_tile = tsumo_tile
        self.parity_info = parity_info

    def to_dict(self) -> Dict[str, Any]:
        """输出规范化 JSON 字典结构"""
        return {
            "round": self.round_info,
            "scores": self.scores,
            "dora_indicators": self.dora_indicators,
            "actual_dora": self.actual_dora,
            "tehai": self.tehai,
            "tehai_mpsz": self.tehai_mpsz,
            "fulou": self.fulou,
            "kawa": self.kawa,
            "shanten": self.shanten_res,
            "hand_dora": {
                "count": self.hand_dora_count,
                "details": self.hand_dora_details
            },
            "parity": self.parity_info,
        }

    def to_mjai_events(self) -> List[Dict[str, Any]]:
        """
        转换为标准 MJAI (Mahjong AI protocol) JSON 事件流
        可直接管道输入给 Mortal (凡夫) / mjai-reviewer 执行 AI 何切与复盘
        """
        events = []
        events.append({"type": "start_game", "names": ["自家", "下家", "对家", "上家"]})

        round_name = self.round_info.get("round", "東1局")
        bakaze = "E"
        if "南" in round_name:
            bakaze = "S"
        elif "西" in round_name:
            bakaze = "W"
        elif "北" in round_name:
            bakaze = "N"

        kyoku_num = 1
        for ch in round_name:
            if ch.isdigit():
                kyoku_num = int(ch)
                break

        p_scores = [
            int(self.scores.get("self", 25000) or 25000),
            int(self.scores.get("shimocha", 25000) or 25000),
            int(self.scores.get("toimen", 25000) or 25000),
            int(self.scores.get("kamicha", 25000) or 25000),
        ]

        dora_marker = self.dora_indicators[0] if self.dora_indicators else "5z"

        events.append({
            "type": "start_kyoku",
            "bakaze": bakaze,
            "kyoku": kyoku_num,
            "honba": int(self.round_info.get("honba", 0)),
            "kyotaku": int(self.round_info.get("kyotaku", 0)),
            "dora_marker": dora_marker,
            "scores": p_scores,
            "tehais": [
                [t for t in self.tehai],
                ["?"] * 13,
                ["?"] * 13,
                ["?"] * 13,
            ]
        })

        # 添加副露事件 (MJAI: chi, pon, daiminkan, ankan, kakan)
        for seat, m_list in self.fulou.items():
            for m in m_list:
                events.append({
                    "type": m.get("type", "pon"),
                    "actor": m.get("actor", 0),
                    "target": m.get("target", 0),
                    "pai": m.get("pai", ""),
                    "consumed": m.get("consumed", []),
                })

        # 添加牌河舍牌 (MJAI dahai)
        seat_order = ["self", "shimocha", "toimen", "kamicha"]
        max_river = max([len(self.kawa.get(s, [])) for s in seat_order] + [0])
        for step in range(max_river):
            for actor_idx, s in enumerate(seat_order):
                river = self.kawa.get(s, [])
                if step < len(river):
                    events.append({
                        "type": "dahai",
                        "actor": actor_idx,
                        "pai": river[step],
                        "tsumogiri": False
                    })

        # 若自家手牌是自摸状态 (14张)
        if len(self.tehai) % 3 == 2 and self.tehai:
            events.append({
                "type": "tsumo",
                "actor": 0,
                "pai": self.tehai[-1]
            })

        return events

    def format_chat_report(self) -> str:
        """生成格式化 QQ/TG 对局客观报告"""
        lines = [
            "🀄【雀魂盘面规范化感知识别结果 (Mortal / MJAI 兼容)】",
            "━━━━━━━━━━━━━━━━━━"
        ]
        round_str = self.round_info.get("round") or "东风战"
        remain_str = self.round_info.get("remaining") or ""
        round_line = f"【对局局况】：{round_str}" + (f" | 牌山{remain_str}" if remain_str else "")
        if self.parity_info and self.parity_info.get("status") == "balanced":
            round_line += f" (余{self.parity_info.get('remaining_wall')}张 ↔ 全局已舍{self.parity_info.get('actual_discards')}巡 物理闭环✓)"
        lines.append(round_line)

        score_lines = ["【四家点数】："]
        s_self = self.scores.get("self", "")
        s_shimo = self.scores.get("shimocha", "")
        s_toi = self.scores.get("toimen", "")
        s_kami = self.scores.get("kamicha", "")
        if s_self: score_lines.append(f"  • 自家(東/庄): {s_self}点")
        if s_shimo: score_lines.append(f"  • 下家(南): {s_shimo}点")
        if s_toi: score_lines.append(f"  • 对家(西): {s_toi}点")
        if s_kami: score_lines.append(f"  • 上家(北): {s_kami}点")
        if len(score_lines) > 1:
            lines.append("\n".join(score_lines))

        # 宝牌
        dora_cn = [MPSZ_TO_CN.get(d, d) for d in self.dora_indicators]
        act_cn = [MPSZ_TO_CN.get(d, d) for d in self.actual_dora]
        if dora_cn:
            d_str = f"【宝牌指示】：{', '.join(dora_cn)}"
            if act_cn:
                d_str += f" (实际宝牌: {', '.join(act_cn)})"
            lines.append(d_str)

        # 自家手牌
        lines.append(f"【自家手牌】：{self.tehai_mpsz}")
        tehai_cn = [MPSZ_TO_CN.get(t, t) for t in self.tehai]
        lines.append(f"【牌名对照】：{' '.join(tehai_cn)}")
        if self.tsumo_tile:
            lines.append(f"【当前摸入】：{MPSZ_TO_CN.get(self.tsumo_tile, self.tsumo_tile)} ({self.tsumo_tile})")

        # 持宝牌
        if self.hand_dora_count > 0:
            lines.append(f"【持宝牌数】：{self.hand_dora_count} 张 ({', '.join(self.hand_dora_details)})")


        # 规范化副露 (全量 3 张一组 + 来源)
        meld_lines = []
        seat_names = {"kamicha": "上家(北)", "toimen": "对家(西)", "shimocha": "下家(南)", "self": "自家(東)"}
        for k, s_name in seat_names.items():
            p_melds = self.fulou.get(k, [])
            if p_melds:
                m_descs = [m.get("desc", m.get("tiles_str", "")) for m in p_melds]
                meld_lines.append(f"  • {s_name}：{' | '.join(m_descs)}")
        if meld_lines:
            lines.append("【四家副露】：\n" + "\n".join(meld_lines))

        # 四家牌河
        river_lines = []
        r_seats = {"self": "自家", "shimocha": "下家", "toimen": "对家", "kamicha": "上家"}
        for k, r_name in r_seats.items():
            r_tiles = self.kawa.get(k, [])
            if r_tiles:
                r_cn = [MPSZ_TO_CN.get(t, t) for t in r_tiles]
                river_lines.append(f"  • {r_name} ({len(r_tiles)}巡)：{' '.join(r_cn)}")
        if river_lines:
            lines.append("【四家牌河】：\n" + "\n".join(river_lines))

        lines.append("━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
