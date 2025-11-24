import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
import io
import plotly.express as px
import pydeck as pdk
from math import radians, sin, cos, sqrt, asin
import os
import numpy as np
import warnings

# Suprime FutureWarnings do Pandas para um Streamlit mais limpo
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- CONFIGURAÇÃO INICIAL E CSS ---
st.set_page_config(page_title="Localizador de Técnicos (v3.0 - Google Maps)", layout="wide") 

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
        margin-top: 5px;
    }
    /* Ajuste visual para o st.radio */
    div[data-testid="stRadio"] label {
        margin-right: 15px;
    }
</style>
""", unsafe_allow_html=True)


# --- VARIÁVEIS GLOBAIS ---
RAIOS = [30, 100, 200]
# CUSTO ATUALIZADO: R$ 1,00/km (ida) * 2 (ida e volta) = R$ 2,00/km
CUSTO_POR_KM = 2.0 

# --- FUNÇÕES ---

def haversine(lat1, lon1, lat2, lon2):
    """Calcula a distância em linha reta (Great-circle distance) entre dois pontos em km."""
    R = 6371  # Raio da Terra em km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c

def get_distance_matrix(origins, destinations, api_key):
    """Obtém a matriz de distância de carro (km e tempo) do Google Maps."""
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": "|".join(origins),
        "destinations": "|".join(destinations),
        "key": api_key,
        "mode": "driving",
        "language": "pt-BR",
    }
    response = requests.get(url, params=params)
    data = response.json()
    return data

@st.cache_data(show_spinner=False)
def geocodificar_endereco(endereco, api_key):
    """Converte um endereço em coordenadas (latitude e longitude)."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": endereco,
        "key": api_key
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return location['lat'], location['lng']
        else:
            return None, None
    except requests.exceptions.RequestException:
        return None, None

@st.cache_data(show_spinner=False)
def load_data(file_path):
    """Carrega os dados do arquivo Excel."""
    try:
        df = pd.read_excel(file_path)
        # Limpeza e padronização para evitar erros futuros
        for col in ['tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador']:
            if col not in df.columns:
                df[col] = '' # Garante que colunas essenciais existam
        
        # Converte coordenadas para numérico, tratando erros
        for col in ['latitude', 'longitude']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    except FileNotFoundError:
        st.error(f"Erro: O arquivo '{file_path}' não foi encontrado.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar ou processar a planilha: {e}")
        return pd.DataFrame()


def preencher_resultado_vazio(resultado):
    """Função auxiliar para preencher campos de técnico vazio na análise em lote."""
    resultado['Técnico_Mais_Próximo'] = 'N/A'
    resultado['Coordenador_Técnico'] = 'N/A'
    resultado['UF_Técnico'] = 'N/A'
    resultado['Distância_km'] = 'N/A'
    resultado['Tempo_Estimado'] = 'N/A'
    resultado['Custo_Estimado_RS'] = 'N/A'
    return resultado

# FUNÇÃO MODIFICADA PARA USAR O RAIO SELECIONADO E INCLUIR TEMPO/CUSTO
def encontrar_tecnico_proximo(endereco_cliente, api_key, df_filtrado, max_distance_km):
    """Encontra os técnicos mais próximos a um endereço de cliente."""
    
    df_validos = df_filtrado.dropna(subset=['latitude', 'longitude']).copy()
    
    if df_validos.empty:
        return None, None

    # 1. GEOCODIFICAR ENDEREÇO DO CLIENTE
    lat_cliente, lng_cliente = geocodificar_endereco(endereco_cliente, api_key)
    
    if lat_cliente is None:
        st.error(f"Não foi possível geocodificar o endereço do cliente: {endereco_cliente}")
        return None, None

    origem = f"{lat_cliente},{lng_cliente}"
    localizacao_cliente = {'lat': lat_cliente, 'lng': lng_cliente}

    # 2. CALCULAR DISTÂNCIAS E TEMPOS EM LOTE
    distancias_tempos = []
    
    destinos_por_lote = 25 
    for i in range(0, len(df_validos), destinos_por_lote):
        lote_df = df_validos.iloc[i : i + destinos_por_lote]
        destinos = [f"{lat},{lon}" for lat, lon in zip(lote_df['latitude'], lote_df['longitude'])]
        
        try:
            matrix_data = get_distance_matrix([origem], destinos, api_key)
        except requests.exceptions.RequestException:
            st.error("Erro de conexão ao calcular as distâncias.")
            return None, None
        
        if matrix_data["status"] != "OK":
            st.error(f"Erro na Google Maps Distance Matrix API: {matrix_data['status']}")
            return None, None
        
        for element in matrix_data["rows"][0]["elements"]:
            if element["status"] == "OK":
                distancia_km = element["distance"]["value"] / 1000
                tempo_text = element["duration"]["text"]
                tempo_seconds = element["duration"]["value"]
                
                distancias_tempos.append({
                    'distancia_km': distancia_km,
                    'tempo_text': tempo_text,
                    'tempo_seconds': tempo_seconds
                })
            else:
                distancias_tempos.append({
                    'distancia_km': float("inf"),
                    'tempo_text': "N/A",
                    'tempo_seconds': float("inf")
                })

    # 3. CONSOLIDAR RESULTADOS E FILTRAR
    df_validos["distancia_km"] = [d['distancia_km'] for d in distancias_tempos]
    df_validos["tempo_text"] = [d['tempo_text'] for d in distancias_tempos]
    df_validos["tempo_seconds"] = [d['tempo_seconds'] for d in distancias_tempos]
    
    # Cálculo de Custo R$ 2/km (ida e volta)
    df_validos["custo_rs"] = df_validos["distancia_km"] * CUSTO_POR_KM

    # Filtro dinâmico pelo raio selecionado
    df_dentro_limite = df_validos[df_validos["distancia_km"] <= max_distance_km]
    
    # Retorna todos os técnicos dentro do limite, ordenados
    return df_dentro_limite.sort_values("distancia_km"), localizacao_cliente

