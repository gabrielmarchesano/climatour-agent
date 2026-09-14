import streamlit as st
import requests

# URL da sua API FastAPI baseada no cli.py existente
API_URL = "http://127.0.0.1:8000/recomendacao"

st.set_page_config(page_title="ClimaTour", page_icon="🌤️")

st.title("ClimaTour Agent")
st.write("Agente de IA para recomendação de passeios turísticos com base no clima atual.")

# Campo de entrada de texto
estado = st.text_input("Em qual estado você está?", placeholder="Ex: Minas Gerais")

# Botão para acionar a busca
if st.button("Buscar Passeios"):
    if not estado.strip():
        st.warning("Nenhum estado informado. Por favor, digite um estado.")
    else:
        # Mostra um spinner de carregamento enquanto aguarda o agente (agent.py/main.py) processar
        with st.spinner(f"Consultando o clima e buscando as melhores opções em {estado}..."):
            try:
                # Requisição para a API local configurada no main.py
                resp = requests.post(API_URL, json={"estado": estado})
                resp.raise_for_status()
                
                # Exibição do resultado do agente
                st.success("Recomendações geradas com sucesso!")
                st.markdown(resp.json()["recomendacao"])
                
            except requests.exceptions.ConnectionError:
                st.error("Não consegui conectar à API. Ela está rodando? Lembre-se de iniciar com: `uvicorn main:app`")
            except requests.exceptions.HTTPError as e:
                st.error(f"Erro na API: {e}")
                try:
                    st.error(f"Detalhe do erro: {resp.json().get('detail')}")
                except ValueError:
                    pass