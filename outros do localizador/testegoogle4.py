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
st.set_page_config(page_title="Localizador de Técnicos (v2.6 Autenticação Editor)", layout="wide") 

st.markdown("""
<style>
    /* Esconde o menu do Streamlit e o rodapé "Made with Streamlit" */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Centraliza o título principal e subtítulos */
    h1, h2, h3 {
        text-align: center;
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
        margin-right: 10px;
        margin-top: 5px;
    }
    .st-emotion-cache-18ni7ap {
        gap: 1rem;
    }
    
    /* Ajuste visual para o st.radio */
    div[data-testid="stRadio"] label {
        margin-right: 15px;
    }
</style>
""", unsafe_allow_html=True)

# --- VARIÁVEIS GLOBAIS ---
RAIOS = [30, 100, 200]
CUSTO_POR_KM = 1.0 

# --- FUNÇÕES DE UTILIDADE ---

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
def analisar_e_limpar_df(file_buffer):
    """
    Carrega, analisa e limpa o DataFrame de técnicos.
    - Garante colunas essenciais.
    - Padroniza textos (UF, Cidade, Coordenador).
    - Corrige formato de coordenadas (vírgula para ponto).
    """
    try:
        df = pd.read_excel(file_buffer)
        df_log = pd.DataFrame() 
        problemas = []
        
        # 1. GARANTIR E PADRONIZAR COLUNAS ESSENCIAIS
        str_cols = ['tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador']
        for col in str_cols:
            df[col] = df.get(col, pd.Series(dtype='str')).astype(str).fillna('')
            df[col] = df[col].str.strip()
            if col in ['tecnico', 'cidade', 'uf', 'coordenador']:
                df[col] = df[col].str.title()
                
        df['coordenador'] = df['coordenador'].replace({'Nan': 'Não Informado', '': 'Não Informado'})

        # 2. TRATAR E CONVERTER COORDENADAS (Ponto vs Vírgula)
        for col in ['latitude', 'longitude']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip() 
                df[col] = df[col].str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 3. ANALISAR E GERAR RELATÓRIO DE PROBLEMAS (Simplificado aqui)
        df_temp_check = df.copy()
        df_temp_check['valid_coord'] = df_temp_check['latitude'].notnull() & df_temp_check['longitude'].notnull()
        sem_coordenadas = df_temp_check[df_temp_check['valid_coord'] == False]
        
        for idx, row in sem_coordenadas.iterrows():
            problemas.append({
                'Técnico': row['tecnico'],
                'Problema': 'Sem Coordenadas Válidas (Lat/Long)',
                'Valor_Original': f"Lat: {row.get('latitude', 'N/A')}, Long: {row.get('longitude', 'N/A')}"
            })
            
        df_log = pd.DataFrame(problemas)
        
        return df, df_log
        
    except Exception as e:
        st.error(f"Erro fatal ao carregar ou processar a planilha: {e}")
        return pd.DataFrame(), pd.DataFrame() 

def load_initial_data(file_path):
    """Carrega o arquivo padrão se nenhum upload for feito e executa a análise."""
    if os.path.exists(file_path):
        df_tecnicos, df_log = analisar_e_limpar_df(file_path)
        return df_tecnicos, df_log
    else:
        # Cria DataFrames vazios
        cols = ['tecnico', 'endereco', 'cidade', 'uf', 'coordenador', 'email_coordenador', 'latitude', 'longitude']
        st.warning(f"O arquivo '{file_path}' não foi encontrado. Usando base vazia.")
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=['Técnico', 'Problema', 'Valor_Original'])

def preencher_resultado_vazio(resultado):
    """Função auxiliar para preencher campos de técnico vazio."""
    resultado['Técnico_Mais_Próximo'] = 'N/A'
    resultado['Coordenador_Técnico'] = 'N/A'
    resultado['UF_Técnico'] = 'N/A'
    resultado['Distância_km'] = 'N/A'
    resultado['Tempo_Estimado'] = 'N/A'
    resultado['Custo_Estimado_RS'] = 'N/A'
    return resultado

