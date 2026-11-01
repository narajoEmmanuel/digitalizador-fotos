# Digitalizador de Fotos

Una aplicación local para **Windows** que convierte fotografías de documentos en un PDF multipágina, conservando **los colores originales**. Detecta los bordes del papel, intenta recortarlo y enderezarlo y permite ajustar manualmente las cuatro esquinas si hace falta. **No utiliza OCR ni transcribe texto**.

## Funciones

- Orden automático por **fecha y hora original de captura** (`EXIF DateTimeOriginal`), no por nombre, descarga, modificación ni sincronización en OneDrive.
- Detección y corrección de perspectiva de cada hoja.
- Comparación entre foto original y página procesada.
- Corrección manual opcional con cuatro esquinas ajustables.
- Campo para **elegir el nombre del PDF** antes de guardarlo.
- Exportación a PDF con páginas ajustadas a los recortes, sin márgenes añadidos.
- Conservación de las fotografías originales. Todo se procesa localmente.

## Requisitos

- Windows 10 u 11.
- Python 3.10 o superior, instalado con la opción de añadirlo al PATH.
- Conexión a Internet **solo para instalar dependencias la primera vez**.

## Inicio rápido

1. Descarga el código ZIP del repositorio y descomprímelo.
2. Abre `INICIAR.bat` con doble clic. Preparará un entorno `.venv` e instalará las dependencias.
3. Selecciona una carpeta con las fotos originales del iPhone, descargadas desde OneDrive sin eliminar sus metadatos.
4. Escribe el nombre del documento PDF.
5. Revisa algunas páginas. Corrige manualmente las esquinas si el recorte no es preciso.
6. Pulsa **Crear PDF** y elige dónde guardarlo.

Formatos de entrada: JPG, JPEG, PNG, HEIC, HEIF, WebP, TIFF y BMP.

## Consejos para mejores recortes

- Fotografía las hojas **sobre una superficie de color diferente al papel**.
- Mantén las cuatro esquinas completamente visibles.
- Coloca el teléfono lo más perpendicular posible y evita sombras duras.
- Usa una carpeta por documento. El programa **reordena automáticamente las fotos por su hora original de captura**, incluso si sus nombres están desordenados.
- Si el recorte automático no es seguro, la aplicación conservará **la foto completa**, para evitar pérdida de contenido.

## Orden de páginas y OneDrive

- El programa lee exclusivamente `EXIF DateTimeOriginal` para saber **cuándo se tomó** cada foto. Si existen, también utiliza los subsegundos (`SubSecTimeOriginal`) y el huso horario (`OffsetTimeOriginal`).
- **No utiliza** el nombre del archivo ni las fechas de creación/modificación de Windows ni la fecha de subida o descarga de OneDrive para ordenar.
- Con fotos tomadas en una misma zona horaria, las organiza cronológicamente. Si todas incluyen zona horaria, compara instantes absolutos; si algunas no la incluyen, compara la hora local registrada por cada cámara.
- Si alguna foto no conserva su fecha EXIF original, **se detiene y muestra cuáles son**, en vez de inventar un orden. Conviene descargar el archivo original, no una captura de pantalla ni una conversión que borre metadatos.
- Si dos imágenes tienen exactamente el mismo valor de captura EXIF, esos metadatos **no permiten saber cuál fue primero**. En ese caso se mantiene el orden de entrada, que puede depender de cómo Windows enumere los archivos.
- La lista lateral muestra la fecha y hora de captura junto al nombre del archivo para verificar el resultado.

## Uso por consola (opcional)

```powershell
.\.venv\Scripts\python.exe digitalizador.py --carpeta "C:\Fotos" --salida "C:\Documentos\Mi documento.pdf"
```

Para incluir las fotografías enteras, sin recortes:

```powershell
.\.venv\Scripts\python.exe digitalizador.py --carpeta "C:\Fotos" --salida "C:\Documentos\Mi documento.pdf" --sin-recorte
```

## Pruebas

Con dependencias instaladas:

```powershell
python -m unittest discover -s tests -v
```

## Privacidad y limitaciones

- No hay conexión con servidores ni subida de imágenes. No incluye analítica.
- No se editan, sustituyen ni eliminan las fotos originales.
- La detección depende del contraste, la iluminación y que el documento sea visible. Comprueba el resultado antes de archivar o descartar el papel.
- Los ajustes manuales de las cuatro esquinas solo se mantienen en la sesión actual.
- Los resultados se guardan como imágenes JPEG de alta calidad dentro del PDF, por lo que no son píxeles idénticos a la foto original. Se mantiene la apariencia a color, sin filtros de blanco y negro.
- Si una fotografía no puede abrirse, se informa del error y se genera el PDF con las páginas válidas. Revisa el resumen al finalizar.

## Archivos principales

- `digitalizador.py`: interfaz, importación de fotografías y generación del PDF.
- `recorte.py`: detector de hojas y esquinas.
- `INICIAR.bat`: inicio sencillo en Windows.
- `requirements.txt`: dependencias.
- `LEEME.txt`: instrucciones incluidas desde la versión 1.1.
- `tests/`: pruebas automatizadas.

**Versión**: 1.2, orden de captura EXIF, sin OCR ni cambios de color.