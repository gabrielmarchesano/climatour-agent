import streamlit as st
from tools.agent import recomendar_passeios


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
                resp = recomendar_passeios(estado)
                
                # Exibição do resultado do agente
                st.success("Recomendações geradas com sucesso!")
                st.markdown(resp)

            except Exception as e:
                st.error(f"Erro ao buscar recomendações: {e}")