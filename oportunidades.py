"""
Módulo "Oportunidades" del dashboard de Mercado Libre Global Selling.
Rutas: GET /oportunidades (vista) · POST /api/oportunidades/analizar · GET /api/oportunidades/tendencias
"""
import os
import re
import statistics

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

API = "https://api.mercadolibre.com"

# País de cada sitio, para detectar vendedores del exterior (CBT)
PAIS_DEL_SITIO = {
    "MLA": "AR", "MLB": "BR", "MLC": "CL", "MCO": "CO", "MLM": "MX",
    "MLU": "UY", "MPE": "PE", "MEC": "EC", "MLV": "VE",
}


# ----------------------------------------------------------------- token
# main.py inyecta sus funciones con registrar(); así se reutiliza el mismo token y renovación.
_obtener_token = lambda: None
_renovar = lambda: None
_nav_html = ""


def _get(path, params=None):
    """GET autenticado con un reintento si el token venció. Devuelve (status, json|None)."""
    for intento in range(2):
        tok = _obtener_token() or ""
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        try:
            r = requests.get(f"{API}{path}", params=params, headers=headers, timeout=25)
        except Exception as e:
            return 0, {"error": str(e)}
        if r.status_code == 401 and intento == 0 and _renovar():
            continue
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None
    return 0, None


def registrar(app, obtener_token, renovar_token, nav_html=""):
    """Se llama una vez desde main.py."""
    global _obtener_token, _renovar, _nav_html
    _obtener_token, _renovar, _nav_html = obtener_token, renovar_token, nav_html
    app.include_router(router)


# ----------------------------------------------------------------- cálculos
def parsear_vendidos(valor):
    """sold_quantity puede ser un número, o un rango tipo 'RANGO_6_255' / '50-99'.
    Devuelve (cantidad_estimada, es_rango)."""
    if valor is None:
        return None, False
    if isinstance(valor, (int, float)):
        return int(valor), False
    if isinstance(valor, str):
        nums = [int(n) for n in re.findall(r"\d+", valor)]
        if len(nums) >= 2:
            return nums[0], True          # cota inferior (conservador)
        if len(nums) == 1:
            return nums[0], True
    return None, False


def nivel_demanda(total):
    if total is None:
        return "Sin datos"
    if total >= 1000:
        return "Alta"
    if total >= 100:
        return "Media"
    return "Baja"


def es_internacional(item, pais_sitio):
    """Heurística: CBT / vendedor del exterior. La API no siempre marca esto de forma uniforme."""
    modo = item.get("international_delivery_mode")
    if modo and str(modo).lower() not in ("none", ""):
        return True
    tags = [str(t).lower() for t in (item.get("tags") or [])]
    envio = item.get("shipping") or {}
    tags += [str(t).lower() for t in (envio.get("tags") or [])]
    if any("cbt" in t or "international" in t or "global" in t for t in tags):
        return True
    sel = item.get("seller") or {}
    stags = [str(t).lower() for t in (sel.get("seller_reputation", {}).get("tags") or [])]
    if any("cbt" in t for t in stags):
        return True
    pais_vend = ((item.get("seller_address") or {}).get("country") or {}).get("id")
    if pais_vend and pais_sitio and pais_vend != pais_sitio:
        return True
    return False


def analizar_resultados(items, site):
    precios, vendedores, cbt_vend, vendidos_tot, hay_vendidos, hay_rango = [], set(), set(), 0, False, False
    moneda = ""
    pais = PAIS_DEL_SITIO.get(site, "")
    for it in items:
        p = it.get("price")
        if isinstance(p, (int, float)) and p > 0:
            precios.append(float(p))
        moneda = moneda or it.get("currency_id", "")
        sid = (it.get("seller") or {}).get("id")
        if sid is not None:
            vendedores.add(sid)
            if es_internacional(it, pais):
                cbt_vend.add(sid)
        v, rango = parsear_vendidos(it.get("sold_quantity"))
        if v is not None:
            hay_vendidos = True
            hay_rango = hay_rango or rango
            vendidos_tot += v
    total = vendidos_tot if hay_vendidos else None
    return {
        "publicaciones": len(items),
        "moneda": moneda,
        "precio_min": min(precios) if precios else None,
        "precio_mediana": statistics.median(precios) if precios else None,
        "precio_max": max(precios) if precios else None,
        "vendedores": len(vendedores),
        "vendedores_cbt": len(cbt_vend),
        "vendidos": total,
        "vendidos_aprox": hay_rango,
        "demanda": nivel_demanda(total),
    }


