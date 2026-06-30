# redirect

`redirect` es una herramienta CLI en Python para levantar proxies locales configurables. Sirve para mantener un frontend apuntando a un origin local, como `http://localhost:8080`, mientras las peticiones se reenvian a una API remota, como `https://api.ejemplo.xyz`.

No modifica el archivo `hosts` del sistema. Ese archivo solo resuelve dominios a IP y no permite redirigir puertos ni convertir `http://localhost:8080` en una API remota HTTPS. Esta herramienta usa un proxy HTTP local.

## Instalacion

Desde la raiz del proyecto:

```bash
python -m pip install -e .
```

Luego verifica que el comando exista:

```bash
redirect --help
```

## Conceptos

`origin` es la URL local donde el proxy escucha. Debe incluir protocolo, host y puerto:

```txt
http://localhost:8080
```

`destination` es la URL remota hacia la que se reenvian las peticiones:

```txt
https://api.ejemplo.xyz
```

Una peticion como:

```txt
GET http://localhost:8080/users?page=1
```

se reenvia como:

```txt
GET https://api.ejemplo.xyz/users?page=1
```

## Referencia de comandos

| Comando | Argumentos | Que hace |
| --- | --- | --- |
| `redirect --help` | ninguno | Muestra la ayuda del CLI y las opciones disponibles. |
| `redirect --set ...` | `id`, `origin`, `destination` | Guarda un proxy persistido e inactivo en `~/.redirect/config.json`. |
| `redirect -t ...` / `redirect --temp ...` | `origin`, `destination`, opcional `--unsafe` | Levanta un proxy temporal en primer plano sin guardarlo en la configuracion. |
| `redirect -l` / `redirect --list` | ninguno | Lista los proxies configurados y muestra si estan activos o inactivos. |
| `redirect -e ID` / `redirect --enable ID` | `ID`, opcional `--unsafe` | Levanta el proxy persistido indicado. Si otro proxy usa el mismo `origin`, pide confirmacion para switchear. |
| `redirect -d ID` / `redirect --disable ID` | `ID` | Detiene el proxy indicado y lo marca como inactivo. |
| `redirect -r ID` / `redirect --remove ID` | `ID` | Elimina el proxy indicado de la configuracion. Si esta activo, lo detiene primero. |
| `redirect --delete ID` | `ID` | Alias de compatibilidad para `--remove`; no aparece en `--help`. |
| `redirect --serve ID` | `ID` | Comando interno usado por `redirect` para ejecutar el proceso del proxy. No se usa manualmente. |

## Argumentos

| Argumento | Uso | Descripcion corta |
| --- | --- | --- |
| `ID` | `-e`, `-d`, `-r`, `--enable`, `--disable`, `--remove` | Identificador del proxy guardado, por ejemplo `qa-api`. No puede estar vacio ni contener espacios. |
| `id=...` | `--set` | ID que tendra el proxy persistido nuevo. Debe ser unico. |
| `origin=...` | `--set`, `--temp` | URL local donde escucha el proxy. Debe ser `http` o `https` e incluir host y puerto, por ejemplo `http://localhost:8080`. |
| `destination=...` | `--set`, `--temp` | URL remota hacia la que se reenvian las peticiones. Debe ser `http` o `https`. |
| `--unsafe` | `--enable`, `--temp` | Permite todos los metodos HTTP. Sin esta opcion, solo pasan `GET`, `HEAD` y `OPTIONS`. |

## Proxies persistidos

Los proxies configurados se guardan en:

```txt
~/.redirect/config.json
```

Crear un proxy persistido:

```bash
redirect --set id=qa-api origin=http://localhost:8080 destination=https://api.ejemplo.xyz
```

El proxy se guarda con `enabled: false` y no se levanta automaticamente.
Puedes guardar mas de un proxy con el mismo `origin`. Como todos se crean
inactivos, no chocan hasta que intentes levantar uno.

Listar proxies:

```bash
redirect -l
redirect --list
```

Habilitar y levantar un proxy:

```bash
redirect -e qa-api
redirect --enable qa-api
```

Deshabilitar y detener un proxy:

```bash
redirect -d qa-api
redirect --disable qa-api
```

