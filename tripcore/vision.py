"""给一张缩略拼图写几句画面描写：只在用户点按钮时调用，用用户自己配置的视觉模型和 key。

- 需要两个环境变量（在用户自己的配置里设，不要发给助手）：DASHSCOPE_API_KEY，TRIPSIGHT_VISION_MODEL（必须是能读图的模型，
  例如 qwen3.7-max-2026-06-08；纯文本模型读不了图）。可选 TRIPSIGHT_VISION_URL（默认百炼的 OpenAI 兼容地址）。
- 发出去的只有一张缩小的拼图和一句提示词；不发原图、不发坐标、不发景点以外的信息。没配置就返回 None，调用方留空。
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

DEFAULT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
PROMPT = ("这是同一个地点拍的几张照片拼成的一张图。请用中文写 1–2 句描写（总共不超过 120 字），只写画面里看得到的光线、天气、色彩和气氛。"
          "不要写画面以外的事实、历史或事件，不要识别或猜测图中的人是谁，不要推测他们在想什么。景点名只作背景：")


class VisionError(Exception):
    pass


def config() -> Optional[dict]:
    key, model = os.environ.get("DASHSCOPE_API_KEY", "").strip(), os.environ.get("TRIPSIGHT_VISION_MODEL", "").strip()
    if not key or not model:
        return None
    return {"key": key, "model": model, "url": os.environ.get("TRIPSIGHT_VISION_URL", "").strip() or DEFAULT_URL}


def describe(sheet_jpeg: bytes, place_name: str) -> str:
    cfg = config()
    if cfg is None:
        raise VisionError("没有配置视觉模型（需要 DASHSCOPE_API_KEY 和 TRIPSIGHT_VISION_MODEL）。")
    body = {"model": cfg["model"], "max_tokens": 300, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(sheet_jpeg).decode()}},
        {"type": "text", "text": PROMPT + place_name}]}]}
    req = urllib.request.Request(cfg["url"], data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cfg["key"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        text = data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise VisionError(f"模型服务返回 {e.code}（模型不支持读图、key 不对或额度不够都会这样）")
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        raise VisionError("调用视觉模型失败（网络或返回格式不对）。")
    text = (text or "").strip() if isinstance(text, str) else ""
    if not text:
        raise VisionError("模型没有返回文字。")
    return text[:300]
