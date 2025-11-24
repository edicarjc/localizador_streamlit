import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
import io
import plotly.express as px
from math import radians, sin, cos, sqrt, asin
import os
import numpy as np
import warnings
import json
from pandas.errors import EmptyDataError 
from datetime import datetime

# Suprime FutureWarnings do Pandas para um Streamlit mais limpo
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- CONFIGURAÇÃO INICIAL E CSS ---
# Título atualizado para refletir a mudança de API
st.set_page_config(page_title="Localizador de Técnicos (v3.0 - Open Source)", layout="wide") 

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
    /* Estilo para o dataframe editável */
    .stDataFrame {
        height: 600px !important; 
    }
</style>
""", unsafe_allow_html=True)


# --- VARIÁVEIS GLOBAIS ---
RAIOS = [30, 100, 200]
# CUSTO ATUALIZADO: R$ 1,00/km (ida) * 2 (ida e volta) = R$ 2,00/km
CUSTO_POR_KM = 2.0 
ARQUIVO_TECNICOS = 'tecnicos.xlsx'

# --- FUNÇÕES ---

def haversine(lat1, lon1, lat2, lon2):
    """Calcula a distância em linha reta (Great-circle distance) entre dois pontos em km."""
    R = 6371 # Raio da Terra em km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c

# --- FUNÇÕES DE API SUBSTITUÍDAS ---

@st.cache_data(show_spinner=False)
def geocodificar_endereco(endereco): # USA NOMINATIM (GRATUITO/OSM)
    """
    Converte um endereço em coordenadas (latitude e longitude) usando a API
    gratuita do Nominatim (OpenStreetMap).
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": endereco,
        "format": "json",
        "limit": 1,
        "addressdetails": 0 # Diminui o payload
    }
    # Adicionar um User-Agent é uma boa prática
    headers = {'User-Agent': 'LocalizadorDeTecnicosApp/1.0 (Streamlit/Python)'} 
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status() # Lança exceção para códigos de erro HTTP
        data = response.json()
        
        if data:
            lat = float(data[0]['lat'])
            lng = float(data[0]['lon'])
            return lat, lng
        else:
            return None, None
    except requests.exceptions.Timeout:
        # st.error("Tempo limite excedido para geocodificação (Nominatim).")
        return None, None
    except requests.exceptions.RequestException:
        # st.error(f"Erro na requisição Nominatim: {e}") 
        return None, None
    except Exception:
        return None, None