Eliminar un proxy:

```bash
redirect -r qa-api
redirect --remove qa-api
```

Si el proxy esta activo, `--remove` lo detiene antes de removerlo de la configuracion.

## Cambiar entre proxies con el mismo origin

Solo puede haber un proxy activo por `origin`, porque ambos intentarian escuchar
en el mismo host y puerto. Si habilitas un proxy cuyo `origin` ya esta activo en
otro proxy, `redirect` muestra cual esta usando ese `origin` y pide confirmacion
antes de hacer el cambio:

```txt
Origin http://localhost:8080 is already active on proxy 'qa-api':
  current: https://qa-api.ejemplo.xyz
  new:     https://staging-api.ejemplo.xyz
Disable 'qa-api' and enable 'staging-api' instead? [y/N]
```

Si respondes `y`, el proxy activo se deshabilita y se levanta el nuevo. Si
respondes cualquier otra cosa, no se cambia nada.

## Proxies temporales

Un proxy temporal se levanta inmediatamente y no se guarda en `~/.redirect/config.json`:

```bash
redirect -t origin=http://localhost:8080 destination=https://api.ejemplo.xyz
redirect --temp origin=http://localhost:8080 destination=https://api.ejemplo.xyz
```

El proceso queda en primer plano. Detenlo con `Ctrl+C`.

## Modo seguro

Por defecto, `redirect` trabaja en modo seguro. Solo permite:

```txt
GET
HEAD
OPTIONS
```

Bloquea metodos que pueden modificar datos:

```txt
POST
PUT
PATCH
DELETE
```

Cuando una peticion se bloquea, responde:

```json
{
  "error": "Request blocked by safe mode",
  "method": "POST",
  "hint": "Use --unsafe if you really need to allow write operations"
}
```

## Modo unsafe

Usa `--unsafe` para permitir todos los metodos HTTP:

```bash
redirect -e qa-api --unsafe
```

Tambien funciona con proxies temporales:

```bash
redirect -t origin=http://localhost:8080 destination=https://api.ejemplo.xyz --unsafe
```

## CORS

El proxy agrega estos headers para facilitar pruebas desde frontends locales:

```txt
Access-Control-Allow-Origin: <Origin de la peticion, o * si no hay Origin>
Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: <Access-Control-Request-Headers, o *>
Access-Control-Allow-Credentials: true
```

Cuando la peticion trae `Origin`, tambien agrega `Vary: Origin`.

## Validaciones

`redirect` valida que:

- no existan IDs repetidos
- no existan destinations repetidos
- `origin` sea una URL `http` o `https` con host y puerto
- `destination` sea una URL `http` o `https`
- no se habilite un proxy si el puerto del `origin` esta ocupado
- si ya hay un proxy activo con el mismo `origin`, se confirme el cambio antes
  de deshabilitar el anterior y levantar el nuevo

## Ejemplo completo

```bash
redirect --set id=qa-api origin=http://localhost:8080 destination=https://api.ejemplo.xyz
redirect -l
redirect -e qa-api
curl http://localhost:8080/users?page=1
redirect -d qa-api
redirect -r qa-api
```

## Pruebas

```bash
python -m unittest discover -s tests
```

## Empaquetar con Briefcase

El proyecto incluye configuracion de Briefcase para construir `redirect` como app de consola. Para empaquetar, instalar el bundle localmente y crear el launcher en `~/.local/bin`:

```bash
./scripts/install_with_briefcase.sh
```

El script:

- instala Briefcase en `.venv-briefcase` si no existe
- ejecuta las pruebas
- corre `briefcase create` o `briefcase update`
- corre `briefcase build`
- corre `briefcase package`
- instala el bundle en `~/.local/share/redirect/briefcase`
- crea el comando `~/.local/bin/redirect`
- verifica `redirect --help`

Opciones utiles:

```bash
SKIP_PACKAGE=1 ./scripts/install_with_briefcase.sh
INSTALL_DIR="$HOME/bin" ./scripts/install_with_briefcase.sh
BRIEFCASE_PLATFORM=linux BRIEFCASE_FORMAT=appimage ./scripts/install_with_briefcase.sh
```
