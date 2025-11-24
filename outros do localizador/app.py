import streamlit as st
import pandas as pd
import requests
import io
import folium
from streamlit_folium import st_folium
from math import radians, sin, cos, atan2, sqrt

st.set_page_config(page_title="Localizador de Técnicos", layout="wide")
API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]

def carregar_planilha(path="tecnicos.xlsx"):
    try:
        df = pd.read_excel(path)
        expected = ['tecnico','cidade','uf','latitude','longitude','endereco','numero','cep','coordenador','email_coordenador']
        for c in expected:
            if c not in df.columns:
                df[c] = pd.NA
        return df
    except Exception:
        return pd.DataFrame(columns=['tecnico','cidade','uf','latitude','longitude','endereco','numero','cep','coordenador','email_coordenador'])

@st.cache_data
def carregar_tecnicos_cache():
    return carregar_planilha()

def geocode_google(address):
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": API_KEY, "language": "pt-BR"}
        r = requests.get(url, params=params, timeout=15)
        j = r.json()
        if j.get("status") == "OK":
            loc = j["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"])
    except Exception:
        pass
    return None, None

def distance_matrix_km(orig, dest):
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {"origins": orig, "destinations": dest, "key": API_KEY, "mode": "driving", "language": "pt-BR"}
        r = requests.get(url, params=params, timeout=30)
        j = r.json()
        if j.get("status") == "OK":
            elem = j["rows"][0]["elements"][0]
            if elem.get("status") == "OK":
                km = elem["distance"]["value"] / 1000.0
                minutes = elem["duration"]["value"] / 60.0
                return round(km, 3), round(minutes, 1)
    except Exception:
        pass
    return None, None

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2.0)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2.0)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def validar_coord(lat, lon):
    try:
        lat = float(lat); lon = float(lon)
        if -35 <= lat <= 6 and -82 <= lon <= -34:
            return True
    except Exception:
        pass
    return False

df_tecnicos = carregar_tecnicos_cache()

st.markdown("<h1 style='text-align:center;'>🔎 Localizador de Técnicos</h1>", unsafe_allow_html=True)
col_left, col_right = st.columns([2,1])
with col_left:
    endereco_origem = st.text_input("Endereço / CEP / Cidade (origem)", help="Ex: Av. Paulista, 1000, São Paulo, SP ou 01310-100")
    raio = st.selectbox("Raio (km)", [10,20,30,50,100,200], index=2)
    buscar = st.button("Buscar técnicos")
