"""Detección conservadora de hojas en fotografías, sin modificar su color.

Combina contornos de bordes con segmentación de la superficie frente al fondo.
Devuelve cuatro esquinas en coordenadas de la fotografía original o None.
"""
from __future__ import annotations

import cv2
import numpy as np


def ordenar_esquinas(points: np.ndarray) -> np.ndarray:
    """Arriba izquierda, arriba derecha, abajo derecha, abajo izquierda."""
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    pts = pts[np.argsort(angles)]
    # En fotografías usuales, el vértice superior izquierdo minimiza (x + y).
    start = np.argmin(pts.sum(axis=1))
    pts = np.roll(pts, -int(start), axis=0)
    if pts[1, 0] < pts[3, 0]:
        pts = pts[[0, 3, 2, 1]]
    return pts


def _validar(quad: np.ndarray, width: int, height: int) -> tuple[bool, float]:
    corners = ordenar_esquinas(quad)
    poly = corners.reshape(-1, 1, 2)
    if not cv2.isContourConvex(poly):
        return False, 0.0
    area_fraction = abs(cv2.contourArea(poly)) / (width * height)
    if not 0.16 <= area_fraction <= 0.995:
        return False, 0.0
    tl, tr, br, bl = corners
    top, bottom = np.linalg.norm(tr-tl), np.linalg.norm(br-bl)
    left, right = np.linalg.norm(bl-tl), np.linalg.norm(br-tr)
    if min(top, bottom, left, right) < min(width, height) * 0.15:
        return False, 0.0
    aspect = ((top + bottom) / 2) / ((left + right) / 2)
    if not 0.42 <= aspect <= 2.4:
        return False, 0.0
    if max(top, bottom) / min(top, bottom) > 2.3 or max(left, right) / min(left, right) > 2.3:
        return False, 0.0
    center = corners.mean(axis=0)
    if np.linalg.norm((center - (width/2, height/2)) / (width, height)) > .25:
        return False, 0.0
    return True, float(area_fraction)


