import os
import json
import time
import requests
from urllib.parse import quote
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("ML_REDIRECT_URI")

TOKEN_FILE = os.getenv("TOKEN_FILE_PATH", "token.json")

app = FastAPI()

USER_IDS_POR_SITIO = {
    "MLA": 2964561487,
    "MLB": 2964561513,
    "MCO": 2964837918,
    "MLC": 2964837908,
    "MLM": 2964837940,
}

NAV_HTML = """
<div style="background:#333; padding:14px 40px; margin:-40px -40px 30px -40px; display:flex; gap:24px; align-items:center;">
    <a href="/dashboard" style="color:#fff; text-decoration:none; font-weight:bold;">Dashboard</a>
    <a href="/ventas" style="color:#fff; text-decoration:none; font-weight:bold;">Ventas</a>
    <a href="/publicar" style="text-decoration:none; font-weight:bold; background:#ffe600; color:#333; padding:6px 14px; border-radius:4px;">+ Publicar producto</a>
    <a href="/notificaciones" style="color:#fff; text-decoration:none; font-weight:bold;">Notificaciones</a>
</div>
"""


def guardar_token(data):
    data["obtenido_en"] = time.time()
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def cargar_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None

def renovar_token():
    token_data = cargar_token()
    if not token_data or "refresh_token" not in token_data:
        return None

    payload = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": token_data["refresh_token"],
    }
    response = requests.post("https://api.mercadolibre.com/oauth/token", data=payload)
    nuevo = response.json()

    if "access_token" in nuevo:
        guardar_token(nuevo)
        return nuevo
    return None


def obtener_access_token():
    """Devuelve un access_token valido, renovandolo automaticamente si esta por vencer."""
    token_data = cargar_token()
    if not token_data:
        return None

    obtenido_en = token_data.get("obtenido_en", 0)
    expires_in = token_data.get("expires_in", 0)
    margen_segundos = 60

    if time.time() >= obtenido_en + expires_in - margen_segundos:
        token_data = renovar_token()

    if not token_data:
        return None
    return token_data.get("access_token")


@app.get("/")
def home():
    auth_url = (
        "https://global-selling.mercadolibre.com/authorization"
        "?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
    )
    return HTMLResponse(f'<a href="{auth_url}">Conectar con Mercado Libre</a>')


@app.get("/callback", response_class=HTMLResponse)
def callback(code: str = None):
    if not code:
        return HTMLResponse("<h2>No llego el codigo de autorizacion.</h2><a href='/'>Volver</a>")

    token_url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    response = requests.post(token_url, data=payload)
    data = response.json()

    if "access_token" in data:
        guardar_token(data)
        return HTMLResponse(
            "<h2 style='color:green;'>Conectado con exito!</h2>"
            "<a href='/dashboard'><button>Ir al Dashboard</button></a>"
        )

    detalle = data.get("message", "Error desconocido")
    return HTMLResponse(f"<h2 style='color:red;'>No se pudo conectar: {detalle}</h2><a href='/'>Volver a intentar</a>")


@app.get("/perfil")
def perfil():
    token_data = cargar_token()
    if not token_data:
        return {"error": "No hay token guardado. Conectate primero desde /"}

    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.mercadolibre.com/users/me", headers=headers)
    return response.json()