def calcular_margen(precio, costo_usa, fx, comision_pct, envio_cbt_usd, impuestos_pct, florida_pct):
    """Margen neto en % sobre el precio de venta (todo en USD).
    neto = precio*(1 - comisión - impuestos) - envío CBT - costo*(1 + impuesto Florida)
    """
    if not precio or not fx or costo_usa is None:
        return None
    p = precio / fx
    neto = p * (1 - comision_pct / 100 - impuestos_pct / 100) - envio_cbt_usd - costo_usa * (1 + florida_pct / 100)
    return neto / p * 100


# ----------------------------------------------------------------- API
@router.post("/api/oportunidades/analizar")
async def analizar(request: Request):
    cuerpo = await request.json()
    site = (cuerpo.get("site") or "MLC").upper().strip()
    claves = [k.strip() for k in (cuerpo.get("keywords") or []) if k and k.strip()][:25]
    filas = []
    for k in claves:
        status, data = _get(f"/sites/{site}/search", {"q": k, "limit": 50})
        if status != 200 or not isinstance(data, dict):
            msg = f"HTTP {status}"
            if isinstance(data, dict):
                msg += " - " + str(data.get("message") or data.get("error") or "")[:160]
            filas.append({"keyword": k, "error": msg})
            continue
        fila = analizar_resultados(data.get("results", []), site)
        fila["keyword"] = k
        fila["total_resultados"] = (data.get("paging") or {}).get("total")
        filas.append(fila)
    return JSONResponse({"site": site, "filas": filas})


@router.get("/api/oportunidades/tendencias")
async def tendencias(site: str = "MLC"):
    site = site.upper().strip()
    status, data = _get(f"/trends/{site}")
    if status != 200 or not isinstance(data, list):
        msg = f"HTTP {status}"
        if isinstance(data, dict):
            msg += " - " + str(data.get("message") or data.get("error") or "")[:160]
        return JSONResponse({"site": site, "error": msg, "tendencias": []})
    return JSONResponse({"site": site, "tendencias": data[:50]})


