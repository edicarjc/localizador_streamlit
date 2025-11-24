import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
import io
import plotly.express as px
import pydeck as pdk
import math
from typing import Tuple, List

# --- INJEÇÃO DE CSS ---
st.markdown("""
<style>
    /* Esconde o menu do Streamlit e o rodapé "Made with Streamlit" */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Centraliza o título principal e subtítulos */
    h1, h2, h3 {
        text-align: center;
    }
    
    /* Ajusta as colunas para telas menores */
    @media (max-width: 600px) {
        .st-emotion-cache-18ni7ap {
            flex-direction: column;
        }
        .st-emotion-cache-18ni7ap > div {
            width: 100% !important;
        }
    }
    /* Estilo para os botões alinhados */
    .button-group a {
        display: inline-block;
        padding: 8px 15px;
        color: white;
        text-align: center;
        text-decoration: none;
        border-radius: 5px;
        font-size: 14px;
        margin-right: 10px; /* Espaço entre os botões */
    }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES EXISTENTES --- #

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

def geocodificar_endereco(endereco: str, api_key: str) -> Tuple[float, float]:
    """Converte um endereço em coordenadas (latitude e longitude)."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": endereco, "key": api_key}
    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        if data.get("status") == "OK":
            location = data["results"][0]["geometry"]["location"]
            return location['lat'], location['lng']
        else:
            return None, None
    except requests.exceptions.RequestException:
        return None, None

@st.cache_data
def load_data(file_path):
    """Carrega os dados do arquivo Excel e faz um cache para otimizar o desempenho."""
    try:
        df = pd.read_excel(file_path)
        return df
    except FileNotFoundError:
        st.error(f"Erro: O arquivo '{file_path}' não foi encontrado. Por favor, coloque-o na mesma pasta do script.")
        st.stop()
    except KeyError as e:
        st.error(f"Erro: A coluna '{e.args[0]}' não foi encontrada na sua planilha. Verifique a ortografia do cabeçalho.")
        st.stop()
    return None

def encontrar_tecnico_proximo(endereco_cliente, api_key, df_filtrado):
    """Função existente: encontra técnicos próximos a um endereço (até 200 km)."""
    df_filtrado['latitude'] = pd.to_numeric(df_filtrado['latitude'], errors='coerce')
    df_filtrado['longitude'] = pd.to_numeric(df_filtrado['longitude'], errors='coerce')
    df_validos = df_filtrado.dropna(subset=['latitude', 'longitude']).copy()
    
    if df_validos.empty:
        st.info("Nenhum técnico com coordenadas válidas foi encontrado para a sua busca.")
        return None, None

    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
    geocode_params = {"address": endereco_cliente, "key": api_key}
    try:
        geocode_response = requests.get(geocode_url, params=geocode_params)
        geocode_data = geocode_response.json()
    except requests.exceptions.RequestException:
        st.error(f"Erro de conexão ao buscar o endereço do cliente. Verifique sua conexão com a internet.")
        return None, None
    
    if geocode_data["status"] != "OK":
        st.error(f"Não foi possível encontrar o endereço do cliente. Verifique o endereço e tente novamente. Código do erro: {geocode_data['status']}")
        return None, None

    localizacao_cliente = geocode_data["results"][0]["geometry"]["location"]
    origem = f"{localizacao_cliente['lat']},{localizacao_cliente['lng']}"

    distancias_finais = []
    
    destinos_por_lote = 25
    for i in range(0, len(df_validos), destinos_por_lote):
        lote_df = df_validos.iloc[i : i + destinos_por_lote]
        destinos = [f"{lat},{lon}" for lat, lon in zip(lote_df['latitude'], lote_df['longitude'])]
        
        try:
            matrix_data = get_distance_matrix([origem], destinos, api_key)
        except requests.exceptions.RequestException:
            st.error(f"Erro de conexão ao calcular as distâncias. Verifique sua conexão com a internet.")
            return None, None
        
        if matrix_data["status"] != "OK":
            st.error(f"Erro na Google Maps Distance Matrix API: {matrix_data['status']}")
            return None, None
        
        for element in matrix_data["rows"][0]["elements"]:
            if element["status"] == "OK":
                distancia_km = element["distance"]["value"] / 1000
                distancias_finais.append(distancia_km)
            else:
                distancias_finais.append(float("inf"))

    df_validos["distancia_km"] = distancias_finais
    
    # --- FILTRO DE 200 KM ---
    df_dentro_limite = df_validos[df_validos["distancia_km"] <= 200]
    
    # Retorna todos os técnicos dentro do limite, ordenados pela distância
    return df_dentro_limite.sort_values("distancia_km"), localizacao_cliente