with col_right:
    st.write("")
    st.write("")
    st.write("")
    st.markdown("**Opções**")
    if st.button("Detectar e corrigir coords inválidas"):
        corrigidos = 0
        for idx, row in df_tecnicos.iterrows():
            lat = row.get("latitude"); lon = row.get("longitude")
            if not validar_coord(lat, lon):
                query_parts = []
                if pd.notna(row.get("endereco")): query_parts.append(str(row.get("endereco")))
                if pd.notna(row.get("numero")): query_parts.append(str(row.get("numero")))
                if pd.notna(row.get("cidade")): query_parts.append(str(row.get("cidade")))
                if pd.notna(row.get("uf")): query_parts.append(str(row.get("uf")))
                q = ", ".join([p for p in query_parts if p])
                if not q:
                    q = str(row.get("tecnico", ""))
                latlng = geocode_google(q)
                if latlng[0] is not None:
                    df_tecnicos.at[idx, "latitude"] = latlng[0]
                    df_tecnicos.at[idx, "longitude"] = latlng[1]
                    corrigidos += 1
        if corrigidos:
            st.success(f"{corrigidos} coordenadas corrigidas na memória. Faça download para salvar.")
        else:
            st.info("Nenhuma coordenada corrigida automaticamente.")
    st.markdown("---")
    if st.button("Baixar planilha atualizada"):
        buf = io.BytesIO()
        df_tecnicos.to_excel(buf, index=False)
        buf.seek(0)
        st.download_button("Download tecnicos_atualizado.xlsx", data=buf, file_name="tecnicos_atualizado.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

if buscar:
    if not endereco_origem or str(endereco_origem).strip() == "":
        st.warning("Digite um endereço de origem válido.")
    else:
        origem_lat, origem_lon = geocode_google(endereco_origem)
        if origem_lat is None:
            st.error("Não foi possível geocodificar o endereço de origem. Verifique e tente novamente.")
        else:
            df_validos = df_tecnicos.copy()
            df_validos["latitude"] = pd.to_numeric(df_validos["latitude"], errors="coerce")
            df_validos["longitude"] = pd.to_numeric(df_validos["longitude"], errors="coerce")
            df_validos = df_validos.dropna(subset=["latitude","longitude"]).reset_index(drop=True)
            if df_validos.empty:
                st.error("Nenhum técnico com coordenadas válidas encontrado na planilha.")
            else:
                candidatos = []
                for _, row in df_validos.iterrows():
                    lat = float(row["latitude"]); lon = float(row["longitude"])
                    geo_dist = haversine_km(origem_lat, origem_lon, lat, lon)
                    if geo_dist <= raio * 1.2:
                        candidatos.append((row, geo_dist))
                if not candidatos:
                    st.warning("Nenhum técnico próximo encontrado pelo pré-filtro geodésico.")
                else:
                    destinos = []
                    for r, _ in candidatos:
                        destinos.append(f"{r['latitude']},{r['longitude']}")
                    dist_confirm = []
                    batch_size = 25
                    for i in range(0, len(destinos), batch_size):
                        batch = destinos[i:i+batch_size]
                        origem_str = f"{origem_lat},{origem_lon}"
                        dest_str = "|".join(batch)
                        try:
                            url = "https://maps.googleapis.com/maps/api/distancematrix/json"
                            params = {"origins": origem_str, "destinations": dest_str, "mode":"driving", "language":"pt-BR", "key":API_KEY}
                            resp = requests.get(url, params=params, timeout=30).json()
                            if resp.get("status") == "OK":
                                elements = resp["rows"][0]["elements"]
                                for el in elements:
                                    if el.get("status") == "OK":
                                        km = el["distance"]["value"] / 1000.0
                                        minutes = el["duration"]["value"] / 60.0
                                        dist_confirm.append((km, minutes))
                                    else:
                                        dist_confirm.append((None,None))
                            else:
                                dist_confirm.extend([(None,None)]*len(batch))
                        except Exception:
                            dist_confirm.extend([(None,None)]*len(batch))
                    resultados = []
                    for (row, geo_d), dc in zip(candidatos, dist_confirm):
                        km, minutes = dc
                        if km is None:
                            continue
                        if km <= raio:
                            custo = round(km * 1.0, 2)
                            resultados.append({
                                "tecnico": row["tecnico"],
                                "cidade": row["cidade"],
                                "uf": row["uf"],
                                "coordenador": row.get("coordenador",""),
                                "distancia_km": round(km,2),
                                "tempo_min": int(round(minutes)),
                                "custo": custo,
                                "lat": float(row["latitude"]),
                                "lon": float(row["longitude"]),
                                "endereco": row.get("endereco","")
                            })
                    if not resultados:
                        st.info("Nenhum técnico dentro do raio selecionado após confirmação por rota.")
                    else:
                        resultados = sorted(resultados, key=lambda x: x["distancia_km"])
                        mapa = folium.Map(location=[origem_lat, origem_lon], zoom_start=8)
                        folium.Marker([origem_lat, origem_lon], popup="Origem", icon=folium.Icon(color="green")).add_to(mapa)
                        for r in resultados:
                            folium.Marker([r["lat"], r["lon"]], popup=f"{r['tecnico']} ({r['distancia_km']} km)", icon=folium.Icon(color="blue")).add_to(mapa)
                        st.subheader("Mapa (origem + técnicos)")
                        st_folium(mapa, width=900, height=450)
                        st.subheader(f"Técnicos encontrados (até {raio} km) - {len(resultados)}")
                        for r in resultados:
                            st.markdown(f"""
                            <div style="border:1px solid #ddd;padding:12px;border-radius:8px;margin-bottom:10px;background:#ffffff">
                                <div style="font-size:16px;font-weight:700">{r['tecnico']}</div>
                                <div style="color:#555">{r['cidade']} / {r['uf']}</div>
                                <div style="margin-top:6px">Coordenador: {r['coordenador']}</div>
                                <div style="margin-top:6px">Distância: <b>{r['distancia_km']} km</b></div>
                                <div>Tempo estimado: <b>{r['tempo_min']} min</b></div>
                                <div>Custo deslocamento: <b>R$ {r['custo']:.2f}</b></div>
                            </div>
                            """, unsafe_allow_html=True)
                        buf = io.BytesIO()
                        df_export = pd.DataFrame(resultados)
                        df_export.to_excel(buf, index=False)
                        buf.seek(0)
                        st.download_button("Baixar resultados (Excel)", data=buf, file_name=f"tecnicos_{raio}km.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.markdown("<hr><div style='text-align:center'>Desenvolvido - Localizador de Técnicos</div>", unsafe_allow_html=True)