# LÓGICA DE BUSCA EM LOTE (Copiei do código novo)
@st.cache_data(show_spinner=False)
def processar_chamados_em_lote(df_chamados, df_tecnicos_base, api_key, max_distance_km, capacidade_diaria):
    """
    Processa chamados em lote usando pré-filtro Haversine e aplica a lógica de
    capacidade diária de atendimento.
    """
    
    if 'endereco' not in df_chamados.columns or df_chamados['endereco'].isnull().all():
        return None, "A planilha de chamados deve conter uma coluna chamada 'endereco' com os endereços a serem buscados."

    df_tecnicos_validos = df_tecnicos_base.dropna(subset=['latitude', 'longitude']).copy()
    df_resultados_finais = []
    
    total_chamados = len(df_chamados)
    chamados_processados = 0
    chamados_com_erro = 0
    chamados_otimizados = 0

    # Inicializa o controle de alocação de capacidade
    tecnicos_capacidade = {t: 0 for t in df_tecnicos_validos['tecnico'].unique()}

    # O Streamlit só mostra a barra de progresso se for chamada dentro da função (ou na thread principal)
    # Aqui, para manter o cache, removemos a barra de progresso e deixamos a mensagem simples
    # progress_bar = st.progress(0, text="Iniciando processamento dos chamados...")

    FATOR_FOLGA = 1.5 
    RAIO_MAXIMO_AEREO = max_distance_km * FATOR_FOLGA

    for index, row_chamado in df_chamados.iterrows():
        endereco_cliente = row_chamado['endereco']
        chamados_processados += 1

        if pd.isnull(endereco_cliente) or not endereco_cliente.strip():
            chamados_com_erro += 1
            row_chamado['Status'] = 'ERRO: Endereço vazio'
            df_resultados_finais.append(preencher_resultado_vazio(row_chamado.to_dict()))
            continue

        # 1. GEOCODIFICAR ENDEREÇO DO CHAMADO
        lat_cliente, lng_cliente = geocodificar_endereco(endereco_cliente, api_key)

        if lat_cliente is None:
            chamados_com_erro += 1
            resultado = row_chamado.to_dict()
            resultado['Status'] = 'ERRO: Falha na Geocodificação'
            df_resultados_finais.append(preencher_resultado_vazio(resultado))
            continue

        origem = f"{lat_cliente},{lng_cliente}"
        
        # 2. PRÉ-FILTRO POR DISTÂNCIA HAVERSINE (OTIMIZAÇÃO)
        df_temp = df_tecnicos_validos.copy()
        
        df_temp['distancia_aerea_km'] = df_temp.apply(
            lambda x: haversine(lat_cliente, lng_cliente, x['latitude'], x['longitude']), axis=1
        )
        
        df_candidatos = df_temp[df_temp['distancia_aerea_km'] <= RAIO_MAXIMO_AEREO].copy()

        if df_candidatos.empty:
            resultado = row_chamado.to_dict()
            resultado['Status'] = f'Nenhum técnico no raio AÉREO de {RAIO_MAXIMO_AEREO:.0f} km'
            df_resultados_finais.append(preencher_resultado_vazio(resultado))
            continue
            
        chamados_otimizados += 1
        
        # 3. CALCULAR DISTÂNCIAS REAIS APENAS PARA CANDIDATOS
        distancias_tempos = []
        destinos_por_lote = 25
        
        for i in range(0, len(df_candidatos), destinos_por_lote):
            lote_df = df_candidatos.iloc[i : i + destinos_por_lote]
            destinos = [f"{lat},{lon}" for lat, lon in zip(lote_df['latitude'], lote_df['longitude'])]
            
            try:
                matrix_data = get_distance_matrix([origem], destinos, api_key)
            except requests.exceptions.RequestException:
                for _ in range(len(lote_df)):
                    distancias_tempos.append({'distancia_km': float("inf"), 'tempo_text': "N/A", 'tempo_seconds': float("inf")})
                continue
            
            if matrix_data["status"] != "OK":
                for _ in range(len(lote_df)):
                    distancias_tempos.append({'distancia_km': float("inf"), 'tempo_text': "N/A", 'tempo_seconds': float("inf")})
                continue
                
            for element in matrix_data["rows"][0]["elements"]:
                if element["status"] == "OK":
                    distancias_tempos.append({
                        'distancia_km': element["distance"]["value"] / 1000,
                        'tempo_text': element["duration"]["text"],
                        'tempo_seconds': element["duration"]["value"]
                    })
                else:
                    distancias_tempos.append({
                        'distancia_km': float("inf"),
                        'tempo_text': "N/A",
                        'tempo_seconds': float("inf")
                    })
        
        # Consolida distâncias reais e filtra pelo raio
        df_candidatos["distancia_km"] = [d['distancia_km'] for d in distancias_tempos]
        df_candidatos["tempo_text"] = [d['tempo_text'] for d in distancias_tempos]
        df_candidatos["custo_rs"] = df_candidatos["distancia_km"] * CUSTO_POR_KM
        
        df_aptos = df_candidatos[df_candidatos["distancia_km"] <= max_distance_km].sort_values("distancia_km")

        # 4. APLICA LÓGICA DE CAPACIDADE E ALOCAÇÃO
        melhor_tecnico = None
        
        for idx_aptos, row_aptos in df_aptos.iterrows():
            tecnico_nome = row_aptos['tecnico']
            if capacidade_diaria == 0 or tecnicos_capacidade[tecnico_nome] < capacidade_diaria:
                melhor_tecnico = row_aptos
                tecnicos_capacidade[tecnico_nome] += 1
                break 
        
        # 5. CONSOLIDA O RESULTADO DO CHAMADO
        if melhor_tecnico is not None:
            
            resultado = row_chamado.to_dict()
            resultado['Status'] = f'Atendimento Alocado (Raio: {max_distance_km} km)'
            resultado['Técnico_Mais_Próximo'] = melhor_tecnico['tecnico']
            resultado['Coordenador_Técnico'] = melhor_tecnico['coordenador']
            resultado['UF_Técnico'] = melhor_tecnico['uf']
            resultado['Distância_km'] = f"{melhor_tecnico['distancia_km']:.2f}"
            resultado['Tempo_Estimado'] = melhor_tecnico['tempo_text']
            resultado['Custo_Estimado_RS'] = f"R$ {melhor_tecnico['custo_rs']:.2f}"
            
        else:
            resultado = row_chamado.to_dict()
            
            if not df_aptos.empty:
                 resultado['Status'] = f'Nenhum técnico disponível no raio (Todos no limite de {capacidade_diaria} chamados)'
            else:
                 resultado['Status'] = f'Nenhum técnico no raio de {max_distance_km} km (Real)'

            resultado = preencher_resultado_vazio(resultado)
            
        df_resultados_finais.append(resultado)
    
    df_final = pd.DataFrame(df_resultados_finais)
    
    # Adicionar coluna de resumo de alocação
    df_alocacao = pd.DataFrame(list(tecnicos_capacidade.items()), columns=['Técnico_Mais_Próximo', 'Chamados_Alocados_Tecnico'])
    df_final = pd.merge(df_final, df_alocacao, on='Técnico_Mais_Próximo', how='left').fillna({'Chamados_Alocados_Tecnico': 0})
    
    total_encontrado = len(df_final[df_final['Status'].str.contains('Alocado')])
    
    resumo = {
        "Total de Chamados na Planilha": total_chamados,
        f"Chamados Alocados (Considerando Capacidade e Raio)": total_encontrado,
        "Chamados Não Alocados": total_chamados - total_encontrado - chamados_com_erro,
        "Chamados com Erro (Endereço Inválido/Vazio)": chamados_com_erro,
        "Chamados Processados na Distance Matrix (Otimizados)": chamados_otimizados
    }
    
    return df_final, resumo

