# Historial de cambios

## 1.13 (2026-11-01)

- Importación y EXIF en segundo plano con fechas de captura reutilizadas.
- Detección de esquinas inicial para todas las fotos, caché reutilizable y contador de progreso.
- Caché de miniaturas y vistas procesadas (24 imágenes) para cambiar de página rápidamente.
- Vista ligera inmediata; fotografía original a alta resolución solo al aplicar zoom.
- Miniaturas de cada bloque procesadas en paralelo con dos trabajadores independientes de la imagen seleccionada.
- Solicitudes simultáneas de detección de la misma fotografía comparten un único cálculo.
- Tareas separadas para miniaturas, detalle e inspección inicial, y cancelación al cerrar.


## 1.12 (2026-11-01)

- Botones de giro de 90° a izquierda o derecha en la matriz, sin modificar archivos originales.
- Cada hoja conserva su orientación independiente de las demás.
- La miniatura, la vista ampliada, la previsualización de inicio y la exportación PDF aplican el mismo giro sin recompresión adicional.
- Los recortes manuales siguen en coordenadas originales, el giro actúa después de corregir la perspectiva.
- Pruebas de dirección del giro, conservación de píxeles, vista previa y orientación del PDF resultante.


## 1.11 (2026-11-01)

- Corregido el desacuerdo entre el detector de esquinas de las miniaturas y el de la exportación.
- Cálculo único y reutilizable de cuatro esquinas para matriz, vista de calidad y PDF.
- Validación de perspectiva y estabilidad de bordes en dos escalas; si no es segura, se conserva la fotografía completa.
- Advertencias ⚠ en la matriz para las páginas que necesitan inspección o recorte manual.
- Pruebas de igualdad geométrica entre vista previa y PDF y de fallback ante una detección inestable.
- Corrección adicional del indicador de progreso de exportación.


## 1.10 (2026-11-01)

- Único nombre de archivo, definido por la persona en la aplicación. Al exportar, Windows solicita solamente la carpeta.
- Estado persistente en la matriz: barra de progreso, recuento de páginas y aviso "✓ PDF guardado" con nombre y ruta.
- Barra al 95 % hasta completar validación de páginas; solo se muestra 100 % tras guardar correctamente.
- Botón **Abrir PDF** al finalizar. Se diferencian errores y advertencias de recortes inseguros.
- Se impide exportar dos veces simultáneamente sin perder la confirmación del archivo anterior.


## 1.9.1 (2026-11-01)

- Corrección de controles ocultos en la matriz: ahora se reserva espacio en el panel izquierdo antes de calcular el tamaño de las miniaturas.
- Miniaturas proporcionadas a la resolución de la pantalla, especialmente en monitores pequeños.
- Nombre del PDF y Exportar PDF en filas separadas, para evitar que el botón quede fuera del borde en ventanas estrechas.
- Toda el área derecha sigue dedicada a la imagen final.


## 1.9 (2026-11-01)

- Corregido el diálogo de exportación de la matriz, ahora se abre delante de ella y muestra el progreso y el resultado.
- El campo de nombre del PDF es editable en la matriz, sincronizado con la ventana principal; el nombre elegido al guardar se conserva.
- Validación del nombre final, extensión PDF y bloqueo de sobrescritura accidental.
- Verificación de páginas e imágenes del PDF temporal antes de publicarlo.
- El recorte manual se respeta aunque el recorte automático esté desactivado, sin cambiar el modo de las demás páginas.
- Nuevas pruebas de nombre, metadatos, recorte y exportación.


## 1.8.2 (2026-11-01)

- Interruptor persistente **Activar esquinas / Desactivar esquinas** en el panel izquierdo.
- El ajuste permanece activo al cambiar de hoja o avanzar entre bloques de 16 páginas.
- Guardar el recorte de una hoja no desactiva la herramienta. Cada hoja conserva sus propios puntos.
- Al desactivar se muestra la vista procesada con zoom. Los cambios sin guardar se confirman o descartan antes de cambiar de modo.


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
