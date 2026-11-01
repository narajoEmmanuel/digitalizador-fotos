# Digitalizador de Fotos

Una aplicación local para **Windows** que convierte fotografías de documentos en un PDF multipágina, conservando **los colores originales**. Detecta los bordes del papel, intenta recortarlo y enderezarlo y permite ajustar manualmente las cuatro esquinas si hace falta. **No utiliza OCR ni transcribe texto**.

## Funciones

### Corregir un PDF aunque ya eliminaste las fotografías originales

1. Selecciona **Abrir PDF existente y corregir páginas**.
2. El programa abre el PDF y muestra **Página X de Y**, número total de páginas y tamaño del PDF.
3. Navega con **Anterior**, **Siguiente**, teclas **Alt + ← / →**, **RePág / AvPág**, o escribe un número en **Ir a**.
   Para revisar muchas páginas de golpe, pulsa **Ver 16 páginas** y elige una miniatura. Puedes pasar a los siguientes bloques de 16 páginas.
4. Selecciona la página borrosa y usa **Reemplazar página con foto**; para una hoja faltante elige **Insertar antes** o **Insertar después**.
5. Para revertir una modificación errónea utiliza **Deshacer**.
6. **Guardar PDF revisado...** genera una copia nueva `_revisado.pdf` y verifica que contenga todas las páginas. Nunca sobrescribe el documento anterior.

Las páginas que no cambias **se copian directamente del PDF**, sin recomprimir ni degradar los JPG que ya contiene. Las fotos nuevas se recortan automáticamente a color y se integran con calidad alta. **Las fotografías nuevas no necesitan EXIF** porque eliges explícitamente su posición.

**Antes de eliminar las fotos o los originales en papel:** abre el PDF resultante y revisa todas las páginas a tamaño real en un lector PDF. Guarda también una segunda copia independiente (por ejemplo, en un disco externo), porque un único PDF sin respaldo no es un archivo seguro.

### Vistas previas rápidas

- La vista previa utiliza una copia pequeña en memoria, sin procesar cada foto de 12 o 48 megapíxeles mientras navegas.
- El procesamiento de vista previa ocurre en segundo hilo, conserva las páginas visualizadas en caché y precarga las páginas anterior y siguiente.
- Abrir el ajuste de las cuatro esquinas también se prepara en segundo hilo para no congelar la ventana.
- La vista general del PDF muestra 16 miniaturas a la vez y se carga en segundo hilo; puedes saltar a cualquier página del bloque.
- Botones Anterior/Siguiente y numeración para recorrer muchas hojas rápidamente.
- El recorte final se calcula **solo al crear el PDF**, con la foto de alta resolución.
- El ajuste manual de esquinas usa miniatura para responder más rápido, sin limitar la calidad final del documento.


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

## Recorte automático y ajuste manual (v1.4)

- El detector compara el color **dentro y fuera de cada lado** de la hoja. Esto reduce la selección errónea de los límites de la fotografía, especialmente con fondos oscuros, coloreados o estampados.
- En **Ajustar esquinas de esta hoja**, la fotografía se adapta automáticamente al espacio disponible en el monitor. Se ven siempre los cuatro puntos y el botón **Guardar recorte**, sin desplazar la ventana ni moverla fuera de la pantalla.
- El editor añade un pequeño margen oscuro alrededor de la imagen para que se puedan arrastrar las esquinas incluso cuando estén pegadas al límite de la fotografía.
- Si no existe evidencia suficiente para un recorte seguro, se conserva la fotografía completa y se avisa. Conviene comprobar esas páginas antes de eliminar los originales.
- El ajuste de esquinas utiliza una miniatura para responder rápido. El PDF se procesa después con la fotografía original en alta resolución.

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
- Las nuevas páginas se guardan como imágenes JPEG de alta calidad (hasta 6000 px por lado) dentro del PDF, por lo que no son píxeles idénticos a la foto original. Se mantiene la apariencia a color, sin filtros de blanco y negro.
- Las miniaturas son solo para navegación; **no reemplazan la imagen de alta resolución dentro del PDF**.
- El archivo se guarda como copia revisada, nunca encima del PDF original. Verifica página por página a tamaño real, que el número de páginas sea correcto y mantén al menos una copia independiente antes de eliminar fotos o papel. Un documento borroso desde la cámara no se puede recuperar por aumentar la resolución del PDF.
- Si una fotografía no puede abrirse, la creación se cancela para no guardar un PDF incompleto. La imagen original no se altera.

## Archivos principales

- `digitalizador.py`: interfaz, importación de fotografías y generación del PDF.
- `recorte.py`: detector de hojas y esquinas.
- `editor_pdf.py`: editor y guardado conservador de PDFs existentes.
- `INICIAR.bat`: inicio sencillo en Windows.
- `requirements.txt`: dependencias.
- `LEEME.txt`: instrucciones incluidas desde la versión 1.1.
- `tests/`: pruebas automatizadas.

**Versión**: 1.3, editor de PDF por página y vista previa optimizada, orden EXIF, sin OCR.
