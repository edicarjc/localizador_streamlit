import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
import io
import plotly.express as px
import pydeck as pdk

# Injeta CSS personalizado para design responsivo e um visual mais limpo
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

# --- FUNÇÕES ---
def get_distance_matrix(origins, destinations, api_key):
    """
    Obtém a matriz de distância de carro do Google Maps.
    """
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

def geocodificar_endereco(endereco, api_key):
    """
    Converte um endereço em coordenadas (latitude e longitude).
    """
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

@st.cache_data
def load_data(file_path):
    """
    Carrega os dados do arquivo Excel e faz um cache para otimizar o desempenho.
    """
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
    """
    Encontra os técnicos mais próximos a um endereço de cliente.
    """
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
    
    return df_validos.sort_values("distancia_km").head(10), localizacao_cliente


# --- LÓGICA DE LOGIN PRINCIPAL ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def check_password_main():
    """Verifica se a senha principal do usuário corresponde à senha secreta."""
    password = st.text_input("Por favor, insira a senha para acessar:", type="password")
    if password == st.secrets["auth"]["senha"]:
        st.session_state.authenticated = True
        st.rerun()

    elif password:
        st.error("Senha incorreta. Tente novamente.")

if not st.session_state.authenticated:
    st.title("🔒 Acesso Restrito")
    check_password_main()
    st.stop()


# --- CÓDIGO DO APLICATIVO PRINCIPAL ---
st.set_page_config(page_title="Localizador de Técnicos", layout="wide")

st.title("🔎 Localizador de Técnicos")
st.markdown("---")

df_tecnicos = load_data('tecnicos.xlsx')
if df_tecnicos is None:
    st.stop()

# --- CONVERTER COLUNAS DE COORDENADAS PARA NUMÉRICO ---
df_tecnicos['latitude'] = pd.to_numeric(df_tecnicos['latitude'], errors='coerce')
df_tecnicos['longitude'] = pd.to_numeric(df_tecnicos['longitude'], errors='coerce')
# -----------------------------------------------------------------

# --- FILTROS DE BUSCA NA BARRA LATERAL ---
st.sidebar.header("Filtros de Busca")
ufs = ["Todos"] + sorted(df_tecnicos['uf'].unique().tolist())
cidades = ["Todas"] + sorted(df_tecnicos['cidade'].unique().tolist())
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
        st.session_state.cidade_selecionada = st.selectbox("Filtrar por Cidade:", cidades_filtradas, index=cidades_filtradas.index(st.session_state.cidade_selecionada) if st.session_state.cidade_selecionada in cidades_filtradas else 0)
    else:
        st.session_state.cidade_selecionada = st.selectbox("Filtrar por Cidade:", cidades, index=cidades.index(st.session_state.cidade_selecionada) if st.session_state.cidade_selecionada in cidades else 0)
    
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

# --- Sistema de abas ---
tab1, tab2, tab3 = st.tabs(["Localizador de Técnicos", "Análise de Dados", "Editor de Dados"])

