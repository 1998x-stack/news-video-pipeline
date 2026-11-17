from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Scene:
    id: str
    title: str
    body: str
    sentences: tuple[str, ...]
    source_id: str = "input"

    def to_dict(self) -> dict:
        out = asdict(self)
        out["sentences"] = list(self.sentences)
        return out


@dataclass(frozen=True)
class Cue:
    scene_id: str
    sentence_index: int
    text: str
    start_sample: int
    end_sample: int

    def to_dict(self, sample_rate: int) -> dict:
        return {
            "scene_id": self.scene_id,
            "sentence_index": self.sentence_index,
            "text": self.text,
            "start_ms": round(self.start_sample * 1000 / sample_rate),
            "end_ms": round(self.end_sample * 1000 / sample_rate),
        }