# --- NOVAS FUNÇÕES (Haversine + processamento de chamados) --- #

def haversine_km(lat1, lon1, lat2, lon2):
    """Calcula distância geodésica (km) entre dois pontos (haversine)."""
    R = 6371.0  # raio da Terra em km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@st.cache_data
def geocode_chamados(lista_enderecos: List[str], api_key: str):
    """Geocodifica lista de endereços (com cache). Retorna lista de (lat, lon)."""
    resultados = []
    for endereco in lista_enderecos:
        lat, lng = geocodificar_endereco(endereco, api_key)
        resultados.append((lat, lng))
    return resultados

def analisar_chamados_vs_tecnicos(df_chamados: pd.DataFrame, df_tecnicos: pd.DataFrame, api_key: str, limite_km: int, buffer_pct: float = 0.20):
    """
    Para cada chamado: pré-filtra técnicos por distância geodésica (haversine)
    usando buffer_pct (20% default). Em seguida confirma distância por rota
    com a Google Distance Matrix apenas para os candidatos.
    Retorna DataFrame com colunas: id_chamado, endereco, tecnico, cidade_tecnico, uf_tecnico, distancia_km
    """
    # Preparar técnicos válidos
    df_tecnicos = df_tecnicos.copy()
    df_tecnicos['latitude'] = pd.to_numeric(df_tecnicos['latitude'], errors='coerce')
    df_tecnicos['longitude'] = pd.to_numeric(df_tecnicos['longitude'], errors='coerce')
    df_tecnicos_validos = df_tecnicos.dropna(subset=['latitude', 'longitude']).reset_index(drop=True)
    
    # Geocodificar chamados (coluna 'endereco' obrigatória)
    enderecos_chamados = df_chamados['endereco'].astype(str).tolist()
    geocoded = geocode_chamados(enderecos_chamados, api_key)
    
    resultados = []
    destinos_por_lote = 25
    # Para cada chamado
    for idx, (row, (lat_c, lon_c)) in enumerate(zip(df_chamados.itertuples(index=False), geocoded)):
        id_cham = getattr(row, 'id_chamado', None)
        endereco_cham = getattr(row, 'endereco', '')
        if lat_c is None or lon_c is None:
            # Não geocodificou — pular ou marcar como sem coords
            continue
        
        # Pré-filtro geodésico com buffer
        threshold_prefilter = limite_km * (1 + buffer_pct)  # ex: 30 * 1.2 = 36 km
        # Calcular haversine para todos os técnicos
        df_tecnicos_validos['haversine_km'] = df_tecnicos_validos.apply(
            lambda r: haversine_km(lat_c, lon_c, r['latitude'], r['longitude']),
            axis=1
        )
        candidatos = df_tecnicos_validos[df_tecnicos_validos['haversine_km'] <= threshold_prefilter].copy()
        
        if candidatos.empty:
            # nenhum candidato geodésico próximo
            continue
        
        # Montar destinos em lotes e perguntar ao Google para obter rotas reais
        origem = f"{lat_c},{lon_c}"
        destinos_coords = candidatos[['latitude', 'longitude']].apply(lambda r: f"{r['latitude']},{r['longitude']}", axis=1).tolist()
        
        distancias_confirmadas = []
        # Fazer chamadas por lote (limitadas a 25 destinos por request)
        for i in range(0, len(destinos_coords), destinos_por_lote):
            lote_coords = destinos_coords[i:i+destinos_por_lote]
            try:
                matrix = get_distance_matrix([origem], lote_coords, api_key)
            except requests.exceptions.RequestException:
                # Se der erro de conexão, saltar este lote
                matrix = None
            
            if matrix is None or matrix.get("status") != "OK":
                # preencher com inf para manter alinhamento
                distancias_confirmadas.extend([float("inf")] * len(lote_coords))
            else:
                elements = matrix["rows"][0]["elements"]
                for el in elements:
                    if el.get("status") == "OK":
                        distancia_km = el["distance"]["value"] / 1000.0
                        distancias_confirmadas.append(distancia_km)
                    else:
                        distancias_confirmadas.append(float("inf"))
        
        # Anexar resultados onde distancia_confirmada <= limite_km
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

