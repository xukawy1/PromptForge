# -*- coding: utf-8 -*-
"""驱动真实应用（不显示窗口），抓取各页面操作状态图（用于抖音操作宣传视频）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = Path(__file__).resolve().parent / "shots"
OUT.mkdir(exist_ok=True)

from PIL import Image, PngImagePlugin

from app.core.application import Application

app = Application()
win = app.window
win.resize(1280, 800)
for _ in range(8):
    app.qt_app.processEvents()

def settle(n=6):
    for _ in range(n):
        app.qt_app.processEvents()

def shot(name):
    settle()
    win.grab().save(str(OUT / f"{name}.png"))
    print("shot:", name)

def go(row):
    win.navigation.setCurrentRow(row)
    settle(10)

# ---------- 1 工作台 ----------
shot("01_dashboard")

# ---------- 2 采集中心：文本采集 ----------
go(1)
page = win.stack.currentWidget()
page.text_edit.setPlainText(
    "赛博朋克风格的霓虹城市夜景描写：高楼之间全息广告闪烁，一位身穿黑色风衣的少女"
    "穿过雨幕，地面倒映着品红与青色的霓虹灯牌，镜头低角度跟随，电影感构图，冷暖光对比强烈。")
page.text_title.setText("霓虹城市夜景素材")
page._update_text_count()
shot("02_collector_text")

# ---------- 3 采集中心：网页识别归纳 ----------
page.url_edit.setText("https://example.com/neon-city-article")
page.url_title.setText("霓虹城市夜景创作参考")
page.function_list.setCurrentRow(2)
settle()
page.url_summary.setPlainText(
    "【English】cyberpunk neon city at night, girl in black trench coat walking through rain, "
    "holographic billboards, low angle tracking shot, teal and magenta reflections, cinematic\n"
    "【中文】赛博朋克霓虹城市夜景，黑色风衣少女雨中穿行，全息广告牌，低角度跟随镜头，青品红反射，电影感\n"
    "Negative prompt: lowres, daylight, watermark\n"
    "建议参数: 21:9 · 5s · slow dolly-in")
shot("03_collector_web")

# ---------- 4 知识库 ----------
go(2)
page = win.stack.currentWidget()
page.list.setCurrentRow(0)
settle()
shot("04_knowledge")

# ---------- 5 Prompt 库 ----------
go(5)
page = win.stack.currentWidget()
page.list.setCurrentRow(0)
settle()
shot("05_prompt_library")

# ---------- 6 Skill 工坊 ----------
go(6)
page = win.stack.currentWidget()
page.skill_combo.setCurrentIndex(0)
settle()
shot("06_skill")

# ---------- 7 Prompt 生成 ----------
go(7)
page = win.stack.currentWidget()
page.input.setPlainText("赛博朋克城市夜景中的少女半身像，霓虹灯光，电影感")
page.result_box.setPlainText(
    "【English】\ncinematic half-body portrait of a girl in a cyberpunk city at night, neon signage glow, "
    "rain-soaked streets, shallow depth of field, teal and magenta palette, ultra detailed\n"
    "【中文】\n赛博朋克夜晚城市中的少女半身电影感人像，霓虹招牌辉光，雨后湿街，浅景深，青品红色调，超精细细节\n"
    "Negative prompt: lowres, bad anatomy, watermark, blurry\n"
    "Steps: 30, CFG: 7, Size: 1080x1620")
page.parsed.setText("英文 148 字 · 中文 62 字 · 负向 44 字 · 参数 有")
page.progress_bar.setValue(100)
page.progress_info.setText("生成完成，共 312 字符")
settle()
shot("07_generator")

# ---------- 8 图片反推 ----------
go(8)
page = win.stack.currentWidget()
img_path = OUT / "sample_gen.png"
info = PngImagePlugin.PngInfo()
info.add_text("parameters",
              "masterpiece, best quality, 1girl, cinematic lighting\n"
              "Negative prompt: lowres, bad anatomy\n"
              "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 42, Size: 512x768")
Image.new("RGB", (512, 768), (88, 64, 180)).save(img_path, "PNG", pnginfo=info)
page._analyze_local(str(img_path))
settle()
shot("08_image_reverse")

# ---------- 9 模型中心（真实连接本机 Ollama） ----------
go(9)
page = win.stack.currentWidget()
page.refresh_models()
for _ in range(400):
    app.qt_app.processEvents()
    if not page._active_tasks:
        break
    import time
    time.sleep(0.05)
settle(20)
shot("09_models")

# ---------- 10 历史记录 ----------
go(10)
shot("10_history")

print("ALL_SHOTS_DONE", len(list(OUT.glob("*.png"))))
app.task_manager.shutdown()
