# Tracklister: guía de uso

Tracklister convierte la tracklist de un set en una carpeta con la música verificada de Soulseek, numerada en el orden del set. En la ventana se lee «Tracklister by Blessel».

Funciona en Windows 10 y 11 de 64 bits. Necesitas tu propia cuenta de Soulseek; si aún no tienes, la creas en el primer arranque. Volver al [README](../README.md).

- [1. Descargar e instalar](#1-descargar-e-instalar)
- [2. Primer arranque](#2-primer-arranque)
- [3. Tu primer set](#3-tu-primer-set)
- [4. Diagnóstico: comprobar que todo funciona](#4-diagnóstico-comprobar-que-todo-funciona)
- [5. El aviso de SmartScreen y la huella SHA-256](#5-el-aviso-de-smartscreen-y-la-huella-sha-256)
- [6. Actualizar a una versión nueva](#6-actualizar-a-una-versión-nueva)
- [7. Si algo falla](#7-si-algo-falla)
- [Ajustes: tema y formato](#ajustes-tema-y-formato)
- [Nota de seguridad: tu contraseña de Soulseek](#nota-de-seguridad-tu-contraseña-de-soulseek)

## 1. Descargar e instalar

1. En la [página de la última versión](https://github.com/blessel-dev/tracklister/releases/latest), descarga `Tracklister-<versión>-win64.zip` (unos 130 MB). No hay que instalar nada más, tampoco Python.
   - En la misma página están `SHA256SUMS.txt`, para comprobar la descarga (punto 5), y el código fuente de los dos motores (`sockseek-3.0.5-source.zip` y `sldl-2.6.0-source.zip`), que no necesitas para usar la app.
2. Clic derecho en el zip → «Extraer todo…» y elige una carpeta tuya, por ejemplo `Documentos`. Dentro queda la carpeta `Tracklister`, con `Tracklister.exe`.
   - No abras el exe desde dentro del zip ni lo saques de su carpeta: necesita lo que tiene al lado (`_internal`, `engines` y `tools`).
   - Para tenerlo a mano: clic derecho en `Tracklister.exe` → «Enviar a» → «Escritorio (crear acceso directo)». En Windows 11, «Enviar a» está dentro de «Mostrar más opciones».

## 2. Primer arranque

1. Doble clic en `Tracklister.exe`. Si sale «Windows protegió su PC», mira el punto 5.
2. Sale la pantalla «Bienvenido a Tracklister». Rellena:
   - **Tu cuenta de Soulseek**: tu usuario y tu contraseña. Se guardan en el Administrador de credenciales de Windows, nunca en un archivo. Si aún no tienes cuenta, inventa un usuario y una contraseña: Soulseek crea la cuenta la primera vez que conectas. Mejor un usuario poco común, que no sea una palabra corriente ni el nombre de un artista: Tracklister lo tapa en todo lo que enseña, y con una palabra corriente también taparía esa palabra en los nombres de las pistas.
   - **Carpeta de tu biblioteca**: de serie, `Música\Tracklister`. Dentro se crea una carpeta por set.
   - **Formato**: «Lossless (recomendado)». Los demás están explicados en [Ajustes](#ajustes-tema-y-formato).
   - **Puerto de escucha**: deja 49998. Si otra persona usa Tracklister en tu misma red, cada uno tiene que poner uno distinto.
   - Lee «Antes de empezar», marca «Entendido» y pulsa «Empezar».
3. En este paso Tracklister no prueba tu usuario ni tu contraseña. Lo hacen el Diagnóstico y la primera descarga, que te dicen claramente si fallan. Por eso, empieza por el Diagnóstico (punto 4).
4. La primera vez que busque en Soulseek, el Firewall de Windows puede preguntarte si dejas usar la red a `sockseek.exe`, el motor de descarga. Marca «Redes privadas» y pulsa «Permitir acceso».
5. Mientras uses Tracklister, no tengas abierta la misma cuenta en Nicotine+ ni en otro programa de Soulseek: Soulseek cortaría una de las dos.

<p align="center"><img src="readme/primer-inicio-hormigon.png" width="640" alt="Pantalla de primer inicio: tu cuenta de Soulseek, la carpeta de la biblioteca, el formato y el puerto de escucha"></p>

## 3. Tu primer set

1. **Nuevo set**: arrastra el CSV de trackid.net, un Excel (.xlsx) o un CSV. También puedes pegar un texto (1001tracklists, MixesDB, un comentario) y pulsar «Leer», o soltar un enlace de YouTube o SoundCloud.
   - «Abrir en trackid.net» abre la web: allí pulsa Export y arrastra el CSV a la ventana. Si con la app abierta te llega un CSV de trackid.net a Descargas, te avisa para importarlo.
   - Los `.xls` del Excel antiguo no se pueden leer: guárdalos como `.xlsx` o `.csv` desde Excel.
2. Revisa la tabla: puedes corregir artista, título y versión, y subir, bajar, añadir o quitar filas. Las filas «ID» van desmarcadas. El número de cada fila es el que llevará su archivo.
3. Escribe el nombre del set y pulsa «Descargar».
4. Si ya tienes una pista de un set anterior, te pregunta cada vez: «Usar el que ya tengo (copiar a este set)» o «Descargar de nuevo en este set». La casilla «Aplicar a todos los repetidos de este set» responde por todas.
5. En **Descarga** ves cada pista con su estado: Verificado, Dudoso, No encontrado, Ya en biblioteca, No cumple formato… Si seleccionas una, debajo salen sus motivos. Si cancelas, se guarda lo hecho y aparece «Continuar descarga».
6. Al terminar tienes «Reintentar fallos», «Copiar tracklist» (texto con tiempos para Mixcloud o Instagram), «Abrir informe» y «Abrir carpeta».

La carpeta del set queda así:

```text
Música\Tracklister\<nombre del set>\
    01 - Artista - Título (Versión).flac
    02 - ...
    _dudosos\        lo que puede ser otra canción u otra versión, o no cuadra en duración
    _originales\     los FLAC originales que «CDJ antiguos» ha pasado a AIFF
    Informe - <nombre del set>.txt
    Tracklist - <nombre del set>.txt
    .tracklister\    el estado del set y el registro para deshacer
```

No borres la carpeta `.tracklister`: la necesitan «Reintentar fallos» y «Abrir un set anterior…».

Para las carpetas que ya bajaste con otro programa está la pestaña **Reordenar**: les pone el número de la tracklist, con vista previa, sin sobrescribir nada y con «Deshacer el último reordenado».

## 4. Diagnóstico: comprobar que todo funciona

El Diagnóstico busca unas pocas pistas en Soulseek sin descargarlas y explica qué candidatos aparecen y por qué acepta o rechaza cada uno. Hazlo la primera vez que uses Tracklister, antes de bajar un set entero, y siempre que una pista no salga bien.

1. Carga una tracklist en «Nuevo set». No hace falta descargarla.
2. Ve a «Diagnóstico»: usa las primeras pistas marcadas de la tabla de «Nuevo set». Para usar otra tracklist, pulsa «Abrir tracklist…».
3. «Pistas que se buscan»: 5 (como mucho 20). Deja sin marcar «Descargar también esas pistas»: es la prueba completa y tarda más.
4. Pulsa «Empezar diagnóstico» y espera a que ponga «Terminado».
5. Si necesitas ayuda, pulsa «Copiar informe» y pégalo con Ctrl+V en el mensaje en el que la pidas.

El informe también se guarda como `Diagnostico_<fecha>.txt` en `%LOCALAPPDATA%\Tracklister\logs` (pega esa ruta en la barra de direcciones del Explorador).

- **Qué lleva**: la versión de Tracklister, el motor, la versión de Windows, el puerto y, por cada pista, los candidatos: carpeta y archivo, tamaño, kbps, duración, puntuación y motivo.
- **Qué no lleva**: tu usuario, tu contraseña ni tu IP. Los demás usuarios salen como peer-1, peer-2… La última línea del informe lo confirma.

Con una descarga en marcha no se puede lanzar el Diagnóstico, ni al revés: los dos entrarían con tu misma cuenta.

## 5. El aviso de SmartScreen y la huella SHA-256

Tracklister no está firmado digitalmente (la firma queda para más adelante), así que Windows no lo conoce y puede avisar al abrirlo:

1. Sale «Windows protegió su PC».
2. Pulsa **«Más información»**.
3. Pulsa **«Ejecutar de todas formas»**.

Normalmente solo pasa la primera vez.

- Para comprobar el zip que has bajado, en PowerShell, en la carpeta del zip: `Get-FileHash .\Tracklister-1.0.0-win64.zip -Algorithm SHA256` (con el nombre de tu zip) tiene que dar el mismo valor que pone `SHA256SUMS.txt`. PowerShell lo escribe en mayúsculas; eso da igual.
- Si en vez de ese aviso sale «Control inteligente de aplicaciones» (Windows 11) y no deja abrirlo, no lo desactives solo por esto: pide ayuda con el mensaje exacto.

## 6. Actualizar a una versión nueva

Tracklister mira como mucho una vez al día si hay una versión nueva. Si la hay, muestra un aviso con el enlace; nunca instala nada solo. También puedes mirarlo con «Buscar actualizaciones», en Ajustes.

Para actualizar, descarga el zip nuevo, descomprímelo y cambia tu carpeta `Tracklister` por la nueva. Tus ajustes, tu cuenta y tu biblioteca están fuera de ella y no se pierden.

## 7. Si algo falla

Si pides ayuda, incluye:

- el mensaje exacto, copiado o en una captura;
- si es al buscar o descargar, un Diagnóstico de esas pistas (punto 4);
- si sale «Algo ha fallado…», las últimas líneas de `%LOCALAPPDATA%\Tracklister\logs\tracklister.log`. Nunca lleva tu cuenta, pero puede llevar rutas de tu PC con tu nombre de usuario de Windows: si quieres, cámbialo por `<usuario>` antes de pegarlo.

Casos conocidos:

- **No se abre o se cierra sin decir nada.** Vuelve a descomprimir el zip entero y abre `Tracklister.exe` dentro de su carpeta. Solo funciona en Windows 10/11 de 64 bits. Si el antivirus lo ha bloqueado o borrado, mira su mensaje.
- **«No se pudo guardar la cuenta…» o «No se pudo leer la cuenta…»** (Administrador de credenciales de Windows). Pide ayuda con el mensaje exacto.
- **«No se pudo entrar en Soulseek…» o «Falta tu cuenta de Soulseek».** Revisa usuario y contraseña en «Ajustes» → «Cuenta de Soulseek» → «Guardar cuenta». Cierra Nicotine+ si usa la misma cuenta. Si ese usuario ya existe con otra contraseña (es de otra persona), elige otro nombre.
- **«Soulseek cortó la sesión…».** Demasiadas búsquedas seguidas, o la misma cuenta abierta en otro programa. Espera 30 minutos y pulsa «Reintentar fallos».
- **No llega ningún resultado o las descargas no arrancan.** Prueba esto y repite el Diagnóstico:
  - abre el puerto TCP 49998 (o el que tengas en Ajustes) en el router, hacia la IP de este PC;
  - deja pasar a `sockseek.exe` (o a `sldl.exe`, si usas el motor alternativo) en el Firewall de Windows, en redes privadas. Están en `%LOCALAPPDATA%\Tracklister\tools\engines\`;
  - si tu operador usa CGNAT, no podrás abrir el puerto: pídele una IP pública;
  - si otra persona usa Tracklister en tu misma red, usad puertos distintos.
- **«El puerto de escucha está ocupado por otro programa».** Cambia el puerto en «Ajustes» → «Red y motor».
- **«No se encuentra el motor…» o «No se pudo arrancar el motor…».** Vuelve a descomprimir el zip entero; puede que el antivirus haya quitado el motor. Si sigue, en «Ajustes» → «Red y motor» → «Motor», elige «sldl 2.6.0 (alternativa)».
- **Una pista sale «Dudoso».** El motivo está debajo de la tabla y en el informe.
  - «otra canción», «otra versión» o «duración»: el archivo está en `_dudosos`. Corrige artista, título o versión en «Nuevo set» y vuelve a descargar, o pulsa «Reintentar fallos», que la busca otra vez sin el usuario que te dio ese archivo. El archivo rechazado nunca se borra.
  - «posible lossless falso» o «revisar»: el archivo se queda en el set, con su número, y decides tú. Con «revisar», escúchalo para confirmar que es la canción. Con «posible lossless falso», escucharlo no siempre lo resuelve: un MP3 de 320 convertido a FLAC puede sonar igual.
  - Tracklister prefiere una duda de más: una errata en un nombre corto del artista, o una etiqueta con solo el apellido, puede acabar en `_dudosos` aunque sea la canción buena. Si te pasa, mira el archivo en `_dudosos`.
- **«No cumple formato».** El archivo llegó, pero no es lo que pide tu formato (por ejemplo, un MP3 VBR o de menos de 320). Pulsa «Reintentar fallos».
- **No se leen los comentarios de YouTube.** «Ajustes» → «Actualizar yt-dlp». Si el vídeo es privado o se ha borrado, no tiene arreglo.
- **Letras raras en nombres con tildes o eñes** (por ejemplo `�` en «Ver registro»). Es solo el texto que el motor le pasa a Tracklister mientras descarga. No debería pasar, porque los dos motores escriben ese texto en UTF-8, que es lo que lee Tracklister. Si te pasa:
  - el progreso de esas pistas puede quedarse quieto hasta el final de la pasada;
  - los archivos y sus nombres salen bien igualmente: al terminar, Tracklister comprueba cada archivo en el disco y lo nombra con los datos de tu tabla. Lo que vale es el estado final y el informe;
  - «Reintentar fallos» puede no saber qué usuario mandó un archivo dudoso con tildes. Entonces no lo vuelve a buscar y te lo dice en el motivo.

  Si pides ayuda, incluye un Diagnóstico con una de esas pistas.

## Ajustes: tema y formato

Todo se guarda al momento y es de cada usuario de Windows: cada persona tiene sus propios ajustes. La cuenta es la excepción: se guarda al pulsar «Guardar cuenta».

**Tema**

- «Hormigón (claro)»: el de serie, con el gris del logo de Blessel.
- «Noche (oscuro)»: casi negro, con el hormigón solo en la cabecera.
- Se cambia en «Ajustes» → «Tema», se aplica al momento y se recuerda la próxima vez.

**Formato** (también se elige en el primer arranque)

- «Lossless» (recomendado): FLAC, WAV o AIFF. Si alguna pista solo está en MP3, te pregunta una vez por set con la lista de esas pistas, y solo busca en MP3 320 las que marques.
- «CDJ antiguos»: para CDJ anteriores al NXS2, que no leen FLAC. Busca AIFF o WAV, y pasa los FLAC a AIFF con el mismo sample rate y bits, tags y carátula. Si un archivo pasa de 48 kHz o de 24 bits, lo baja a 48 kHz/24 bits (88,2 y 176,4 kHz bajan a 44,1 kHz), con aviso. El FLAC original queda en `_originales`.
- «Solo MP3 320»: MP3 CBR de 320 kbps, comprobado en el propio archivo. El VBR (también el V0) no vale: sale «No cumple formato».
- «Personalizado»: eliges los formatos, el MP3 mínimo (320, 256 o 192 kbps), el sample rate y los bits máximos, y si te pregunta por MP3 cuando no hay lossless.

En Ajustes también están la cuenta, la carpeta de la biblioteca, el puerto, el motor, «Completar datos al importar», el análisis de espectro, la vigilancia de Descargas, «Actualizar yt-dlp» y «Buscar actualizaciones».

## Nota de seguridad: tu contraseña de Soulseek

- Tu cuenta solo está en el Administrador de credenciales de Windows. Ningún archivo de Tracklister la guarda, y en los registros, los informes y el Diagnóstico sale tapada (`***` o `[censurado]`).
- Para conectarse, el motor de descarga (Sockseek o sldl) necesita tu cuenta, y no ofrece otra forma de recibirla que su línea de comandos (`--user` y `--pass`) o un archivo de configuración con la contraseña escrita. Tracklister nunca escribe tu contraseña en un archivo, así que se la pasa por la línea de comandos.
- Mientras el motor está en marcha, otros programas que se ejecutan en tu PC pueden leer su línea de comandos y, con ella, tu contraseña de Soulseek.
- Por eso: usa en Soulseek una contraseña que no uses en ningún otro sitio, y no descargues desde un PC en el que no confíes.
