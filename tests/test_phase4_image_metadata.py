import json
from pathlib import Path
from PIL import Image, PngImagePlugin

from app.database.migrations import migrate
from app.services.image_analysis_service import ImageAnalysisService


A1111_TEXT = (
    "masterpiece, best quality, 1girl, cinematic lighting\n"
    "Negative prompt: lowres, bad anatomy, blurry\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x768, Model: anime_v3"
)

COMFYUI_WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 99, "steps": 25, "cfg": 6.5,
                                               "sampler_name": "euler", "scheduler": "normal",
                                               "denoise": 1.0,
                                               "positive": ["6", 0], "negative": ["7", 0],
                                               "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat astronaut, neon city"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "worst quality"}},
}


def make_png(tmp_path: Path, name: str, text_chunks: dict) -> Path:
    path = tmp_path / name
    info = PngImagePlugin.PngInfo()
    for key, value in text_chunks.items():
        info.add_text(key, value)
    Image.new("RGB", (8, 8), (10, 120, 200)).save(path, "PNG", pnginfo=info)
    return path


def test_parse_a1111_parameters():
    result = ImageAnalysisService.parse_a1111_parameters(A1111_TEXT)
    assert result["tool"] == "a1111"
    assert result["positive"] == "masterpiece, best quality, 1girl, cinematic lighting"
    assert result["negative"] == "lowres, bad anatomy, blurry"
    assert result["settings"]["Steps"] == "20"
    assert result["settings"]["Sampler"] == "Euler a"
    assert result["settings"]["Seed"] == "12345"
    assert result["settings"]["Width"] == "512"
    assert result["settings"]["Height"] == "768"


def test_parse_comfyui_workflow():
    result = ImageAnalysisService.parse_comfyui_workflow(json.dumps(COMFYUI_WORKFLOW))
    assert result["tool"] == "comfyui"
    assert "a cat astronaut" in result["positive"]
    assert "worst quality" in result["negative"]
    assert result["settings"]["steps"] == 25
    assert result["settings"]["model"] == "sd_xl_base.safetensors"


def test_analyze_path_detects_tool(tmp_path: Path):
    a1111_png = make_png(tmp_path, "a1111.png", {"parameters": A1111_TEXT})
    comfy_png = make_png(tmp_path, "comfy.png", {"prompt": json.dumps(COMFYUI_WORKFLOW)})
    plain_png = make_png(tmp_path, "plain.png", {})

    a = ImageAnalysisService.analyze_path(a1111_png)
    assert a["tool"] == "a1111" and "cinematic lighting" in a["positive"]

    b = ImageAnalysisService.analyze_path(comfy_png)
    assert b["tool"] == "comfyui" and "neon city" in b["positive"]

    c = ImageAnalysisService.analyze_path(plain_png)
    assert c["tool"] == "none" and c["positive"] == ""


def test_analyze_image_and_save_prompt(tmp_path: Path):
    db = tmp_path / "img.db"
    migrate(db)
    service = ImageAnalysisService(db)
    png = make_png(tmp_path, "gen.png", {"parameters": A1111_TEXT})

    from app.database.repositories.core import ImageRepository
    image_id = ImageRepository(db).create({
        "file_path": str(png), "file_hash": "hash-gen-1",
        "width": 8, "height": 8, "format": "png", "analysis_status": "pending",
    })

    analysis = service.analyze_image(image_id)
    assert analysis["tool"] == "a1111"
    row = service.images.get(image_id)
    assert row["analysis_status"] == "analyzed"
    assert json.loads(row["metadata"])["generation_metadata"]["tool"] == "a1111"

    outcome = service.save_as_prompt(image_id, title="测试反推")
    assert outcome["status"] == "created"
    prompt = service.prompts.get(outcome["prompt_id"])
    assert prompt["prompt_text"] == "masterpiece, best quality, 1girl, cinematic lighting"
    assert prompt["negative_prompt"] == "lowres, bad anatomy, blurry"
    assert prompt["image_id"] == image_id

    duplicate = service.save_as_prompt(image_id)
    assert duplicate["status"] == "duplicate"


def test_delete_image_record_and_file(tmp_path: Path):
    # 模拟真实布局：<root>/data/database/xxx.db，资料图片在 <root>/data/knowledge/images/
    db = tmp_path / "data" / "database" / "del.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    migrate(db)
    service = ImageAnalysisService(db)
    from app.database.repositories.core import ImageRepository
    repo = ImageRepository(db)

    # 文件在软件数据目录内 → 记录与文件一起删除
    image_dir = tmp_path / "data" / "knowledge" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    inside = image_dir / "copy.png"
    Image.new("RGB", (10, 10), (10, 10, 10)).save(inside)
    iid = repo.create({"file_path": str(inside), "file_hash": "del-1", "format": "png"})
    outcome = service.delete_image(iid)
    assert outcome["file_removed"] is True
    assert not inside.exists()
    assert repo.get(iid) is None

    # 文件不在数据目录内 → 只删记录，文件保留
    outside = tmp_path / "originals" / "keep.png"
    outside.parent.mkdir(exist_ok=True)
    Image.new("RGB", (10, 10), (20, 20, 20)).save(outside)
    iid2 = repo.create({"file_path": str(outside), "file_hash": "del-2", "format": "png"})
    outcome2 = service.delete_image(iid2)
    assert outcome2["file_removed"] is False
    assert outside.exists()
    assert repo.get(iid2) is None