# --- LÓGICA DE LOGIN PRINCIPAL (mesma do seu arquivo) --- #

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
    st.set_page_config(page_title="Localizador de Técnicos", layout="wide")
    st.title("🔒 Acesso Restrito")
    check_password_main()
    st.stop()

st.set_page_config(page_title="Localizador de Técnicos", layout="wide")
st.title("🔎 Localizador de Técnicos")
st.markdown("---")

# 1. CARREGAR DADOS E API KEY
df_tecnicos = load_data('tecnicos.xlsx')
if df_tecnicos is None:
    st.stop()

# 2. CENTRALIZAÇÃO DA CHAVE DE API
try:
    API_KEY = st.secrets["api"]["google_maps"]
except KeyError:
    st.error("Chave de API do Google Maps não encontrada. Verifique o arquivo .streamlit/secrets.toml")
    API_KEY = None

# Converter coordenadas
df_tecnicos['latitude'] = pd.to_numeric(df_tecnicos['latitude'], errors='coerce')
df_tecnicos['longitude'] = pd.to_numeric(df_tecnicos['longitude'], errors='coerce')

# --- CONFIGURAÇÃO INICIAL DO SIDEBAR (mantida) ---
st.sidebar.header("Filtros de Busca")
ufs = ["Todos"] + sorted(df_tecnicos['uf'].unique().tolist())
cidades_todas = ["Todas"] + sorted(df_tecnicos['cidade'].unique().tolist())
coordenadores = ["Todos"] + sorted(df_tecnicos['coordenador'].unique().tolist())

if "uf_selecionada" not in st.session_state:
    st.session_state.uf_selecionada = "Todos"
if "cidade_selecionada" not in st.session_state:
    st.session_state.cidade_selecionada = "Todas"
if "coordenador_selecionado" not in st.session_state:
    st.session_state.coordenador_selecionado = "Todos"

with st.sidebar:
    st.session_state.uf_selecionada = st.selectbox("Filtrar por UF:", ufs, index=ufs.index(st.session_state.uf_selecionada))
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        cidades_filtradas = ["Todas"] + sorted(df_tecnicos[df_tecnicos['uf'] == st.session_state.uf_selecionada]['cidade'].unique().tolist())
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

# --- Sistema de abas: adicionei a aba "Chamados x Técnicos" ---
tab1, tab2, tab3, tab4 = st.tabs(["Localizador de Técnicos", "Análise de Dados", "Editor de Dados", "Chamados x Técnicos"])