def _quad_from_contour(contour: np.ndarray) -> list[tuple[np.ndarray, bool]]:
    """Polígonos de cuatro lados, y caja rotada cuando hay bordes irregulares."""
    result = []
    for part in (contour, cv2.convexHull(contour)):
        perimeter = cv2.arcLength(part, True)
        if perimeter < 10:
            continue
        for eps in (.012, .02, .03, .045, .065):
            approx = cv2.approxPolyDP(part, eps * perimeter, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                result.append((approx.reshape(4, 2), False))
        # Útil cuando el borde de papel se ve irregular debido a sombras.
        rect = cv2.minAreaRect(part)
        box = cv2.boxPoints(rect)
        area = cv2.contourArea(part)
        box_area = max(1.0, cv2.contourArea(box))
        if area / box_area >= .87:
            result.append((box, True))
    return result


def _contraste_exterior(quad: np.ndarray, lab: np.ndarray) -> tuple[float, int]:
    """Comprueba que cada lado separa papel de fondo real, no del marco de foto.

    Se comparan muestras a ambos lados de la arista en vez de premiar solo el
    área del rectángulo. Esto reduce falsos positivos con fondos estampados.
    """
    height, width = lab.shape[:2]
    center = quad.mean(axis=0)
    offset = max(5., min(height, width) * .014)
    strengths = []
    sides_with_background = 0
    for p1, p2 in zip(quad, np.roll(quad, -1, axis=0)):
        t = np.linspace(.15, .85, 29, dtype=np.float32)[:, None]
        positions = p1[None, :] * (1. - t) + p2[None, :] * t
        inward = center - positions.mean(axis=0)
        norm = float(np.linalg.norm(inward))
        if norm < 1:
            strengths.append(0.)
            continue
        inward = inward / norm * offset
        inside, outside = positions + inward, positions - inward
        valid = ((outside[:, 0] >= 2) & (outside[:, 0] < width-2)
                 & (outside[:, 1] >= 2) & (outside[:, 1] < height-2)
                 & (inside[:, 0] >= 1) & (inside[:, 0] < width-1)
                 & (inside[:, 1] >= 1) & (inside[:, 1] < height-1))
        if np.count_nonzero(valid) < 20:
            strengths.append(0.)
            continue
        sides_with_background += 1
        a = np.rint(inside[valid]).astype(int)
        b = np.rint(outside[valid]).astype(int)
        distances = np.linalg.norm(lab[a[:, 1], a[:, 0]] - lab[b[:, 1], b[:, 0]], axis=1)
        strengths.append(float(np.median(distances)))
    return float(np.median(strengths)), sides_with_background


def detectar_hoja(rgb: np.ndarray) -> np.ndarray | None:
    """Localiza cuatro esquinas sin necesidad de papel blanco o fondo negro."""
    h, w = rgb.shape[:2]
    if min(h, w) < 150:
        return None
    scale = min(1.0, 1300 / max(w, h))
    small = cv2.resize(rgb, (round(w*scale), round(h*scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    k3 = np.ones((3, 3), np.uint8)
    k7 = np.ones((7, 7), np.uint8)
    masks: list[tuple[str, np.ndarray]] = []

    # Contornos naturales: intenta varias sensibilidades y une trazos rotos.
    for lower, upper in ((25, 85), (45, 130), (65, 170)):
        edges = cv2.Canny(blurred, lower, upper)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k7, iterations=2)
        masks.append(("bordes", edges))

    # Página clara sobre mesa oscura (y viceversa), incluso si faltan aristas.
    otsu_threshold, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edge_w = max(8, int(sw * .055))
    edge_h = max(8, int(sh * .055))
    patches = [blurred[:edge_h, :edge_w], blurred[:edge_h, -edge_w:],
               blurred[-edge_h:, :edge_w], blurred[-edge_h:, -edge_w:]]
    background_lightness = float(np.median(np.concatenate([p.ravel() for p in patches])))
    center_lightness = float(np.median(blurred[sh//3:2*sh//3, sw//3:2*sw//3]))
    if abs(center_lightness - background_lightness) >= 18:
        binary = (blurred > otsu_threshold) if center_lightness > background_lightness else (blurred < otsu_threshold)
        mask = cv2.morphologyEx((binary * 255).astype(np.uint8), cv2.MORPH_CLOSE, k7, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3)
        masks.append(("luminosidad", mask))

    # Segmentación LAB por diferencia de color entre esquinas y hoja.
    labs = [lab[:edge_h, :edge_w], lab[:edge_h, -edge_w:],
            lab[-edge_h:, :edge_w], lab[-edge_h:, -edge_w:]]
    bg_colors = [np.median(p.reshape(-1, 3), axis=0) for p in labs]
    distances = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in bg_colors]), axis=0)
    dist8 = np.uint8(np.clip(distances * 2.0, 0, 255))
    threshold, _ = cv2.threshold(dist8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = max(22, threshold)
    color_mask = np.uint8(dist8 > threshold) * 255
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, k7, iterations=2)
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, k3)
    masks.append(("color", color_mask))

    # La intensidad del borde de la hoja es evidencia adicional independiente.
    grad_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    gradients = cv2.magnitude(grad_x, grad_y)
    gradients = cv2.dilate(gradients, k3)
    gradient_scale = max(15., float(np.percentile(gradients, 90)))
    candidates = []
    for method, mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST if method == "bordes" else cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:16]:
            area = cv2.contourArea(contour)
            if area < .13 * sw * sh:
                continue
            for raw, is_box_fallback in _quad_from_contour(contour):
                quad = ordenar_esquinas(raw)
                valid, fraction = _validar(quad, sw, sh)
                if not valid:
                    continue
                # Evidencia de un borde físico en cada lado, evita elegir un
                # bloque rectangular de contenido sin contraste exterior.
                supports = []
                for p1, p2 in zip(quad, np.roll(quad, -1, axis=0)):
                    pts = np.linspace(p1, p2, num=35)[3:-3]
                    xy = np.rint(pts).astype(int)
                    xs = np.clip(xy[:, 0], 0, sw-1)
                    ys = np.clip(xy[:, 1], 0, sh-1)
                    supports.append(float(np.median(gradients[ys, xs])))
                edge_quality = float(np.clip(np.median(supports) / gradient_scale, 0, 1))
                center = quad.mean(axis=0)
                off_center = np.linalg.norm((center-(sw/2, sh/2)) / (sw, sh))
                # La hoja debe separar físicamente el papel del fondo, con
                # evidencia en al menos tres lados. El marco de la fotografía
                # carece de píxeles exteriores y ya no puede ganar por ser grande.
                contrast, observed_sides = _contraste_exterior(quad, lab)
                if observed_sides < 3 or contrast < 7.5:
                    continue
                color_quality = min(1.0, contrast / 35.)
                score = (fraction * .32 + edge_quality * .20 + color_quality * 1.5
                         - off_center * .16 - (.06 if is_box_fallback else 0))
                candidates.append((score, quad, method))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, best, _ = candidates[0]
    # Si apenas hay señal de que exista una hoja, conservar la foto completa.
    if score < .3:
        return None
    return best / scale