# ----------------------------------------------------------------- vista
PAGINA = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oportunidades</title>
<style>
 body{font-family:system-ui,sans-serif;margin:0;padding:40px;background:#f4f5f7;color:#222}
 main{max-width:1300px;margin:auto}
 .card{background:#fff;border-radius:10px;padding:14px;margin-bottom:14px;box-shadow:0 1px 3px #0002}
 textarea,input,select{font:inherit;padding:8px;border:1px solid #bbb;border-radius:6px;box-sizing:border-box}
 textarea{width:100%;min-height:90px}
 button{font:inherit;padding:9px 14px;border:0;border-radius:6px;background:#3483fa;color:#fff;cursor:pointer;margin:4px 4px 0 0}
 button.sec{background:#555}
 .params{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
 .params label{font-size:13px;display:block}
 .params input{width:100%}
 .scroll{overflow-x:auto}
 table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}
 th,td{padding:7px 9px;border-bottom:1px solid #e3e3e3;text-align:right;white-space:nowrap}
 th{background:#eee;cursor:pointer;position:sticky;top:0}
 th:first-child,td:first-child{text-align:left}
 tr.rojo td{background:#ffd6d6;color:#8a0000}
 td input{width:90px;text-align:right}
 .err{color:#b00020}
 .nota{font-size:12px;color:#666}
 ol{margin:6px 0 0 18px;padding:0;columns:2}
 @media(max-width:600px){ol{columns:1}}
</style></head><body>
@@NAV@@
<main>
<div class="card">
 <b>Palabras clave</b> <span class="nota">(una por línea)</span>
 <textarea id="kw" placeholder="ssd samsung 1tb&#10;mouse logitech mx master"></textarea>
 <div style="margin-top:8px">Sitio:
  <select id="site"><option>MLC</option><option>MLA</option><option>MCO</option><option>MLB</option><option>MLM</option></select>
  <button onclick="analizar()">Analizar</button>
  <button class="sec" onclick="tendencias()">Ver tendencias</button>
  <button class="sec" onclick="csv()">Exportar CSV</button>
 </div>
 <div id="estado" class="nota"></div>
</div>

<div class="card">
 <b>Parámetros de margen</b> <span class="nota">(se guardan en este navegador)</span>
 <div class="params">
  <label>Comisión ML %<input id="p_com" type="number" step="0.1" value="13"></label>
  <label>Envío CBT (USD)<input id="p_env" type="number" step="0.1" value="15"></label>
  <label>Impuestos %<input id="p_imp" type="number" step="0.1" value="19"></label>
  <label>Impuesto Florida %<input id="p_fl" type="number" step="0.1" value="7"></label>
  <label>Tipo de cambio (moneda local por USD)<input id="p_fx" type="number" step="0.01" value="950"></label>
  <label>Margen mínimo % (rojo si menor)<input id="p_min" type="number" step="1" value="20"></label>
 </div>
 <div class="nota">Margen = precio mediano (en USD) × (1 − comisión − impuestos) − envío CBT − costo EE.UU. × (1 + imp. Florida), dividido por el precio mediano. Cargá el costo en EE.UU. en USD.</div>
</div>

<div class="card scroll">
 <table id="tabla"><thead><tr id="cab"></tr></thead><tbody id="cuerpo"></tbody></table>
</div>

<div class="card" id="tend" style="display:none"><b>Tendencias del sitio</b><ol id="tendlista"></ol></div>
</main>
<script>
const COLS=[["keyword","Palabra clave"],["publicaciones","Publ."],["precio_min","Mín"],["precio_mediana","Mediana"],["precio_max","Máx"],
 ["vendedores","Vendedores"],["vendedores_cbt","CBT"],["vendidos","Vendidos"],["demanda","Demanda"],["costo","Costo EE.UU. (USD)"],["margen","Margen %"]];
let filas=[], orden={k:null,asc:true};
const $=id=>document.getElementById(id);
const P=["p_com","p_env","p_imp","p_fl","p_fx","p_min"];
try{P.forEach(i=>{const v=localStorage.getItem(i);if(v!==null)$(i).value=v;});
 const s=localStorage.getItem("op_site"); if(s)$("site").value=s;
 const k=localStorage.getItem("op_kw"); if(k)$("kw").value=k;
 filas=JSON.parse(localStorage.getItem("op_filas")||"[]");}catch(e){}
P.forEach(i=>$(i).addEventListener("input",()=>{try{localStorage.setItem(i,$(i).value)}catch(e){};recalc();}));

function num(i){return parseFloat($(i).value)||0}
function margen(f){
 if(f.costo===undefined||f.costo===""||f.costo===null||!f.precio_mediana) return null;
 const fx=num("p_fx"); if(!fx) return null;
 const p=f.precio_mediana/fx;
 const neto=p*(1-num("p_com")/100-num("p_imp")/100)-num("p_env")-parseFloat(f.costo)*(1+num("p_fl")/100);
 return neto/p*100;
}
function fmt(n){return n==null?"–":Number(n).toLocaleString("es-AR",{maximumFractionDigits:2})}
function guardar(){try{localStorage.setItem("op_filas",JSON.stringify(filas));localStorage.setItem("op_kw",$("kw").value);localStorage.setItem("op_site",$("site").value)}catch(e){}}

function dibujar(){
 $("cab").innerHTML=COLS.map(c=>`<th onclick="ordenar('${c[0]}')">${c[1]}${orden.k===c[0]?(orden.asc?" ▲":" ▼"):""}</th>`).join("");
 let vista=filas.map((f,i)=>({f,i,m:margen(f)}));
 if(orden.k){vista.sort((a,b)=>{
   const g=x=>orden.k==="margen"?x.m:x.f[orden.k];
   let va=g(a),vb=g(b); if(va==null)va=-Infinity; if(vb==null)vb=-Infinity;
   if(typeof va==="string"||typeof vb==="string")return String(va).localeCompare(String(vb))*(orden.asc?1:-1);
   return (va-vb)*(orden.asc?1:-1);});}
 const min=num("p_min");
 $("cuerpo").innerHTML=vista.map(({f,i,m})=>{
  if(f.error) return `<tr><td>${esc(f.keyword)}</td><td colspan="10" class="err" style="text-align:left">Error: ${esc(f.error)}</td></tr>`;
  const rojo=(m!=null&&m<min)?' class="rojo"':'';
  const vend=f.vendidos==null?"sin dato":((f.vendidosAprox||f.vendidos_aprox)?"≥ ":"")+fmt(f.vendidos);
  return `<tr${rojo}><td>${esc(f.keyword)}</td><td>${f.publicaciones}</td><td>${fmt(f.precio_min)}</td><td>${fmt(f.precio_mediana)}</td><td>${fmt(f.precio_max)}</td>
  <td>${f.vendedores}</td><td>${f.vendedores_cbt}</td><td>${vend}</td><td>${f.demanda}</td>
  <td><input type="number" step="0.01" value="${f.costo??""}" onchange="setCosto(${i},this.value)"></td><td id="m${i}">${m==null?"–":m.toFixed(1)+"%"}</td></tr>`;
 }).join("");
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function ordenar(k){orden.asc=(orden.k===k)?!orden.asc:true;orden.k=k;dibujar()}
function setCosto(i,v){filas[i].costo=v===""?"":parseFloat(v);guardar();dibujar()}
function recalc(){dibujar()}

async function analizar(){
 const kws=$("kw").value.split("\n").map(s=>s.trim()).filter(Boolean);
 if(!kws.length){$("estado").textContent="Escribí al menos una palabra clave.";return}
 $("estado").textContent="Analizando "+kws.length+" palabra(s)… puede tardar unos segundos.";
 const costos={};filas.forEach(f=>{if(f.costo!==undefined&&f.costo!=="")costos[f.keyword]=f.costo});
 try{
  const r=await fetch("/api/oportunidades/analizar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({keywords:kws,site:$("site").value})});
  const d=await r.json();
  filas=d.filas.map(f=>({...f,costo:costos[f.keyword]??""}));
  const monedas=[...new Set(filas.map(f=>f.moneda).filter(Boolean))];
  $("estado").textContent="Listo. Moneda de precios: "+(monedas.join(", ")||"?")+". Ajustá el tipo de cambio según esa moneda.";
  guardar();dibujar();
 }catch(e){$("estado").textContent="Error: "+e}
}
async function tendencias(){
 const r=await fetch("/api/oportunidades/tendencias?site="+$("site").value);const d=await r.json();
 $("tend").style.display="block";
 $("tendlista").innerHTML=d.error?`<li class="err">No se pudieron traer las tendencias (${esc(d.error)})</li>`
  :d.tendencias.map(t=>`<li><a href="#" onclick="usar('${esc(t.keyword).replace(/'/g,"")}');return false">${esc(t.keyword)}</a></li>`).join("");
}
function usar(k){$("kw").value=($("kw").value.trim()+"\n"+k).trim();guardar()}
function csv(){
 const cab=COLS.map(c=>c[1]);
 const lin=filas.filter(f=>!f.error).map(f=>{const m=margen(f);return [f.keyword,f.publicaciones,f.precio_min,f.precio_mediana,f.precio_max,f.vendedores,f.vendedores_cbt,f.vendidos??"",f.demanda,f.costo??"",m==null?"":m.toFixed(1)]});
 const t=[cab,...lin].map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(";")).join("\r\n");
 const a=document.createElement("a");a.href=URL.createObjectURL(new Blob(["﻿"+t],{type:"text/csv;charset=utf-8"}));
 a.download="oportunidades.csv";a.click();
}
dibujar();
</script></body></html>"""


@router.get("/oportunidades", response_class=HTMLResponse)
async def vista_oportunidades():
    return HTMLResponse(PAGINA.replace("@@NAV@@", _nav_html))