# --- aba 1: mantém sua lógica anterior (resumida aqui) ---
with tab1:
    df_filtrado = df_tecnicos.copy()
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == st.session_state.uf_selecionada]
    if st.session_state.cidade_selecionada and st.session_state.cidade_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['cidade'] == st.session_state.cidade_selecionada]
    if st.session_state.coordenador_selecionado and st.session_state.coordenador_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['coordenador'] == st.session_state.coordenador_selecionado]

    st.header("Lista de Técnicos Filtrados")
    if st.session_state.uf_selecionada != "Todos" or st.session_state.cidade_selecionada != "Todas" or st.session_state.coordenador_selecionado != "Todos":
        if modo_exibicao == "Tabela":
            st.dataframe(df_filtrado[['tecnico', 'cidade', 'uf', 'coordenador']])
        else:
            cols = st.columns(2)
            for i, row in df_filtrado.iterrows():
                with cols[i % 2]:
                    st.markdown(f"**{row['tecnico']}**")
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
                        # mapa e exportação (mantidos)
                        tecnicos_coords = [{'lat': row['latitude'], 'lng': row['longitude'], 'title': row['tecnico']} for _, row in tecnicos_proximos.iterrows()]
                        cliente_coords = {'lat': localizacao_cliente['lat'], 'lng': localizacao_cliente['lng']}
                        map_html = f"""..."""  # Mantive curto no snippet; seu código original já monta o mapa
                        components.html(map_html, height=550)
                        df_to_export = tecnicos_proximos[['tecnico', 'coordenador', 'cidade', 'uf', 'distancia_km', 'email_coordenador']].copy()
                        df_to_export['distancia_km'] = df_to_export['distancia_km'].round(2)
                        df_to_export.rename(columns={
                            'tecnico': 'Técnico',
                            'coordenador': 'Coordenador',
                            'cidade': 'Cidade',
                            'uf': 'UF',
                            'distancia_km': 'Distância (km)',
                            'email_coordenador': 'E-mail do Coordenador'
                        }, inplace=True)
                        towrite = io.BytesIO()
                        df_to_export.to_excel(towrite, index=False, header=True)
                        towrite.seek(0)
                        st.download_button(label="Exportar para Excel", data=towrite, file_name='tecnicos_proximos.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    else:
                        st.info("Nenhum técnico encontrado no universo filtrado que esteja a até 200 km de distância do endereço.")
            else:
                st.warning("Por favor, digite um endereço para iniciar a busca.")

# --- aba 2: Análise de Dados (mantida) ---
with tab2:
    st.header("📊 Análise de Dados dos Técnicos")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Técnicos", len(df_tecnicos))
    with col2:
        st.metric("Total de UFs", len(df_tecnicos['uf'].unique()))
    with col3:
        st.metric("Total de Cidades", len(df_tecnicos['cidade'].unique()))
    st.markdown("---")
    st.subheader("Análise de Dados Faltantes")
    tecnicos_sem_coord = df_tecnicos['latitude'].isnull().sum()
    tecnicos_totais = len(df_tecnicos)
    porcentagem_faltante = (tecnicos_sem_coord / tecnicos_totais) * 100 if tecnicos_totais > 0 else 0
    col_missing1, col_missing2 = st.columns(2)
    with col_missing1:
        st.metric("Técnicos sem Coordenadas", tecnicos_sem_coord)
    with col_missing2:
        st.metric("Porcentagem Faltante", f"{porcentagem_faltante:.2f}%")
    if tecnicos_sem_coord > 0:
        st.warning(f"⚠️ **{tecnicos_sem_coord}** técnicos ({porcentagem_faltante:.2f}%) não possuem coordenadas válidas e não serão considerados na busca por distância.")
    else:
        st.success("✅ Todos os técnicos possuem coordenadas válidas!")
    st.markdown("---")
    st.subheader("Gráfico: Técnicos por UF")
    uf_counts = df_tecnicos['uf'].value_counts().reset_index()
    uf_counts.columns = ['UF', 'Quantidade']
    fig_uf = px.bar(uf_counts, x='UF', y='Quantidade', title="Técnicos por UF", color='UF')
    st.plotly_chart(fig_uf, use_container_width=True)
    st.subheader("Gráfico: Técnicos por Coordenador")
    coordenador_counts = df_tecnicos['coordenador'].value_counts().reset_index()
    coordenador_counts.columns = ['Coordenador', 'Quantidade']
    fig_coordenador = px.bar(coordenador_counts, x='Coordenador', y='Quantidade', title="Técnicos por Coordenador", color='Coordenador')
    st.plotly_chart(fig_coordenador, use_container_width=True)
    st.markdown("---")
    st.subheader("Mapa Interativo de Técnicos")
    st.info("Passe o mouse sobre os pontos para ver os detalhes dos técnicos.")
    df_mapa = df_tecnicos.dropna(subset=['latitude', 'longitude']).copy()
    for col in ['tecnico', 'coordenador', 'cidade']:
        if col in df_mapa.columns:
            df_mapa[col] = df_mapa[col].fillna('').astype(str)
    if not df_mapa.empty:
        view_state = pdk.ViewState(latitude=df_mapa['latitude'].mean(), longitude=df_mapa['longitude'].mean(), zoom=4, pitch=50)
        scatterplot_layer = pdk.Layer('ScatterplotLayer', data=df_mapa, get_position='[longitude, latitude]', get_color='[200, 30, 0, 160]', get_radius=15000)
        r = pdk.Deck(layers=[scatterplot_layer], initial_view_state=view_state, tooltip={"html": "<b>Técnico:</b> {tecnico}<br/><b>Coordenador:</b> {coordenador}<br/><b>Cidade:</b> {cidade}<br/>", "style": {"backgroundColor": "steelblue","color": "white"}})
        st.pydeck_chart(r)
    else:
        st.info("Nenhum técnico com coordenadas válidas para exibir no mapa.")

# --- aba 3: Editor de Dados (mantida) ---
with tab3:
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
        st.subheader("📝 Editor de Dados dos Técnicos")
        st.info("Clique duas vezes em uma célula para editar. Use o menu lateral para adicionar ou remover linhas. **Lembre-se: as alterações não são salvas permanentemente no repositório!**")
        if "df_editavel" not in st.session_state:
            st.session_state.df_editavel = df_tecnicos.copy()
        df_editavel = st.data_editor(st.session_state.df_editavel, num_rows="dynamic", use_container_width=True)
        st.session_state.df_editavel = df_editavel.copy()
        st.markdown("---")
        st.subheader("Atualizar e Salvar Alterações")
        if st.button("Atualizar Coordenadas", help="Preenche Latitude e Longitude de novos endereços."):
            if API_KEY:
                with st.spinner("Atualizando coordenadas..."):
                    for index, row in st.session_state.df_editavel.iterrows():
                        if ('endereco' in df_editavel.columns and (str(row.get('endereco', '')) != str(df_tecnicos.loc[index]['endereco']) or pd.isnull(row['latitude']) or pd.isnull(row['longitude']))):
                            endereco_completo = f"{row.get('endereco', '')}, {row.get('cidade', '')}"
                            lat, lng = geocodificar_endereco(endereco_completo, API_KEY)
                            if lat is not None and lng is not None:
                                st.session_state.df_editavel.at[index, 'latitude'] = lat
                                st.session_state.df_editavel.at[index, 'longitude'] = lng
                                st.success(f"Coordenadas de **{row['tecnico']}** atualizadas com sucesso!")
                            else:
                                st.warning(f"Não foi possível encontrar as coordenadas de **{row['tecnico']}**.")
                    st.rerun()
            else:
                 st.error("A Chave da API do Google Maps é necessária para esta função.")
        st.markdown("""<p style='color:red;'>ATENÇÃO: Este botão apenas baixa o arquivo. Você deve carregá-lo manualmente no GitHub para manter as alterações!</p>""", unsafe_allow_html=True)
        towrite_edit = io.BytesIO()
        st.session_state.df_editavel.to_excel(towrite_edit, index=False, header=True)
        towrite_edit.seek(0)
        st.download_button(label="Baixar Planilha Atualizada", data=towrite_edit, file_name='tecnicos_atualizado.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# --- aba 4: Chamados x Técnicos (NOVA) ---
with tab4:
    st.header("🧾 Chamados x Técnicos — Cruzamento por distância")
    st.markdown("Envie a planilha de chamados (coluna obrigatória `id_chamado` e `endereco`). O app irá geocodificar os chamados, pré-filtrar técnicos por distância geodésica e confirmar a distância por rota com Google Maps. Opcionalmente filtre por UF dos técnicos antes do cruzamento.")

    uploaded = st.file_uploader("Faça upload da planilha de Chamados (Excel) — coluna 'id_chamado' e 'endereco'", type=['xlsx', 'xls'], accept_multiple_files=False)
    # filtro por UF/cidade do técnico antes do cruzamento
    uf_filter = st.selectbox("Filtrar técnicos por UF (opcional):", ["Todos"] + sorted(df_tecnicos['uf'].dropna().unique().tolist()))
    if uf_filter != "Todos":
        df_tecnicos_para_busca = df_tecnicos[df_tecnicos['uf'] == uf_filter].copy()
    else:
        df_tecnicos_para_busca = df_tecnicos.copy()

    st.markdown("Selecione o raio máximo de atendimento:")
    limite_escolha = st.selectbox("Limite (km):", [30, 50, 100], index=0)

    st.markdown("---")
    st.info("OBS: O app tentará reduzir chamadas à API usando um pré-filtro geodésico. Ainda assim, chamadas ao Google serão feitas para confirmar distâncias por rota.")

    if uploaded is not None:
        try:
            df_chamados = pd.read_excel(uploaded)
        except Exception as e:
            st.error("Erro ao ler a planilha. Verifique o arquivo.")
            df_chamados = None

        if df_chamados is not None:
            # verificar colunas obrigatórias
            if 'id_chamado' not in df_chamados.columns or 'endereco' not in df_chamados.columns:
                st.error("A planilha deve conter as colunas 'id_chamado' e 'endereco'.")
            else:
                total_chamados = len(df_chamados)
                total_tecn = len(df_tecnicos_para_busca)
                st.success(f"Planilha carregada: {total_chamados} chamados. Técnicos considerados: {total_tecn}.")

                if API_KEY is None:
                    st.error("Chave Google Maps não encontrada. Não é possível prosseguir.")
                else:
                    if st.button("Iniciar Cruzamento (Pré-filtro + Distance Matrix)"):
                        with st.spinner("Executando cruzamento — isso pode levar alguns minutos dependendo do volume e da quota da API..."):
                            # executar análise
                            df_resultado = analisar_chamados_vs_tecnicos(df_chamados, df_tecnicos_para_busca, API_KEY, limite_escolha, buffer_pct=0.20)
                            if df_resultado.empty:
                                st.info("Nenhum técnico encontrado dentro do limite selecionado para os chamados carregados.")
                            else:
                                st.success(f"Encontrados {len(df_resultado)} combinações chamado ↔ técnico dentro de {limite_escolha} km.")
                                st.dataframe(df_resultado.head(200))
                                # download
                                towrite = io.BytesIO()
                                df_resultado.to_excel(towrite, index=False, header=True)
                                towrite.seek(0)
                                st.download_button(label="Baixar relatório (Excel)", data=towrite, file_name=f'chamados_tecnicos_{limite_escolha}km.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

                                st.markdown("### Resumo por chamado")
                                resumo = df_resultado.groupby(['id_chamado', 'endereco_chamado']).agg({'tecnico': 'count'}).reset_index().rename(columns={'tecnico': 'qtde_tecnicos_disponiveis'})
                                st.dataframe(resumo)

                                st.markdown("### Amostra (primeiros 200 resultados)")
                                st.dataframe(df_resultado.head(200))
    else:
        st.info("Faça o upload da planilha de chamados para iniciar o cruzamento.")

# Rodapé
st.markdown("---")
st.markdown("<div style='text-align:center;'>Desenvolvido por Edmilson Carvalho - Edmilson.carvalho@globalhitss.com.br © 2025</div>", unsafe_allow_html=True)