# --- LÓGICA DE BUSCA PRINCIPAL (Ajustada para Tempo e Custo) ---

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
    
    # Cálculo de Custo R$ 1/km
    df_validos["custo_rs"] = df_validos["distancia_km"] * CUSTO_POR_KM

    # Filtro dinâmico pelo raio selecionado
    df_dentro_limite = df_validos[df_validos["distancia_km"] <= max_distance_km]
    
    # Retorna todos os técnicos dentro do limite, ordenados
    return df_dentro_limite.sort_values("distancia_km"), localizacao_cliente

# --- LÓGICA DE UPLOAD E CONFRONTO DE CHAMADOS (OTIMIZADA COM CAPACIDADE) ---

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
    chamados_sem_tecnico = 0 # Inclui chamados sem técnico por distância OU capacidade
    chamados_otimizados = 0

    # Inicializa o controle de alocação de capacidade
    tecnicos_capacidade = {t: 0 for t in df_tecnicos_validos['tecnico'].unique()}

    progress_bar = st.progress(0, text="Iniciando processamento dos chamados...")

    # Fator de folga para a distância aérea (1.5x é um bom ponto de partida)
    FATOR_FOLGA = 1.5 
    RAIO_MAXIMO_AEREO = max_distance_km * FATOR_FOLGA

    for index, row_chamado in df_chamados.iterrows():
        endereco_cliente = row_chamado['endereco']
        
        chamados_processados += 1
        progress_bar.progress(chamados_processados / total_chamados, text=f"Processando {chamados_processados}/{total_chamados} chamados...")
        
        if pd.isnull(endereco_cliente) or not endereco_cliente.strip():
            chamados_com_erro += 1
            row_chamado['Status'] = 'ERRO: Endereço vazio'
            df_resultados_finais.append(preencher_resultado_vazio(row_chamado.to_dict()))
            continue

        # 1. GEOCODIFICAR ENDEREÇO DO CHAMADO
        lat_cliente, lng_cliente = geocodificar_endereco(endereco_cliente, api_key)

        if lat_cliente is None:
            chamados_com_erro += 1
            row_chamado['Status'] = 'ERRO: Falha na Geocodificação'
            df_resultados_finais.append(preencher_resultado_vazio(row_chamado.to_dict()))
            continue

        origem = f"{lat_cliente},{lng_cliente}"
        
        # 2. PRÉ-FILTRO POR DISTÂNCIA HAVERSINE (OTIMIZAÇÃO)
        df_temp = df_tecnicos_validos.copy()
        
        # Calcula a distância aérea para todos os técnicos em lote
        df_temp['distancia_aerea_km'] = df_temp.apply(
            lambda x: haversine(lat_cliente, lng_cliente, x['latitude'], x['longitude']), axis=1
        )
        
        # Filtra apenas os técnicos que estão dentro do raio aéreo de folga
        df_candidatos = df_temp[df_temp['distancia_aerea_km'] <= RAIO_MAXIMO_AEREO].copy()

        # Se não houver candidatos nem por distância aérea, pula a Distance Matrix
        if df_candidatos.empty:
            chamados_sem_tecnico += 1
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
        
        # Filtro final pelo raio MÁXIMO (carro) e ordenação
        df_aptos = df_candidatos[df_candidatos["distancia_km"] <= max_distance_km].sort_values("distancia_km")

        # 4. APLICA LÓGICA DE CAPACIDADE E ALOCAÇÃO
        melhor_tecnico = None
        
        for idx_aptos, row_aptos in df_aptos.iterrows():
            tecnico_nome = row_aptos['tecnico']
            # Se a capacidade diária for 0, não há limite. Caso contrário, verifica o limite.
            if capacidade_diaria == 0 or tecnicos_capacidade[tecnico_nome] < capacidade_diaria:
                melhor_tecnico = row_aptos
                
                # ALOCAÇÃO DE FATO
                tecnicos_capacidade[tecnico_nome] += 1
                break # Encontrou o melhor e mais próximo que tem capacidade
        
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
            chamados_sem_tecnico += 1
            resultado = row_chamado.to_dict()
            
            # Mensagem mais específica se o problema for a capacidade
            if not df_aptos.empty:
                 resultado['Status'] = f'Nenhum técnico disponível no raio (Todos no limite de {capacidade_diaria} chamados)'
            else:
                 resultado['Status'] = f'Nenhum técnico no raio de {max_distance_km} km (Real)'

            resultado = preencher_resultado_vazio(resultado)
            
        df_resultados_finais.append(resultado)
    
    progress_bar.empty()
    
    df_final = pd.DataFrame(df_resultados_finais)
    
    # 6. ADICIONAR COLUNA DE RESUMO DE ALOCAÇÃO FINAL
    df_alocacao = pd.DataFrame(list(tecnicos_capacidade.items()), columns=['Técnico_Mais_Próximo', 'Chamados_Alocados_Tecnico'])
    
    # Faz o merge para incluir a contagem total no resultado final. Uso 'left' para manter chamados não alocados.
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

