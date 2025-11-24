 # teste.py
import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
import io
import plotly.express as px
import pydeck as pdk
import math
from typing import Tuple, List

# ----------------- CONFIG INICIAL -----------------
st.set_page_config(page_title="Localizador de Técnicos", layout="wide")
# Injeção CSS
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    h1, h2, h3 { text-align: center; }
    @media (max-width: 600px) {
        .st-emotion-cache-18ni7ap { flex-direction: column; }
        .st-emotion-cache-18ni7ap > div { width: 100% !important; }
    }
    .button-group a {
        display: inline-block;
        padding: 8px 15px;
        color: white;
        text-align: center;
        text-decoration: none;
        border-radius: 5px;
        font-size: 14px;
        margin-right: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- FUNÇÕES UTILITÁRIAS -----------------
def is_coord_valid_for_brazil(lat, lon):
    """Valida se coordenada parece estar no Brasil (faixa aproximada)."""
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return False
    # Brasil: lat entre ~ -35 e +6 ; lon entre ~ -82 e -34
    if lat < -35 or lat > 6:
        return False
    if lon < -82 or lon > -34:
        return False
    return True

def get_distance_matrix(origins: List[str], destinations: List[str], api_key: str):
    """Obtém a matriz de distância de carro do Google Maps."""
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": "|".join(origins),
        "destinations": "|".join(destinations),
        "key": api_key,
        "mode": "driving",
        "language": "pt-BR",
    }
    response = requests.get(url, params=params, timeout=30)
    data = response.json()
    return data

