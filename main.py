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
def dashboard(msg: str = None, detalle: str = None):
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
        banner = '<div style="background:#e6f4ea;color:#2e7d32;padding:12px;border-radius:4px;margin-bottom:16px;">Cambio aplicado con exito.</div>'
    elif msg == "error":
        detalle_txt = detalle or "Error desconocido"
        banner = f'<div style="background:#fdecea;color:#c62828;padding:12px;border-radius:4px;margin-bottom:16px;">Error al aplicar el cambio: {detalle_txt}</div>'

    url_lista = f"https://api.mercadolibre.com/marketplace/users/{user_id}/items/search"
    lista = requests.get(url_lista, headers=headers).json()
    ids = lista.get("results", [])

    filas = ""
    for item_id in ids:
        url_item = f"https://api.mercadolibre.com/marketplace/items/{item_id}"
        item = requests.get(url_item, headers=headers).json()

        titulo = item.get("title", "Sin titulo")
        precio = item.get("price", "-")
        ganancia_actual = precio if isinstance(precio, (int, float)) else ""
        stock = item.get("available_quantity", "-")
        estado = item.get("status", "-")
        foto = item.get("thumbnail", "")
        marketplace_items = item.get("marketplace_items", [])
        sites_ids = sorted(set(m["site_id"] for m in marketplace_items))
        paises = ", ".join(sites_ids)
        sites_csv = ",".join(sites_ids)
        siteless_id = marketplace_items[0]["siteless_user_product_id"] if marketplace_items else ""

        color_estado = "#2e7d32" if estado == "active" else "#f9a825"
        texto_estado = "Activa" if estado == "active" else "Pausada"

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
        {banner}
        <table>
            <tr>
                <th>Foto</th>
                <th>Producto</th>
                <th>Ganancia (USD)</th>
                <th>Stock</th>
                <th>Estado</th>
                <th>Paises</th>
                <th>Acciones</th>
            </tr>
            {filas}
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
        return RedirectResponse(url="/dashboard?msg=ok")

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