# --- LÓGICA DE LOGIN PRINCIPAL ---

def check_password_general(password_key, error_msg, key_input):
    """Verifica uma senha genérica do secrets, usando uma chave única para o input."""
    # Se a chave de senha não existir nos secrets (ex: deploy local sem secrets), permite o acesso
    if password_key not in st.secrets.get("auth", {}):
        return True 
    
    password = st.text_input("Por favor, insira a senha para acessar:", type="password", key=key_input)
    if password == st.secrets["auth"][password_key]:
        return True
    elif password:
        st.error(error_msg)
        return False
    return False


# --- INÍCIO DA EXECUÇÃO ---

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "editor_authenticated" not in st.session_state:
    st.session_state.editor_authenticated = False
if "lote_authenticated" not in st.session_state:
    st.session_state.lote_authenticated = False # NOVO ESTADO DE AUTENTICAÇÃO
if "raio_selecionado" not in st.session_state:
    st.session_state.raio_selecionado = 30 


# BLOCO DE LOGIN GERAL
if not st.session_state.authenticated:
    st.title("🔒 Acesso Restrito")
    # Usa a função generalizada
    if check_password_general("senha", "Senha incorreta. Tente novamente.", "global_auth_input"):
        st.session_state.authenticated = True
        st.rerun()
    st.stop()


