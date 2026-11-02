"""Aprendizaje local y explícito de recortes manuales, sin conservar fotografías.

No se entrena ni escribe nada hasta que el usuario pulsa "Aprender de mis ajustes".
Se almacena una memoria de ejemplos (color aproximado y geometría) en APPDATA.
Sólo se aplican pequeñas correcciones a fotos con características parecidas.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import os
import tempfile
import threading

import cv2
import numpy as np

VERSION = 1
MAX_EXAMPLES = 400
MAX_NORMALIZED_SHIFT = .08
MAX_DISTANCE = .14
_LOCK = threading.Lock()


def learning_path() -> Path:
    root = Path(os.environ.get("APPDATA") or
                (Path.home() / ".config")) / "DigitalizadorFotos"
    return root / "aprendizaje_esquinas.json"


def _ordered(points: np.ndarray) -> np.ndarray:
    from recorte import ordenar_esquinas
    return ordenar_esquinas(np.asarray(points, dtype=np.float32).reshape(4, 2))


def _valid(points: np.ndarray, width: int, height: int) -> bool:
    from digitalizador import safe_auto_geometry
    return safe_auto_geometry(points, width, height)


def _feature(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Describe fondo, papel y ubicación de la hoja, sin datos identificables."""
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    d = max(4, min(h, w) // 32)
    samples = [
        lab[d:2*d, d:2*d],
        lab[d:2*d, w-2*d:w-d],
        lab[h-2*d:h-d, d:2*d],
        lab[h-2*d:h-d, w-2*d:w-d],
    ]
    background = np.median(np.stack(
        [np.median(s.reshape(-1, 3), axis=0) for s in samples]), axis=0)
    center = np.mean(quad, axis=0).astype(int)
    cx = int(np.clip(center[0], d, w-d-1))
    cy = int(np.clip(center[1], d, h-d-1))
    paper = np.median(lab[cy-d:cy+d, cx-d:cx+d].reshape(-1, 3), axis=0)
    widths = [float(np.linalg.norm(quad[i]-quad[(i+1) % 4]))
              for i in range(4)]
    ratio = (widths[0]+widths[2]) / max(1., widths[1]+widths[3])
    area = abs(cv2.contourArea(quad)) / (w*h)
    return np.array([
        *(paper / 255 * .8), *(background / 255 * .8),
        float(center[0]/w), float(center[1]/h), float(area),
        float(np.clip(np.log(max(.1, ratio)), -1.5, 1.5)) * .3,
    ], dtype=np.float32)


def make_example(image: np.ndarray, base_corners: np.ndarray,
                 corrected_corners: np.ndarray, full_size: tuple[int, int],
                 fingerprint: str = "") -> dict | None:
    """Ejemplo de corrección real, con límites de seguridad geométrica."""
    h, w = image.shape[:2]
    fw, fh = full_size
    if fw <= 0 or fh <= 0:
        return None
    factor = np.float32([w/fw, h/fh])
    base = _ordered(base_corners * factor)
    corrected = _ordered(corrected_corners * factor)
    if not _valid(base, w, h) or not _valid(corrected, w, h):
        return None
    adjustment = (corrected-base) / np.float32([w, h])
    move = float(np.max(np.linalg.norm(corrected-base, axis=1)))
    if move < 2 or float(np.max(np.abs(adjustment))) > MAX_NORMALIZED_SHIFT:
        return None
    feature = _feature(image, base)
    return {
        "feature": np.round(feature, 5).tolist(),
        "adjustment": np.round(adjustment, 6).tolist(),
        "fingerprint": fingerprint,
    }


def fingerprint_photo(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=1)
def _load(path: str) -> tuple[dict, ...]:
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        if data.get("version") != VERSION or not isinstance(data.get("examples"), list):
            return ()
        valid = []
        for item in data["examples"][-MAX_EXAMPLES:]:
            try:
                feature = np.asarray(item["feature"], dtype=float)
                correction = np.asarray(item["adjustment"], dtype=float)
                if (feature.shape == (10,) and correction.shape == (4, 2)
                        and np.isfinite(feature).all()
                        and np.isfinite(correction).all()
                        and np.max(np.abs(correction)) <= MAX_NORMALIZED_SHIFT):
                    valid.append(item)
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(valid)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ()


def read_examples(path: Path | None = None) -> tuple[dict, ...]:
    return _load(str(path or learning_path()))


def save_examples(examples: list[dict], path: Path | None = None) -> tuple[int, int]:
    """Sólo el botón explícito llama a esta función. Escritura atómica."""
    destination = path or learning_path()
    if not examples:
        return 0, len(read_examples(destination))
    with _LOCK:
        previous = list(read_examples(destination))
        used = {e.get("fingerprint") for e in previous if e.get("fingerprint")}
        added = 0
        for item in examples:
            key = item.get("fingerprint")
            if key and key in used:
                continue
            if key:
                used.add(key)
            previous.append(item)
            added += 1
        if not added:
            return 0, len(previous)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".aprendizaje_", suffix=".json",
                                   dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": VERSION, "examples": previous[-MAX_EXAMPLES:]},
                          stream, ensure_ascii=False, indent=2)
            os.replace(temp, destination)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        _load.cache_clear()
        return added, min(len(previous), MAX_EXAMPLES)


def apply_learning(image: np.ndarray, base_corners: np.ndarray,
                   path: Path | None = None) -> np.ndarray | None:
    """Calibración de vecinos similares, no reemplaza el detector ni fuerza casos raros."""
    examples = read_examples(path)
    if not examples:
        return None
    h, w = image.shape[:2]
    base = _ordered(base_corners)
    if not _valid(base, w, h):
        return None
    descriptor = _feature(image, base)
    ranked = []
    for item in examples:
        score = float(np.linalg.norm(
            descriptor - np.asarray(item["feature"], dtype=np.float32)))
        if score < MAX_DISTANCE:
            ranked.append((score, item))
    if not ranked:
        return None
    closest = sorted(ranked, key=lambda x: x[0])[:5]
    weights = np.array([1 / max(.02, distance)**2 for distance, _ in closest])
    corrections = np.stack([
        np.asarray(sample["adjustment"], dtype=np.float32) for _, sample in closest])
    adjustment = np.average(corrections, axis=0, weights=weights)
    # Conservador: tres cuartas partes de la corrección aprendida.
    candidate = base + adjustment * np.float32([w, h]) * .75
    if not _valid(candidate, w, h):
        return None
    old_area = abs(cv2.contourArea(base))
    new_area = abs(cv2.contourArea(candidate))
    if old_area <= 0 or abs(new_area/old_area-1) > .18:
        return None
    if np.max(np.linalg.norm(candidate-base, axis=1)) < 1.25:
        return None
    return candidate.astype(np.float32)