# --- LÓGICA DE LOGIN (MODIFICADA PARA SER REUTILIZÁVEL) ---

def check_password_general(password_key, error_msg, key_input):
    """Verifica uma senha genérica do secrets, usando uma chave única para o input."""
    # Se a chave não existir no secrets, assume acesso livre (para evitar falhas)
    if password_key not in st.secrets.get("auth", {}):
        return True 
    
    password = st.text_input("Por favor, insira a senha para acessar:", type="password", key=key_input)
    if password == st.secrets["auth"][password_key]:
        return True
    elif password:
        st.error(error_msg)
        return False
    return False

# --- CÓDIGO DO APLICATIVO PRINCIPAL ---

# 0. INICIALIZAÇÃO DE ESTADO E AUTENTICAÇÃO
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# NOVO: Estado de autenticação para o Editor de Dados
if "editor_authenticated" not in st.session_state:
    st.session_state.editor_authenticated = False
    
# Inicia ou carrega o estado da base de dados
if "df_tecnicos" not in st.session_state:
    df_tecnicos_init, df_log_init = load_initial_data('tecnicos.xlsx')
    st.session_state.df_tecnicos = df_tecnicos_init
    st.session_state.df_log_erros = df_log_init 
    st.session_state.df_original = st.session_state.df_tecnicos.copy() 

# --------------------------------------------------------------------------
# --- AUTENTICAÇÃO GLOBAL ---
# --------------------------------------------------------------------------
if not st.session_state.authenticated:
    st.title("🔒 Acesso Restrito")
    # A senha está no secrets.toml na seção [auth], chave 'senha'
    if check_password_general("senha", "Senha incorreta. Tente novamente.", "global_auth_input"):
        st.session_state.authenticated = True
        st.rerun()
    st.stop()


# 1. CARREGAR DADOS E API KEY
df_tecnicos = st.session_state.df_tecnicos

try:
    API_KEY = st.secrets["api"]["google_maps"]
except KeyError:
    st.error("Chave de API do Google Maps não encontrada. Verifique o arquivo .streamlit/secrets.toml")
    API_KEY = None
    
# --- CONFIGURAÇÃO INICIAL DO SIDEBAR ---
st.sidebar.header("Filtros de Busca")

# 1. Raio Máximo de Busca 
if "raio_selecionado" not in st.session_state:
    st.session_state.raio_selecionado = 30 

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
ufs = ["Todos"] + sorted(df_tecnicos['uf'].unique().tolist()) if 'uf' in df_tecnicos.columns and not df_tecnicos.empty else ["Todos"]
cidades_todas = ["Todas"] + sorted(df_tecnicos['cidade'].unique().tolist()) if 'cidade' in df_tecnicos.columns and not df_tecnicos.empty else ["Todas"]
coordenadores = ["Todos"] + sorted(df_tecnicos['coordenador'].unique().tolist()) if 'coordenador' in df_tecnicos.columns and not df_tecnicos.empty else ["Todos"]

