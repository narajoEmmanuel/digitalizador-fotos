"""Digitalizador de fotografías a PDF, sin OCR ni transcripción.

Compatible con Windows 10/11, Python 3.10+.
El programa conserva el color y nunca modifica las fotografías originales.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import datetime, timedelta, timezone
import os
import queue
import re
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Callable

from recorte import detectar_hoja, ordenar_esquinas

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageCms, ImageOps, ImageTk
from reportlab.pdfgen import canvas

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
MAX_SIDE = 6000  # Guardar detalle para archivo a largo plazo (no disminuir fotos normales del iPhone).


def normalized_pdf_name(value: str) -> str:
    """Valida un nombre Windows y añade .pdf exactamente una vez."""
    name = value.strip()
    if name.lower().endswith(".pdf"):
        name = name[:-4].strip()
    if not name or name in {".", ".."}:
        raise ValueError("Escribe un nombre para el PDF.")
    if any(char in name for char in '<>:"/\\|?*') or name.endswith(".") or name.endswith(" "):
        raise ValueError("El nombre contiene caracteres que Windows no permite.")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{i}" for i in range(1, 10))
    reserved.update(f"LPT{i}" for i in range(1, 10))
    if name.upper().split(".")[0] in reserved:
        raise ValueError("Elige otro nombre, Windows reserva ese nombre.")
    return name + ".pdf"


def normalize_pdf_destination(selected: str) -> Path:
    """Conserva carpeta y nombre elegidos en Guardar como, exige extensión PDF."""
    path = Path(selected)
    if path.suffix and path.suffix.lower() != ".pdf":
        raise ValueError("El archivo debe tener la extensión .pdf.")
    return path.with_name(normalized_pdf_name(path.name))


def build_export_destination(folder: Path, typed_name: str) -> Path:
    """El nombre definido en la aplicación es definitivo, no el del diálogo Windows."""
    if not folder.is_dir():
        raise ValueError("Selecciona una carpeta de destino válida.")
    return folder / normalized_pdf_name(typed_name)


def export_success_text(path: Path, pages: int, uncropped: int = 0) -> str:
    """Mensaje compacto y verificable para la confirmación de exportación."""
    text = f"✓ PDF guardado: {path.name}\n{pages} páginas · {path.parent}"
    if uncropped:
        text += f"\n⚠ {uncropped} página(s) sin recorte seguro"
    return text


def verify_pdf_export(path: Path, expected_pages: int) -> None:
    """Revisa el PDF temporal antes de publicarlo como archivo definitivo."""
    import fitz
    with fitz.open(path) as document:
        if document.is_encrypted or document.page_count != expected_pages:
            raise RuntimeError("El PDF exportado está incompleto o no se puede abrir.")
        for page_number in range(document.page_count):
            if not document.load_page(page_number).get_images(full=True):
                raise RuntimeError(f"La página {page_number + 1} del PDF no contiene la imagen.")



def capture_datetime(photo: Path) -> datetime:
    """Obtiene la fecha ORIGINAL de toma (EXIF DateTimeOriginal), no la del archivo.

    No se usan nombres, fechas de descarga ni modificaciones de OneDrive.
    El offset horario y fracciones de segundo se conservan cuando existen.
    """
    try:
        with Image.open(photo) as image:
            exif = image.getexif()
            camera_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            raw = camera_ifd.get(36867) or exif.get(36867)  # DateTimeOriginal
            subsec = camera_ifd.get(37521) or exif.get(37521)  # SubSecTimeOriginal
            offset = camera_ifd.get(36881) or exif.get(36881)  # OffsetTimeOriginal
    except Exception as exc:
        raise ValueError(f"{photo.name}: no se pudieron leer sus metadatos de captura ({exc}).") from exc

    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")
    if not isinstance(raw, str):
        raise ValueError(
            f"{photo.name}: falta EXIF DateTimeOriginal. Exporta la foto original "
            "desde el iPhone/OneDrive sin eliminar metadatos; no se usará la fecha de subida."
        )
    try:
        result = datetime.strptime(raw.strip().strip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"{photo.name}: hora EXIF DateTimeOriginal no válida: {raw!r}.") from exc

    if isinstance(subsec, bytes):
        subsec = subsec.decode("ascii", errors="replace")
    if subsec is not None:
        digits = str(subsec).strip().strip("\x00")
        if digits.isdigit():
            result = result.replace(microsecond=int((digits + "000000")[:6]))

    if isinstance(offset, bytes):
        offset = offset.decode("ascii", errors="replace")
    if isinstance(offset, str):
        match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset.strip().strip("\x00"))
        if match:
            hours, minutes = int(match[2]), int(match[3])
            if hours <= 23 and minutes <= 59:
                delta = timedelta(hours=hours, minutes=minutes)
                result = result.replace(tzinfo=timezone(delta if match[1] == "+" else -delta))
    return result


def capture_order(paths: list[Path]) -> list[Path]:
    """Orden estricto por captura; si faltan metadatos, no adivina el orden."""
    dates = []
    failures = []
    for photo in paths:
        try:
            dates.append((photo, capture_datetime(photo)))
        except ValueError as exc:
            failures.append(str(exc))
    if failures:
        sample = "\n".join(f"- {message}" for message in failures[:8])
        remaining = f"\n... y {len(failures) - 8} más." if len(failures) > 8 else ""
        raise ValueError(
            f"{len(failures)} foto(s) sin fecha original de captura válida. "
            "No se creará el PDF con un orden supuesto.\n" + sample + remaining
        )
    # Si TODAS las fotos tienen zona horaria, comparar instantes absolutos en UTC.
    # Si algunas no la incluyen, comparar la hora local registrada por la cámara.
    all_zoned = all(timestamp.tzinfo is not None for _, timestamp in dates)
    dates.sort(key=lambda item: item[1].astimezone(timezone.utc)
               if all_zoned else item[1].replace(tzinfo=None))
    # Empates exactos conservan el orden de entrada: EXIF no permite distinguirlos.
    return [path for path, _ in dates]


def discover_images(folder: Path) -> list[Path]:
    photos = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS]
    return capture_order(photos)


def open_color_image(path: Path) -> Image.Image:
    if path.suffix.lower() in {".heic", ".heif"} and not HEIC_AVAILABLE:
        raise RuntimeError("Para abrir fotos HEIC instala pillow-heif: pip install pillow-heif")
    with Image.open(path) as source:
        source.load()
        corrected = ImageOps.exif_transpose(source)
        icc = corrected.info.get("icc_profile")
        # Si la imagen es Display P3, convertirla a sRGB conserva su aspecto en lectores PDF.
        if icc:
            try:
                from io import BytesIO
                corrected = ImageCms.profileToProfile(
                    corrected.convert("RGB"), ImageCms.ImageCmsProfile(BytesIO(icc)), ImageCms.createProfile("sRGB"),
                    outputMode="RGB",
                )
            except Exception:
                corrected = corrected.convert("RGB")
        else:
            corrected = corrected.convert("RGB")
        return corrected.copy()



def preview_image(photo: Path, max_side: int = 1150) -> tuple[Image.Image, tuple[int, int]]:
    """Lee una miniatura para vista previa y editor de esquinas, sin procesar 12/48 MP.

    Retorna imagen RGB y dimensiones originales corregidas por orientación EXIF.
    """
    with Image.open(photo) as src:
        width, height = src.size
        orientation = src.getexif().get(274, 1)
        if orientation in (5, 6, 7, 8):
            width, height = height, width
        if photo.suffix.lower() in ('.jpg', '.jpeg'):
            src.draft('RGB', (max_side * 2, max_side * 2))
        src.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
        frame = ImageOps.exif_transpose(src)
        icc = frame.info.get('icc_profile')
        if icc:
            try:
                from io import BytesIO
                frame = ImageCms.profileToProfile(frame.convert('RGB'),
                    ImageCms.ImageCmsProfile(BytesIO(icc)), ImageCms.createProfile('sRGB'), outputMode='RGB')
            except Exception:
                frame = frame.convert('RGB')
        else:
            frame = frame.convert('RGB')
        return frame.copy(), (width, height)



def find_document_corners(rgb: np.ndarray) -> np.ndarray | None:
    """Encuentra la hoja usando bordes, contraste y color del fondo."""
    return detectar_hoja(rgb)


def safe_auto_geometry(quad: np.ndarray, width: int, height: int) -> bool:
    """Descarta perspectivas extremas antes de transformar una hoja."""
    pts = ordenar_esquinas(quad)
    if not np.isfinite(pts).all() or not cv2.isContourConvex(pts.reshape(-1, 1, 2)):
        return False
    if ((pts[:, 0] < 0).any() or (pts[:, 1] < 0).any()
            or (pts[:, 0] > width-1).any() or (pts[:, 1] > height-1).any()):
        return False
    area = abs(cv2.contourArea(pts)) / (width * height)
    if not .18 <= area <= .98:
        return False
    edges = [float(np.linalg.norm(pts[(i+1)%4]-pts[i])) for i in range(4)]
    if min(edges) < .18 * min(width, height):
        return False
    if max(edges[0], edges[2]) / min(edges[0], edges[2]) > 1.85:
        return False
    if max(edges[1], edges[3]) / min(edges[1], edges[3]) > 1.85:
        return False
    return True


@lru_cache(maxsize=4096)
def _cached_auto_corners(photo: Path, modified_ns: int, size_bytes: int):
    """Detector a la misma escala para matriz, zoom y exportación."""
    reduced, full_size = preview_image(photo, 1050)
    try:
        image = np.asarray(reduced)
        h, w = image.shape[:2]
        quad = find_document_corners(image)
        if quad is None:
            return None, "No se detectó la hoja"
        quad = ordenar_esquinas(quad)
        if not safe_auto_geometry(quad, w, h):
            return None, "Perspectiva dudosa"
        # Segunda escala: si el detector cambia de hoja, no deformar el PDF.
        scale = min(1., 700 / max(w, h))
        if scale < 1:
            second_image = cv2.resize(image, (round(w*scale), round(h*scale)),
                                      interpolation=cv2.INTER_AREA)
            second = find_document_corners(second_image)
            if second is None:
                return None, "Bordes inestables"
            second = ordenar_esquinas(second) / scale
            if np.max(np.linalg.norm(quad - second, axis=1)) > max(18., .035*max(w, h)):
                return None, "Esquinas inestables"
        full_w, full_h = full_size
        corners = quad * np.float32([full_w / w, full_h / h])
        return corners.astype(np.float32), None
    finally:
        reduced.close()


def automatic_page_corners(photo: Path) -> tuple[np.ndarray | None, str | None]:
    """Coordenadas originales compartidas por todas las vistas y el PDF."""
    photo = Path(photo)
    stat = photo.stat()
    corners, reason = _cached_auto_corners(photo, stat.st_mtime_ns, stat.st_size)
    return (corners.copy() if corners is not None else None), reason


def normalized_rotation(degrees: int) -> int:
    """Solo cuartos de vuelta, sin pérdida de calidad ni interpolaciones."""
    if not isinstance(degrees, int) or degrees % 90:
        raise ValueError("El giro debe ser 0, 90, 180 o 270 grados.")
    return degrees % 360


def rotate_final_page(image: Image.Image, degrees: int) -> Image.Image:
    """Giro horario del resultado final, sin modificar el archivo original."""
    turns = normalized_rotation(degrees)
    if turns == 0:
        return image
    transposes = {90: Image.Transpose.ROTATE_270,
                  180: Image.Transpose.ROTATE_180,
                  270: Image.Transpose.ROTATE_90}
    rotated = image.transpose(transposes[turns])
    image.close()
    return rotated


def preview_pair(photo: Path, auto_crop: bool, manual_corners: np.ndarray | None,
                 rotation: int = 0):
    """Miniatura con la misma geometría que el PDF real."""
    original, (full_w, full_h) = preview_image(photo, 1050)
    frame = np.asarray(original)
    processed = original.copy()
    cropped = False
    if manual_corners is not None:
        corners = np.asarray(manual_corners, np.float32)
    elif auto_crop:
        corners, _issue = automatic_page_corners(photo)
    else:
        corners = None
    if corners is not None:
        quad = ordenar_esquinas(corners * np.float32([
            frame.shape[1] / full_w, frame.shape[0] / full_h]))
        tl, tr, br, bl = quad
        width = int(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
        height = int(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
        if width >= 35 and height >= 35:
            dest = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
            result = cv2.warpPerspective(frame, cv2.getPerspectiveTransform(quad, dest),
                                         (width, height), flags=cv2.INTER_CUBIC)
            processed.close()
            processed = Image.fromarray(result, "RGB")
            cropped = True
    return original, rotate_final_page(processed, rotation), cropped


def prepare_page(
    photo: Path, auto_crop: bool = True, manual_corners: np.ndarray | None = None,
    rotation: int = 0,
) -> tuple[Image.Image, bool]:
    """Transforma a resolución completa usando esquinas de la misma vista previa."""
    if manual_corners is not None:
        corners = np.asarray(manual_corners, np.float32)
    elif auto_crop:
        corners, _reason = automatic_page_corners(photo)
    else:
        corners = None
    pil = open_color_image(photo)
    try:
        image = np.asarray(pil)
        cropped = False
        if corners is not None:
            corners = ordenar_esquinas(corners)
            tl, tr, br, bl = corners
            width = int(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
            height = int(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
            if width >= 100 and height >= 100:
                factor = min(1.0, MAX_SIDE / max(width, height))
                out_w, out_h = max(1, round(width*factor)), max(1, round(height*factor))
                dest = np.float32([[0, 0], [out_w-1, 0],
                                   [out_w-1, out_h-1], [0, out_h-1]])
                warped = cv2.warpPerspective(image, cv2.getPerspectiveTransform(corners.astype(np.float32), dest),
                                             (out_w, out_h), flags=cv2.INTER_CUBIC)
                pil.close()
                pil = Image.fromarray(warped, "RGB")
                cropped = True
        if not cropped and max(pil.size) > MAX_SIDE:
            pil.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        return rotate_final_page(pil, rotation), cropped
    except Exception:
        pil.close()
        raise


def fit_on_page(image_file: Path, pdf: canvas.Canvas):
    """El PDF ocupa solo el área recortada, sin bordes blancos artificiales."""
    with Image.open(image_file) as img:
        w, h = img.size
    # Tamaño de página según la relación de aspecto real del recorte.
    # La anchura es equivalente a A4, sin obligar a páginas con márgenes.
    page_w = 595.28 if w <= h else 841.89
    page_h = page_w * h / w
    pdf.setPageSize((page_w, page_h))
    pdf.drawImage(str(image_file), 0, 0, width=page_w, height=page_h)
    pdf.showPage()


def create_pdf(
    paths: list[Path], target: Path, auto_crop: bool = True,
    progress: Callable[[int, int, str], None] | None = None,
    manual_corners: dict[Path, np.ndarray] | None = None,
    preserve_input_order: bool = False,
    rotations: dict[Path, int] | None = None,
) -> dict:
    if not paths:
        raise ValueError("La carpeta no contiene fotografías compatibles.")
    # Orden EXIF en importación; las inserciones/sustituciones respetan su posición manual.
    paths = list(paths) if preserve_input_order else capture_order(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Ya existe {target}. Elige otro nombre para proteger tu PDF anterior.")
    warnings: list[str] = []
    errors: list[str] = []
    written = 0
    with tempfile.TemporaryDirectory(prefix="digitalizador_") as temp_dir:
        with tempfile.NamedTemporaryFile(
            prefix=".digitalizador_", suffix=".pdf", dir=target.parent, delete=False
        ) as pdf_temp:
            temp_pdf = Path(pdf_temp.name)
        try:
            pdf = canvas.Canvas(str(temp_pdf), pagesize=(595.28, 841.89), pageCompression=1)
            pdf.setTitle(target.stem)
            pdf.setAuthor("Digitalizador de fotos")
            pdf.setSubject("Documento digitalizado desde fotografías, sin OCR")
            for i, path in enumerate(paths, 1):
                try:
                    result, cropped = prepare_page(
                        path, auto_crop=auto_crop,
                        manual_corners=(manual_corners or {}).get(path),
                        rotation=(rotations or {}).get(path, 0),
                    )
                    filename = Path(temp_dir) / f"pagina_{i:06d}.jpg"
                    result.save(filename, "JPEG", quality=97, subsampling=0, optimize=True)
                    result.close()
                    fit_on_page(filename, pdf)
                    written += 1
                    if auto_crop and not cropped and path not in (manual_corners or {}):
                        _, reason = automatic_page_corners(path)
                        warnings.append(path.name + (f': {reason}' if reason else ''))
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
                finally:
                    if progress:
                        progress(i, len(paths), path.name)
            if errors:
                raise RuntimeError(f"No se guardó el PDF: {len(errors)} páginas fallaron. " + "; ".join(errors[:5]))
            if written == 0:
                raise RuntimeError("No se pudo procesar ninguna imagen. " + "; ".join(errors[:3]))
            pdf.save()
            # Si faltan páginas o imágenes, no se deja un PDF aparentemente terminado.
            verify_pdf_export(temp_pdf, written)
            os.replace(temp_pdf, target)
        finally:
            if temp_pdf.exists():
                temp_pdf.unlink()
    return {"pages": written, "uncropped": warnings, "errors": errors, "file": str(target)}


def cli_main(arguments: argparse.Namespace):
    folder = Path(arguments.carpeta).expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"No existe la carpeta: {folder}")
    try:
        paths = discover_images(folder)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    destination = Path(arguments.salida).expanduser().resolve()
    print(f"Imágenes encontradas: {len(paths)}")
    result = create_pdf(paths, destination, auto_crop=not arguments.sin_recorte,
                        progress=lambda n, total, name: print(f"[{n}/{total}] {name}"))
    print(f"PDF listo: {result['file']} ({result['pages']} páginas)")
    if result["uncropped"]:
        print(f"Aviso: {len(result['uncropped'])} fotos sin recorte seguro, se incluyeron completas.")
    if result["errors"]:
        print("Archivos que fallaron:")
        print("\n".join(result["errors"]))


def gui_main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class DigitalizadorApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("Digitalizador de fotos")
            self.root.geometry("1050x720")
            self.root.minsize(780, 570)
            self.folder: Path | None = None
            self.paths: list[Path] = []
            self.manual_corners: dict[Path, np.ndarray] = {}
            self.rotations: dict[Path, int] = {}
            self.pdf_name = tk.StringVar(value="")
            self.previous_folder_name: str | None = None
            self.auto_crop = tk.BooleanVar(value=True)
            self.info = tk.StringVar(value="Selecciona una carpeta con las fotos de tus documentos.")
            self.progress_text = tk.StringVar(value="")
            self.events: queue.Queue = queue.Queue()
            self.busy = False
            self.preview_photos: list[ImageTk.PhotoImage] = []
            self.preview_cache: OrderedDict = OrderedDict()
            self.preview_pending = set()
            self.preview_token = 0
            self.preview_after = None
            self.preview_pool = ThreadPoolExecutor(max_workers=2)
            self.detection_pool = ThreadPoolExecutor(max_workers=1)
            self.detection_generation = 0
            self.detection_done = 0
            self.detection_total = 0
            self.detection_warnings = 0
            self.active_review = None
            self.page_position = tk.StringVar(value='Página 0 de 0')
            self.crop_loading = False
            self.latest_pdf: Path | None = None
            self.export_review = None
            self.export_folder: Path | None = None

            style = ttk.Style(root)
            if "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure("Main.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 10))
            style.configure("Small.TButton", font=("Segoe UI", 10), padding=(12, 7))
            style.configure("TLabel", font=("Segoe UI", 10))
            style.configure("TCheckbutton", font=("Segoe UI", 10))
            style.configure("TProgressbar", thickness=14)
            root.configure(bg="#F6F7F8")

            body = ttk.Frame(root, padding=20)
            body.pack(fill="both", expand=True)
            ttk.Label(body, text="Fotografías a PDF", font=("Segoe UI", 21, "bold")).pack(anchor="w")
            ttk.Separator(body).pack(fill="x", pady=(8, 12))

            actions = ttk.Frame(body)
            actions.pack(fill="x")
            self.folder_button = ttk.Button(actions, text="Elegir fotos", style="Main.TButton", command=self.pick_folder)
            self.folder_button.pack(side="left")
            ttk.Button(actions, text="Editar PDF existente",
                       command=self.edit_existing_pdf).pack(side="left", padx=(12, 0))
            self.make_button = ttk.Button(actions, text="Crear PDF", style="Main.TButton", command=self.make_pdf)
            self.make_button.pack(side="right")
            self.make_button.state(["disabled"])
            name_row = ttk.Frame(body)
            name_row.pack(fill="x", pady=(12, 2))
            ttk.Label(name_row, text="Nombre del PDF:", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
            self.name_entry = ttk.Entry(name_row, textvariable=self.pdf_name, font=("Segoe UI", 11), width=44)
            self.name_entry.pack(side="left", fill="x", expand=True)
            ttk.Label(name_row, text=".pdf", font=("Segoe UI", 10)).pack(side="left", padx=(5, 0))
            ttk.Label(body, textvariable=self.info, wraplength=920).pack(anchor="w", pady=(6, 9))
            crop_row = ttk.Frame(body)
            crop_row.pack(fill="x", pady=(0, 4))
            ttk.Checkbutton(crop_row, text="Recorte automático", variable=self.auto_crop,
                            command=self.refresh_preview).pack(side="left")
            self.manual_button = ttk.Button(crop_row, text="Editar esquinas", style="Small.TButton", command=self.adjust_corners)
            self.manual_button.pack(side="right")
            self.manual_button.state(["disabled"])
            review_bar = ttk.Frame(body)
            review_bar.pack(fill="x", pady=(3, 9))
            self.matrix_btn = ttk.Button(review_bar, text="Revisar en matriz",
                                         command=self.open_matrix)
            self.matrix_btn.pack(side="left")
            self.matrix_btn.state(["disabled"])

            panes = ttk.Panedwindow(body, orient="horizontal")
            panes.pack(fill="both", expand=True)
            left = ttk.Frame(panes, width=230)
            right = ttk.Frame(panes)
            panes.add(left, weight=1)
            panes.add(right, weight=4)
            ttk.Label(left, text="Páginas (orden de captura)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
            listcontainer = ttk.Frame(left)
            listcontainer.pack(fill="both", expand=True)
            self.listbox = tk.Listbox(listcontainer, activestyle="none", exportselection=False,
                                      font=("Segoe UI", 10), selectmode="browse", borderwidth=0)
            scroll = ttk.Scrollbar(listcontainer, orient="vertical", command=self.listbox.yview)
            self.listbox.configure(yscrollcommand=scroll.set)
            self.listbox.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            self.listbox.bind("<<ListboxSelect>>", lambda _event: self.refresh_preview())
            nav = ttk.Frame(left)
            nav.pack(fill="x", pady=(8, 0))
            ttk.Button(nav, text="◀ Anterior", command=lambda: self.next_photo(-1)).pack(side="left")
            ttk.Button(nav, text="Siguiente ▶", command=lambda: self.next_photo(1)).pack(side="right")
            ttk.Label(left, textvariable=self.page_position,
                      font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 0))
            self.listbox.bind('<Prior>', lambda _e: self.next_photo(-1))
            self.listbox.bind('<Next>', lambda _e: self.next_photo(1))

            ttk.Label(right, text="Vista previa", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=(16, 0), pady=(0, 6))
            previews = ttk.Frame(right)
            previews.pack(fill="both", expand=True, padx=(16, 0))
            self.preview_orig = tk.Label(previews, text="Original", bg="#E9EDF0", compound="top", font=("Segoe UI", 10))
            self.preview_result = tk.Label(previews, text="Procesado", bg="#E9EDF0", compound="top", font=("Segoe UI", 10))
            self.preview_orig.pack(side="left", fill="both", expand=True, padx=(0, 5))
            self.preview_result.pack(side="left", fill="both", expand=True, padx=(5, 0))
            self.preview_status = tk.StringVar(value="")
            ttk.Label(right, textvariable=self.preview_status, wraplength=640).pack(anchor="w", padx=(16, 0), pady=(7, 0))

            footer = ttk.Frame(body)
            footer.pack(fill="x", pady=(14, 0))
            self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
            self.progress.pack(fill="x")
            ttk.Label(footer, textvariable=self.progress_text).pack(anchor="w", pady=(6, 0))
            root.after(100, self.poll_events)

        def pick_folder(self):
            folder = filedialog.askdirectory(title="Selecciona la carpeta con fotografías")
            if not folder:
                return
            chosen_folder = Path(folder)
            try:
                chosen_paths = discover_images(chosen_folder)
            except ValueError as exc:
                messagebox.showerror("Metadatos de captura", str(exc))
                return
            self.folder = chosen_folder
            self.paths = chosen_paths
            self.detection_generation += 1
            self.detection_done = 0
            self.detection_total = len(chosen_paths)
            self.detection_warnings = 0
            if self.active_review is not None and not self.active_review.closed:
                self.active_review.close()
            self.active_review = None
            self.manual_corners = {}
            self.rotations = {}
            self.preview_cache.clear()
            self.preview_pending.clear()
            self.preview_token += 1
            if not self.pdf_name.get().strip() or self.pdf_name.get().strip() == self.previous_folder_name:
                self.pdf_name.set(self.folder.name)
            self.previous_folder_name = self.folder.name
            self.listbox.delete(0, "end")
            for photo in self.paths:
                captured = capture_datetime(photo)
                self.listbox.insert("end", f"{captured:%d/%m %H:%M:%S}  {photo.name}")
            self.info.set(
                f"{len(self.paths)} fotografías ordenadas por fecha/hora original de captura (EXIF). "
                "No por nombre, descarga o subida a OneDrive."
            )
            self.make_button.state(["!disabled"] if self.paths else ["disabled"])
            self.manual_button.state(["!disabled"] if self.paths else ["disabled"])
            self.matrix_btn.state(["!disabled"] if self.paths else ["disabled"])
            if self.paths:
                # Un único barrido inicial, también para páginas fuera de la matriz visible.
                self._preload_detections(list(self.paths), self.detection_generation)
                self.listbox.selection_set(0)
                self.refresh_preview()
            else:
                self.set_preview(self.preview_orig, None, "Original")
                self.set_preview(self.preview_result, None, "Procesado")
                messagebox.showinfo("No hay fotografías", "Esta carpeta no contiene fotos JPG, PNG o HEIC compatibles.")

        def _preload_detections(self, photos: list[Path], generation: int):
            """Precalcular las esquinas de todo el lote sin bloquear la interfaz."""
            self.progress_text.set(f"Preparando recortes: 0/{len(photos)}")
            def scan():
                processed = 0
                warnings = 0
                for photo in photos:
                    if generation != self.detection_generation:
                        return
                    try:
                        _corners, issue = automatic_page_corners(photo)
                        warnings += bool(issue)
                    except Exception:
                        warnings += 1
                    processed += 1
                    if processed % 3 == 0 or processed == len(photos):
                        self.events.put(("batch_detection", generation,
                                         processed, len(photos), warnings))
            self.detection_pool.submit(scan)

        def edit_existing_pdf(self):
            from editor_pdf import open_editor
            open_editor(self.root)

        def _sync_review_list(self, focus):
            """Refleja las correcciones del revisor sin reordenar las páginas."""
            self.preview_cache.clear()
            self.preview_pending.clear()
            self.preview_token += 1
            self.listbox.delete(0, "end")
            for photo in self.paths:
                try:
                    timestamp = f"{capture_datetime(photo):%d/%m %H:%M:%S}"
                except ValueError:
                    timestamp = "Añadida manualmente"
                self.listbox.insert("end", f"{timestamp}  {photo.name}")
            self.listbox.selection_set(focus)
            self.listbox.activate(focus)
            self.listbox.see(focus)
            self.refresh_preview()
            self.progress_text.set(f"{len(self.paths)} páginas listas para revisión y exportación")

        def _replace_review_photo(self, index, new_path):
            # Las fotos insertadas o sustituidas también se analizan una sola vez.
            self.detection_pool.submit(automatic_page_corners, new_path)
            old_path = self.paths[index]
            self.rotations.pop(old_path, None)
            self.manual_corners.pop(old_path, None)
            self.paths[index] = new_path
            self._sync_review_list(index)

        def _insert_review_photo(self, index, new_path):
            self.detection_pool.submit(automatic_page_corners, new_path)
            self.paths.insert(index, new_path)
            self._sync_review_list(index)

        def _rotate_review_photo(self, index: int, degrees: int) -> int:
            photo = self.paths[index]
            rotation = normalized_rotation(self.rotations.get(photo, 0) + degrees)
            if rotation:
                self.rotations[photo] = rotation
            else:
                self.rotations.pop(photo, None)
            self.preview_cache.clear()
            self.preview_pending.clear()
            self.preview_token += 1
            self.refresh_preview()
            return rotation

        def open_matrix(self):
            """Matriz, ajuste, zoom y sustituciones ANTES de exportar el PDF."""
            if not self.paths or self.busy:
                return
            from revisor import ReviewWorkspace
            if self.active_review is not None and not self.active_review.closed:
                self.active_review.window.lift()
                self.active_review.window.focus_force()
                return
            manual = self.manual_corners
            auto = self.auto_crop.get()

            def processed(path):
                original, result, _ = preview_pair(
                    path, auto, manual.get(path), rotation=self.rotations.get(path, 0))
                original.close()
                reason = None
                if auto and path not in manual:
                    _, reason = automatic_page_corners(path)
                return result, reason

            self.active_review = ReviewWorkspace(
                self.root, self.paths, processed, self._matrix_save,
                preview_image, manual, self._replace_review_photo,
                self._insert_review_photo, self.make_pdf, auto_crop=auto,
                pdf_name=self.pdf_name, rotations=self.rotations,
                on_rotate=self._rotate_review_photo)
            self.active_review.set_detection_progress(
                self.detection_done, self.detection_total)

        def _matrix_save(self, index, corners):
            photo = self.paths[index]
            self.manual_corners[photo] = corners.copy()
            # Guardar una hoja no debe cambiar el recorte de las demás páginas.
            self.preview_cache.clear()
            if self.listbox.curselection() != (index,):
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(index)
                self.listbox.activate(index)
                self.listbox.see(index)
            self.refresh_preview()

        def open_pdf_matrix(self):
            from editor_pdf import PdfEditorWindow, open_editor
            if self.latest_pdf and self.latest_pdf.is_file():
                PdfEditorWindow(self.root, self.latest_pdf).open_overview()
            else:
                editor = open_editor(self.root)
                if editor:
                    editor.open_overview()

        def open_pdf_zoom(self):
            from tkinter import filedialog, messagebox
            from vistas import PdfZoomViewer
            path = self.latest_pdf
            if path is None or not path.exists():
                chosen = filedialog.askopenfilename(parent=self.root, title="Elegir PDF para revisión final",
                    filetypes=[("Documento PDF", "*.pdf")])
                if not chosen:
                    return
                path = Path(chosen)
            try:
                PdfZoomViewer(self.root, path)
            except Exception as exc:
                messagebox.showerror("Vista final", str(exc), parent=self.root)

        def next_photo(self, step):
            if not self.paths:
                return
            current = self.listbox.curselection()
            index = max(0, min(len(self.paths)-1, (current[0] if current else 0) + step))
            self.listbox.selection_clear(0, 'end')
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self.refresh_preview()

        def thumb(self, image: Image.Image) -> ImageTk.PhotoImage:
            image = image.copy()
            image.thumbnail((340, 410), Image.Resampling.BILINEAR)
            return ImageTk.PhotoImage(image)

        def set_preview(self, widget: tk.Label, image: Image.Image | None, title: str):
            if image is None:
                widget.configure(image='', text=title)
                return
            ph = self.thumb(image)
            self.preview_photos.append(ph)
            widget.configure(image=ph, text=title, padx=5, pady=5)

        def _show_preview(self, photo, originals, processed, cropped):
            self.preview_photos.clear()
            self.set_preview(self.preview_orig, originals, 'Original')
            self.set_preview(self.preview_result, processed, 'Resultado PDF')
            self.preview_status.set(
                'Recorte manual aplicado.' if cropped and photo in self.manual_corners
                else 'Hoja detectada y enderezada.' if cropped
                else 'No se detectó la hoja. Ajusta sus esquinas manualmente.'
                if self.auto_crop.get() else 'Sin recorte: imagen completa.')

        def refresh_preview(self):
            if self.busy or not self.paths:
                return
            selected = self.listbox.curselection()
            if not selected:
                return
            index = selected[0]
            photo = self.paths[index]
            self.page_position.set(f'Página {index+1} de {len(self.paths)}')
            self.preview_token += 1
            token = self.preview_token
            if self.preview_after is not None:
                self.root.after_cancel(self.preview_after)
            key = (photo, self.auto_crop.get(), tuple(self.manual_corners[photo].ravel())
                   if photo in self.manual_corners else None, self.rotations.get(photo, 0))
            if key in self.preview_cache:
                self.preview_cache.move_to_end(key)
                orig, result, cropped = self.preview_cache[key]
                self._show_preview(photo, orig, result, cropped)
                self._prefetch_photo_neighbors(index)
                return
            self.preview_status.set(f'Preparando vista rápida de {photo.name}...')
            self.preview_after = self.root.after(65, lambda: self._submit_preview(token, key))

        def _submit_preview(self, token, key):
            if key in self.preview_pending or key in self.preview_cache:
                return
            if len(self.preview_pending) >= 6:
                return
            photo, crop, _, rotation = key
            manual = self.manual_corners.get(photo)
            self.preview_pending.add(key)
            # Procesamiento fuera del hilo de interfaz: el usuario puede navegar mientras carga.
            def work():
                try:
                    result = preview_pair(photo, crop, manual, rotation=rotation)
                    self.events.put(('preview', token, key, result, None))
                except Exception as exc:
                    self.events.put(('preview', token, key, None, str(exc)))
            self.preview_pool.submit(work)

        def _prefetch_photo_neighbors(self, index):
            """Precarga fotos contiguas para que Anterior/Siguiente responda al instante."""
            for n in (index + 1, index - 1):
                if 0 <= n < len(self.paths):
                    photo = self.paths[n]
                    key = (photo, self.auto_crop.get(),
                           tuple(self.manual_corners[photo].ravel()) if photo in self.manual_corners else None,
                           self.rotations.get(photo, 0))
                    self._submit_preview(-1, key)

        def adjust_corners(self):
            """Carga la foto para ajustar esquinas sin bloquear el hilo gráfico."""
            if self.busy or not self.paths or self.crop_loading:
                return
            selected = self.listbox.curselection()
            if not selected:
                return
            photo = self.paths[selected[0]]
            self.crop_loading = True
            self.manual_button.state(["disabled"])
            self.preview_status.set(f"Abriendo ajuste de esquinas de {photo.name}...")
            # Leer dimensiones de Tk solo desde el hilo gráfico.
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            limit = max(280, min(840, screen_w - 150, screen_h - 245))

            def worker():
                try:
                    # La lectura y el redimensionado de HEIC ocurren fuera de Tk.
                    preview, size = preview_image(photo, limit)
                    detection = find_document_corners(np.asarray(preview))
                    self.events.put(('crop_ready', photo, preview, size, detection, None))
                except Exception as exc:
                    self.events.put(('crop_ready', photo, None, None, None, str(exc)))

            self.preview_pool.submit(worker)

        def show_crop_editor(self, photo, preview, full_size, detected_small):
            """La interfaz Tk y su imagen se construyen únicamente en el hilo principal."""
            w, h = full_size
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            # Reserva espacio para encabezado, controles, barras de Windows
            # y los cuatro tiradores, incluso con escalado de pantalla.
            max_width = max(240, screen_w - 150)
            max_height = max(240, screen_h - 245)
            if preview.width > max_width or preview.height > max_height:
                preview.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            width, height = preview.size
            ratio_x, ratio_y = width / w, height / h
            img = ImageTk.PhotoImage(preview)
            detected = (detected_small / np.float32([ratio_x, ratio_y])
                        if detected_small is not None else None)
            preview.close()
            initial = self.manual_corners.get(photo)
            if initial is None:
                initial = detected
            if initial is None:
                initial = np.float32([[w*.05, h*.05], [w*.95, h*.05],
                                     [w*.95, h*.95], [w*.05, h*.95]])
            points = (ordenar_esquinas(initial) * np.float32([ratio_x, ratio_y])).tolist()
            popup = tk.Toplevel(self.root)
            popup.title(f"Ajustar recorte: {photo.name}")
            popup.transient(self.root)
            popup.grab_set()
            container = ttk.Frame(popup, padding=14)
            container.pack(fill="both", expand=True)
            ttk.Label(container, text="Arrastra los cuatro círculos a las esquinas de la hoja.",
                      font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
            padding = 14  # los tiradores no quedan cortados en bordes de foto
            board = tk.Canvas(container, width=width + 2*padding,
                              height=height + 2*padding, highlightthickness=0,
                              borderwidth=0, cursor="crosshair", bg="#1B242C")
            board.pack()
            board.create_image(padding, padding, image=img, anchor="nw")
            board.image_reference = img
            poly = board.create_polygon(0, 0, 0, 0, outline="#16A6DB", fill="", width=3)
            handles = [board.create_oval(0, 0, 0, 0, fill="#16A6DB", outline="white", width=2)
                       for _ in range(4)]
            labels = [board.create_text(0, 0, fill="white", text=str(i+1), font=("Segoe UI", 10, "bold"))
                      for i in range(4)]
            selected_handle = [None]

            def redraw():
                board.coords(poly, *[value + padding for xy in points for value in xy])
                for i, (x, y) in enumerate(points):
                    board.coords(handles[i], x+padding-11, y+padding-11,
                                 x+padding+11, y+padding+11)
                    board.coords(labels[i], x+padding, y+padding)

            def near_handle(event):
                distances = [np.hypot(x+padding-event.x, y+padding-event.y) for x, y in points]
                closest = int(np.argmin(distances))
                return closest if distances[closest] < 38 else None

            def press(event):
                selected_handle[0] = near_handle(event)

            def drag(event):
                i = selected_handle[0]
                if i is not None:
                    points[i] = [max(0, min(width-1, event.x-padding)),
                                 max(0, min(height-1, event.y-padding))]
                    redraw()

            board.bind("<ButtonPress-1>", press)
            board.bind("<B1-Motion>", drag)
            board.bind("<ButtonRelease-1>", lambda _event: selected_handle.__setitem__(0, None))

            def reset():
                quad = detected if detected is not None else np.float32([
                    [w*.05, h*.05], [w*.95, h*.05], [w*.95, h*.95], [w*.05, h*.95]])
                points[:] = (ordenar_esquinas(quad) * np.float32([ratio_x, ratio_y])).tolist()
                redraw()

            def save():
                quad = np.asarray(points, dtype=np.float32) / np.float32([ratio_x, ratio_y])
                # Comprobar que no se cruzan las aristas ni se recorta una zona diminuta.
                shape = quad.reshape(-1, 1, 2)
                if not cv2.isContourConvex(shape) or cv2.contourArea(shape) < .07*w*h:
                    messagebox.showwarning("Esquinas incorrectas", "Los puntos deben formar una hoja sin cruzarse.", parent=popup)
                    return
                self.manual_corners[photo] = quad
                self.auto_crop.set(True)
                popup.destroy()
                self.refresh_preview()

            redraw()
            controls = ttk.Frame(container)
            controls.pack(fill="x", pady=(11, 0))
            ttk.Button(controls, text="Volver a detección automática", command=reset).pack(side="left")
            ttk.Button(controls, text="Cancelar", command=popup.destroy).pack(side="right", padx=(7, 0))
            ttk.Button(controls, text="Guardar recorte", command=save).pack(side="right")
            popup.update_idletasks()
            popup_w = min(popup.winfo_reqwidth(), screen_w - 30)
            popup_h = min(popup.winfo_reqheight(), screen_h - 85)
            x = max(0, (screen_w - popup_w)//2)
            y = max(0, (screen_h - popup_h)//2 - 20)
            popup.geometry(f"{popup_w}x{popup_h}+{x}+{y}")
            popup.resizable(False, False)

        @staticmethod
        def clean_name(value: str) -> str:
            return normalized_pdf_name(value)

        def make_pdf(self, review=None):
            if not self.folder or not self.paths or self.busy:
                return
            dialog_parent = (review.window if review is not None and not review.closed
                             else self.root)
            try:
                target_name = self.clean_name(self.pdf_name.get())
            except ValueError as exc:
                messagebox.showwarning("Nombre del PDF", str(exc), parent=dialog_parent)
                return
            # La carpeta se elige aparte. El nombre escrito no puede ser
            # reemplazado por un nombre antiguo o sugerido por Windows.
            directory = filedialog.askdirectory(
                parent=dialog_parent, title=f"Guardar {target_name} en...",
                initialdir=str(self.export_folder or self.folder.parent),
                mustexist=True,
            )
            if not directory:
                return
            try:
                target = build_export_destination(Path(directory), self.pdf_name.get())
            except ValueError as exc:
                messagebox.showwarning("Destino del PDF", str(exc), parent=dialog_parent)
                return
            if target.exists():
                messagebox.showwarning("PDF existente",
                    "Ya existe un archivo con ese nombre. Elige otro para conservar el original.",
                    parent=dialog_parent)
                return
            # Refleja el nombre realmente elegido, tanto en la matriz como en inicio.
            self.pdf_name.set(target.stem)
            self.export_folder = target.parent
            self.export_review = review
            if review is not None and not review.closed:
                review.begin_export(target, len(self.paths))
            self.busy = True
            self.folder_button.state(["disabled"])
            self.make_button.state(["disabled"])
            self.manual_button.state(["disabled"])
            self.matrix_btn.state(["disabled"])
            self.name_entry.state(["disabled"])
            self.progress.configure(maximum=len(self.paths), value=0)
            self.progress_text.set(f"Preparando {len(self.paths)} páginas...")
            paths = list(self.paths)
            should_crop = self.auto_crop.get()
            manual = dict(self.manual_corners)
            rotations = dict(self.rotations)

            def worker():
                try:
                    output = create_pdf(paths, target, should_crop,
                        progress=lambda number, total, name: self.events.put(("progress", number, total, name)),
                        manual_corners=manual, preserve_input_order=True, rotations=rotations)
                    self.events.put(("done", output))
                except Exception as exc:
                    self.events.put(("failed", str(exc), traceback.format_exc()))
            threading.Thread(target=worker, daemon=True).start()

        def poll_events(self):
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                if event[0] == 'preview':
                    _, token, key, result, failure = event
                    self.preview_pending.discard(key)
                    if result is not None:
                        self.preview_cache[key] = result
                        if len(self.preview_cache) > 18:
                            self.preview_cache.popitem(last=False)
                    current = self.listbox.curselection()
                    if current and self.paths[current[0]] == key[0]:
                        expected = (key[0], self.auto_crop.get(),
                                    tuple(self.manual_corners[key[0]].ravel())
                                    if key[0] in self.manual_corners else None,
                                    self.rotations.get(key[0], 0))
                        if key == expected:
                            if failure:
                                self.preview_status.set(f'Vista previa no disponible: {failure}')
                            elif result:
                                self._show_preview(key[0], *result)
                                self._prefetch_photo_neighbors(current[0])
                elif event[0] == "batch_detection":
                    _, generation, done, total, warnings = event
                    if generation == self.detection_generation:
                        self.detection_done, self.detection_total = done, total
                        self.detection_warnings = warnings
                        if not self.busy:
                            self.progress_text.set(
                                f"Recortes preparados: {done}/{total}"
                                + (f" · {warnings} para revisar" if warnings else ""))
                        review = self.active_review
                        if review is not None and not review.closed:
                            review.set_detection_progress(done, total)
                elif event[0] == 'crop_ready':
                    _, photo, preview, size, detection, failure = event
                    self.crop_loading = False
                    if not self.busy:
                        self.manual_button.state(["!disabled"] if self.paths else ["disabled"])
                    if failure:
                        messagebox.showerror("No se puede abrir", failure)
                    else:
                        self.show_crop_editor(photo, preview, size, detection)
                elif event[0] == "progress":
                    _, n, total, name = event
                    self.progress.configure(value=n)
                    self.progress_text.set(f"Procesando {n} de {total}: {name}")
                    review = self.export_review
                    if review is not None and not review.closed:
                        review.update_export_progress(n, total)
                elif event[0] == "done":
                    info = event[1]
                    self.latest_pdf = Path(info['file'])
                    self.reset_controls()
                    review = self.export_review
                    dialog_parent = (review.window if review is not None and not review.closed
                                     else self.root)
                    if review is not None and not review.closed:
                        review.finish_export(self.latest_pdf, info['pages'], len(info['uncropped']))
                    self.export_review = None
                    details = f"PDF creado con {info['pages']} páginas.\n\n{info['file']}"
                    if info["uncropped"]:
                        details += f"\n\n{len(info['uncropped'])} fotos no se pudieron recortar con seguridad y se incluyeron completas.\n" + "\n".join(info["uncropped"][:8])
                    if info["errors"]:
                        details += f"\n\n{len(info['errors'])} fotos no se pudieron incluir:\n" + "\n".join(info["errors"][:8])
                    self.progress_text.set(f"Listo: {info['pages']} páginas guardadas.")
                    # La matriz muestra una señal permanente de éxito,
                    # sin un diálogo modal que pueda ocultarse detrás.
                    if review is None or review.closed:
                        messagebox.showinfo("PDF terminado", details, parent=dialog_parent)
                elif event[0] == "failed":
                    self.reset_controls()
                    self.progress_text.set("No se pudo crear el PDF.")
                    review = self.export_review
                    dialog_parent = (review.window if review is not None and not review.closed
                                     else self.root)
                    if review is not None and not review.closed:
                        review.fail_export(event[1])
                    self.export_review = None
                    messagebox.showerror("Error al generar PDF", event[1], parent=dialog_parent)
            self.root.after(100, self.poll_events)

        def reset_controls(self):
            self.busy = False
            self.folder_button.state(["!disabled"])
            self.make_button.state(["!disabled"] if self.paths else ["disabled"])
            self.manual_button.state(["!disabled"] if self.paths else ["disabled"])
            self.matrix_btn.state(["!disabled"] if self.paths else ["disabled"])
            self.name_entry.state(["!disabled"])

    root = tk.Tk()
    DigitalizadorApp(root)
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digitaliza fotografías a PDF, con color original y sin OCR.")
    parser.add_argument("--carpeta", help="Carpeta de fotografías, opcional para usar sin interfaz.")
    parser.add_argument("--salida", help="Archivo PDF de salida al usar --carpeta.")
    parser.add_argument("--sin-recorte", action="store_true", help="No intentar recortar ni enderezar las hojas.")
    args = parser.parse_args()
    if args.carpeta or args.salida:
        if not args.carpeta or not args.salida:
            parser.error("Para el modo automático debes indicar --carpeta y --salida.")
        cli_main(args)
    else:
        gui_main()