# 1. CARREGAR DADOS E API KEY
df_tecnicos = load_data('tecnicos.xlsx')
if df_tecnicos.empty and "df_editavel" not in st.session_state:
     st.stop()
if "df_editavel" not in st.session_state:
    st.session_state.df_editavel = df_tecnicos.copy() # Cria a primeira cópia editável

# 2. CENTRALIZAÇÃO DA CHAVE DE API
try:
    API_KEY = st.secrets["api"]["google_maps"]
except KeyError:
    st.error("Chave de API do Google Maps não encontrada. Verifique o arquivo .streamlit/secrets.toml")
    API_KEY = None
    
# --- CONFIGURAÇÃO INICIAL DO SIDEBAR ---
st.sidebar.header("Filtros de Busca")


# 1. Raio Máximo de Busca 
st.sidebar.markdown("**Raio Máximo (km):**")
st.session_state.raio_selecionado = st.radio(
    "Escolha o Raio:",
    options=RAIOS,
    index=RAIOS.index(st.session_state.raio_selecionado) if st.session_state.raio_selecionado in RAIOS else 0,
    format_func=lambda x: f"{x} km", 
    horizontal=True,
    key='radio_raio' 
)
st.sidebar.markdown("---")


# Inicialização dos outros filtros
if "uf_selecionada" not in st.session_state: st.session_state.uf_selecionada = "Todos"
if "cidade_selecionada" not in st.session_state: st.session_state.cidade_selecionada = "Todas"
if "coordenador_selecionado" not in st.session_state: st.session_state.coordenador_selecionado = "Todos"

# Listas de opções para filtros
ufs = ["Todos"] + sorted(st.session_state.df_editavel['uf'].unique().tolist()) if 'uf' in st.session_state.df_editavel.columns and not st.session_state.df_editavel.empty else ["Todos"]
cidades_todas = ["Todas"] + sorted(st.session_state.df_editavel['cidade'].unique().tolist()) if 'cidade' in st.session_state.df_editavel.columns and not st.session_state.df_editavel.empty else ["Todas"]
coordenadores = ["Todos"] + sorted(st.session_state.df_editavel['coordenador'].unique().tolist()) if 'coordenador' in st.session_state.df_editavel.columns and not st.session_state.df_editavel.empty else ["Todos"]


# --- SIDEBAR (FILTROS) ---
with st.sidebar:
    
    # Filtros por UF, Cidade e Coordenador
    st.session_state.uf_selecionada = st.selectbox("Filtrar por UF:", ufs, index=ufs.index(st.session_state.uf_selecionada) if st.session_state.uf_selecionada in ufs else 0)
    
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        cidades_filtradas = ["Todas"] + sorted(st.session_state.df_editavel[st.session_state.df_editavel['uf'] == st.session_state.uf_selecionada]['cidade'].unique().tolist())
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
        st.session_state.raio_selecionado = 30
        st.rerun()
        
    st.markdown("---")
    st.markdown("**Opções de Visualização**")
    modo_exibicao = st.radio("Formato da Lista de Técnicos:", ["Tabela", "Colunas"], index=1)
# --------------------------------------------------------------------------


# --- Sistema de abas (ADICIONEI A ABA DE LOTE) ---
tab1, tab2, tab3, tab4 = st.tabs(["Busca Individual", "Análise de Dados", "Editor de Dados", "Análise de Chamados (Lote)"])

