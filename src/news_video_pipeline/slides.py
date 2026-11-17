from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from .models import Scene

BG = "#101D31"
ACCENT = "#E2BB6C"
WHITE = "#FFFFFF"
SUBTLE = "#B9C8D9"


def font_path(config: dict) -> str:
    custom = config["render"].get("font_path", "")
    if custom:
        if not Path(custom).is_file():
            raise FileNotFoundError(f"font_path missing: {custom}")
        return str(custom)
    if shutil.which("fc-match"):
        try:
            found = subprocess.check_output(["fc-match", "-f", "%{file}", "Noto Sans CJK SC"], text=True, timeout=5).strip()
            if found and Path(found).is_file():
                return found
        except Exception:
            pass
    for path in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(path).is_file():
            return path
    raise RuntimeError("Install a Chinese-capable font (e.g. fonts-noto-cjk) or set render.font_path")


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines = []
    for para in text.splitlines() or [text]:
        line = ""
        for ch in para:
            next_line = line + ch
            if line and draw.textlength(next_line, font=font) > width:
                lines.append(line)
                line = ch
            else:
                line = next_line
        if line:
            lines.append(line)
    return lines


def render_slides(scenes: list[Scene], title: str, config: dict, out: Path) -> list[Path]:
    """One source of scene data creates both editable PPTX and pixel-based video slides."""
    width, height = int(config["render"]["width"]), int(config["render"]["height"])
    if width < 640 or height < 360:
        raise ValueError("Minimum slide size is 640x360")
    font_file = font_path(config)
    out.mkdir(parents=True, exist_ok=True)
    pres = Presentation()
    pres.slide_width = Inches(13.333333)
    pres.slide_height = Inches(7.5)
    prs_outputs: list[Path] = []
    scale = width / 1280
    headline_font = ImageFont.truetype(font_file, round(43 * scale))
    detail_font = ImageFont.truetype(font_file, round(32 * scale))
    footer_font = ImageFont.truetype(font_file, round(18 * scale))
    for idx, scene in enumerate(scenes, 1):
        img = Image.new("RGB", (width, height), BG)
        draw = ImageDraw.Draw(img)
        edge = round(80 * scale)
        draw.rectangle([edge, round(93 * scale), round(150 * scale), round(99 * scale)], fill=ACCENT)
        draw.text((edge, round(49 * scale)), config["project"]["title_prefix"], font=footer_font, fill=SUBTLE)
        heading_lines = wrap(draw, scene.title, headline_font, width - edge * 2)
        body_lines = wrap(draw, scene.body, detail_font, width - edge * 2)
        if len(heading_lines) > 2 or len(body_lines) > 7:
            raise ValueError(f"Text overflow on {scene.id}; reduce max_chars_per_scene or split long sentences")
        y = round(132 * scale)
        for line in heading_lines:
            draw.text((edge, y), line, fill=WHITE, font=headline_font)
            y += round(62 * scale)
        y += round(44 * scale)
        for line in body_lines:
            draw.text((edge, y), line, fill=SUBTLE, font=detail_font)
            y += round(57 * scale)
        if y > height - round(85 * scale):
            raise ValueError(f"Body overlaps footer on {scene.id}")
        draw.line((edge, height - round(65 * scale), width - edge, height - round(65 * scale)), fill="#36516C", width=max(1, round(2 * scale)))
        draw.text((edge, height - round(52 * scale)), title[:45], font=footer_font, fill=SUBTLE)
        counter = f"{idx:02d} / {len(scenes):02d}"
        cw = draw.textlength(counter, font=footer_font)
        draw.text((width - edge - cw, height - round(52 * scale)), counter, font=footer_font, fill=ACCENT)
        image_path = out / f"slide_{idx:03d}.png"
        img.save(image_path)
        prs_outputs.append(image_path)

        # Create matching native PowerPoint shapes/text, not flattened screenshot slides.
        slide = pres.slides.add_slide(pres.slide_layouts[6])
        rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, pres.slide_width, pres.slide_height)
        rect.fill.solid(); rect.fill.fore_color.rgb = RGBColor(16, 29, 49)
        rect.line.fill.background()
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.83), Inches(.97), Inches(.73), Inches(.065))
        bar.fill.solid(); bar.fill.fore_color.rgb = RGBColor(226, 187, 108); bar.line.fill.background()
        def add_text(text: str, x: float, y: float, w: float, h: float, size: int, color: tuple[int, int, int]) -> None:
            shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            tf = shape.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = 0
            tf.margin_top = tf.margin_bottom = 0
            tf.text = text
            for p in tf.paragraphs:
                p.font.name = "Noto Sans CJK SC"
                p.font.size = Pt(size)
                p.font.color.rgb = RGBColor(*color)
        add_text(config["project"]["title_prefix"], .83, .49, 11.0, .3, 12, (185, 200, 217))
        add_text(scene.title, .83, 1.30, 11.8, 1.2, 27, (255, 255, 255))
        add_text(scene.body, .83, 3.0, 11.7, 3.65, 20, (185, 200, 217))
        add_text(f"{title[:38]}                                      {idx:02d}/{len(scenes):02d}", .83, 7.0, 11.8, .30, 10, (226, 187, 108))
    pptx_file = out.parent / "daily.pptx"
    pres.save(pptx_file)
    return prs_outputs