@app.get("/publicaciones")
def publicaciones():
    token_data = cargar_token()
    if not token_data:
        return {"error": "No hay token guardado. Conectate primero desde /"}

    access_token = token_data["access_token"]
    user_id = token_data["user_id"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/marketplace/users/{user_id}/items/search"
    response = requests.get(url, headers=headers)
    return response.json()

@app.get("/publicaciones/detalle")
def publicaciones_detalle():
    token_data = cargar_token()
    if not token_data:
        return {"error": "No hay token guardado. Conectate primero desde /"}

    access_token = token_data["access_token"]
    user_id = token_data["user_id"]
    headers = {"Authorization": f"Bearer {access_token}"}

    url_lista = f"https://api.mercadolibre.com/marketplace/users/{user_id}/items/search"
    lista = requests.get(url_lista, headers=headers).json()
    ids = lista.get("results", [])

    detalles = []
    for item_id in ids:
        url_item = f"https://api.mercadolibre.com/marketplace/items/{item_id}"
        item = requests.get(url_item, headers=headers).json()
        detalles.append(item)

    return {"total": len(detalles), "publicaciones": detalles}

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(msg: str = None, detalle: str = None, estado: str = "todos", orden: str = "", buscar: str = ""):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = obtener_access_token()
    if not access_token:
        return HTMLResponse("<h2>No se pudo renovar el token. <a href='/'>Conectate de nuevo</a></h2>")

    user_id = token_data["user_id"]
    headers = {"Authorization": f"Bearer {access_token}"}

    banner = ""
    if msg == "ok":
        detalle_txt = f" {detalle}" if detalle else ""
        banner = f'<div style="background:#e6f4ea;color:#2e7d32;padding:12px;border-radius:4px;margin-bottom:16px;">Cambio aplicado con exito.{detalle_txt}</div>'
    elif msg == "error":
        detalle_txt = detalle or "Error desconocido"
        banner = f'<div style="background:#fdecea;color:#c62828;padding:12px;border-radius:4px;margin-bottom:16px;">Error al aplicar el cambio: {detalle_txt}</div>'

    url_lista = f"https://api.mercadolibre.com/marketplace/users/{user_id}/items/search"
    lista = requests.get(url_lista, headers=headers).json()
    ids = lista.get("results", [])

    productos = []
    for item_id in ids:
        url_item = f"https://api.mercadolibre.com/marketplace/items/{item_id}"
        item = requests.get(url_item, headers=headers).json()

        precio = item.get("price", "-")
        stock_valor = item.get("available_quantity", 0) or 0
        marketplace_items = item.get("marketplace_items", [])

        productos.append({
            "item_id": item_id,
            "titulo": item.get("title", "Sin titulo"),
            "precio": precio,
            "ganancia_actual": precio if isinstance(precio, (int, float)) else "",
            "stock": item.get("available_quantity", "-"),
            "stock_valor": stock_valor,
            "vendidos": item.get("sold_quantity", 0) or 0,
            "estado": item.get("status", "-"),
            "sub_estado": item.get("sub_status") or [],
            "foto": item.get("thumbnail", ""),
            "sites_ids": sorted(set(m["site_id"] for m in marketplace_items)),
            "siteless_id": marketplace_items[0]["siteless_user_product_id"] if marketplace_items else "",
        })

    if estado in ("active", "paused"):
        productos = [p for p in productos if p["estado"] == estado]

    if buscar:
        buscar_lower = buscar.lower()
        productos = [p for p in productos if buscar_lower in p["titulo"].lower()]

    ORDENES = {
        "stock_desc": ("stock_valor", True),
        "stock_asc": ("stock_valor", False),
        "vendidos_desc": ("vendidos", True),
        "vendidos_asc": ("vendidos", False),
    }
    if orden in ORDENES:
        campo, descendente = ORDENES[orden]
        productos.sort(key=lambda p: p[campo], reverse=descendente)

    filas = ""
    for p in productos:
        item_id = p["item_id"]
        titulo = p["titulo"]
        precio = p["precio"]
        ganancia_actual = p["ganancia_actual"]
        stock = p["stock"]
        vendidos = p["vendidos"]
        estado_item = p["estado"]
        sub_estado = p["sub_estado"]
        foto = p["foto"]
        paises = ", ".join(p["sites_ids"])
        sites_csv = ",".join(p["sites_ids"])
        siteless_id = p["siteless_id"]

        if estado_item == "active":
            color_estado, texto_estado = "#2e7d32", "Activa"
        elif estado_item == "paused":
            color_estado, texto_estado = "#f9a825", "Pausada"
        elif estado_item == "closed":
            color_estado, texto_estado = "#c62828", "Cerrada por ML"
        else:
            color_estado, texto_estado = "#757575", estado_item

        if sub_estado:
            texto_estado += f" ({', '.join(sub_estado)})"

        filas += f"""
        <tr>
            <td><img src="{foto}" width="60"></td>
            <td>{titulo}</td>
            <td>
                USD {precio}
                <form action="/cambiar-precio" method="get" style="margin-top:4px;">
                    <input type="hidden" name="siteless_id" value="{siteless_id}">
                    <input type="hidden" name="sites" value="{sites_csv}">
                    <input type="number" step="0.01" name="nueva_ganancia" style="width:70px;" value="{ganancia_actual}" min="0" placeholder="Ganancia">
                    <button type="submit">Actualizar</button>
                </form>
            </td>
            <td>{stock}</td>
            <td>{vendidos}</td>
            <td style="color:{color_estado}; font-weight:bold;">{texto_estado}</td>
            <td>{paises}</td>
            <td>
                <a href="/cambiar-estado?siteless_id={siteless_id}&nuevo_estado=paused" onclick="return confirm('Pausar esta publicacion?');"><button>Pausar</button></a>
                <a href="/cambiar-estado?siteless_id={siteless_id}&nuevo_estado=active" onclick="return confirm('Activar esta publicacion?');"><button>Activar</button></a>
                <form action="/cambiar-stock" method="get" style="display:inline;">
                    <input type="hidden" name="siteless_id" value="{siteless_id}">
                    <input type="number" name="nueva_cantidad" style="width:60px;" value="{stock if isinstance(stock, int) else ''}" min="0">
                    <button type="submit">Actualizar</button>
                </form>
                <a href="/duplicar?item_id={item_id}"><button>Duplicar</button></a>
                <a href="/editar?item_id={item_id}"><button>Editar</button></a>
            </td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>Dashboard Global Selling</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }}
            th {{ background: #ffe600; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Mis Publicaciones - Global Selling</h1>
        <div style="background:#fff8e1; color:#8a6d00; padding:10px 14px; border-radius:4px; margin-bottom:16px; font-size:14px;">
            El estado (Activa/Pausada) que ves aca es el agregado de Mercado Libre y puede no reflejar al instante lo que pasa en cada pais.
            Si ML pausa, cierra o remueve una publicacion por moderacion en un pais puntual, puede no verse reflejado aca.
            Ante cualquier duda, confirma el estado real en <a href="https://global-selling.mercadolibre.com" target="_blank">el panel de Global Selling</a>.
        </div>
        {banner}
        <form method="get" style="background:white; padding:16px; border-radius:4px; margin-bottom:16px; display:flex; gap:16px; align-items:end; flex-wrap:wrap;">
            <div>
                <label>Buscar por titulo:</label><br>
                <input type="text" name="buscar" value="{buscar}" placeholder="Ej: salt">
            </div>
            <div>
                <label>Estado:</label><br>
                <select name="estado">
                    <option value="todos" {"selected" if estado == "todos" else ""}>Todos</option>
                    <option value="active" {"selected" if estado == "active" else ""}>Activos</option>
                    <option value="paused" {"selected" if estado == "paused" else ""}>Pausados</option>
                </select>
            </div>
            <div>
                <label>Ordenar por:</label><br>
                <select name="orden">
                    <option value="" {"selected" if orden == "" else ""}>Sin orden</option>
                    <option value="stock_desc" {"selected" if orden == "stock_desc" else ""}>Stock: mayor a menor</option>
                    <option value="stock_asc" {"selected" if orden == "stock_asc" else ""}>Stock: menor a mayor</option>
                    <option value="vendidos_desc" {"selected" if orden == "vendidos_desc" else ""}>Vendidos: mayor a menor</option>
                    <option value="vendidos_asc" {"selected" if orden == "vendidos_asc" else ""}>Vendidos: menor a mayor</option>
                </select>
            </div>
            <button type="submit">Filtrar</button>
            <a href="/dashboard" style="align-self:center;">Limpiar filtros</a>
        </form>
        <table>
            <tr>
                <th>Foto</th>
                <th>Producto</th>
                <th>Ganancia (USD)</th>
                <th>Stock</th>
                <th>Vendidos</th>
                <th>Estado</th>
                <th>Paises</th>
                <th>Acciones</th>
            </tr>
            {filas if productos else '<tr><td colspan="8">No hay publicaciones que coincidan con el filtro.</td></tr>'}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/categoria")
def categoria(q: str):
    token_data = cargar_token()
    if not token_data:
        return {"error": "No hay token guardado. Conectate primero desde /"}

    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/marketplace/domain_discovery/search?q={q}"
    response = requests.get(url, headers=headers)
    return response.json()


@app.get("/publicar", response_class=HTMLResponse)
def publicar_form():
    html = f"""
    <html>
    <head>
        <title>Publicar producto</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            input[type=text] {{ width: 400px; padding: 8px; font-size: 16px; }}
            button {{ padding: 8px 16px; font-size: 16px; background: #ffe600; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Publicar producto nuevo</h1>
        <form action="/buscar-categoria" method="get">
            <label>Nombre del producto (en ingles funciona mejor):</label><br><br>
            <input type="text" name="titulo" placeholder="Ej: Himalayan Pink Salt 16oz">
            <button type="submit">Buscar categoria</button>
        </form>

        <hr style="margin:30px 0;">

        <p>Para copiar titulo, categoria, atributos y foto de <b>una publicacion tuya existente</b> y solo ajustar precio y stock, anda al <a href="/dashboard">Dashboard</a> y usa el boton "Duplicar" en esa fila.</p>

        <hr style="margin:30px 0;">

        <p>Para cargar un producto que encontraste en Amazon, Walmart u otro sitio: abrilo en otra pestana, copia el titulo, la descripcion y los links de las fotos, y pegalos aca. <a href="/externo">Cargar producto externo</a></p>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/externo", response_class=HTMLResponse)
def externo_form():
    html = f"""
    <html>
    <head>
        <title>Cargar producto externo</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            input[type=text], textarea {{ width: 500px; padding: 8px; font-size: 16px; }}
            button {{ padding: 8px 16px; font-size: 16px; background: #ffe600; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Cargar producto externo (Amazon, Walmart, etc)</h1>
        <p>Abri el producto en otra pestana y copia/pega cada dato aca. Despues elegis la categoria de Mercado Libre igual que siempre.</p>
        <form action="/buscar-categoria" method="get">
            <p><label>Titulo (en ingles funciona mejor para encontrar la categoria):</label><br>
            <input type="text" name="titulo" placeholder="Ej: Himalayan Pink Salt 16oz"></p>

            <p><label>Descripcion:</label><br>
            <textarea name="descripcion" rows="5"></textarea></p>

            <p><label>URL de la foto principal:</label><br>
            <input type="text" name="foto_url"></p>

            <p><label>URLs de fotos adicionales (una por linea):</label><br>
            <textarea name="fotos_extra" rows="4"></textarea></p>

            <button type="submit">Buscar categoria</button>
        </form>
        <br><a href="/publicar">Volver</a>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/buscar-categoria", response_class=HTMLResponse)
def buscar_categoria(titulo: str, descripcion: str = "", foto_url: str = "", fotos_extra: str = ""):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/marketplace/domain_discovery/search?q={titulo}"
    opciones = requests.get(url, headers=headers).json()

    extras = f"&titulo={quote(titulo)}&descripcion={quote(descripcion)}&foto_url={quote(foto_url)}&fotos_extra={quote(fotos_extra)}"

    filas = ""
    for op in opciones:
        filas += f"""
        <tr>
            <td>{op['category_name']}</td>
            <td>{op['domain_name']}</td>
            <td><a href="/atributos?category_id={op['category_id']}&domain_id={op['domain_id']}{extras}">
                <button>Elegir esta</button></a></td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }}
            th {{ background: #ffe600; }}
            button {{ padding: 6px 12px; background: #3483fa; color: white; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Elegi la categoria correcta para: "{titulo}"</h1>
        <table>
            <tr><th>Categoria</th><th>Tipo de producto</th><th></th></tr>
            {filas}
        </table>
        <br><a href="/publicar">Volver</a>
    </body>
    </html>
    """
    return HTMLResponse(html)

def render_formulario_publicacion(titulo, category_id, campos_html, foto_url_prefill="", descripcion_prefill="", fotos_extra_prefill=""):
    return f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            input[type=text], select, textarea {{ width: 400px; padding: 6px; }}
            button {{ padding: 8px 16px; font-size: 16px; background: #ffe600; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Completa los datos de: {titulo}</h1>
        <form action="/crear-publicacion" method="post" enctype="multipart/form-data">
            <input type="hidden" name="titulo" value="{titulo}">
            <input type="hidden" name="category_id" value="{category_id}">

            <p><label>Ganancia deseada por unidad (USD):</label><br>
            <input type="text" name="ganancia"></p>

            <p><label>Costo de envio internacional estimado por unidad (USD):</label><br>
            <input type="text" name="envio" value="0"></p>

            <p><label>Cantidad disponible:</label><br>
            <input type="text" name="cantidad"></p>

            <p><label>Paises donde publicar:</label><br>
            <label><input type="checkbox" name="paises" value="MLA" checked> Argentina</label><br>
            <label><input type="checkbox" name="paises" value="MLB" checked> Brasil</label><br>
            <label><input type="checkbox" name="paises" value="MCO" checked> Colombia</label><br>
            <label><input type="checkbox" name="paises" value="MLC" checked> Chile</label></p>

            <p><label>Descripcion:</label><br>
            <textarea name="descripcion" rows="4" style="width:500px;">{descripcion_prefill}</textarea></p>

            <p><label>Foto principal - opcion 1, link directo a una imagen .jpg o .png:</label><br>
            <input type="text" name="foto_url" style="width:500px;" value="{foto_url_prefill}"></p>

            <p><label>Foto principal - opcion 2, subi una imagen desde tu computadora (si elegis un archivo, se usa en vez del link):</label><br>
            <input type="file" name="foto_archivo" accept="image/*"></p>

            <p><label>Fotos adicionales (opcional, una URL por linea):</label><br>
            <textarea name="fotos_extra" rows="4" style="width:500px;">{fotos_extra_prefill}</textarea></p>

            {campos_html}

            <button type="submit">Publicar</button>
        </form>
        <br><a href="/publicar">Volver</a>
    </body>
    </html>
    """


@app.get("/atributos", response_class=HTMLResponse)
def atributos(titulo: str, category_id: str, domain_id: str, descripcion: str = "", foto_url: str = "", fotos_extra: str = ""):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = obtener_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/categories/{category_id}/attributes"
    attrs = requests.get(url, headers=headers).json()

    campos = ""
    for a in attrs:
        tags = a.get("tags", {})
        if not tags.get("required"):
            continue

        nombre = a.get("name", a["id"])
        aid = a["id"]
        value_type = a.get("value_type", "string")

        if value_type == "list" and a.get("values"):
            opciones = "".join(f'<option value="{v["id"]}|{v["name"]}">{v["name"]}</option>' for v in a["values"])
            campos += f"""
            <p><label>{nombre}:</label><br>
            <select name="attr_{aid}">{opciones}</select></p>
            """
        else:
            campos += f"""
            <p><label>{nombre}:</label><br>
            <input type="text" name="attr_{aid}"></p>
            """

    return HTMLResponse(render_formulario_publicacion(titulo, category_id, campos, foto_url, descripcion, fotos_extra))


@app.get("/duplicar", response_class=HTMLResponse)
def duplicar(item_id: str):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = obtener_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    item = requests.get(f"https://api.mercadolibre.com/marketplace/items/{item_id}", headers=headers).json()

    if "id" not in item:
        detalle = item.get("message", "Publicacion no encontrada")
        return HTMLResponse(
            f"<h2>No se pudo leer esa publicacion: {detalle}</h2><a href='/dashboard'>Volver</a>"
        )

    titulo = item.get("title", "")
    category_id = item.get("category_id", "")
    pictures = item.get("pictures", [])
    foto_url_prefill = pictures[0].get("secure_url") or pictures[0].get("url") if pictures else ""

    campos = ""
    for a in item.get("attributes", []):
        aid = a.get("id")
        nombre = a.get("name", aid)
        value_id = a.get("value_id")
        value_name = a.get("value_name")
        if not aid or not value_name:
            continue
        valor = f"{value_id}|{value_name}" if value_id else value_name
        campos += f"""
        <p><label>{nombre}:</label><br>
        <input type="text" name="attr_{aid}" value="{valor}"></p>
        """

    return HTMLResponse(render_formulario_publicacion(titulo, category_id, campos, foto_url_prefill))


@app.get("/editar", response_class=HTMLResponse)
def editar(item_id: str):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = obtener_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}
    item = requests.get(f"https://api.mercadolibre.com/marketplace/items/{item_id}", headers=headers).json()

    if "id" not in item:
        detalle = item.get("message", "Publicacion no encontrada")
        return HTMLResponse(
            f"<h2>No se pudo leer esa publicacion: {detalle}</h2><a href='/dashboard'>Volver</a>"
        )

    titulo = item.get("title", "")
    cbt_id = item.get("id", "")
    marketplace_items = item.get("marketplace_items", [])
    siteless_id = marketplace_items[0]["siteless_user_product_id"] if marketplace_items else ""
    pictures = item.get("pictures", [])
    foto_actual = pictures[0].get("secure_url") or pictures[0].get("url") if pictures else ""

    descripcion_actual = ""
    if marketplace_items:
        site_id = marketplace_items[0]["site_id"]
        desc = requests.get(
            f"https://api.mercadolibre.com/marketplace/items/{cbt_id}/description"
            f"?site_id={site_id}&logistic_type=remote",
            headers=headers,
        ).json()
        descripcion_actual = desc.get("plain_text", "")

    html = f"""
    <html>
    <head>
        <title>Editar publicacion</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            input[type=text], textarea {{ width: 500px; padding: 8px; font-size: 16px; }}
            button {{ padding: 8px 16px; font-size: 16px; background: #ffe600; border: none; cursor: pointer; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Editar publicacion</h1>
        <img src="{foto_actual}" width="120"><br><br>
        <form action="/actualizar-publicacion" method="post" enctype="multipart/form-data">
            <input type="hidden" name="siteless_id" value="{siteless_id}">
            <input type="hidden" name="item_id" value="{item_id}">

            <p><label>Titulo:</label><br>
            <input type="text" name="titulo" value="{titulo}"></p>

            <p><label>Descripcion:</label><br>
            <textarea name="descripcion" rows="5">{descripcion_actual}</textarea></p>

            <p><label>Nueva foto - opcion 1, link directo a una imagen (dejar vacio para no cambiarla):</label><br>
            <input type="text" name="foto_url"></p>

            <p><label>Nueva foto - opcion 2, subi un archivo desde tu computadora:</label><br>
            <input type="file" name="foto_archivo" accept="image/*"></p>

            <button type="submit">Guardar cambios</button>
        </form>
        <br><a href="/dashboard">Volver</a>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.post("/actualizar-publicacion", response_class=HTMLResponse)
async def actualizar_publicacion(request: Request):
    access_token = obtener_access_token()
    if not access_token:
        return HTMLResponse("<h2>No se pudo renovar el token. <a href='/dashboard'>Volver</a></h2>")

    form = await request.form()
    siteless_id = form.get("siteless_id")
    item_id = form.get("item_id")
    titulo = form.get("titulo")
    descripcion = form.get("descripcion")
    foto_url = form.get("foto_url")
    foto_archivo = form.get("foto_archivo")

    headers_json = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    headers_auth = {"Authorization": f"Bearer {access_token}"}

    body = {}
    if titulo:
        body["title"] = titulo
    if descripcion:
        body["description"] = {"plain_text": descripcion}

    contenido_foto = None
    nombre_archivo = "foto.jpg"
    tipo_archivo = "image/jpeg"
    if foto_archivo is not None and getattr(foto_archivo, "filename", ""):
        contenido_foto = await foto_archivo.read()
        nombre_archivo = foto_archivo.filename
        tipo_archivo = foto_archivo.content_type
    elif foto_url:
        descarga = requests.get(foto_url)
        if descarga.status_code == 200:
            contenido_foto = descarga.content

    if contenido_foto:
        files = {"file": (nombre_archivo, contenido_foto, tipo_archivo)}
        pic_response = requests.post(
            "https://api.mercadolibre.com/pictures/items/upload", headers=headers_auth, files=files
        )
        pic_data = pic_response.json()
        if pic_response.status_code in (200, 201) and pic_data.get("id"):
            body["pictures"] = [{"id": pic_data["id"]}]
        else:
            detalle = pic_data.get("message", "No se pudo subir la nueva foto")
            return HTMLResponse(
                f"<h2 style='color:red;'>Error con la foto: {detalle}</h2>"
                f"<a href='/editar?item_id={item_id}'>Volver a intentar</a> | <a href='/dashboard'>Volver al dashboard</a>"
            )

    if not body:
        return RedirectResponse(url="/dashboard?msg=ok")

    url = f"https://api.mercadolibre.com/global/user-products/{siteless_id}"
    response = requests.put(url, headers=headers_json, json=body)

    if response.status_code == 200:
        return RedirectResponse(url="/dashboard?msg=ok")

    resultado = response.json()
    detalle = resultado.get("message") or json.dumps(resultado.get("errors", resultado))
    return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote(str(detalle))}")


@app.post("/crear-publicacion", response_class=HTMLResponse)
async def crear_publicacion(request: Request):
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    form = await request.form()
    SITIOS = form.getlist("paises")
    titulo = form.get("titulo")
    category_id = form.get("category_id")
    ganancia = form.get("ganancia")
    envio = form.get("envio") or "0"
    precios_por_pais = calcular_precios(ganancia, envio, SITIOS)
    cantidad = form.get("cantidad")
    foto_url = form.get("foto_url")
    foto_archivo = form.get("foto_archivo")
    descripcion = form.get("descripcion") or titulo
    fotos_extra = form.get("fotos_extra") or ""

    access_token = obtener_access_token()

    pictures = []
    if foto_archivo is not None and getattr(foto_archivo, "filename", ""):
        contenido = await foto_archivo.read()
        files = {"file": (foto_archivo.filename, contenido, foto_archivo.content_type)}
        pic_headers = {"Authorization": f"Bearer {access_token}"}
        pic_response = requests.post(
            "https://api.mercadolibre.com/pictures/items/upload", headers=pic_headers, files=files
        )
        pic_data = pic_response.json()
        if pic_response.status_code in (200, 201) and pic_data.get("id"):
            pictures = [{"id": pic_data["id"]}]

    if not pictures and foto_url:
        pictures = [{"source": foto_url}]

    for linea in fotos_extra.splitlines():
        linea = linea.strip()
        if linea:
            pictures.append({"source": linea})

    CAMPOS_NUMERICOS = ["PACKAGE_HEIGHT", "PACKAGE_WIDTH", "PACKAGE_LENGTH", "PACKAGE_WEIGHT"]

    attributes = []
    for key, value in form.items():
        if key.startswith("attr_") and value:
            attr_id = key.replace("attr_", "").upper()
            if "|" in value:
                value_id, value_name = value.split("|", 1)
                attributes.append({"id": attr_id, "value_id": value_id, "value_name": value_name})
            else:
                attributes.append({"id": attr_id, "value_name": value})

    if not any(a["id"] == "ITEM_CONDITION" for a in attributes):
        attributes.append({"id": "ITEM_CONDITION", "values": [{"id": "2230284", "name": "New"}]})

    body = {
        "sites_to_sell": [
            {
                "site_id": site,
                "logistic_type": "remote",
                "user_id": USER_IDS_POR_SITIO[site],
                "net_proceeds": float(ganancia),
            }
            for site in SITIOS
        ],
        "title": titulo,
        "description": {"plain_text": descripcion},
        "category_id": category_id,
        "currency_id": "USD",
        "available_quantity": int(cantidad),
        "listing_type_id": "gold_pro",
        "condition": "new",
        "pictures": pictures,
        "attributes": attributes,
        "sale_terms": [
            {"id": "WARRANTY_TYPE", "value_id": "2230280"},
            {"id": "WARRANTY_TIME", "value_name": "30 days"},
        ],
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = requests.post("https://api.mercadolibre.com/global/user-products", headers=headers, json=body)
    resultado = response.json()

    if response.status_code in (200, 201):
        mensaje = f"<h2 style='color:green;'>Publicacion creada con exito!</h2><pre>{json.dumps(resultado, indent=2)}</pre>"
    else:
        mensaje = f"<h2 style='color:red;'>Error al publicar</h2><pre>{json.dumps(resultado, indent=2)}</pre>"

    return HTMLResponse(f"""
    <html><body style="font-family: Arial; margin: 40px;">
    {mensaje}
    <br><a href="/publicar">Publicar otro producto</a> | <a href="/dashboard">Ver dashboard</a>
    </body></html>
    """)

@app.get("/ver-atributos")
def ver_atributos(category_id: str):
    token_data = cargar_token()
    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/categories/{category_id}/attributes"
    return requests.get(url, headers=headers).json()

@app.get("/costo")
def costo(site: str, price: float):
    token_data = cargar_token()
    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/sites/{site}/listing_prices?price={price}"
    return requests.get(url, headers=headers).json()

@app.get("/renovar")
def renovar():
    resultado = renovar_token()
    if resultado:
        return {"mensaje": "Token renovado con exito"}
    return {"error": "No se pudo renovar"}
    SITIOS = form.getlist("paises")

def obtener_comision_pct(site):
    token_data = cargar_token()
    access_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/sites/{site}/listing_prices?price=100"
    data = requests.get(url, headers=headers).json()
    for opcion in data:
        if opcion.get("listing_type_id") == "gold_pro":
            return opcion["sale_fee_details"]["percentage_fee"]
    return 20  # valor de respaldo si no se encuentra


def calcular_precios(ganancia, envio, sitios):
    precios = {}
    for site in sitios:
        pct = obtener_comision_pct(site)
        precio = (float(ganancia) + float(envio)) / (1 - pct / 100)
        precios[site] = round(precio, 2)
    return precios

@app.get("/diagnostico")
def diagnostico():
    token_data = cargar_token()
    access_token = token_data["access_token"]
    user_id = token_data["user_id"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.mercadolibre.com/marketplace/users/{user_id}"
    return requests.get(url, headers=headers).json()

NOTIFICACIONES_FILE = "notificaciones.log"

@app.post("/notificaciones")
async def recibir_notificacion(request: Request):
    data = await request.json()
    print(f"[notificacion ML] {json.dumps(data)}")
    try:
        with open(NOTIFICACIONES_FILE, "a") as f:
            f.write(json.dumps(data) + "\n")
    except Exception:
        pass
    return {"received": True}

@app.get("/notificaciones", response_class=HTMLResponse)
def ver_notificaciones():
    try:
        with open(NOTIFICACIONES_FILE) as f:
            lineas = f.readlines()[-50:]
    except FileNotFoundError:
        lineas = []
    filas = "".join(
        f'<pre style="background:white; padding:10px; border-radius:4px; margin-bottom:8px; overflow-x:auto;">{linea}</pre>'
        for linea in reversed(lineas)
    )
    return HTMLResponse(f"""
    <html>
    <head>
        <title>Notificaciones</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Notificaciones de Mercado Libre</h1>
        {filas or '<p>Sin notificaciones todavia.</p>'}
    </body>
    </html>
    """)

@app.get("/reintentar-paises")
def reintentar_paises(siteless_id: str, ganancia: float, paises: str):
    token_data = cargar_token()
    access_token = token_data["access_token"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    lista_paises = paises.split(",")
    body = {
        "sites_to_sell": [
            {
                "site_id": site,
                "logistic_type": "remote",
                "user_id": USER_IDS_POR_SITIO[site],
                "net_proceeds": ganancia,
            }
            for site in lista_paises
        ]
    }

    url = f"https://api.mercadolibre.com/global/user-products/{siteless_id}"
    response = requests.put(url, headers=headers, json=body)
    return response.json()

@app.get("/cambiar-estado")
def cambiar_estado(siteless_id: str, nuevo_estado: str):
    access_token = obtener_access_token()
    if not access_token:
        return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote('No se pudo renovar el token')}")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://api.mercadolibre.com/global/user-products/{siteless_id}"
    body = {"status": nuevo_estado}
    response = requests.put(url, headers=headers, json=body)

    if response.status_code == 200:
        detalle = quote("Mercado Libre acepto el pedido. Puede tardar en reflejarse por pais.")
        return RedirectResponse(url=f"/dashboard?msg=ok&detalle={detalle}")

    detalle = response.json().get("message", f"HTTP {response.status_code}")
    return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote(detalle)}")


@app.get("/cambiar-stock")
def cambiar_stock(siteless_id: str, nueva_cantidad: int):
    access_token = obtener_access_token()
    if not access_token:
        return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote('No se pudo renovar el token')}")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://api.mercadolibre.com/global/user-products/{siteless_id}"
    body = {"available_quantity": nueva_cantidad}
    response = requests.put(url, headers=headers, json=body)

    if response.status_code == 200:
        return RedirectResponse(url="/dashboard?msg=ok")

    detalle = response.json().get("message", f"HTTP {response.status_code}")
    return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote(detalle)}")


@app.get("/cambiar-precio")
def cambiar_precio(siteless_id: str, nueva_ganancia: float, sites: str):
    access_token = obtener_access_token()
    if not access_token:
        return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote('No se pudo renovar el token')}")

    lista_sites = [s for s in sites.split(",") if s in USER_IDS_POR_SITIO]
    if not lista_sites:
        detalle = "No se pudo determinar en que paises esta publicado (proba de nuevo en unos minutos)"
        return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote(detalle)}")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://api.mercadolibre.com/global/user-products/{siteless_id}"
    body = {
        "sites_to_sell": [
            {
                "site_id": site,
                "logistic_type": "remote",
                "user_id": USER_IDS_POR_SITIO[site],
                "net_proceeds": nueva_ganancia,
            }
            for site in lista_sites
        ]
    }
    response = requests.put(url, headers=headers, json=body)

    if response.status_code == 200:
        return RedirectResponse(url="/dashboard?msg=ok")

    detalle = response.json().get("message", f"HTTP {response.status_code}")
    return RedirectResponse(url=f"/dashboard?msg=error&detalle={quote(detalle)}")


@app.get("/ventas", response_class=HTMLResponse)
def ventas():
    token_data = cargar_token()
    if not token_data:
        return HTMLResponse("<h2>No hay token guardado. <a href='/'>Conectate primero</a></h2>")

    access_token = obtener_access_token()
    if not access_token:
        return HTMLResponse("<h2>No se pudo renovar el token. <a href='/'>Conectate de nuevo</a></h2>")

    user_id = token_data["user_id"]
    headers = {"Authorization": f"Bearer {access_token}"}

    url = f"https://api.mercadolibre.com/marketplace/orders/search?seller={user_id}"
    data = requests.get(url, headers=headers).json()
    resultados = data.get("results", [])

    ESTADOS_ES = {
        "pending": "Pendiente",
        "ready_to_ship": "Listo para enviar",
        "shipped": "Enviado",
        "delivered": "Entregado",
        "not_delivered": "No entregado",
        "cancelled": "Cancelado",
    }
    ESTADOS_IMPRIMIBLES = {"pending", "ready_to_ship", "handling"}

    filas = ""
    for orden in resultados:
        item_id = orden.get("config", {}).get("items", [{}])[0].get("id", "")
        buyer_id = orden.get("buyer", {}).get("id", "")
        shipment_id = orden.get("shipment", {}).get("id")

        item = requests.get(f"https://api.mercadolibre.com/marketplace/items/{item_id}", headers=headers).json()
        titulo = item.get("title", "Sin titulo")
        foto = item.get("thumbnail", "")

        estado_raw, tracking = "", ""
        if shipment_id:
            envio = requests.get(f"https://api.mercadolibre.com/marketplace/shipments/{shipment_id}", headers=headers).json()
            estado_raw = envio.get("status", "")
            tracking = envio.get("tracking_number") or ""

        comprador = ""
        if buyer_id:
            u = requests.get(f"https://api.mercadolibre.com/users/{buyer_id}", headers=headers).json()
            comprador = u.get("nickname", "")

        estado = ESTADOS_ES.get(estado_raw, estado_raw or "-")
        boton_etiqueta = (
            f'<a href="/etiqueta?shipment_id={shipment_id}"><button>Imprimir etiqueta</button></a>'
            if shipment_id and estado_raw in ESTADOS_IMPRIMIBLES
            else "-"
        )

        filas += f"""
        <tr>
            <td><img src="{foto}" width="50"></td>
            <td>{titulo}</td>
            <td>{comprador}</td>
            <td>{estado}</td>
            <td>{tracking}</td>
            <td>{boton_etiqueta}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>Ventas - Global Selling</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            h1 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #ddd; text-align: left; }}
            th {{ background: #ffe600; }}
        </style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Ventas - Global Selling</h1>
        <table>
            <tr>
                <th>Foto</th>
                <th>Producto</th>
                <th>Comprador</th>
                <th>Estado envio</th>
                <th>Tracking</th>
                <th>Etiqueta</th>
            </tr>
            {filas if filas else '<tr><td colspan="6">Todavia no tenes ventas.</td></tr>'}
        </table>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/etiqueta")
def etiqueta(shipment_id: str):
    access_token = obtener_access_token()
    if not access_token:
        return HTMLResponse("<h2>No se pudo renovar el token. <a href='/ventas'>Volver</a></h2>")

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/pdf"}
    url = f"https://api.mercadolibre.com/marketplace/shipments/{shipment_id}/labels"
    response = requests.get(url, headers=headers)

    if response.status_code == 200 and "pdf" in response.headers.get("Content-Type", ""):
        return Response(
            content=response.content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=etiqueta-{shipment_id}.pdf"},
        )

    try:
        detalle = response.json().get("message", f"HTTP {response.status_code}")
    except ValueError:
        detalle = f"HTTP {response.status_code}"

    return HTMLResponse(
        f"<h2 style='color:red;'>No se pudo generar la etiqueta: {detalle}</h2><a href='/ventas'>Volver</a>"
    )