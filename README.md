# Digitalizador de Fotos

Aplicación local para Windows que convierte fotografías a un PDF a color, con recorte y corrección de perspectiva. **No transcribe texto ni utiliza OCR**.

## Flujo de trabajo

1. Abre `INICIAR.bat` y elige una carpeta con fotografías.
2. Escribe el nombre del PDF.
3. Pulsa **Revisar en matriz** para ver 16 páginas por bloque.
4. Revisa las miniaturas de un vistazo. Selecciona una hoja para verla rápidamente y haz zoom únicamente si necesitas comprobar el detalle de calidad final.
5. Pulsa **Crear PDF** o **Exportar PDF** desde la matriz. El nombre que escribas en cualquiera de las dos pantallas será el nombre exacto del PDF. Windows solo te pedirá la **carpeta** de destino. **No hay aprobación individual de páginas.**

### Rendimiento

- El lote de fotografías se importa y ordena por EXIF sin congelar la ventana.
- Se calculan automáticamente las esquinas de **todas las fotografías**, no solo de las 16 visibles, mediante una tarea de fondo con progreso `Preparando esquinas: X/Y`.
- La matriz y la vista de lectura comparten una caché limitada de 24 imágenes, y al seleccionar una miniatura aparece primero una vista ligera.
- **Solo al ampliar** una hoja se carga el resultado final a alta resolución, con la misma compresión JPEG utilizada en el PDF.
- Los giros y recortes manuales actualizan únicamente la página modificada.

### Matriz de revisión

- **Izquierda (36 %):** matriz de 16 páginas, navegación y **todos los botones** (recortar, detectar, sustituir, insertar, exportar y cerrar). Los controles tienen espacio reservado debajo de las miniaturas, sin desaparecer por el tamaño de la pantalla. El nombre y **Exportar PDF** ocupan filas independientes.
- **Derecha (64 %):** solo la imagen procesada, sin barras ni controles que reduzcan el área de visualización. Al editar el recorte aparecen los cuatro puntos sobre la imagen.
- **⚠ Página N:** el detector encontró esquinas inestables o una perspectiva dudosa. La aplicación conserva la fotografía completa en lugar de deformar el documento. Si hace falta, abre esa página y corrige las cuatro esquinas.
- **Misma geometría:** las miniaturas, la vista ampliada y la exportación aplican las mismas esquinas, calculadas una sola vez a una escala fija. La vista ampliada usa la imagen final a alta resolución.
- **Rueda del mouse:** zoom alrededor del puntero. **Arrastrar:** mover la imagen ampliada. **Doble clic:** encajar la página.
- La vista de calidad presenta las dimensiones finales en píxeles y el zoom. A **100 %**, un píxel de imagen corresponde a un píxel de pantalla.
- **Activar esquinas / Desactivar esquinas:** interruptor global del revisor. Al activarlo, todas las páginas que selecciones muestran los cuatro puntos hasta que lo desactives. No asigna las mismas esquinas a todas; cada fotografía tiene su propio recorte.
- **Detectar:** recalcula el contorno de la página actual. **Guardar recorte:** guarda solo las esquinas de esa hoja sin desactivar la herramienta, para continuar con otras. Al desactivar las esquinas, aparece la imagen final con zoom.
- **Sustituir:** cambia la fotografía seleccionada. **+ Antes** y **+ Después:** insertan una página en el lugar indicado.
- **↶ 90° / 90° ↷:** giran únicamente la página seleccionada a izquierda o derecha. La miniatura, vista ampliada y PDF final respetan el giro. La fotografía original y las esquinas guardadas no cambian. Puedes pulsar dos veces para girar 180°, o deshacer girando al lado contrario.

El contenido de la matriz se calcula a tamaño ligero. La vista individual de calidad procede de la fotografía original y reproduce la compresión JPEG que se integrará en el PDF. Durante la exportación aparece una barra de progreso bajo **Exportar PDF**. Tras validar el archivo aparece **✓ PDF guardado**, con nombre, ubicación y número de páginas, y el botón **Abrir PDF**. Los avisos de error se distinguen claramente. Nunca se sobrescribe automáticamente un PDF existente. La edición no modifica ni borra las fotos originales. Los cambios pendientes duran únicamente la sesión, así que exporta antes de cerrar la aplicación.

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

**Versión actual: 1.13.**