with tab1:
    st.title("Localizador de Técnicos")
    
    # --- APLICAR OS FILTROS ---
    df_filtrado = st.session_state.df_editavel.copy()
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == st.session_state.uf_selecionada]
    if st.session_state.cidade_selecionada and st.session_state.cidade_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['cidade'] == st.session_state.cidade_selecionada]
    if st.session_state.coordenador_selecionado and st.session_state.coordenador_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['coordenador'] == st.session_state.coordenador_selecionado]

    # --- LISTA DE TÉCNICOS FILTRADOS ---
    st.header("Lista de Técnicos Filtrados")
    if st.session_state.uf_selecionada != "Todos" or st.session_state.cidade_selecionada != "Todas" or st.session_state.coordenador_selecionado != "Todos":
        cols_display = ['tecnico', 'cidade', 'uf', 'coordenador']
        
        if modo_exibicao == "Tabela":
            st.dataframe(df_filtrado[cols_display], width='stretch')
        else:
            cols = st.columns(2)
            for i, row in df_filtrado.iterrows():
                with cols[i % 2]:
                    st.markdown(f"**{row['tecnico']}** - {row['cidade']}/{row['uf']}")
                    st.write(f"Coordenador: **{row.get('coordenador', 'Não informado')}**")
                    st.markdown("---")
    else:
        st.info("Utilize os filtros na barra lateral para ver uma lista de técnicos.")

    st.markdown("---")
    st.header("Busca por Distância (Logística)")

    # AVISO DE FILTRO E RESTRIÇÃO DE KM (AGORA DINÂMICO)
    if not df_filtrado.empty:
        st.info(f"A busca será restrita aos **{len(df_filtrado)}** técnicos selecionados e **apenas técnicos a até {st.session_state.raio_selecionado} km** serão listados.")
    else:
        st.warning("Não há técnicos nos filtros selecionados para realizar a busca por distância.")

    if API_KEY:
        endereco_cliente = st.text_input("Endereço do Chamado (Ponto de Origem)", help="Ex: Av. Paulista, 1000, São Paulo, SP")
        
        if st.button("Buscar Técnico Mais Próximo", key='btn_busca_individual'):
            if endereco_cliente:
                with st.spinner(f"Buscando técnicos a até {st.session_state.raio_selecionado} km..."):
                    
                    # Usa o raio selecionado
                    tecnicos_proximos, localizacao_cliente = encontrar_tecnico_proximo(
                        endereco_cliente, 
                        API_KEY, 
                        df_filtrado, 
                        st.session_state.raio_selecionado # Raio dinâmico
                    )
                    
                    if tecnicos_proximos is not None and not tecnicos_proximos.empty:
                        st.success(f"Busca concluída! Encontrados {len(tecnicos_proximos)} técnicos a até {st.session_state.raio_selecionado} km de distância.")
                        
                        col_mapa, col_lista = st.columns([1, 1]) 
                        
                        with col_mapa:
                            st.subheader("📍 Mapa dos Resultados (Google Maps)")
                            
                            tecnicos_coords = [
                                {'lat': row['latitude'], 'lng': row['longitude'], 'title': row['tecnico']}
                                for _, row in tecnicos_proximos.iterrows()
                            ]
                            
                            cliente_coords = {'lat': localizacao_cliente['lat'], 'lng': localizacao_cliente['lng']}
                            
                            # CÓDIGO HTML DO MAPA (MANTIDO)
                            map_html = f"""
                            <!DOCTYPE html>
                            <html>
                            <head>
                                <style>
                                    #map {{
                                        height: 500px;
                                        width: 100%;
                                    }}
                                </style>
                            </head>
                            <body>
                                <div id="map"></div>
                                <script>
                                    function initMap() {{
                                        const cliente = {{ lat: {cliente_coords['lat']}, lng: {cliente_coords['lng']} }};
                                        const map = new google.maps.Map(document.getElementById("map"), {{
                                            zoom: 10,
                                            center: cliente,
                                        }});

                                        // Marcador do Cliente (Vermelho - icon14)
                                        const cliente_marker = new google.maps.Marker({{
                                            position: cliente,
                                            map: map,
                                            title: "Cliente (Origem)",
                                            icon: "http://googlemaps.com/mapfiles/kml/pal2/icon14.png" // Ícone Vermelho
                                        }});

                                        // Marcadores dos Técnicos (Azul - icon4)
                                        const tecnicos = {tecnicos_coords};
                                        tecnicos.forEach((tecnico) => {{
                                            new google.maps.Marker({{
                                                position: {{ lat: tecnico.lat, lng: tecnico.lng }},
                                                map: map,
                                                title: tecnico.title,
                                                icon: "http://googlemaps.com/mapfiles/kml/pal2/icon4.png" // Ícone Azul
                                            }});
                                        }});
                                    }}
                                </script>
                                <script async defer src="https://maps.googleapis.com/maps/api/js?key={API_KEY}&callback=initMap">
                                </script>
                            </body>
                            </html>
                            """
                            components.html(map_html, height=550)


                        with col_lista:
                            st.subheader(f"🛠️ Técnicos (Até {st.session_state.raio_selecionado} km)")
                            
                            st.markdown(f"**Custo Estimado:** R$ {CUSTO_POR_KM:.2f} por KM (Considerando ida e volta)")
                            
                            # Preparação para exportação (AGORA COM TEMPO/CUSTO)
                            df_to_export = tecnicos_proximos[[
                                'tecnico', 'coordenador', 'cidade', 'uf', 
                                'distancia_km', 'tempo_text', 'custo_rs', 
                                'email_coordenador'
                            ]].copy()
                            df_to_export['distancia_km'] = df_to_export['distancia_km'].round(2)
                            df_to_export['custo_rs'] = df_to_export['custo_rs'].round(2)
                            
                            df_to_export.rename(columns={
                                'tecnico': 'Técnico',
                                'coordenador': 'Coordenador',
                                'distancia_km': 'Distância (km)',
                                'tempo_text': 'Tempo Estimado',
                                'custo_rs': f'Custo Estimado (R$ {CUSTO_POR_KM:.2f}/km - Ida e Volta)',
                            }, inplace=True)
                            
                            # Botão de download
                            towrite = io.BytesIO()
                            df_to_export.to_excel(towrite, index=False, header=True)
                            towrite.seek(0)
                            st.download_button(
                                label="Exportar Resultados para Excel",
                                data=towrite,
                                file_name=f'tecnicos_proximos_custo_{st.session_state.raio_selecionado}km.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            )

                            st.markdown("---")
                            
                            # Lista formatada em colunas (AGORA COM TEMPO/CUSTO)
                            cols_tecnicos = st.columns(2)
                            
                            for i, row in tecnicos_proximos.reset_index(drop=True).iterrows():
                                with cols_tecnicos[i % 2]:
                                    st.markdown(f"**{row['tecnico']}** - {row['cidade']}/{row['uf']}")
                                    st.markdown(f"**Distância: {row['distancia_km']:.2f} km**") 
                                    st.markdown(f"Coordenador: **{row['coordenador']}**") 
                                    st.write(f"Tempo Estimado: {row['tempo_text']}")
                                    st.write(f"Custo Estimado: R$ {row['custo_rs']:.2f}")
                                    
                                    email_coordenador = row.get('email_coordenador')
                                    if email_coordenador:
                                        st.markdown(
                                            f"""
                                            <div class="button-group">
                                                <a href="https://teams.microsoft.com/l/chat/0/0?users={email_coordenador}" target="_blank" style="background-color: #28a745;">📞 Falar com Coordenador</a>
                                                <a href="mailto:{email_coordenador}" target="_blank" style="background-color: #007bff;">✉️ Enviar E-mail</a>
                                            </div>
                                            """, 
                                            unsafe_allow_html=True
                                        )
                                    st.markdown("---")


                    else:
                        st.info(f"Nenhum técnico encontrado no universo filtrado que esteja a até {st.session_state.raio_selecionado} km de distância do endereço.")
            else:
                st.warning("Por favor, digite um endereço para iniciar a busca.")


with tab2:
    # --- DASHBOARD DE ESTATÍSTICAS ---
    st.header("📊 Análise de Dados dos Técnicos")
    
    df_analise = st.session_state.df_editavel.copy()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de Técnicos", len(df_analise))
    with col2:
        st.metric("Total de UFs", len(df_analise['uf'].unique()))
    with col3:
        st.metric("Total de Cidades", len(df_analise['cidade'].unique()))

    st.markdown("---")
    st.subheader("Análise de Dados Faltantes")
    tecnicos_sem_coord = df_analise['latitude'].isnull().sum()
    tecnicos_totais = len(df_analise)
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

    # Gráficos
    st.subheader("Gráfico: Técnicos por UF")
    uf_counts = df_analise['uf'].value_counts().reset_index()
    uf_counts.columns = ['UF', 'Quantidade']
    fig_uf = px.bar(uf_counts, x='UF', y='Quantidade', title="Técnicos por UF", color='UF')
    st.plotly_chart(fig_uf, use_container_width=True)
    
    st.subheader("Gráfico: Técnicos por Coordenador")
    coordenador_counts = df_analise['coordenador'].value_counts().reset_index()
    coordenador_counts.columns = ['Coordenador', 'Quantidade']
    fig_coordenador = px.bar(coordenador_counts, x='Coordenador', y='Quantidade', title="Técnicos por Coordenador", color='Coordenador')
    st.plotly_chart(fig_coordenador, use_container_width=True)
    
    # --- MAPA INTERATIVO ---
    st.markdown("---")
    st.subheader("Mapa Interativo de Técnicos")
    st.info("Passe o mouse sobre os pontos para ver os detalhes dos técnicos.")
    
    df_mapa = df_analise.dropna(subset=['latitude', 'longitude']).copy()
    
    for col in ['tecnico', 'coordenador', 'cidade']:
        if col in df_mapa.columns:
            df_mapa[col] = df_mapa[col].fillna('').astype(str)

    if not df_mapa.empty:
        view_state = pdk.ViewState(
            latitude=df_mapa['latitude'].mean(),
            longitude=df_mapa['longitude'].mean(),
            zoom=4,
            pitch=50,
        )
        
        scatterplot_layer = pdk.Layer(
            'ScatterplotLayer',
            data=df_mapa,
            get_position='[longitude, latitude]',
            get_color='[0, 102, 204, 160]', # Azul customizado
            get_radius=15000,
        )

        r = pdk.Deck(
            layers=[scatterplot_layer],
            initial_view_state=view_state,
            tooltip={
                "html": "<b>Técnico:</b> {tecnico}<br/>"
                        "<b>Coordenador:</b> {coordenador}<br/>"
                        "<b>Cidade:</b> {cidade}<br/>",
                "style": {
                    "backgroundColor": "steelblue",
                    "color": "white"
                }
            }
        )
        st.pydeck_chart(r)
    else:
        st.info("Nenhum técnico com coordenadas válidas para exibir no mapa.")

with tab3:
    st.header("📝 Editor de Dados dos Técnicos")

    # --- AUTENTICAÇÃO SECUNDÁRIA PARA O EDITOR ---
    if not st.session_state.editor_authenticated:
        st.warning("Esta seção requer uma autenticação adicional para edição de dados.")
        # Chave "editor_senha" no secrets
        if check_password_general("editor_senha", "Senha do Editor incorreta. Tente novamente.", "editor_auth_input"):
            st.session_state.editor_authenticated = True
            st.rerun() 
    
    if st.session_state.editor_authenticated:
        st.info("⚠️ **IMPORTANTE:** As alterações feitas aqui são salvas APENAS na sessão atual. Para tornar permanente, use o botão de exportação ao final.")
        
        # 1. EDIÇÃO MANUAL (st.data_editor)
        df_editable = st.data_editor(
            st.session_state.df_editavel,
            column_config={
                "latitude": st.column_config.NumberColumn("Latitude", format="%.6f"),
                "longitude": st.column_config.NumberColumn("Longitude", format="%.6f"),
                "endereco": st.column_config.TextColumn("Endereço Completo", width="large")
            },
            num_rows="dynamic",
            width='stretch', 
            key="data_editor"
        )
        
        # 2. BOTÃO PARA SALVAR ALTERAÇÕES MANUAIS NO ESTADO DA SESSÃO
        if st.button("Salvar Alterações Manuais na Sessão", key='btn_save_manual'):
            st.session_state.df_editavel = df_editable.copy()
            st.success("Alterações manuais salvas com sucesso na sessão!")
            st.rerun() 

        
        st.markdown("---")
        st.subheader("Ferramenta de Geocodificação Automática")
        
        df_to_geocode = df_editable[df_editable['latitude'].isnull() | df_editable['longitude'].isnull()]
        
        col_geocode, col_export = st.columns([2, 1])
        
        with col_geocode:
            if st.button(f"Geocodificar {len(df_to_geocode)} Endereço(s) Sem Coordenadas", disabled=df_to_geocode.empty or API_KEY is None, key='btn_geocode'):
                if API_KEY:
                    with st.spinner(f"Geocodificando {len(df_to_geocode)} endereços. Isso pode levar um tempo e consumir API key..."):
                        
                        df_updated = df_editable.copy()
                        count_updated = 0
                        
                        for index, row in df_to_geocode.iterrows():
                            # Usa endereço e cidade para melhorar a busca
                            endereco_completo = f"{row.get('endereco', '')}, {row.get('cidade', '')}"
                            
                            if endereco_completo.strip() and endereco_completo.strip() != ',':
                                lat, lng = geocodificar_endereco(endereco_completo, API_KEY)
                                
                                if lat is not None:
                                    df_updated.loc[index, 'latitude'] = lat
                                    df_updated.loc[index, 'longitude'] = lng
                                    count_updated += 1

                        st.session_state.df_editavel = df_updated
                        
                        st.success(f"Concluído! **{count_updated}** coordenadas de técnicos foram atualizadas. A base de dados na sessão foi atualizada.")
                        st.rerun() 
                else:
                    st.error("Chave de API não está configurada. Não é possível geocodificar.")
        
        with col_export:
            # 3. BOTÃO DE EXPORTAÇÃO
            st.markdown("""
            <p style='color:red; font-size: 12px; margin-top: 10px;'>ATENÇÃO: Baixe e substitua o arquivo original para manter as alterações permanentemente!</p>
            """, unsafe_allow_html=True)
            
            df_final_export = st.session_state.df_editavel 
            towrite_tecnicos = io.BytesIO()
            df_final_export.to_excel(towrite_tecnicos, index=False, header=True)
            towrite_tecnicos.seek(0)
            
            st.download_button(
                label="Baixar Base Atualizada (Excel)",
                data=towrite_tecnicos,
                file_name='tecnicos_atualizado.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
    else:
        pass # Autenticação pendente


# =========================================================================
# === ABA: ANÁLISE DE CHAMADOS EM LOTE === (NOVA ABA COM AUTENTICAÇÃO)
# =========================================================================
with tab4:
    st.title("Análise de Chamados em Lote")

    # --- NOVO BLOCO DE AUTENTICAÇÃO PARA A ABA DE LOTE ---
    if not st.session_state.lote_authenticated:
        st.header("🔒 Acesso Restrito ao Processamento em Lote")
        st.warning("Esta seção consome cotas da API do Google Maps. É necessária a mesma senha do Editor para acesso.")
        # Usa a senha do editor ("editor_senha") para autenticar o acesso à aba de lote
        if check_password_general("editor_senha", "Senha do Editor/Lote incorreta. Tente novamente.", "lote_auth_input"):
            st.session_state.lote_authenticated = True
            st.rerun() 
        st.stop()
    # --- FIM DO BLOCO DE AUTENTICAÇÃO ---

    
    st.header("Confrontar Planilha de Chamados com Base de Técnicos")
    st.warning(f"Custo de Distância por KM: R$ {CUSTO_POR_KM:.2f} (Considerando ida e volta). Este recurso consome cotas da Google Maps API rapidamente. A otimização por distância aérea foi aplicada para reduzir o consumo.")
    
    st.markdown("---")
    st.subheader("Configurações da Análise")
    
    col_raio, col_capacidade = st.columns(2)
    
    with col_raio:
        raio_lote = st.select_slider(
            "1. Raio Máximo de Atendimento (km):",
            options=[10, 20, 30, 50, 100, 200],
            value=st.session_state.raio_selecionado
        )
    
    with col_capacidade:
        capacidade_diaria = st.number_input(
            "2. Capacidade Máxima Diária por Técnico (0 = Ilimitado):",
            min_value=0,
            value=5,
            step=1,
            help="Defina o número máximo de chamados que um técnico pode receber nesta alocação."
        )
    
    st.markdown("---")
    st.subheader("3. Upload da Planilha de Chamados")
    st.info("A planilha DEVE conter uma coluna chamada **'endereco'** com os endereços dos chamados.")
    
    uploaded_chamados = st.file_uploader(
        "Carregar Planilha de Chamados (.xlsx):", 
        type=['xlsx'], 
        key='upload_chamados'
    )
    
    if uploaded_chamados is not None:
        try:
            df_chamados = pd.read_excel(uploaded_chamados)
            st.success(f"Planilha de chamados carregada com sucesso! Total de {len(df_chamados)} chamados.")
            
            if st.button(f"Iniciar Análise de Confronto e Alocação (Raio: {raio_lote} km | Capacidade: {capacidade_diaria})", key='btn_confronto'):
                if API_KEY and not st.session_state.df_editavel.empty:
                    
                    # Usa uma cópia dos dados editáveis
                    with st.spinner("Processando chamados em lote. Isso pode levar alguns minutos..."):
                        df_resultados, resumo = processar_chamados_em_lote(
                            df_chamados.copy(), 
                            st.session_state.df_editavel.copy(), 
                            API_KEY, 
                            raio_lote,
                            capacidade_diaria
                        )
                    
                    st.markdown("---")
                    st.subheader("4. Resultados da Análise de Alocação")
                    
                    col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)
                    col_sum1.metric(label="Total Chamados", value=resumo['Total de Chamados na Planilha'])
                    col_sum2.metric(label=f"Alocados (Capacidade & Raio)", value=resumo[f"Chamados Alocados (Considerando Capacidade e Raio)"])
                    col_sum3.metric(label="Não Alocados", value=resumo["Chamados Não Alocados"])
                    col_sum4.metric(label="Otimizados (Economia API)", value=resumo["Chamados Processados na Distance Matrix (Otimizados)"])


                    st.markdown("### Tabela Detalhada dos Resultados e Carga de Trabalho")
                    
                    df_resultados_sorted = df_resultados.sort_values(by=['Status', 'Distância_km'], ascending=[False, True])

                    st.dataframe(df_resultados_sorted, width='stretch')
                    
                    st.markdown("### Resumo da Carga de Trabalho por Técnico")
                    
                    df_carga = df_resultados_sorted[df_resultados_sorted['Técnico_Mais_Próximo'] != 'N/A'].groupby(['Técnico_Mais_Próximo', 'Coordenador_Técnico'])['Técnico_Mais_Próximo'].size().reset_index(name='Total_Alocado_Nesta_Busca')
                    
                    st.dataframe(df_carga.sort_values(by='Total_Alocado_Nesta_Busca', ascending=False), width='stretch')

                    towrite_chamados = io.BytesIO()
                    df_resultados.to_excel(towrite_chamados, index=False, header=True)
                    towrite_chamados.seek(0)
                    st.download_button(
                        label="Exportar Resultados (Excel)",
                        data=towrite_chamados,
                        file_name='analise_chamados_alocacao_final.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    
                else:
                    st.error("Erro: Verifique se a Chave API e a Base de Técnicos (na aba Editor de Dados) foram carregadas corretamente.")
        
        except Exception as e:
            st.error(f"Erro ao ler a planilha de chamados. Verifique o formato do arquivo: {e}")
# =========================================================================

# Rodapé com informações do desenvolvedor (Mantido)
st.markdown("---")
st.markdown("<div style='text-align:center;'>Desenvolvido por Edmilson Carvalho - Edmilson.carvalho@globalhitss.com.br © 2025</div>", unsafe_allow_html=True)