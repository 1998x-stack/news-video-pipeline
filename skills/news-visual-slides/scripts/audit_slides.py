#!/usr/bin/env python3
"""Slide image and editable PPTX package count audit using stdlib."""
import argparse
import json
import struct
from pathlib import Path
from zipfile import ZipFile

def audit(root: Path) -> dict:
    expected = len(json.loads((root / "scenes.json").read_text(encoding="utf-8")))
    pptx = root / "presentation/daily.pptx"
    with ZipFile(pptx) as archive:
        slides = [s for s in archive.namelist() if
                  s.startswith("ppt/slides/slide") and s.endswith(".xml") and
                  "/" not in s[len("ppt/slides/"):]]
        if not archive.testzip() is None:
            raise ValueError("Corrupt PPTX package")
    pngs = sorted((root / "presentation/slides").glob("slide_*.png"))
    if len(slides) != expected or len(pngs) != expected:
        raise ValueError(f"Scene={expected} PPTX={len(slides)} PNG={len(pngs)}")
    sizes = set()
    for png in pngs:
        with png.open("rb") as fp:
            header = fp.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Invalid PNG: {png}")
        sizes.add(struct.unpack(">II", header[16:24]))
    if len(sizes) != 1:
        raise ValueError(f"Inconsistent slide sizes: {sizes}")
    return {"status": "passed", "slides": expected, "png_size": list(sizes.pop()),
            "visual_semantic_review_required": True}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    print(json.dumps(audit(p.parse_args().output), ensure_ascii=False, indent=2))
