"""Sinh mô hình cơ thể 3D cho Dashboard (public/models/body-{male,female}.glb + body.json) từ Anny.

Anny (NAVER LABS Europe, Apache-2.0) là mô hình người tham số dựa trên tài nguyên MakeHuman (CC0), với các
tham số kiểu hình gender, age, muscle, weight, height, proportions trong [0, 1]. Mỗi file GLB là lưới của
người trưởng thành ở mức trung bình (tư thế chữ A) kèm 4 morph target là độ lệch vị trí và pháp tuyến:

    weight_hi = weight 1.0, weight_lo = weight 0.0, muscle_hi = muscle 1.0, muscle_lo = muscle 0.0

Frontend (src/components/dashboard/bodyMorph.ts) trộn chúng theo BMI và tỷ lệ mỡ, rồi co giãn theo chiều cao.
Chạy một lần (cần mạng để pip tải gói, khoảng 600 MB cùng PyTorch CPU):

    python -m venv /tmp/anny && /tmp/anny/bin/pip install anny numpy
    /tmp/anny/bin/python frontend/scripts/body-model/build_body_models.py --out frontend/public/models
"""
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

import numpy as np
import torch

import anny

# Anny: gender 0 = nam, 1 = nữ (kiểm tra: nữ có tỉ lệ hông/eo lớn hơn và thấp hơn ở cùng height = 0.5).
MODELS = {"male": 0.0, "female": 1.0}
TARGETS = {"weight_hi": ("weight", 1.0), "weight_lo": ("weight", 0.0),
           "muscle_hi": ("muscle", 1.0), "muscle_lo": ("muscle", 0.0)}
# Tư thế gốc dang tay ngang; hạ cánh tay quanh trục y cục bộ của upperarm01 để thành tư thế chữ A.
ARM_DEGREES = 40.0
LICENSE = """Mô hình cơ thể 3D (body-male.glb, body-female.glb, body.json)

Sinh bằng frontend/scripts/body-model/build_body_models.py từ Anny {version}
(NAVER LABS Europe, https://pypi.org/project/anny/), mã nguồn Apache License 2.0.
Lưới và blendshape gốc là tài nguyên MakeHuman/MPFB2, CC0 1.0 (public domain).
Tham chiếu: Human Mesh Modeling for Anny Body, arXiv:2511.03589.
"""


