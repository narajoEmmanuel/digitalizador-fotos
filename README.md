# Digitalizador de Fotos

Aplicación local para Windows que convierte fotografías a un PDF a color, con recorte y corrección de perspectiva. **No transcribe texto ni utiliza OCR**.

## Flujo de trabajo

1. Abre `INICIAR.bat` y elige una carpeta con fotografías.
2. Escribe el nombre del PDF.
3. Pulsa **Revisar en matriz** para ver 16 páginas por bloque.
4. Revisa rápidamente todas las miniaturas. Selecciona solo las páginas dudosas para ver el resultado a resolución final, ampliar o corregir.
5. Pulsa **Crear PDF** o **Exportar PDF** desde la matriz. **No hay aprobación individual de páginas.**

### Matriz de revisión

- **Izquierda (36 %):** matriz de 16 páginas, navegación y **todos los botones** (recortar, detectar, sustituir, insertar, exportar y cerrar).
- **Derecha (64 %):** solo la imagen procesada, sin barras ni controles que reduzcan el área de visualización. Al editar el recorte aparecen los cuatro puntos sobre la imagen.
- **Rueda del mouse:** zoom alrededor del puntero. **Arrastrar:** mover la imagen ampliada. **Doble clic:** encajar la página.
- La vista de calidad presenta las dimensiones finales en píxeles y el zoom. A **100 %**, un píxel de imagen corresponde a un píxel de pantalla.
- **Activar esquinas / Desactivar esquinas:** interruptor global del revisor. Al activarlo, todas las páginas que selecciones muestran los cuatro puntos hasta que lo desactives. No asigna las mismas esquinas a todas; cada fotografía tiene su propio recorte.
- **Detectar:** recalcula el contorno de la página actual. **Guardar recorte:** guarda solo las esquinas de esa hoja sin desactivar la herramienta, para continuar con otras. Al desactivar las esquinas, aparece la imagen final con zoom.
- **Sustituir:** cambia la fotografía seleccionada. **+ Antes** y **+ Después:** insertan una página en el lugar indicado.

El contenido de la matriz se calcula a tamaño ligero. La vista individual de calidad procede de la fotografía original y reproduce la compresión JPEG que se integrará en el PDF. La edición no modifica ni borra las fotos originales. Los cambios pendientes duran únicamente la sesión, así que exporta antes de cerrar la aplicación.

### Corregir un PDF ya existente

Utiliza **Editar PDF existente** solo para modificaciones posteriores. Es posible insertar o sustituir páginas y guardar un PDF nuevo sin recomprimir las páginas que no cambiaron. El original no se sobrescribe.

## Orden de fotografías de iPhone y OneDrive

El orden inicial se basa en el momento de captura `EXIF DateTimeOriginal`, con subsegundos y zona horaria cuando existan. No depende del nombre, la fecha de modificación o la fecha de subida a OneDrive.

Si una foto no contiene ese dato, la importación inicial lo indica y se detiene para evitar un orden inventado. Las sustituciones e inserciones realizadas desde el revisor mantienen la posición elegida, incluso cuando la foto nueva no tiene EXIF.

## Instalación en Windows

Requisitos: Windows 10 u 11 y Python 3.10 o posterior. La primera ejecución de `INICIAR.bat` prepara el entorno y descarga las dependencias. No es necesario enviar fotografías a ningún servidor.

Para actualizar desde GitHub:

```powershell
Set-Location C:\dev\digitalizador-fotos
git pull --ff-only origin main
.\INICIAR.bat
```

Para ejecutar las pruebas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Uso opcional por consola:

```powershell
.\.venv\Scripts\python.exe digitalizador.py --carpeta "C:\Fotos" --salida "C:\Documentos\Mi documento.pdf"
```

## Calidad y conservación

- La aplicación conserva el color, corrige la perspectiva y usa JPEG de alta calidad. En el procesamiento final puede reducir imágenes muy grandes para limitar el tamaño del PDF.
- Si el detector no reconoce con seguridad una hoja, puede conservar la fotografía completa, para evitar cortar información importante.
- Un zoom alto no recupera una fotografía desenfocada. Sustitúyela por una nueva captura si el texto se ve borroso al 100 %.
- Antes de borrar las fotografías originales o el papel, confirma la cantidad de páginas, inspecciona el PDF final al 100 % y guarda **dos copias independientes**.
- El PDF no contiene texto reconocido y las fotos se procesan localmente.

## Archivos principales

- `digitalizador.py`: importación, interfaz y generación de PDF.
- `recorte.py`: detector automático.
- `revisor.py` y `revisor_base.py`: matriz, revisión, zoom y edición previa.
- `editor_pdf.py`: correcciones de un PDF existente.
- `vistas.py`: utilidades de visualización.
- `tests/`: pruebas automatizadas.

**Versión actual: 1.8.**
