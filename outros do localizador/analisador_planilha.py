import pandas as pd
import os
import sys

# --- CONFIGURAÇÃO ---
# O script espera encontrar o arquivo 'tecnicos.xlsx' na mesma pasta.
FILE_NAME = 'tecnicos.xlsx'
OUTPUT_FILE_NAME = 'tecnicos_analisado_e_limpo.xlsx'

def analisar_e_limpar(file_path):
    """
    Carrega o DataFrame, corrige o formato das coordenadas (vírgula para ponto)
    e padroniza campos de texto essenciais.
    """
    print(f"Iniciando a análise do arquivo: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"\nERRO: Arquivo '{file_path}' não encontrado. Certifique-se de que o arquivo está na mesma pasta que este script.")
        return None

    try:
        # Tenta ler o arquivo Excel
        df = pd.read_excel(file_path)
    except Exception as e:
        print(f"\nERRO ao ler o arquivo Excel: {e}")
        return None
    
    # DataFrame para coletar todos os problemas encontrados
    problemas_encontrados = []

    print(f"Total de técnicos na planilha: {len(df)}")
    print("---")
    
    # =========================================================================
    # 1. PADRONIZAÇÃO DE TEXTO (UF, Cidade, Coordenador)
    # =========================================================================
    print("1. Padronização de campos de texto (UF, Cidade, Coordenador)...")
    str_cols = ['tecnico', 'cidade', 'uf', 'coordenador', 'endereco', 'email_coordenador']
    
    for col in str_cols:
        if col in df.columns:
            # Garante que é string, remove espaços e padroniza para Título (Primeira Maiúscula)
            df[col] = df[col].astype(str).str.strip()
            
            # Padroniza para título apenas colunas que não são endereço ou e-mail
            if col in ['tecnico', 'cidade', 'uf', 'coordenador']:
                df[col] = df[col].str.title()
            
            # Tratar valores vazios ou 'nan' (que vira 'Nan' após title())
            if col == 'coordenador':
                df[col] = df[col].replace({'Nan': 'Não Informado', '': 'Não Informado'})
            elif col in ['tecnico', 'cidade', 'uf'] and (df[col] == 'Nan').any():
                 # Substitui NaN's que viraram 'Nan' (string) para um valor vazio, se necessário
                 df[col] = df[col].replace('Nan', '')
    
    print("   -> Padronização concluída.")

    # =========================================================================
    # 2. CORREÇÃO DE COORDENADAS (Vírgula para Ponto)
    # =========================================================================
    print("\n2. Corrigindo e convertendo coordenadas (Vírgula ',' para Ponto '.')...")
    
    for col in ['latitude', 'longitude']:
        if col in df.columns:
            # Converte para string para usar o replace
            df[col] = df[col].astype(str).str.strip()
            # O Passo CRÍTICO: Troca vírgula por ponto
            df[col] = df[col].str.replace(',', '.', regex=False)
            # Converte para numérico, forçando erros (como letras ou 'N/A') a virarem NaN
            # Este é o valor que será usado no Streamlit
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            print(f"   AVISO: Coluna '{col}' não encontrada na planilha. Ignorando.")

    # =========================================================================
    # 3. RELATÓRIO DE INCONSISTÊNCIAS (NaNs)
    # =========================================================================
    
    print("\n3. Verificando inconsistências de dados...")
    
    # Técnicos que ficaram com NaN nas coordenadas
    tecnicos_sem_coord = df[df['latitude'].isnull() | df['longitude'].isnull()]
    
    if not tecnicos_sem_coord.empty:
        print(f"   [ERRO] Técnicos perdidos na busca de proximidade (SEM COORDENADAS VÁLIDAS): {len(tecnicos_sem_coord)}")
        
        # Log de problemas para o relatório
        for idx, row in tecnicos_sem_coord.iterrows():
            problemas_encontrados.append({
                'Técnico': row['tecnico'],
                'Problema': 'SEM COORDENADAS VÁLIDAS (NaN)',
                'Detalhe': f"Lat: {row.get('latitude')}, Long: {row.get('longitude')}"
            })
            print(f"      -> {row['tecnico']} ({row.get('cidade', 'N/A')}): Coordenada inválida ou ausente.")
            
    else:
        print("   [OK] Todas as linhas possuem Latitude e Longitude válidas.")

    # Verificação do Romulo (Específico, para confirmar a correção)
    # A padronização de texto garante que a busca por nome funcione
    romulo = df[df['tecnico'] == 'Romulo Neilson Bernardes Trajano']
    if not romulo.empty:
        # A função pd.notnull é mais segura para verificar NaN
        if pd.notnull(romulo.iloc[0]['latitude']) and pd.notnull(romulo.iloc[0]['longitude']):
             print(f"\n   [OK] Status do Romulo: Coordenadas válidas após a limpeza ({romulo.iloc[0]['latitude']:.4f}, {romulo.iloc[0]['longitude']:.4f}).")
        else:
             print("\n   [ERRO] Status do Romulo: Coordenadas AINDA estão inválidas. Verifique se o valor original na planilha é realmente um número (ex: não é 'N/A').")
    else:
        print("\n   AVISO: O técnico 'Romulo Neilson Bernardes Trajano' não foi encontrado na planilha.")


    # =========================================================================
    # 4. SALVAR ARQUIVO LIMPO E RELATÓRIO
    # =========================================================================
    
    # Salva o DataFrame limpo
    try:
        df.to_excel(OUTPUT_FILE_NAME, index=False)
        print(f"\n--- SUCESSO ---")
        print(f"Planilha analisada e limpa salva em: {OUTPUT_FILE_NAME}")
        
        if problemas_encontrados:
            df_log = pd.DataFrame(problemas_encontrados)
            log_file = 'relatorio_inconsistencias.xlsx'
            df_log.to_excel(log_file, index=False)
            print(f"Relatório de Inconsistências salvo em: {log_file}")
            print("\nPróximo passo: Renomeie o arquivo salvo ou use este arquivo limpo para rodar o Streamlit e teste novamente.")
        
    except Exception as e:
        print(f"\nERRO ao salvar o arquivo: {e}")
        
    return df


if __name__ == "__main__":
    # Permite passar o nome do arquivo como argumento, se necessário
    if len(sys.argv) > 1:
        FILE_NAME = sys.argv[1]
        
    analisar_e_limpar(FILE_NAME)