def geocodificar_endereco(endereco: str, api_key: str) -> Tuple:
    """Converte um endereço em coordenadas (latitude, longitude) via Google Geocode API."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": endereco, "key": api_key}
    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        if data.get("status") == "OK" and len(data.get("results", [])) > 0:
            loc = data["results"][0]["geometry"]["location"]
            return loc.get("lat"), loc.get("lng"), data["results"][0].get("formatted_address")
        else:
            return None, None, None
    except requests.exceptions.RequestException:
        return None, None, None

@st.cache_data
def load_data(file_path: str, sheet_name: str = 0):
    """Carrega os dados do arquivo Excel e faz cache."""
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        return df
    except FileNotFoundError:
        st.error(f"Erro: O arquivo '{file_path}' não foi encontrado. Coloque-o na mesma pasta do script.")
        st.stop()
    except Exception as e:
        st.error(f"Erro ao ler planilha: {e}")
        st.stop()

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ----------------- FUNÇÕES EXISTENTES (BUSCA POR DISTÂNCIA) -----------------
def encontrar_tecnico_proximo(endereco_cliente, api_key, df_filtrado, limite_km=200):
    """Encontra técnicos próximos a um endereço usando Geocode + Distance Matrix (limite em km)."""
    df_filtrado['latitude'] = pd.to_numeric(df_filtrado['latitude'], errors='coerce')
    df_filtrado['longitude'] = pd.to_numeric(df_filtrado['longitude'], errors='coerce')
    df_validos = df_filtrado.dropna(subset=['latitude', 'longitude']).copy()
    
    if df_validos.empty:
        st.info("Nenhum técnico com coordenadas válidas foi encontrado para a sua busca.")
        return None, None

    latc, lonc, formatted = geocodificar_endereco(endereco_cliente, api_key)
    if latc is None or lonc is None:
        st.error("Não foi possível geocodificar o endereço do cliente. Verifique o texto do endereço.")
        return None, None

    origem = f"{latc},{lonc}"
    distancias_finais = []
    destinos_por_lote = 25
    for i in range(0, len(df_validos), destinos_por_lote):
        lote_df = df_validos.iloc[i : i + destinos_por_lote]
        destinos = [f"{lat},{lon}" for lat, lon in zip(lote_df['latitude'], lote_df['longitude'])]
        try:
            matrix_data = get_distance_matrix([origem], destinos, api_key)
        except requests.exceptions.RequestException:
            st.error("Erro de conexão ao calcular as distâncias.")
            return None, None
        if matrix_data.get("status") != "OK":
            st.error(f"Erro na Distance Matrix API: {matrix_data.get('status')}")
            return None, None
        for element in matrix_data["rows"][0]["elements"]:
            if element.get("status") == "OK":
                distancia_km = element["distance"]["value"] / 1000
                distancias_finais.append(distancia_km)
            else:
                distancias_finais.append(float("inf"))

    df_validos["distancia_km"] = distancias_finais
    df_dentro_limite = df_validos[df_validos["distancia_km"] <= limite_km]
    return df_dentro_limite.sort_values("distancia_km"), {"lat": latc, "lng": lonc, "address": formatted}

# ----------------- FUNÇÕES NOVAS: Validação e correção em lote -----------------
def scan_and_fix_invalid_coordinates(df_tecnicos: pd.DataFrame, api_key: str, save_back: bool = False, path="tecnicos.xlsx", sheet_name="Planilha1"):
    """
    Varre técnicos e corrige coordenadas inválidas:
    - marca linhas com coordenadas inválidas
    - tenta geocodificar usando a coluna 'endereco' ou 'tecnico' + 'cidade'
    - se conseguir, atualiza latitude/longitude e formatted_address (opcional)
    - se save_back=True, sobrescreve o arquivo Excel com os ajustes
    Retorna (df_result, resumo)
    """
    df = df_tecnicos.copy()
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    invalid_mask = ~df.apply(lambda r: is_coord_valid_for_brazil(r['latitude'], r['longitude']), axis=1)
    invalid_idx = df[invalid_mask].index.tolist()
    resumo = {"total": len(df), "invalid_count": len(invalid_idx), "fixed": 0, "not_fixed": 0}
    fixed_rows = []

    for idx in invalid_idx:
        row = df.loc[idx]
        # Montar melhor string de busca para geocoding
        parts = []
        if 'endereco' in df.columns and pd.notna(row['endereco']):
            parts.append(str(row['endereco']))
        if 'cidade' in df.columns and pd.notna(row['cidade']):
            parts.append(str(row['cidade']))
        if 'uf' in df.columns and pd.notna(row['uf']):
            parts.append(str(row['uf']))
        if not parts:
            search = str(row.get('tecnico', ''))
        else:
            search = ", ".join(parts)
        lat, lng, formatted = geocodificar_endereco(search, api_key)
        if lat is not None and lng is not None and is_coord_valid_for_brazil(lat, lng):
            df.at[idx, 'latitude'] = lat
            df.at[idx, 'longitude'] = lng
            if 'endereco_formatted' in df.columns:
                df.at[idx, 'endereco_formatted'] = formatted
            resumo['fixed'] += 1
            fixed_rows.append((idx, lat, lng, formatted))
        else:
            resumo['not_fixed'] += 1

    if save_back and resumo['fixed'] > 0:
        try:
            # Sobrescrever apenas a planilha especificada
            with pd.ExcelWriter(path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        except Exception as e:
            st.error(f"Erro ao salvar arquivo: {e}")

    return df, resumo, fixed_rows

# ----------------- FUNÇÕES Chamados vs Técnicos (mantidas) -----------------
@st.cache_data
def geocode_chamados(lista_enderecos: List[str], api_key: str):
    resultados = []
    for endereco in lista_enderecos:
        lat, lng, _ = geocodificar_endereco(endereco, api_key)
        resultados.append((lat, lng))
    return resultados

def analisar_chamados_vs_tecnicos(df_chamados: pd.DataFrame, df_tecnicos: pd.DataFrame, api_key: str, limite_km: int, buffer_pct: float = 0.20):
    df_tecnicos = df_tecnicos.copy()
    df_tecnicos['latitude'] = pd.to_numeric(df_tecnicos['latitude'], errors='coerce')
    df_tecnicos['longitude'] = pd.to_numeric(df_tecnicos['longitude'], errors='coerce')
    df_tecnicos_validos = df_tecnicos.dropna(subset=['latitude', 'longitude']).reset_index(drop=True)
    enderecos_chamados = df_chamados['endereco'].astype(str).tolist()
    geocoded = geocode_chamados(enderecos_chamados, api_key)
    resultados = []
    destinos_por_lote = 25
    for idx, (row, (lat_c, lon_c)) in enumerate(zip(df_chamados.itertuples(index=False), geocoded)):
        id_cham = getattr(row, 'id_chamado', None)
        endereco_cham = getattr(row, 'endereco', '')
        if lat_c is None or lon_c is None:
            continue
        threshold_prefilter = limite_km * (1 + buffer_pct)
        df_tecnicos_validos['haversine_km'] = df_tecnicos_validos.apply(
            lambda r: haversine_km(lat_c, lon_c, r['latitude'], r['longitude']), axis=1
        )
        candidatos = df_tecnicos_validos[df_tecnicos_validos['haversine_km'] <= threshold_prefilter].copy()
        if candidatos.empty:
            continue
        origem = f"{lat_c},{lon_c}"
        destinos_coords = candidatos[['latitude', 'longitude']].apply(lambda r: f"{r['latitude']},{r['longitude']}", axis=1).tolist()
        distancias_confirmadas = []
        for i in range(0, len(destinos_coords), destinos_por_lote):
            lote_coords = destinos_coords[i:i+destinos_por_lote]
            try:
                matrix = get_distance_matrix([origem], lote_coords, api_key)
            except requests.exceptions.RequestException:
                matrix = None
            if matrix is None or matrix.get("status") != "OK":
                distancias_confirmadas.extend([float("inf")] * len(lote_coords))
            else:
                elements = matrix["rows"][0]["elements"]
                for el in elements:
                    if el.get("status") == "OK":
                        distancia_km = el["distance"]["value"] / 1000.0
                        distancias_confirmadas.append(distancia_km)
                    else:
                        distancias_confirmadas.append(float("inf"))
        candidatos = candidatos.reset_index(drop=True)
        candidatos['distancia_km_confirmada'] = distancias_confirmadas[:len(candidatos)]
        dentro_limite = candidatos[candidatos['distancia_km_confirmada'] <= limite_km]
        for _, trow in dentro_limite.iterrows():
            resultados.append({
                "id_chamado": id_cham,
                "endereco_chamado": endereco_cham,
                "tecnico": trow.get('tecnico'),
                "coordenador": trow.get('coordenador'),
                "cidade_tecnico": trow.get('cidade'),
                "uf_tecnico": trow.get('uf'),
                "distancia_km": round(trow['distancia_km_confirmada'], 2)
            })
    df_result = pd.DataFrame(resultados)
    return df_result

# ----------------- LOGIN e CARREGAMENTO -----------------
def check_password_main():
    password = st.text_input("Por favor, insira a senha para acessar:", type="password")
    if password == st.secrets["auth"]["senha"]:
        st.session_state.authenticated = True
        st.rerun()
    elif password:
        st.error("Senha incorreta. Tente novamente.")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Acesso Restrito")
    check_password_main()
    st.stop()

st.title("🔎 Localizador de Técnicos")
st.markdown("---")

# Carregar técnicos
FILE_TEC = "tecnicos.xlsx"
SHEET_TEC = "Planilha1"
df_tecnicos = load_data(FILE_TEC, sheet_name=SHEET_TEC)
if df_tecnicos is None:
    st.stop()

# API_KEY
try:
    API_KEY = st.secrets["api"]["google_maps"]
except Exception:
    API_KEY = None
    st.error("Chave de API do Google Maps não encontrada em st.secrets['api']['google_maps'].")

# Garantir colunas numéricas
if 'latitude' in df_tecnicos.columns:
    df_tecnicos['latitude'] = pd.to_numeric(df_tecnicos['latitude'], errors='coerce')
if 'longitude' in df_tecnicos.columns:
    df_tecnicos['longitude'] = pd.to_numeric(df_tecnicos['longitude'], errors='coerce')

# Sidebar filtros
st.sidebar.header("Filtros de Busca")
ufs = ["Todos"] + sorted(df_tecnicos['uf'].dropna().unique().tolist()) if 'uf' in df_tecnicos.columns else ["Todos"]
cidades_todas = ["Todas"] + sorted(df_tecnicos['cidade'].dropna().unique().tolist()) if 'cidade' in df_tecnicos.columns else ["Todas"]
coordenadores = ["Todos"] + sorted(df_tecnicos['coordenador'].dropna().unique().tolist()) if 'coordenador' in df_tecnicos.columns else ["Todos"]

if "uf_selecionada" not in st.session_state:
    st.session_state.uf_selecionada = "Todos"
if "cidade_selecionada" not in st.session_state:
    st.session_state.cidade_selecionada = "Todas"
if "coordenador_selecionado" not in st.session_state:
    st.session_state.coordenador_selecionado = "Todos"

with st.sidebar:
    st.session_state.uf_selecionada = st.selectbox("Filtrar por UF:", ufs, index=ufs.index(st.session_state.uf_selecionada) if st.session_state.uf_selecionada in ufs else 0)
    if st.session_state.uf_selecionada != "Todos":
        cidades_filtradas = ["Todas"] + sorted(df_tecnicos[df_tecnicos['uf'] == st.session_state.uf_selecionada]['cidade'].dropna().unique().tolist())
        try:
            current_index = cidades_filtradas.index(st.session_state.cidade_selecionada)
        except ValueError:
            current_index = 0
            st.session_state.cidade_selecionada = "Todas"
        st.session_state.cidade_selecionada = st.selectbox("Filtrar por Cidade:", cidades_filtradas, index=current_index)
    else:
        st.session_state.cidade_selecionada = st.selectbox("Filtrar por Cidade:", cidades_todas, index=cidades_todas.index(st.session_state.cidade_selecionada) if st.session_state.cidade_selecionada in cidades_todas else 0)
    st.session_state.coordenador_selecionado = st.selectbox("Filtrar por Coordenador:", coordenadores, index=coordenadores.index(st.session_state.coordenador_selecionado) if st.session_state.coordenador_selecionado in coordenadores else 0)
    st.markdown("---")
    if st.button("Limpar Filtros"):
        st.session_state.uf_selecionada = "Todos"
        st.session_state.cidade_selecionada = "Todas"
        st.session_state.coordenador_selecionado = "Todos"
        st.rerun()
    st.markdown("---")
    st.markdown("**Opções de Visualização**")
    modo_exibicao = st.radio("Formato da Lista de Técnicos:", ["Tabela", "Colunas"], index=1)

# Abas
tab1, tab2, tab3, tab4 = st.tabs(["Localizador de Técnicos", "Análise de Dados", "Editor de Dados", "Chamados x Técnicos"])

# ----------------- ABA 1: Localizador -----------------
with tab1:
    df_filtrado = df_tecnicos.copy()
    if st.session_state.uf_selecionada != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == st.session_state.uf_selecionada]
    if st.session_state.cidade_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['cidade'] == st.session_state.cidade_selecionada]
    if st.session_state.coordenador_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['coordenador'] == st.session_state.coordenador_selecionado]

    st.header("Lista de Técnicos Filtrados")
    if st.session_state.uf_selecionada != "Todos" or st.session_state.cidade_selecionada != "Todas" or st.session_state.coordenador_selecionado != "Todos":
        if modo_exibicao == "Tabela":
            mostrar_cols = [c for c in ['tecnico', 'cidade', 'uf', 'coordenador'] if c in df_filtrado.columns]
            st.dataframe(df_filtrado[mostrar_cols])
        else:
            cols = st.columns(2)
            for i, row in df_filtrado.iterrows():
                with cols[i % 2]:
                    st.markdown(f"**{row.get('tecnico','')}**")
                    st.write(f"Coordenador: {row.get('coordenador', 'Não informado')}")
                    st.write(f"Cidade: {row.get('cidade', 'Não informada')}")
                    st.markdown("---")
    else:
        st.info("Utilize os filtros na barra lateral para ver uma lista de técnicos.")

    st.markdown("---")
    st.header("Busca por Distância")
    if not df_filtrado.empty:
        st.info(f"A busca será restrita aos **{len(df_filtrado)}** técnicos selecionados e **apenas técnicos a até 200 km** serão listados.")
    else:
        st.warning("Não há técnicos nos filtros selecionados para realizar a busca por distância.")

    if API_KEY:
        endereco_cliente = st.text_input("Endereço / CEP / Cidade", help="Ex: Av. Paulista, 1000, São Paulo, SP ou 01310-100 ou São Paulo")
        if st.button("Buscar Técnico Mais Próximo"):
            if endereco_cliente:
                with st.spinner("Buscando o técnico mais próximo..."):
                    tecnicos_proximos, localizacao_cliente = encontrar_tecnico_proximo(endereco_cliente, API_KEY, df_filtrado)
                    if tecnicos_proximos is not None and not tecnicos_proximos.empty:
                        st.success(f"Busca concluída! Encontrados {len(tecnicos_proximos)} técnicos a até 200 km de distância.")
                        # preparar coords para o mapa
                        tecnicos_coords = [
                            {'lat': row['latitude'], 'lng': row['longitude'], 'title': row.get('tecnico','')}
                            for _, row in tecnicos_proximos.iterrows()
                        ]
                        cliente_coords = {'lat': localizacao_cliente['lat'], 'lng': localizacao_cliente['lng']}
                        # Montar HTML do mapa usando Google Maps JS (requer API_KEY)
                        map_html = f"""
                        <!DOCTYPE html>
                        <html>
                        <head>
                            <meta name="viewport" content="initial-scale=1.0, user-scalable=no" />
                            <style> #map {{ height: 520px; width:100%; }} </style>
                        </head>
                        <body>
                            <div id="map"></div>
                            <script>
                                function initMap() {{
                                    const cliente = {{ lat: {cliente_coords['lat']}, lng: {cliente_coords['lng']} }};
                                    const map = new google.maps.Map(document.getElementById('map'), {{
                                        zoom: 10,
                                        center: cliente
                                    }});
                                    const cliente_marker = new google.maps.Marker({{
                                        position: cliente,
                                        map: map,
                                        title: "Cliente",
                                        icon: "http://googlemaps.com/mapfiles/kml/pal2/icon14.png"
                                    }});
                                    const tecnicos = {tecnicos_coords};
                                    tecnicos.forEach(function(t) {{
                                        new google.maps.Marker({{
                                            position: {{lat: t.lat, lng: t.lng}},
                                            map: map,
                                            title: t.title,
                                            icon: "http://googlemaps.com/mapfiles/kml/pal2/icon4.png"
                                        }});
                                    }});
                                }}
                            </script>
                            <script async defer src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&callback=initMap"></script>
                        </body>
                        </html>
                        """
                        components.html(map_html, height=560)
                        # Preparação para exportação
                        out_cols = ['tecnico','coordenador','cidade','uf','distancia_km','email_coordenador']
                        exist_cols = [c for c in out_cols if c in tecnicos_proximos.columns]
                        df_to_export = tecnicos_proximos[exist_cols].copy()
                        if 'distancia_km' in df_to_export.columns:
                            df_to_export['distancia_km'] = df_to_export['distancia_km'].round(2)
                        # renomear colunas para saída amigável
                        rename_map = { 'tecnico':'Técnico', 'coordenador':'Coordenador', 'cidade':'Cidade', 'uf':'UF', 'distancia_km':'Distância (km)', 'email_coordenador':'E-mail do Coordenador' }
                        df_to_export.rename(columns={k:v for k,v in rename_map.items() if k in df_to_export.columns}, inplace=True)
                        towrite = io.BytesIO()
                        df_to_export.to_excel(towrite, index=False, header=True)
                        towrite.seek(0)
                        st.download_button(label="Exportar para Excel", data=towrite, file_name='tecnicos_proximos.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                        # Exibir lista simples
                        st.markdown("### Técnicos encontrados")
                        st.dataframe(tecnicos_proximos[['tecnico','distancia_km']].sort_values('distancia_km') if 'distancia_km' in tecnicos_proximos.columns else tecnicos_proximos.head(50))
                    else:
                        st.info("Nenhum técnico encontrado no universo filtrado que esteja a até 200 km de distância do endereço.")
            else:
                st.warning("Por favor, digite um endereço para iniciar a busca.")
    else:
        st.warning("API Key do Google não encontrada — funções de geocoding e mapas estarão indisponíveis.")

# ----------------- ABA 2: Análise -----------------
with tab2:
    st.header("📊 Análise de Dados dos Técnicos")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Técnicos", len(df_tecnicos))
    with col2:
        st.metric("Total de UFs", len(df_tecnicos['uf'].unique()) if 'uf' in df_tecnicos.columns else 0)
    with col3:
        st.metric("Total de Cidades", len(df_tecnicos['cidade'].unique()) if 'cidade' in df_tecnicos.columns else 0)
    st.markdown("---")
    tecnicos_sem_coord = df_tecnicos['latitude'].isnull().sum() if 'latitude' in df_tecnicos.columns else 0
    tecnicos_totais = len(df_tecnicos)
    porcentagem_faltante = (tecnicos_sem_coord / tecnicos_totais) * 100 if tecnicos_totais > 0 else 0
    col_missing1, col_missing2 = st.columns(2)
    with col_missing1:
        st.metric("Técnicos sem Coordenadas", tecnicos_sem_coord)
    with col_missing2:
        st.metric("Porcentagem Faltante", f"{porcentagem_faltante:.2f}%")
    if tecnicos_sem_coord > 0:
        st.warning(f"⚠️ {tecnicos_sem_coord} técnicos não possuem coordenadas válidas.")
    else:
        st.success("✅ Todos os técnicos possuem coordenadas válidas (aparente).")
    st.markdown("---")
    st.subheader("Gráfico: Técnicos por UF")
    if 'uf' in df_tecnicos.columns:
        uf_counts = df_tecnicos['uf'].value_counts().reset_index()
        uf_counts.columns = ['UF','Quantidade']
        fig_uf = px.bar(uf_counts, x='UF', y='Quantidade', title="Técnicos por UF", color='UF')
        st.plotly_chart(fig_uf, use_container_width=True)
    st.markdown("---")
    st.subheader("Mapa Interativo de Técnicos (pydeck)")
    df_mapa = df_tecnicos.dropna(subset=['latitude','longitude']).copy()
    if not df_mapa.empty:
        for col in ['tecnico','coordenador','cidade']:
            if col in df_mapa.columns:
                df_mapa[col] = df_mapa[col].fillna('').astype(str)
        view_state = pdk.ViewState(latitude=df_mapa['latitude'].mean(), longitude=df_mapa['longitude'].mean(), zoom=4, pitch=50)
        scatterplot_layer = pdk.Layer('ScatterplotLayer', data=df_mapa, get_position='[longitude, latitude]', get_radius=15000)
        r = pdk.Deck(layers=[scatterplot_layer], initial_view_state=view_state, tooltip={"html":"<b>Técnico:</b> {tecnico}<br/><b>Coordenador:</b> {coordenador}<br/><b>Cidade:</b> {cidade}<br/>"})
        st.pydeck_chart(r)
    else:
        st.info("Nenhum técnico com coordenadas válidas para exibir no mapa.")

# ----------------- ABA 3: Editor de Dados (com validação) -----------------
with tab3:
    st.header("📝 Editor de Dados dos Técnicos")
    # Autenticação para editor (mantida)
    if "editor_authenticated" not in st.session_state:
        st.session_state.editor_authenticated = False

    def check_password_editor():
        password = st.text_input("Insira a senha do editor para editar a planilha:", type="password")
        if password == st.secrets["auth"]["editor_senha"]:
            st.session_state.editor_authenticated = True
            st.rerun()
        elif password:
            st.error("Senha de editor incorreta. Acesso negado.")

    if not st.session_state.editor_authenticated:
        st.subheader("🔒 Acesso a Edição Restrito")
        check_password_editor()
    else:
        st.info("Clique duas vezes em uma célula para editar. Use os botões abaixo para atualizar coordenadas inválidas.")
        if "df_editavel" not in st.session_state:
            st.session_state.df_editavel = df_tecnicos.copy()
        df_editavel = st.data_editor(st.session_state.df_editavel, num_rows="dynamic", use_container_width=True)
        st.session_state.df_editavel = df_editavel.copy()

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Detectar e Corrigir Coordenadas Inválidas (auto)"):
                if API_KEY is None:
                    st.error("API Key do Google necessária para correções automáticas.")
                else:
                    with st.spinner("Verificando e corrigindo coordenadas..."):
                        new_df, resumo, fixed_rows = scan_and_fix_invalid_coordinates(st.session_state.df_editavel, API_KEY, save_back=False)
                        st.session_state.df_editavel = new_df.copy()
                        st.success(f"Verificação concluída. Total inválidos: {resumo['invalid_count']}. Corrigidos: {resumo['fixed']}. Não corrigidos: {resumo['not_fixed']}.")
                        if resumo['fixed'] > 0:
                            st.write("Amostra de correções aplicadas (índice, lat, lon, endereco_formatado):")
                            st.dataframe(pd.DataFrame(fixed_rows, columns=['index','lat','lon','formatted']).head(20))
        with col_b:
            if st.button("Salvar alterações na planilha (sobrescrever)"):
                try:
                    with pd.ExcelWriter(FILE_TEC, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                        st.session_state.df_editavel.to_excel(writer, sheet_name=SHEET_TEC, index=False)
                    st.success("Arquivo salvo com sucesso!")
                    # recarregar dados em cache limpando o cache do load_data (forçar recarregar)
                    load_data.clear()
                    df_tecnicos = load_data(FILE_TEC, sheet_name=SHEET_TEC)
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

        st.markdown("---")
        towrite_edit = io.BytesIO()
        st.session_state.df_editavel.to_excel(towrite_edit, index=False, header=True)
        towrite_edit.seek(0)
        st.download_button(label="Baixar Planilha Atualizada", data=towrite_edit, file_name='tecnicos_atualizado.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ----------------- ABA 4: Chamados x Técnicos (nova) -----------------
with tab4:
    st.header("🧾 Chamados x Técnicos — Cruzamento por distância")
    st.markdown("Envie a planilha de chamados (colunas obrigatórias `id_chamado` e `endereco`).")
    uploaded = st.file_uploader("Faça upload da planilha de Chamados (Excel)", type=['xlsx','xls'], accept_multiple_files=False)
    uf_filter = st.selectbox("Filtrar técnicos por UF (opcional):", ["Todos"] + (sorted(df_tecnicos['uf'].dropna().unique().tolist()) if 'uf' in df_tecnicos.columns else []))
    if uf_filter != "Todos":
        df_tecnicos_para_busca = df_tecnicos[df_tecnicos['uf'] == uf_filter].copy()
    else:
        df_tecnicos_para_busca = df_tecnicos.copy()
    limite_escolha = st.selectbox("Limite (km):", [30,50,100], index=0)
    st.markdown("---")
    if uploaded is not None:
        try:
            df_chamados = pd.read_excel(uploaded)
        except Exception:
            st.error("Erro ao ler a planilha de chamados.")
            df_chamados = None
        if df_chamados is not None:
            if 'id_chamado' not in df_chamados.columns or 'endereco' not in df_chamados.columns:
                st.error("A planilha deve conter 'id_chamado' e 'endereco'.")
            else:
                st.success(f"Planilha carregada: {len(df_chamados)} chamados. Técnicos considerados: {len(df_tecnicos_para_busca)}.")
                if API_KEY is None:
                    st.error("API Key do Google necessária para cruzamento.")
                else:
                    if st.button("Iniciar Cruzamento (pré-filtro + Distance Matrix)"):
                        with st.spinner("Executando cruzamento..."):
                            df_resultado = analisar_chamados_vs_tecnicos(df_chamados, df_tecnicos_para_busca, API_KEY, limite_escolha, buffer_pct=0.20)
                            if df_resultado.empty:
                                st.info("Nenhuma combinação encontrada dentro do limite.")
                            else:
                                st.success(f"{len(df_resultado)} combinações encontradas.")
                                st.dataframe(df_resultado.head(200))
                                towrite = io.BytesIO()
                                df_resultado.to_excel(towrite, index=False, header=True)
                                towrite.seek(0)
                                st.download_button(label="Baixar relatório (Excel)", data=towrite, file_name=f'chamados_tecnicos_{limite_escolha}km.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        st.info("Faça upload da planilha de chamados para iniciar o cruzamento.")

# Rodapé
st.markdown("---")
st.markdown("<div style='text-align:center;'>Desenvolvido por Edmilson Carvalho - Edmilson.carvalho@globalhitss.com.br © 2025</div>", unsafe_allow_html=True)