@st.cache_data(show_spinner=False) # Adição do cache para evitar recálculo para o mesmo par de coordenadas.
def get_route_distance_osrm(origem_lat, origem_lng, destino_lat, destino_lng):
    """
    Obtém a distância de carro (km) e tempo (texto e segundos) do OSRM (GRATUITO/OSM).
    Substitui o Google Maps Distance Matrix.
    """
    # Serviço OSRM Público para Rotas
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lng},{origem_lat};{destino_lng},{destino_lat}"
    
    params = {
        "steps": "false", 
        "alternatives": "false",
        "geometries": "geojson",
        "overview": "false"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == "Ok":
            distance_meters = data["routes"][0]["distance"]
            duration_seconds = data["routes"][0]["duration"]
            
            # Conversão para km
            distancia_km = distance_meters / 1000
            
            # Formatação simples de tempo (em minutos)
            minutos = int(duration_seconds // 60)
            tempo_text = f"{minutos} min"
            
            return distancia_km, tempo_text, duration_seconds
        else:
            # Retorna infinito se a rota não puder ser calculada (ex: pontos no mar)
            return float("inf"), "N/A", float("inf") 
    except requests.exceptions.Timeout:
        return float("inf"), "N/A", float("inf")
    except (requests.exceptions.RequestException, KeyError, IndexError, TypeError):
        return float("inf"), "N/A", float("inf")

# --- FIM DAS FUNÇÕES DE API SUBSTITUÍDAS ---


@st.cache_data(show_spinner=False)
def load_data(file_path):
    """Carrega os dados do arquivo Excel."""
    try:
        df = pd.read_excel(file_path)
        # Limpeza e padronização para evitar erros futuros
        cols_default = ['tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador']
        for col in cols_default:
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
    except EmptyDataError:
        st.error(f"Erro: O arquivo '{file_path}' está vazio.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar ou processar a planilha: {e}")
        return pd.DataFrame()

def save_data(df, file_path):
    """Salva os dados de volta para o arquivo Excel."""
    try:
        df.to_excel(file_path, index=False)
        st.success("Dados salvos com sucesso!")
        return True
    except Exception as e:
        st.error(f"Erro ao salvar a planilha: {e}")
        return False

def preencher_resultado_vazio(resultado):
    """Função auxiliar para preencher campos de técnico vazio na análise em lote."""
    resultado['Técnico_Mais_Próximo'] = 'N/A'
    resultado['Coordenador_Técnico'] = 'N/A'
    resultado['UF_Técnico'] = 'N/A'
    resultado['Distância_km'] = 'N/A'
    resultado['Tempo_Estimado'] = 'N/A'
    resultado['Custo_Estimado_RS'] = 'N/A'
    resultado['Chamados_Alocados_Tecnico'] = 0 # Adicionado para garantir a coluna no merge
    return resultado

# FUNÇÃO MODIFICADA PARA USAR OSRM
def encontrar_tecnico_proximo(endereco_cliente, df_filtrado, max_distance_km):
    """
    Encontra os técnicos mais próximos a um endereço de cliente usando 
    geocodificação Nominatim e rotas de carro OSRM.
    """
    
    df_validos = df_filtrado.dropna(subset=['latitude', 'longitude']).copy()
    
    if df_validos.empty:
        return None, None

    # 1. GEOCODIFICAR ENDEREÇO DO CLIENTE (USA NOMINATIM)
    lat_cliente, lng_cliente = geocodificar_endereco(endereco_cliente)
    
    if lat_cliente is None:
        # st.error(f"Não foi possível geocodificar o endereço do cliente: {endereco_cliente}")
        return None, None

    localizacao_cliente = {'lat': lat_cliente, 'lng': lng_cliente}

    # 2. PRÉ-FILTRO HAVERSINE PARA OTIMIZAÇÃO (SEM CHAMADA DE API)
    FATOR_FOLGA = 1.5  
    RAIO_MAXIMO_AEREO = max_distance_km * FATOR_FOLGA

    df_temp = df_validos.copy()
    df_temp['distancia_aerea_km'] = df_temp.apply(
        lambda x: haversine(lat_cliente, lng_cliente, x['latitude'], x['longitude']), axis=1
    )
    df_candidatos = df_temp[df_temp['distancia_aerea_km'] <= RAIO_MAXIMO_AEREO].copy()

    if df_candidatos.empty:
        return pd.DataFrame(), localizacao_cliente # Retorna vazio, mas com localização do cliente

    # 3. CALCULAR DISTÂNCIAS E TEMPOS (USA OSRM)
    distancias_tempos = []
    
    for index, row in df_candidatos.iterrows():
        dist_km, tempo_text, tempo_seconds = get_route_distance_osrm(
            lat_cliente, lng_cliente, row['latitude'], row['longitude']
        )
        
        distancias_tempos.append({
            'index': index,
            'distancia_km': dist_km,
            'tempo_text': tempo_text,
            'tempo_seconds': tempo_seconds
        })

    df_rotas = pd.DataFrame(distancias_tempos).set_index('index')
    
    # 4. CONSOLIDAR RESULTADOS E FILTRAR
    df_candidatos = df_candidatos.join(df_rotas)
    
    # Cálculo de Custo R$ 2/km (ida e volta)
    df_candidatos["custo_rs"] = df_candidatos["distancia_km"] * CUSTO_POR_KM

    # Filtro dinâmico pelo raio selecionado (usando a distância de carro OSRM)
    df_dentro_limite = df_candidatos[df_candidatos["distancia_km"] <= max_distance_km]
    
    # Retorna todos os técnicos dentro do limite, ordenados
    return df_dentro_limite.sort_values("distancia_km"), localizacao_cliente

# LÓGICA DE BUSCA EM LOTE (MODIFICADA PARA USAR OSRM)
@st.cache_data(show_spinner=False)
def processar_chamados_em_lote(df_chamados, df_tecnicos_base, max_distance_km, capacidade_diaria):
    """
    Processa chamados em lote usando pré-filtro Haversine e a API OSRM para rotas.
    Aplicação da lógica de capacidade diária de atendimento.
    """
    
    if 'endereco' not in df_chamados.columns or df_chamados['endereco'].isnull().all():
        return None, "A planilha de chamados deve conter uma coluna chamada 'endereco' com os endereços a serem buscados."

    df_tecnicos_validos = df_tecnicos_base.dropna(subset=['latitude', 'longitude']).copy()
    df_resultados_finais = []
    
    total_chamados = len(df_chamados)
    chamados_com_erro = 0
    chamados_otimizados = 0

    # Inicializa o controle de alocação de capacidade
    tecnicos_capacidade = {t: 0 for t in df_tecnicos_validos['tecnico'].unique()}

    FATOR_FOLGA = 1.5  
    RAIO_MAXIMO_AEREO = max_distance_km * FATOR_FOLGA

    # Usa o st.progress para dar feedback visual no processamento
    progress_bar = st.progress(0, text="Processando 0% dos chamados...")
    
    for i, row_chamado in df_chamados.iterrows():
        endereco_cliente = row_chamado['endereco']
        
        progress_bar.progress((i + 1) / total_chamados, text=f"Processando chamado {i + 1} de {total_chamados}...")

        if pd.isnull(endereco_cliente) or not endereco_cliente.strip():
            chamados_com_erro += 1
            row_chamado['Status'] = 'ERRO: Endereço vazio'
            df_resultados_finais.append(preencher_resultado_vazio(row_chamado.to_dict()))
            continue

        # 1. GEOCODIFICAR ENDEREÇO DO CHAMADO (USA NOMINATIM)
        lat_cliente, lng_cliente = geocodificar_endereco(endereco_cliente)

        if lat_cliente is None:
            chamados_com_erro += 1
            resultado = row_chamado.to_dict()
            resultado['Status'] = 'ERRO: Falha na Geocodificação'
            df_resultados_finais.append(preencher_resultado_vazio(resultado))
            continue

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
        
        # 3. CALCULAR DISTÂNCIAS REAIS APENAS PARA CANDIDATOS (USA OSRM)
        distancias_reais = []
        
        for idx_candidato, row_candidato in df_candidatos.iterrows():
            # Chamada OSRM (pode ser lenta)
            dist_km, tempo_text, tempo_seconds = get_route_distance_osrm(
                lat_cliente, lng_cliente, row_candidato['latitude'], row_candidato['longitude']
            )
            distancias_reais.append({
                'index': idx_candidato,
                'distancia_km': dist_km,
                'tempo_text': tempo_text,
                'tempo_seconds': tempo_seconds
            })

        df_rotas = pd.DataFrame(distancias_reais).set_index('index')
        df_candidatos = df_candidatos.join(df_rotas)
        
        # Cálculo de Custo R$ 2/km (ida e volta)
        df_candidatos["custo_rs"] = df_candidatos["distancia_km"] * CUSTO_POR_KM
        
        # Filtra pelo raio real (distância de carro OSRM)
        df_aptos = df_candidatos[df_candidatos["distancia_km"] <= max_distance_km].sort_values("distancia_km")

        # 4. APLICA LÓGICA DE CAPACIDADE E ALOCAÇÃO
        melhor_tecnico = None
        
        for _, row_aptos in df_aptos.iterrows():
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
    
    progress_bar.empty() # Remove a barra de progresso no final
    
    df_final = pd.DataFrame(df_resultados_finais)
    
    # Adicionar coluna de resumo de alocação
    df_alocacao = pd.DataFrame(list(tecnicos_capacidade.items()), columns=['Técnico_Mais_Próximo', 'Chamados_Alocados_Tecnico'])
    
    # Preenche 'Técnico_Mais_Próximo' com os nomes para o merge
    df_final['Técnico_Mais_Próximo'] = df_final['Técnico_Mais_Próximo'].replace('N/A', np.nan) 
    
    df_final = pd.merge(df_final, df_alocacao, on='Técnico_Mais_Próximo', how='left').fillna({'Chamados_Alocados_Tecnico': 0})
    
    # Ajusta o tipo da coluna
    df_final['Chamados_Alocados_Tecnico'] = df_final['Chamados_Alocados_Tecnico'].astype(int)
    
    total_encontrado = len(df_final[df_final['Status'].str.contains('Alocado')])
    
    resumo = {
        "Total de Chamados na Planilha": total_chamados,
        f"Chamados Alocados (Considerando Capacidade e Raio)": total_encontrado,
        "Chamados Não Alocados (Fora do Raio ou Sem Capacidade)": total_chamados - total_encontrado - chamados_com_erro,
        "Chamados com Erro (Endereço Inválido/Vazio/Geocod.)": chamados_com_erro,
        "Chamados Processados na Rota OSRM (Otimizados)": chamados_otimizados
    }
    
    return df_final, resumo

# --- LÓGICA DE LOGIN PRINCIPAL ---

def check_password_general(password_key, error_msg, key_input):
    """Verifica uma senha genérica do secrets, usando uma chave única para o input."""
    # Se a chave de senha não existir nos secrets (ex: deploy local sem secrets), permite o acesso
    if st.secrets.get("auth", {}).get(password_key) is None:
        return True 
    
    password = st.text_input("Por favor, insira a senha para acessar:", type="password", key=key_input)
    if password == st.secrets["auth"][password_key]:
        return True
    elif password:
        st.error(error_msg)
        return False
    return False

def reset_df_editavel():
    """Recarrega o dataframe de técnicos da planilha original."""
    st.session_state.df_editavel = load_data(ARQUIVO_TECNICOS).copy()
    st.cache_data.clear() # Limpa o cache para garantir que os dados de rotas sejam recarregados (se necessário)

# --- INÍCIO DA EXECUÇÃO ---

if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "editor_authenticated" not in st.session_state: st.session_state.editor_authenticated = False
if "raio_selecionado" not in st.session_state: st.session_state.raio_selecionado = 30 
if "df_editavel" not in st.session_state: st.session_state.df_editavel = pd.DataFrame() # Inicialização

# BLOCO DE LOGIN GERAL
if not st.session_state.authenticated:
    st.title("🔒 Acesso Restrito")
    # Tenta usar a senha 'senha' ou permite acesso se a senha não estiver no secrets
    if check_password_general("senha", "Senha de acesso principal incorreta.", "global_auth_input"):
        st.session_state.authenticated = True
        st.rerun()
    st.stop()


# 1. CARREGAR DADOS E REMOVER CHAVE DE API DO GOOGLE
if st.session_state.df_editavel.empty:
    df_tecnicos_temp = load_data(ARQUIVO_TECNICOS)
    if df_tecnicos_temp.empty:
        st.warning("O arquivo de técnicos está vazio ou não pode ser carregado. Por favor, faça o upload de uma planilha na aba 'Editor de Dados'.")
        # Cria um DataFrame mínimo para não quebrar a aplicação.
        st.session_state.df_editavel = pd.DataFrame(columns=['tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador', 'latitude', 'longitude'])
    else:
        st.session_state.df_editavel = df_tecnicos_temp.copy()

API_KEY = None # Confirma a remoção do Google API Key

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

# Inicialização e extração das opções de filtro
if 'df_editavel' in st.session_state and not st.session_state.df_editavel.empty:
    df_temp = st.session_state.df_editavel.copy()
    ufs = ["Todos"] + sorted(df_temp['uf'].astype(str).unique().tolist())
    cidades_todas = ["Todas"] + sorted(df_temp['cidade'].astype(str).unique().tolist())
    coordenadores = ["Todos"] + sorted(df_temp['coordenador'].astype(str).unique().tolist())
    
    # Remove 'nan' se houver
    ufs = [u for u in ufs if u != 'nan']
    cidades_todas = [c for c in cidades_todas if c != 'nan']
    coordenadores = [c for c in coordenadores if c != 'nan']
else:
    ufs = ["Todos"]
    cidades_todas = ["Todas"]
    coordenadores = ["Todos"]

# Inicialização dos estados para filtros
if "uf_selecionada" not in st.session_state: st.session_state.uf_selecionada = "Todos"
if "cidade_selecionada" not in st.session_state: st.session_state.cidade_selecionada = "Todas"
if "coordenador_selecionado" not in st.session_state: st.session_state.coordenador_selecionado = "Todos"


# --- SIDEBAR (FILTROS) ---
with st.sidebar:
    
    # Filtros por UF, Cidade e Coordenador
    st.session_state.uf_selecionada = st.selectbox("Filtrar por UF:", ufs, index=ufs.index(st.session_state.uf_selecionada) if st.session_state.uf_selecionada in ufs else 0)
    
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        df_uf_filtrado = df_temp[df_temp['uf'].astype(str) == st.session_state.uf_selecionada]
        cidades_filtradas = ["Todas"] + sorted(df_uf_filtrado['cidade'].astype(str).unique().tolist())
        cidades_filtradas = [c for c in cidades_filtradas if c != 'nan']
        
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


# --- Aplicar os filtros aos dados editáveis ---
df_filtrado = st.session_state.df_editavel.copy()
if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
    df_filtrado = df_filtrado[df_filtrado['uf'].astype(str) == st.session_state.uf_selecionada]
if st.session_state.cidade_selecionada and st.session_state.cidade_selecionada != "Todas":
    df_filtrado = df_filtrado[df_filtrado['cidade'].astype(str) == st.session_state.cidade_selecionada]
if st.session_state.coordenador_selecionado and st.session_state.coordenador_selecionado != "Todos":
    df_filtrado = df_filtrado[df_filtrado['coordenador'].astype(str) == st.session_state.coordenador_selecionado]


# --- Sistema de abas ---
tab1, tab2, tab3, tab4 = st.tabs(["Busca Individual", "Análise de Dados", "Editor de Dados", "Análise de Chamados (Lote)"])

# =========================================================================
# TAB 1: BUSCA INDIVIDUAL
# =========================================================================
with tab1:
    st.title("Localizador de Técnicos")
    
    # --- LISTA DE TÉCNICOS FILTRADOS ---
    st.header("Lista de Técnicos Filtrados")
    if st.session_state.uf_selecionada != "Todos" or st.session_state.cidade_selecionada != "Todas" or st.session_state.coordenador_selecionado != "Todos":
        cols_display = ['tecnico', 'cidade', 'uf', 'coordenador']
        
        if modo_exibicao == "Tabela":
            st.dataframe(df_filtrado[cols_display], use_container_width=True)
        else:
            # Garante que o DataFrame filtrado não esteja vazio antes de iterar
            if not df_filtrado.empty:
                cols = st.columns(2)
                for i, row in df_filtrado.iterrows():
                    with cols[i % 2]:
                        st.markdown(f"**{row['tecnico']}** - {row['cidade']}/{row['uf']}")
                        st.write(f"Coordenador: **{row.get('coordenador', 'Não informado')}**")
                        st.markdown("---")
            else:
                 st.info("Nenhum técnico encontrado com os filtros selecionados.")
    else:
        st.info("Utilize os filtros na barra lateral para ver uma lista de técnicos.")

    st.markdown("---")
    st.header("Busca por Distância (Logística)")

    # AVISO DE FILTRO E RESTRIÇÃO DE KM
    if not df_filtrado.empty:
        st.info(f"A busca será restrita aos **{len(df_filtrado)}** técnicos selecionados e **apenas técnicos a até {st.session_state.raio_selecionado} km** (de carro) serão listados.")
    else:
        st.warning("Não há técnicos nos filtros selecionados para realizar a busca por distância.")

    
    endereco_cliente = st.text_input("Endereço do Chamado (Ponto de Origem)", help="Ex: Av. Paulista, 1000, São Paulo, SP")
    
    if st.button("Buscar Técnico Mais Próximo", key='btn_busca_individual'):
        if endereco_cliente:
            with st.spinner(f"Buscando técnicos a até {st.session_state.raio_selecionado} km..."):
                
                # CHAMADA DA FUNÇÃO SEM API_KEY
                tecnicos_proximos, localizacao_cliente = encontrar_tecnico_proximo(
                    endereco_cliente, 
                    df_filtrado, 
                    st.session_state.raio_selecionado # Raio dinâmico
                )
                
                if tecnicos_proximos is not None and not tecnicos_proximos.empty:
                    st.success(f"Busca concluída! Encontrados {len(tecnicos_proximos)} técnicos a até {st.session_state.raio_selecionado} km de distância.")
                    
                    st.subheader(f"🛠️ Técnicos Encontrados (Até {st.session_state.raio_selecionado} km)")
                    
                    st.markdown(f"**Custo Estimado:** R$ {CUSTO_POR_KM:.2f} por KM (Considerando ida e volta)")
                    
                    # Preparação para exportação
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
                    
                    # Lista formatada em colunas
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


# =========================================================================
# TAB 2: ANÁLISE DE DADOS (COMPLETA)
# =========================================================================
with tab2:
    st.header("📊 Análise de Dados dos Técnicos")
    
    df_analise = st.session_state.df_editavel.copy()
    
    col1, col2, col3 = st.columns(3)
    
    if not df_analise.empty:
        with col1:
            st.metric("Total de Técnicos", len(df_analise))
        with col2:
            st.metric("Total de Coordenadores", df_analise['coordenador'].nunique())
        with col3:
            st.metric("Total de UFs Cobertas", df_analise['uf'].nunique())
        
        st.markdown("---")
        
        # Gráfico 1: Distribuição de Técnicos por UF
        st.subheader("Distribuição de Técnicos por UF")
        df_uf = df_analise.groupby('uf')['tecnico'].count().reset_index(name='Total de Técnicos')
        fig_uf = px.bar(df_uf.sort_values('Total de Técnicos', ascending=False).head(10), 
                        x='uf', y='Total de Técnicos', title='Top 10 UFs por Número de Técnicos',
                        color='uf', template='plotly_white')
        st.plotly_chart(fig_uf, use_container_width=True)
        
        # Gráfico 2: Distribuição por Coordenador
        st.subheader("Distribuição por Coordenador")
        df_coord = df_analise.groupby('coordenador')['tecnico'].count().reset_index(name='Total de Técnicos')
        df_coord = df_coord[df_coord['Total de Técnicos'] > 0] # Remove coordenadores sem técnicos
        fig_coord = px.pie(df_coord, values='Total de Técnicos', names='coordenador', 
                           title='Distribuição de Técnicos por Coordenador', hole=0.3)
        st.plotly_chart(fig_coord, use_container_width=True)
        
    else:
        st.warning("Nenhum dado de técnico para análise. Por favor, carregue ou insira dados na aba 'Editor de Dados'.")


# =========================================================================
# TAB 3: EDITOR DE DADOS (COMPLETA)
# =========================================================================
with tab3:
    st.header("📝 Editor de Dados (Técnicos)")
    
    # --- AUTENTICAÇÃO DO EDITOR ---
    if not st.session_state.editor_authenticated:
        st.subheader("Autenticação de Editor")
        # Tenta usar a senha 'editor_senha' ou permite acesso se a senha não estiver no secrets
        if check_password_general("editor_senha", "Senha de editor incorreta.", "editor_auth_input"):
            st.session_state.editor_authenticated = True
            st.rerun()
        st.stop()
    
    # --- INTERFACE DO EDITOR ---
    
    st.info("Aqui você pode visualizar, editar, deletar ou adicionar novos técnicos. Lembre-se de clicar em **'Salvar Alterações'** para persistir os dados na planilha `tecnicos.xlsx`.")
    
    # 1. Upload de Novo Arquivo (Sobrescrever)
    uploaded_file = st.file_uploader("Upload de nova planilha `tecnicos.xlsx` (Isso irá SOBRESCREVER os dados atuais)", type=["xlsx"])
    if uploaded_file is not None:
        try:
            df_uploaded = pd.read_excel(uploaded_file)
            st.session_state.df_editavel = df_uploaded.copy()
            st.success("Nova planilha carregada com sucesso! Clique em 'Salvar Alterações' para persistir.")
            st.experimental_rerun()
        except Exception as e:
            st.error(f"Erro ao ler o arquivo: {e}")
            
    st.markdown("---")
    
    # 2. Editor Interativo
    st.subheader("Tabela Interativa de Técnicos")
    
    # Display columns: As 6 colunas essenciais
    df_display = st.session_state.df_editavel[[
        'tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador', 'latitude', 'longitude'
    ]].copy()
    
    edited_df = st.data_editor(
        df_display, 
        key="data_editor_tecnicos",
        height=400,
        use_container_width=True,
        num_rows="dynamic", # Permite adicionar/deletar linhas
        column_config={
            "tecnico": st.column_config.TextColumn("Técnico", required=True),
            "endereco": st.column_config.TextColumn("Endereço Base", required=True),
            "cidade": st.column_config.TextColumn("Cidade", required=True),
            "uf": st.column_config.TextColumn("UF", required=True, width="small"),
            "coordenador": st.column_config.TextColumn("Coordenador"),
            "email_coordenador": st.column_config.TextColumn("E-mail Coordenador"),
            "latitude": st.column_config.NumberColumn("Latitude", format="%.6f"),
            "longitude": st.column_config.NumberColumn("Longitude", format="%.6f"),
        }
    )
    
    # 3. Botões de Ação
    col_save, col_reload, col_geocode = st.columns(3)
    
    with col_save:
        if st.button("💾 Salvar Alterações", type="primary"):
            st.session_state.df_editavel = edited_df
            if save_data(st.session_state.df_editavel, ARQUIVO_TECNICOS):
                # Limpa o cache para recarregar filtros na sidebar e dados
                reset_df_editavel()
                st.rerun()

    with col_reload:
        if st.button("🔄 Descartar/Recarregar Planilha Original"):
            reset_df_editavel()
            st.success("Dados recarregados da planilha original.")
            st.rerun()
            
    with col_geocode:
        if st.button("📍 Tentar Geocodificar Endereços Faltantes"):
            df_geocod = st.session_state.df_editavel.copy()
            
            # Filtra linhas sem lat/lng ou com endereço preenchido
            mask_to_geocode = (df_geocod['endereco'].astype(str).str.strip() != '') & (df_geocod['latitude'].isnull() | df_geocod['longitude'].isnull())
            
            if mask_to_geocode.any():
                count_to_geocode = mask_to_geocode.sum()
                st.info(f"Geocodificando {count_to_geocode} endereços faltantes...")
                
                progress_bar = st.progress(0, text="Geocodificando 0% dos endereços...")
                
                newly_geocoded = 0
                for i, index in enumerate(df_geocod[mask_to_geocode].index):
                    endereco = df_geocod.loc[index, 'endereco']
                    lat, lng = geocodificar_endereco(endereco)
                    
                    if lat is not None:
                        df_geocod.loc[index, 'latitude'] = lat
                        df_geocod.loc[index, 'longitude'] = lng
                        newly_geocoded += 1
                        
                    progress_bar.progress((i + 1) / count_to_geocode, text=f"Geocodificando... Encontrados {newly_geocoded} de {count_to_geocode} com sucesso.")
                
                progress_bar.empty()
                st.session_state.df_editavel = df_geocod
                
                if save_data(st.session_state.df_editavel, ARQUIVO_TECNICOS):
                    reset_df_editavel()
                    st.success(f"Geocodificação concluída! {newly_geocoded} novos endereços geocodificados e salvos.")
                    st.rerun()
            else:
                st.info("Todos os técnicos com endereço preenchido já possuem Latitude/Longitude, ou não há endereços válidos para processar.")


# =========================================================================
# TAB 4: ANÁLISE DE CHAMADOS (LOTE) (COMPLETA)
# =========================================================================
with tab4:
    st.header("📋 Análise de Chamados (Lote)")
    
    st.markdown("Esta funcionalidade permite que você faça o upload de uma planilha com múltiplos endereços de chamados e descubra, para cada um, qual o **técnico mais próximo** (de carro) que está **dentro do raio** e **abaixo do limite de capacidade diária**.")
    st.markdown("O raio de busca será de **$** {st.session_state.raio_selecionado} **km** (o mesmo selecionado na barra lateral).")
    st.markdown("---")
    
    # 1. Parâmetros do Lote
    col_cap, col_file = st.columns(2)
    
    with col_cap:
        capacidade_diaria = st.number_input(
            "Capacidade Diária Máxima de Chamados por Técnico (0 = Ilimitado)", 
            min_value=0, 
            value=1, 
            step=1,
            help="Se for 1, um técnico só poderá ser alocado para o primeiro chamado mais próximo que ele atender."
        )
    
    with col_file:
        uploaded_lote_file = st.file_uploader("Upload da Planilha de Chamados (.xlsx)", type=["xlsx"])

    # 2. Processamento
    if uploaded_lote_file is not None:
        try:
            df_chamados = pd.read_excel(uploaded_lote_file)
            st.success(f"Planilha de chamados carregada: {len(df_chamados)} chamados encontrados.")
            
            if 'endereco' not in df_chamados.columns:
                 st.error("A planilha de chamados deve conter uma coluna chamada **'endereco'** com os endereços completos.")
            else:
                st.markdown("---")
                if st.button(f"✨ Iniciar Processamento de {len(df_chamados)} Chamados", type="primary"):
                    
                    if st.session_state.df_editavel.empty:
                        st.error("Não há dados de técnicos carregados para realizar o processamento.")
                        st.stop()
                        
                    # Lógica de processamento em lote
                    df_resultados_final, resumo = processar_chamados_em_lote(
                        df_chamados, 
                        st.session_state.df_editavel, 
                        st.session_state.raio_selecionado, 
                        capacidade_diaria
                    )
                    
                    st.success("✅ Processamento de Lote Concluído!")
                    
                    # --- RESUMO DOS RESULTADOS ---
                    st.subheader("Resumo da Alocação")
                    
                    col_resumo = st.columns(5)
                    for idx, (key, value) in enumerate(resumo.items()):
                        with col_resumo[idx % 5]:
                            st.metric(key, value)
                            
                    st.markdown("---")
                    
                    # --- RESULTADOS DETALHADOS ---
                    st.subheader("Resultados Detalhados (Por Chamado)")
                    st.dataframe(df_resultados_final, use_container_width=True)
                    
                    # --- DOWNLOAD ---
                    csv_data = df_resultados_final.to_excel(index=False)
                    st.download_button(
                        label="⬇️ Baixar Resultados da Alocação (Excel)",
                        data=io.BytesIO(csv_data.encode('utf-8')),
                        file_name=f'alocacao_chamados_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )

        except Exception as e:
            st.error(f"Erro ao processar a planilha de chamados: {e}")
    else:
        st.info("Por favor, faça o upload de uma planilha Excel de chamados para iniciar a análise em lote.")