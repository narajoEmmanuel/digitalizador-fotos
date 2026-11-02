# Historial de cambios

## 1.8.1 (2026-11-01)

- Todos los botones del revisor se trasladaron bajo la matriz del panel izquierdo.
- Panel derecho reservado al 100 % para la fotografía y el zoom, sin barras de controles.
- Matriz ajustada al 36 % de la anchura para ampliar la zona de inspección.
- Revisión rápida sin aprobaciones individuales, sin modificar el procesamiento ni la exportación.


## 1.8 (2026-11-01)

- Eliminados **Aprobar** por página, contador de páginas revisadas y advertencia al exportar.
- Matriz de 16 miniaturas para inspección rápida, sin necesidad de abrir cada hoja.
- Botones y mensajes más cortos, sin instrucciones redundantes en la ventana.
- Zoom, recorte y sustitución solo cuando se selecciona una página; las fotos originales siguen intactas.
- Exportación directa una vez hechas las correcciones necesarias.


## 1.7 (2026-11-01)

- Seleccionar una miniatura abre el resultado final sin superponer esquinas.
- La vista se genera desde la fotografía original y replica incluso la codificación JPEG del PDF final.
- Indicador de resolución real en píxeles y zoom 100 %, rueda centrada en el puntero, arrastre y doble clic para encajar.
- **Editar esquinas** muestra los puntos únicamente cuando se solicita.
- **Detectar hoja de nuevo** avisa si no encuentra esquinas o si no cambian.
- **Guardar recorte y ver resultado** regresa automáticamente a la imagen procesada.
- **Marcar página revisada** queda separado del guardado de recorte.


## 1.6 (2026-11-01)

- Matriz maximizada con 16 miniaturas a la izquierda y editor continuo de esquinas a la derecha.
- Vista previa ampliada desde la imagen original, antes de crear el PDF, con zoom y desplazamiento.
- Sustituir e insertar imágenes en cualquier posición durante la revisión sin requerir EXIF de la foto nueva.
- El orden EXIF se conserva solo como orden inicial, los cambios manuales no se reordenan al exportar.
- Marcado de páginas aprobadas y advertencia al exportar con páginas pendientes.
- Pruebas para preservar el orden manual y proteger los originales.


## 1.5 (2026-11-01)

- Matriz rápida de 16 recortes previstos antes de crear el PDF, con navegación por bloques.
- Pulsar una miniatura selecciona la foto y abre su ajuste manual de cuatro esquinas.
- Vista final ampliada que renderiza el PDF guardado, con zoom, ajuste a ventana, desplazamiento y pantalla completa (F11).
- Visor ampliado accesible tanto desde la ventana principal como desde el editor de PDF existente.
- Renderizado en segundo plano y límite de memoria para las vistas, sin modificar ni recomprimir el archivo.
- Dos pruebas nuevas de integridad del PDF y zoom, además de comprobación visual de la interfaz.

## 1.4 (2026-11-01)

- Selección automática de hoja más fiable con fondos de color o estampados: contraste entre interior y exterior en cada lado del papel, sin preferir el marco de la imagen por su mayor tamaño.
- Ajuste manual dimensionado a la pantalla disponible, con los cuatro tiradores y los botones visibles en pantallas pequeñas.
- Margen visual alrededor de la fotografía para poder tomar los cuatro tiradores incluso junto al borde.
- Pruebas adicionales con papel perforado sobre fondo estampado y con marco de fotografía sin hoja.
- Se mantiene el procesamiento local, a color y sin OCR.

## 1.3 (2026-11-01)

- Editor de PDF existente: sustituir página, insertar antes/después y deshacer, sin necesitar fotos antiguas.
- Copia nueva de seguridad obligatoria: no se sobrescribe el PDF de origen.
- Contador y navegación rápida de páginas, campo «Ir a», teclas Alt+flechas y AvPág/RePág.
- Páginas ya digitalizadas se copian sin volver a convertirlas en JPG.
- Vistas previas ligeras, asíncronas, con caché y precarga de páginas adyacentes.
- Ajuste manual de esquinas carga en segundo hilo para evitar bloquear la ventana.
- Vista general del PDF con 16 miniaturas y salto directo a página, carga en segundo hilo.
- Aumentada la resolución máxima de exportación a 6000 píxeles y JPEG de calidad 97, sin OCR.
- Exportación inicial ahora aborta ante páginas fallidas en lugar de producir un archivo incompleto.
- 11 pruebas automatizadas para orden, recorte, protección de originales e inserción/reemplazo.

## 1.2 (2026-11-01)

- Orden de páginas basado en `EXIF DateTimeOriginal` de las fotos, independiente del nombre y las fechas de OneDrive o Windows.
- Soporte de subsegundos y offset horario EXIF cuando estén disponibles.
- La aplicación se detiene y señala las fotos sin fecha de captura para evitar un orden inventado.
- La interfaz muestra la fecha y hora de toma de cada página.
- Nuevas pruebas automáticas de orden cronológico y metadatos ausentes.

## 1.1 (2026-11-01)

- Recorte mejorado mediante detección de bordes, luminosidad y color del fondo.
- Ajuste manual de las cuatro esquinas cuando el recorte automático falla.
- Nombre personalizado para el PDF antes de crearlo.
- Páginas del PDF sin márgenes artificiales.
- Se mantienen los colores originales y no se realiza OCR ni transcripción.

## 1.0 (2026-11-01)

- Procesamiento local por lotes de fotografías.
- Orden natural de las imágenes y creación de un PDF multipágina.
- Interfaz de Windows y un iniciador por doble clic.