def _rotation_y(degrees: float) -> torch.Tensor:
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    matrix = torch.eye(4)
    matrix[:3, :3] = torch.tensor([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    return matrix[None]


def vertices(model: anny.Anny, *, posed: bool = True, **phenotype: float) -> np.ndarray:
    values = {label: 0.5 for label in model.phenotype_labels}
    values.update(phenotype)
    pose = {"upperarm01.L": _rotation_y(ARM_DEGREES), "upperarm01.R": _rotation_y(-ARM_DEGREES)} if posed else None
    with torch.no_grad():
        out = model(phenotype_kwargs=values, pose_parameters=pose)["vertices"][0].cpu().numpy().astype(np.float64)
    # Anny: z hướng lên, mặt trước về phía −y. glTF: Y hướng lên, mặt trước về phía +Z.
    return np.stack([out[:, 0], out[:, 2], -out[:, 1]], axis=1)


def normals(points: np.ndarray, faces: np.ndarray) -> np.ndarray:
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    face = np.cross(b - a, c - a)  # độ dài tỉ lệ diện tích: trung bình có trọng số theo diện tích
    result = np.zeros_like(points)
    for corner in range(3):
        np.add.at(result, faces[:, corner], face)
    length = np.linalg.norm(result, axis=1, keepdims=True)
    return result / np.where(length == 0, 1, length)


def anchors(points: np.ndarray) -> dict[str, float]:
    """Mốc ngực / eo / hông (tỉ lệ chiều cao): eo hẹp nhất, hông rộng nhất, ngực sâu nhất của thân (tay dang ngang)."""
    height = points[:, 1].max()
    torso = points[np.abs(points[:, 0]) < 0.2]

    def profile(low: float, high: float, measure):
        best = None
        for fraction in np.arange(low, high, 0.005):
            band = torso[np.abs(torso[:, 1] - fraction * height) < 0.008 * height]
            if len(band) < 8:
                continue
            value = measure(band)
            best = (fraction, value) if best is None or value[0] > best[1][0] else best
        return round(float(best[0]), 3)

    depth = lambda band: (band[:, 2].max() - band[:, 2].min(),)  # noqa: E731
    narrow = lambda band: (-(band[:, 0].max() - band[:, 0].min()),)  # noqa: E731
    # Hông: chỗ sâu nhất của mông (độ rộng ở vùng này lẫn cả hai đùi nên không dùng được).
    return {"chest": profile(0.68, 0.78, depth), "waist": profile(0.56, 0.66, narrow), "hip": profile(0.47, 0.56, depth)}


class Glb:
    """Ghi glTF 2.0 nhị phân tối thiểu: một lưới, một node, morph target có tên (extras.targetNames)."""

    def __init__(self):
        self.blob, self.views, self.accessors = bytearray(), [], []

    def add(self, array: np.ndarray, kind: str, component: int, target: int | None, *, bounds: bool) -> int:
        data = array.tobytes()
        while len(self.blob) % 4:
            self.blob.append(0)
        view = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.blob.extend(data)
        self.views.append(view)
        accessor = {"bufferView": len(self.views) - 1, "componentType": component, "count": int(array.shape[0]),
                    "type": kind}
        if bounds:
            accessor["min"] = [float(x) for x in array.min(axis=0)]
            accessor["max"] = [float(x) for x in array.max(axis=0)]
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def write(self, path: Path, base: np.ndarray, base_normals: np.ndarray, faces: np.ndarray,
              targets: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
        f32, u16, u32 = 5126, 5123, 5125
        position = self.add(base.astype(np.float32), "VEC3", f32, 34962, bounds=True)
        normal = self.add(base_normals.astype(np.float32), "VEC3", f32, 34962, bounds=False)
        index_type = u16 if len(base) < 65536 else u32
        indices = self.add(faces.reshape(-1).astype(np.uint16 if index_type == u16 else np.uint32), "SCALAR",
                           index_type, 34963, bounds=False)
        morphs = [{"POSITION": self.add(delta.astype(np.float32), "VEC3", f32, 34962, bounds=True),
                   "NORMAL": self.add(nd.astype(np.float32), "VEC3", f32, 34962, bounds=False)}
                  for delta, nd in targets.values()]
        document = {
            "asset": {"version": "2.0", "generator": "HercFit build_body_models.py (Anny)"},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "body"}],
            "meshes": [{"name": "body", "weights": [0.0] * len(morphs), "extras": {"targetNames": list(targets)},
                        "primitives": [{"attributes": {"POSITION": position, "NORMAL": normal}, "indices": indices,
                                        "mode": 4, "targets": morphs}]}],
            "buffers": [{"byteLength": len(self.blob)}], "bufferViews": self.views, "accessors": self.accessors,
        }
        text = json.dumps(document, separators=(",", ":")).encode()
        text += b" " * (-len(text) % 4)
        blob = bytes(self.blob) + b"\0" * (-len(self.blob) % 4)
        with path.open("wb") as handle:
            handle.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(text) + 8 + len(blob)))
            handle.write(struct.pack("<II", len(text), 0x4E4F534A) + text)
            handle.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def build(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    model = anny.Anny()
    assert {"gender", "muscle", "weight"} <= set(model.phenotype_labels), model.phenotype_labels
    faces = model.faces.cpu().numpy().astype(np.int64)
    meta = {}
    for name, gender in MODELS.items():
        base = vertices(model, gender=gender)
        floor, center = base[:, 1].min(), (base.min(axis=0) + base.max(axis=0)) / 2
        offset = np.array([center[0], floor, center[2]])  # gốc toạ độ giữa hai bàn chân, trên mặt đất
        base -= offset
        base_normals = normals(base, faces)
        targets = {}
        for target, (label, value) in TARGETS.items():
            shaped = vertices(model, gender=gender, **{label: value}) - offset
            targets[target] = (shaped - base, normals(shaped, faces) - base_normals)
        Glb().write(out / f"body-{name}.glb", base, base_normals, faces, targets)
        # Mốc đo trên tư thế gốc (tay dang ngang) để cánh tay không lọt vào vùng thân.
        meta[name] = {"height_cm": round(float(base[:, 1].max()) * 100, 1),
                      "anchors": anchors(vertices(model, posed=False, gender=gender) - offset)}
        print(name, meta[name], f"{(out / f'body-{name}.glb').stat().st_size / 1e6:.2f} MB")
    (out / "body.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    (out / "LICENSE.txt").write_text(LICENSE.format(version=getattr(anny, "__version__", "0.6.2")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "public" / "models")
    build(parser.parse_args().out)
