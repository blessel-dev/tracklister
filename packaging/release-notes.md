# Tracklister {version}

Descarga **{zip_name}**, descomprímelo entero y abre `Tracklister\Tracklister.exe`.
Para Windows 10/11 de 64 bits; no hace falta instalar Python.

- Windows SmartScreen puede avisar ("Windows protegió su PC") porque la app no está firmada:
  pulsa "Más información" y luego "Ejecutar de todas formas".
- Para comprobar la descarga, en PowerShell:
  `Get-FileHash .\{zip_name} -Algorithm SHA256` tiene que dar el valor de `SHA256SUMS.txt`.
- `sockseek-3.0.5-source.zip` y `sldl-2.6.0-source.zip` son el código fuente exacto de los motores
  que van dentro (AGPL-3.0 y GPL-3.0). Los avisos de terceros están en `NOTICES.txt`, dentro del zip.

SHA-256:

```
{sums}
```