with tab1:
    # --- APLICAR OS FILTROS ---
    df_filtrado = df_tecnicos.copy()
    if st.session_state.uf_selecionada and st.session_state.uf_selecionada != "Todos":
        df_filtrado = df_filtrado[df_filtrado['uf'] == st.session_state.uf_selecionada]
    if st.session_state.cidade_selecionada and st.session_state.cidade_selecionada != "Todas":
        df_filtrado = df_filtrado[df_filtrado['cidade'] == st.session_state.cidade_selecionada]
    if st.session_state.coordenador_selecionado and st.session_state.coordenador_selecionado != "Todos":
        df_filtrado = df_filtrado[df_filtrado['coordenador'] == st.session_state.coordenador_selecionado]

    # --- LISTA DE TÉCNICOS FILTRADOS ---
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

    try:
        API_KEY = st.secrets["api"]["google_maps"]
    except KeyError:
        st.error("Chave de API do Google Maps não encontrada. Verifique o arquivo .streamlit/secrets.toml")
        API_KEY = None

    if API_KEY:
        endereco_cliente = st.text_input("Endereço / CEP / Cidade", help="Ex: Av. Paulista, 1000, São Paulo, SP ou 01310-100 ou São Paulo")
        
        if st.button("Buscar Técnico Mais Próximo"):
            if endereco_cliente:
                with st.spinner("Buscando o técnico mais próximo..."):
                    tecnicos_proximos, localizacao_cliente = encontrar_tecnico_proximo(endereco_cliente, API_KEY, df_filtrado)
                    
                    if tecnicos_proximos is not None and not tecnicos_proximos.empty:
                        st.success("Busca concluída!")
                        
                        st.subheader("📍 Mapa dos Resultados (Google Maps)")
                        
                        tecnicos_coords = [
                            {'lat': row['latitude'], 'lng': row['longitude'], 'title': row['tecnico']}
                            for _, row in tecnicos_proximos.iterrows()
                        ]
                        
                        cliente_coords = {'lat': localizacao_cliente['lat'], 'lng': localizacao_cliente['lng']}
                        
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

                                    const cliente_marker = new google.maps.Marker({{
                                        position: cliente,
                                        map: map,
                                        title: "Cliente",
                                        icon: "http://googlemaps.com/mapfiles/kml/pal2/icon14.png"
                                    }});

                                    const tecnicos = {tecnicos_coords};
                                    tecnicos.forEach((tecnico) => {{
                                        new google.maps.Marker({{
                                            position: {{ lat: tecnico.lat, lng: tecnico.lng }},
                                            map: map,
                                            title: tecnico.title,
                                            icon: "http://googlemaps.com/mapfiles/kml/pal2/icon4.png"
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

                        st.markdown("<h3 style='text-align: center;'>Top 10 Técnicos Mais Próximos</h3>", unsafe_allow_html=True)
                        
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
                        st.download_button(
                            label="Exportar para Excel",
                            data=towrite,
                            file_name='tecnicos_proximos.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                        )

                        cols = st.columns(2)
                        for i, row in tecnicos_proximos.iterrows():
                            with cols[i % 2]:
                                st.markdown(f"**{i+1}. {row['tecnico']}**")
                                st.write(f"Coordenador: {row.get('coordenador', 'Não informado')}")
                                st.write(f"Cidade: {row.get('cidade', 'Não informada')}")
                                st.write(f"Distância: {row['distancia_km']:.2f} km")
                                
                                email_coordenador = row.get('email_coordenador')
                                if email_coordenador:
                                    # Usa st.markdown para criar uma div que alinha os botões
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
                        st.info("Nenhum técnico encontrado para os filtros e o local informados.")
            else:
                st.warning("Por favor, digite um endereço para iniciar a busca.")

with tab2:
    # --- DASHBOARD DE ESTATÍSTICAS NA ABA PRÓPRIA ---
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

    # Gráfico de barras para técnicos por UF
    st.subheader("Gráfico: Técnicos por UF")
    uf_counts = df_tecnicos['uf'].value_counts().reset_index()
    uf_counts.columns = ['UF', 'Quantidade']
    fig_uf = px.bar(uf_counts, x='UF', y='Quantidade', title="Técnicos por UF", color='UF')
    st.plotly_chart(fig_uf, use_container_width=True)
    
    # Gráfico de barras para técnicos por Coordenador
    st.subheader("Gráfico: Técnicos por Coordenador")
    coordenador_counts = df_tecnicos['coordenador'].value_counts().reset_index()
    coordenador_counts.columns = ['Coordenador', 'Quantidade']
    fig_coordenador = px.bar(coordenador_counts, x='Coordenador', y='Quantidade', title="Técnicos por Coordenador", color='Coordenador')
    st.plotly_chart(fig_coordenador, use_container_width=True)
    
    # --- MAPA INTERATIVO ---
    st.markdown("---")
    st.subheader("Mapa Interativo de Técnicos")
    st.info("Passe o mouse sobre os pontos para ver os detalhes dos técnicos.")
    
    df_mapa = df_tecnicos.dropna(subset=['latitude', 'longitude']).copy()
    
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
            get_color='[200, 30, 0, 160]',
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
    # --- LÓGICA DE LOGIN PARA O EDITOR ---
    if "editor_authenticated" not in st.session_state:
        st.session_state.editor_authenticated = False

    def check_password_editor():
        """Verifica a senha específica para o editor."""
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
        st.info("Clique duas vezes em uma célula para editar. Use o menu lateral para adicionar ou remover linhas.")

        if "df_editavel" not in st.session_state:
            st.session_state.df_editavel = df_tecnicos.copy()
            
        df_editavel = st.data_editor(st.session_state.df_editavel, num_rows="dynamic", use_container_width=True)

        st.session_state.df_editavel = df_editavel.copy()

        st.markdown("---")
        st.subheader("Atualizar e Salvar Alterações")
        
        API_KEY = st.secrets["api"]["google_maps"]
        if st.button("Atualizar Coordenadas", help="Preenche Latitude e Longitude de novos endereços."):
            with st.spinner("Atualizando coordenadas..."):
                for index, row in st.session_state.df_editavel.iterrows():
                    if ('endereco' in df_editavel.columns and str(row.get('endereco', '')) != str(df_tecnicos.loc[index]['endereco'])) or pd.isnull(row['latitude']) or pd.isnull(row['longitude']):
                        endereco_completo = f"{row.get('endereco', '')}, {row.get('cidade', '')}"
                        lat, lng = geocodificar_endereco(endereco_completo, API_KEY)
                        
                        if lat is not None and lng is not None:
                            st.session_state.df_editavel.at[index, 'latitude'] = lat
                            st.session_state.df_editavel.at[index, 'longitude'] = lng
                            st.success(f"Coordenadas de **{row['tecnico']}** atualizadas com sucesso!")
                        else:
                            st.warning(f"Não foi possível encontrar as coordenadas de **{row['tecnico']}**.")
                st.rerun()

        towrite_edit = io.BytesIO()
        st.session_state.df_editavel.to_excel(towrite_edit, index=False, header=True)
        towrite_edit.seek(0)
        st.download_button(
            label="Baixar Planilha Atualizada",
            data=towrite_edit,
            file_name='tecnicos_atualizado.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

# Rodapé com informações do desenvolvedor
st.markdown("---")
st.markdown("<div style='text-align:center;'>Desenvolvido por Edmilson Carvalho - Edmilson.carvalho@globalhitss.com.br © 2025</div>", unsafe_allow_html=True)
