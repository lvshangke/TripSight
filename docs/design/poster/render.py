"""把 poster.html 渲染成 docs/images/poster.jpg（2000×1000，2 倍清晰度）。需要 pip install playwright pillow && playwright install chromium。
用法：在本目录运行 python render.py"""
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
here = Path(__file__).resolve().parent
tmp = here / "_poster.png"
with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files"])
    pg = b.new_page(viewport={"width": 2000, "height": 1000}, device_scale_factor=2)
    pg.goto((here / "poster.html").as_uri()); pg.wait_for_timeout(1200); pg.screenshot(path=str(tmp)); b.close()
Image.open(tmp).convert("RGB").save(here.parent.parent / "images" / "poster.jpg", quality=90)
tmp.unlink()
print("已生成", here.parent.parent / "images" / "poster.jpg")