# --- SIDEBAR (FILTROS) ---
with st.sidebar:
    
    # Filtros por UF, Cidade e Coordenador
    st.session_state.uf_selecionada = st.selectbox("Filtrar por UF:", ufs, index=ufs.index(st.session_state.uf_selecionada) if st.session_state.uf_selecionada in ufs else 0)
    
    # Lógica para filtrar as cidades com base na UF selecionada
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
        st.session_state.raio_selecionado = 30
        st.rerun()
        
    st.markdown("---")
    st.markdown("**Opções de Visualização**")
    modo_exibicao = st.radio("Formato da Lista de Técnicos:", ["Tabela", "Colunas"], index=1)
# --------------------------------------------------------------------------


# --- Sistema de abas ---
tab1, tab2, tab3, tab4 = st.tabs(["Busca Individual", "Análise de Dados", "Editor de Dados", "Análise de Chamados (Lote)"])

with tab1:
    st.title("Localizador de Técnicos")
    
    # --- APLICAR OS FILTROS ---
    df_filtrado = df_tecnicos.copy()
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == st.session_state.uf_selecionada]
    if st.session_state.cidade_selecionada and st.session_state.cidade_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['cidade'] == st.session_state.cidade_selecionada]
    if st.session_state.coordenador_selecionado and st.session_state.coordenador_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['coordenador'] == st.session_state.coordenador_selecionado]

    # --- LISTA DE TÉCNICOS FILTRADOS (ACIMA DA BUSCA) ---
    st.header("Lista de Técnicos Filtrados")
    if st.session_state.uf_selecionada != "Todos" or st.session_state.cidade_selecionada != "Todas" or st.session_state.coordenador_selecionado != "Todos":
        cols_display = ['tecnico', 'cidade', 'uf', 'coordenador']
        
        if modo_exibicao == "Tabela":
            # use_container_width=True -> width='stretch'
            st.dataframe(df_filtrado[cols_display], width='stretch') 
        else:
            cols = st.columns(2)
            for i, row in df_filtrado.iterrows():
                with cols[i % 2]:
                    st.markdown(f"**{row['tecnico']}** - {row['cidade']}/{row['uf']}")
                    st.write(f"Coordenador: {row.get('coordenador', 'Não informado')}")
                    st.markdown("---")
    else:
        st.info("Utilize os filtros na barra lateral para ver uma lista de técnicos.")

    st.markdown("---")
    st.header("Busca por Distância (Logística)")

    if not df_filtrado.empty:
        st.info(f"A busca será restrita aos **{len(df_filtrado)}** técnicos selecionados e ao raio de **{st.session_state.raio_selecionado} km**.")
    else:
        st.warning("Não há técnicos nos filtros selecionados para realizar a busca por distância.")

    if API_KEY:
        endereco_cliente = st.text_input("Endereço do Chamado (Ponto de Origem)", help="Ex: Av. Paulista, 1000, São Paulo, SP")
        
        if st.button("Buscar Técnico Mais Próximo", key='btn_busca_individual'):
            if endereco_cliente:
                with st.spinner(f"Buscando técnicos a até {st.session_state.raio_selecionado} km..."):
                    
                    tecnicos_proximos, localizacao_cliente = encontrar_tecnico_proximo(
                        endereco_cliente, 
                        API_KEY, 
                        df_filtrado, 
                        st.session_state.raio_selecionado
                    )
                    
                    if tecnicos_proximos is not None and not tecnicos_proximos.empty:
                        st.success(f"Busca concluída! Encontrados {len(tecnicos_proximos)} técnicos a até {st.session_state.raio_selecionado} km de distância.")
                        
                        col_mapa, col_lista = st.columns([1, 1]) 
                        
                        with col_mapa:
                            st.subheader("📍 Mapa dos Resultados")
                            
                            # --- CÓDIGO DO MAPA (COM CÍRCULO DE RAIO) ---
                            
                            # 1. Preparar dados
                            df_tecnicos_mapa = tecnicos_proximos[['latitude', 'longitude', 'tecnico']].rename(
                                columns={'latitude': 'lat', 'longitude': 'lon'}
                            )
                            df_cliente_mapa = pd.DataFrame([localizacao_cliente]).rename(columns={'lat': 'lat', 'lng': 'lon'})
                            
                            # 2. Dados do Círculo de Cobertura
                            df_raio = pd.DataFrame([
                                {'lat': localizacao_cliente['lat'], 'lon': localizacao_cliente['lng'], 'radius': st.session_state.raio_selecionado * 1000} # Raio em metros
                            ])
                            
                            # 3. Definir o estado inicial do mapa (centrado no cliente)
                            view_state = pdk.ViewState(
                                latitude=localizacao_cliente['lat'],
                                longitude=localizacao_cliente['lng'],
                                zoom=10, # Zoom ajustado para melhor visualização do raio
                                pitch=0,
                            )
                            
                            # 4. Camada de Cobertura (Raio)
                            camada_cobertura = pdk.Layer(
                                'ScatterplotLayer',
                                df_raio,
                                get_position='[lon, lat]',
                                get_fill_color=[255, 0, 0, 40], # Vermelho transparente
                                get_radius='radius', # Usa o raio em metros
                                radius_scale=1,
                                radius_min_pixels=1,
                                pickable=True,
                                filled=True,
                                stroked=True,
                                get_line_color=[255, 0, 0, 100], # Borda
                                line_width_min_pixels=1
                            )

                            # 5. Camada dos Técnicos (Pontos Azuis)
                            camada_tecnicos = pdk.Layer(
                                'ScatterplotLayer',
                                df_tecnicos_mapa,
                                get_position='[lon, lat]',
                                get_color='[0, 100, 200, 255]', # Azul
                                get_radius=1, 
                                radius_min_pixels=5, 
                                pickable=True,
                                z_index=1 # Garante que os pontos dos técnicos fiquem acima do raio
                            )
                            
                            # 6. Camada do Cliente (Ponto de Origem - Maior e Vermelho)
                            camada_cliente = pdk.Layer(
                                'ScatterplotLayer',
                                df_cliente_mapa,
                                get_position='[lon, lat]',
                                get_color='[255, 0, 0, 255]', # Vermelho
                                get_radius=1, 
                                radius_min_pixels=12, 
                                pickable=True,
                                z_index=2 # Garante que o cliente fique no topo
                            )
                            
                            # 7. Renderizar o mapa
                            st.pydeck_chart(pdk.Deck(
                                map_style='light', 
                                initial_view_state=view_state,
                                layers=[camada_cobertura, camada_tecnicos, camada_cliente], 
                            ))
                            # ------------------------------------------------

                        with col_lista:
                            st.subheader("🛠️ Lista de Técnicos (Apto para Atendimento)")
                            
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
                                'custo_rs': f'Custo Estimado (R$ {CUSTO_POR_KM}/km)',
                            }, inplace=True)
                            
                            # Botão de download
                            towrite = io.BytesIO()
                            df_to_export.to_excel(towrite, index=False, header=True)
                            towrite.seek(0)
                            st.download_button(
                                label="Exportar Resultados para Excel",
                                data=towrite,
                                file_name='tecnicos_proximos_e_custo.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            )

                            st.markdown("---")
                            
                            # Lista formatada em colunas (AGORA COM COORDENADOR)
                            cols_tecnicos = st.columns(2)
                            
                            for i, row in tecnicos_proximos.reset_index(drop=True).iterrows():
                                with cols_tecnicos[i % 2]:
                                    st.markdown(f"**{row['tecnico']}** - {row['cidade']}/{row['uf']}")
                                    st.write(f"Coordenador: **{row['coordenador']}**") 
                                    st.write(f"Distância: **{row['distancia_km']:.2f} km**")
                                    st.write(f"Tempo Estimado: **{row['tempo_text']}**")
                                    st.write(f"Custo Estimado: **R$ {row['custo_rs']:.2f}**")
                                    st.markdown("---")

                    else:
                        st.info(f"Nenhum técnico encontrado no universo filtrado que esteja a até {st.session_state.raio_selecionado} km de distância do endereço.")
            else:
                st.warning("Por favor, digite um endereço para iniciar a busca.")

with tab2:
    st.header("📊 Análise de Dados dos Técnicos")

    if df_tecnicos.empty:
        st.warning("A base de dados está vazia. Faça o upload na aba Editor de Dados para começar a analisar.")
    else:
        st.subheader("1. Distribuição Geográfica e de Equipe")
        
        col_uf, col_coordenador = st.columns(2)
        
        with col_uf:
            st.markdown("#### Técnicos por UF")
            # Contagem por UF
            df_uf = df_tecnicos['uf'].value_counts().reset_index()
            df_uf.columns = ['UF', 'Contagem']
            
            # Criação do gráfico de barras (Plotly)
            fig_uf = px.bar(
                df_uf, 
                x='UF', 
                y='Contagem', 
                title='Contagem de Técnicos por UF',
                color='Contagem',
                color_continuous_scale=px.colors.sequential.Teal
            )
            st.plotly_chart(fig_uf, use_container_width=True)
            
        with col_coordenador:
            st.markdown("#### Técnicos por Coordenador")
            # Contagem por Coordenador
            df_coord = df_tecnicos['coordenador'].value_counts().reset_index()
            df_coord.columns = ['Coordenador', 'Contagem']
            
            # Criação do gráfico de barras (Plotly)
            fig_coord = px.bar(
                df_coord, 
                x='Contagem', 
                y='Coordenador', 
                orientation='h',
                title='Contagem de Técnicos por Coordenador',
                color='Contagem',
                color_continuous_scale=px.colors.sequential.Plasma
            )
            st.plotly_chart(fig_coord, use_container_width=True)
            
        st.markdown("---")
        st.subheader("2. Qualidade dos Dados de Localização")
        
        # Criação da coluna de status de geocodificação
        df_tecnicos['Geocodificacao_Valida'] = df_tecnicos['latitude'].notnull() & df_tecnicos['longitude'].notnull()
        
        df_qualidade = df_tecnicos['Geocodificacao_Valida'].value_counts().reset_index()
        df_qualidade.columns = ['Status', 'Contagem']
        df_qualidade['Status'] = df_qualidade['Status'].replace({True: 'Com Coordenadas (Apto para Busca)', False: 'Sem Coordenadas (Requer Correção)'})
        
        total_tecnicos = len(df_tecnicos)
        validos = df_qualidade[df_qualidade['Status'] == 'Com Coordenadas (Apto para Busca)']['Contagem'].sum()
        invalidos = df_qualidade[df_qualidade['Status'] == 'Sem Coordenadas (Requer Correção)']['Contagem'].sum()
        
        col_metricas, col_grafico = st.columns([1, 1])

        with col_metricas:
            st.metric(label="Total de Técnicos na Base", value=total_tecnicos)
            st.metric(label="Técnicos Prontos para Busca (Lat/Long Válidas)", value=validos, delta=f"{validos/total_tecnicos*100:.1f}%")
            st.metric(label="Técnicos com Problema na Localização", value=invalidos, delta=f"{-invalidos/total_tecnicos*100:.1f}%", delta_color="inverse")
            
            # Tabela de problemas de limpeza (Log)
            if not st.session_state.df_log_erros.empty:
                st.markdown("##### Detalhes dos Problemas de Localização")
                # use_container_width=True -> width='stretch'
                st.dataframe(st.session_state.df_log_erros, width='stretch')


        with col_grafico:
            # Criação do gráfico de pizza
            fig_pizza = px.pie(
                df_qualidade, 
                names='Status', 
                values='Contagem', 
                title='Qualidade dos Dados de Localização',
                color='Status',
                color_discrete_map={'Com Coordenadas (Apto para Busca)':'#00BFFF', 'Sem Coordenadas (Requer Correção)':'#FF4500'}
            )
            st.plotly_chart(fig_pizza, use_container_width=True)


with tab3:
    st.header("📝 Editor de Dados dos Técnicos")
    
    # --------------------------------------------------------------------------
    # --- AUTENTICAÇÃO SECUNDÁRIA PARA O EDITOR ---
    # --------------------------------------------------------------------------
    if not st.session_state.editor_authenticated:
        st.warning("Esta seção requer uma autenticação adicional para edição de dados.")
        if check_password_general("editor_senha", "Senha do Editor incorreta. Tente novamente.", "editor_auth_input"):
            st.session_state.editor_authenticated = True
            st.rerun() # Recarrega para mostrar o conteúdo do editor
        # Se a senha for pedida e ainda não foi inserida corretamente, o código para aqui.
        if not st.session_state.editor_authenticated:
            st.stop()
    # --------------------------------------------------------------------------

    # O restante do código da tab3 só é executado se a autenticação do editor for True
    st.info("⚠️ **IMPORTANTE:** As alterações feitas aqui são salvas APENAS na sessão atual. Para tornar permanente, use o botão de exportação ao final.")
    
    # Criando uma cópia para edição
    df_editable = st.session_state.df_tecnicos.copy()

    if not df_editable.empty:
        
        # 1. EDIÇÃO MANUAL (st.data_editor)
        # use_container_width=True -> width='stretch'
        edited_df = st.data_editor(
            df_editable,
            column_config={
                "latitude": st.column_config.NumberColumn("Latitude", format="%.6f"),
                "longitude": st.column_config.NumberColumn("Longitude", format="%.6f"),
                "endereco": st.column_config.TextColumn("Endereço Completo", width="large")
            },
            num_rows="dynamic",
            width='stretch', # Substitui use_container_width=True
            key="data_editor"
        )
        
        # 2. BOTÃO PARA SALVAR ALTERAÇÕES MANUAIS NO ESTADO DA SESSÃO
        if st.button("Salvar Alterações Manuais na Sessão", key='btn_save_manual'):
            # Salva o DataFrame editado pelo usuário no estado da sessão
            st.session_state.df_tecnicos = edited_df.copy()
            st.success("Alterações manuais salvas com sucesso na sessão!")
            st.rerun() # Recarrega para refletir na análise e busca

        
        st.markdown("---")
        st.subheader("Ferramenta de Geocodificação Automática")
        
        # Identifica linhas no DF editado (que ainda não está no session_state, mas é o DF atual)
        df_to_geocode = edited_df[edited_df['latitude'].isnull() | edited_df['longitude'].isnull()]
        
        col_geocode, col_export = st.columns([2, 1])
        
        with col_geocode:
            if st.button(f"Geocodificar {len(df_to_geocode)} Endereço(s) Sem Coordenadas", disabled=df_to_geocode.empty or API_KEY is None, key='btn_geocode'):
                if API_KEY:
                    with st.spinner(f"Geocodificando {len(df_to_geocode)} endereços. Isso pode levar um tempo e consumir API key..."):
                        
                        df_updated = edited_df.copy()
                        count_updated = 0
                        
                        for index, row in df_to_geocode.iterrows():
                            endereco = row['endereco']
                            if endereco and endereco.strip():
                                lat, lng = geocodificar_endereco(endereco, API_KEY)
                                
                                if lat is not None:
                                    df_updated.loc[index, 'latitude'] = lat
                                    df_updated.loc[index, 'longitude'] = lng
                                    count_updated += 1

                        # Salva o resultado final no estado da sessão (AÇÃO DEFINITIVA)
                        st.session_state.df_tecnicos = df_updated
                        
                        st.success(f"Concluído! **{count_updated}** coordenadas de técnicos foram atualizadas. A base de dados na sessão foi atualizada.")
                        st.rerun() 
                else:
                    st.error("Chave de API não está configurada. Não é possível geocodificar.")
        
        with col_export:
            # 3. BOTÃO DE EXPORTAÇÃO (Para tornar as alterações "online/permanentes")
            df_final_export = st.session_state.df_tecnicos # Exporta a versão mais atualizada na sessão
            towrite_tecnicos = io.BytesIO()
            df_final_export.to_excel(towrite_tecnicos, index=False, header=True)
            towrite_tecnicos.seek(0)
            
            st.download_button(
                label="Exportar Base Atualizada (Excel)",
                data=towrite_tecnicos,
                file_name='base_tecnicos_atualizada.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                help="Baixe esta planilha para substituir o arquivo original, tornando as alterações permanentes."
            )
            
    else:
        st.warning("Base de dados vazia. Faça o upload de uma nova planilha para começar a editar.")


# =========================================================================
# === ABA: ANÁLISE DE CHAMADOS EM LOTE ===
# =========================================================================
with tab4:
    st.title("Análise de Chamados em Lote")
    st.header("Confrontar Planilha de Chamados com Base de Técnicos")
    st.warning("ATENÇÃO: Este recurso consome cotas da Google Maps API rapidamente. A otimização por distância aérea foi aplicada para reduzir o consumo.")
    
    st.markdown("---")
    st.subheader("Configurações da Análise")
    
    col_raio, col_capacidade = st.columns(2)
    
    with col_raio:
        raio_lote = st.select_slider(
            "1. Raio Máximo de Atendimento (km):",
            options=[10, 20, 30, 50, 100, 200],
            value=30
        )
    
    with col_capacidade:
        # Novo campo de entrada para capacidade diária
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
            
            # Botão com a nova variável de capacidade
            if st.button(f"Iniciar Análise de Confronto e Alocação (Raio: {raio_lote} km | Capacidade: {capacidade_diaria})", key='btn_confronto'):
                if API_KEY and not df_tecnicos.empty:
                    
                    df_resultados, resumo = processar_chamados_em_lote(
                        df_chamados.copy(), 
                        df_tecnicos.copy(), 
                        API_KEY, 
                        raio_lote,
                        capacidade_diaria # Novo parâmetro sendo passado
                    )
                    
                    st.markdown("---")
                    st.subheader("4. Resultados da Análise de Alocação")
                    
                    # Exibe o resumo
                    col_sum1, col_sum2, col_sum3, col_sum4 = st.columns(4)
                    col_sum1.metric(label="Total Chamados", value=resumo['Total de Chamados na Planilha'])
                    col_sum2.metric(label=f"Alocados (Capacidade & Raio)", value=resumo[f"Chamados Alocados (Considerando Capacidade e Raio)"])
                    col_sum3.metric(label="Não Alocados", value=resumo["Chamados Não Alocados"])
                    col_sum4.metric(label="Otimizados (Economia API)", value=resumo["Chamados Processados na Distance Matrix (Otimizados)"])


                    st.markdown("### Tabela Detalhada dos Resultados e Carga de Trabalho")
                    
                    # Ordena o resultado para que os chamados alocados venham primeiro
                    df_resultados_sorted = df_resultados.sort_values(by=['Status', 'Distância_km'], ascending=[False, True])

                    # use_container_width=True -> width='stretch'
                    st.dataframe(df_resultados_sorted, width='stretch')
                    
                    # Tabela Resumo de Carga de Trabalho
                    st.markdown("### Resumo da Carga de Trabalho por Técnico")
                    
                    # Cria um DF de resumo
                    df_carga = df_resultados_sorted[df_resultados_sorted['Técnico_Mais_Próximo'] != 'N/A'].groupby(['Técnico_Mais_Próximo', 'Coordenador_Técnico'])['Técnico_Mais_Próximo'].size().reset_index(name='Total_Alocado_Nesta_Busca')
                    
                    # use_container_width=True -> width='stretch'
                    st.dataframe(df_carga.sort_values(by='Total_Alocado_Nesta_Busca', ascending=False), width='stretch')

                    # Botão de download
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
                    st.error("Erro: Verifique se a Chave API e a Base de Técnicos foram carregadas corretamente.")
        
        except Exception as e:
            st.error(f"Erro ao ler a planilha de chamados. Verifique o formato do arquivo: {e}")
# =========================================================================

# Rodapé com informações do desenvolvedor (Mantido)
st.markdown("---")
st.markdown("<div style='text-align:center;'>Desenvolvido por Edmilson Carvalho - Edmilson.carvalho@globalhitss.com.br © 2025</div>", unsafe_allow_html=True)