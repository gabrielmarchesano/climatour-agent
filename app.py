import streamlit as st
from tools.agent import recomendar_passeios


def obter_fuso_do_navegador() -> tuple[str | None, int | None]:
    """Lê o fuso horário do navegador de quem está acessando o app.

    O servidor que hospeda o Streamlit normalmente roda em UTC, então usar o
    relógio dele erraria o dia perto da meia-noite (às 22h em Brasília já é o
    dia seguinte em UTC). ``st.context`` expõe o fuso do próprio navegador,
    que é o que define o "hoje" do usuário.

    Preferimos o nome IANA (``timezone``) porque ele carrega as regras de
    horário de verão; o deslocamento em minutos (``timezone_offset``) serve de
    reserva. Ambos são lidos defensivamente: são atributos relativamente
    recentes do Streamlit (1.42+) e podem vir vazios em reruns automáticos.

    :return: (nome IANA do fuso ou None, deslocamento em minutos ou None).
    """
    contexto = getattr(st, "context", None)
    if contexto is None:
        return None, None

    nome = getattr(contexto, "timezone", None) or None
    offset = getattr(contexto, "timezone_offset", None)
    if not isinstance(offset, (int, float)):
        offset = None
    return nome, offset


def init_estado() -> None:
    """Cria as chaves de sessão na primeira renderização.

    Como ``st.session_state`` é reiniciado a cada recarregamento da página, o
    histórico começa vazio automaticamente (Requisito 2.4).
    """
    if "mensagens" not in st.session_state:
        st.session_state["mensagens"] = []      # list[dict]
    if "feedback" not in st.session_state:
        st.session_state["feedback"] = {}        # dict[int, str]


def render_historico() -> None:
    """Exibe todas as mensagens do histórico na ordem cronológica.

    A ordem de iteração é exatamente a ordem de inserção na lista, distinguindo
    balões de usuário e do assistente (Requisitos 1.2, 1.3). As respostas do
    assistente recebem os botões de feedback 👍/👎 (Requisito 2.1).
    """
    for indice, msg in enumerate(st.session_state["mensagens"]):
        with st.chat_message(msg["role"]):        # "user" | "assistant"
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_botoes_feedback(indice)


def render_botoes_feedback(indice: int) -> None:
    """Renderiza 👍/👎 para a resposta na posição ``indice`` do histórico.

    A avaliação atual é destacada com ``type="primary"``; as demais ficam como
    ``secondary`` (Requisito 5.1).
    """
    col_pos, col_neg = st.columns(2)
    atual = st.session_state["feedback"].get(indice)
    if col_pos.button("👍", key=f"fb_pos_{indice}",
                      type="primary" if atual == "positivo" else "secondary"):
        registrar_feedback(indice, "positivo")
    if col_neg.button("👎", key=f"fb_neg_{indice}",
                      type="primary" if atual == "negativo" else "secondary"):
        registrar_feedback(indice, "negativo")


def registrar_feedback(indice: int, avaliacao: str) -> None:
    """Associa o Feedback_Aval à resposta e força re-renderização.

    O feedback é indexado pela posição da resposta no histórico, associando cada
    avaliação à resposta correta (Requisito 5.2).
    """
    st.session_state["feedback"][indice] = avaliacao
    st.rerun()


def main() -> None:
    """Orquestra a interface de chat: estado, histórico, entrada e erros.

    Configura a página, inicializa o estado da sessão, renderiza o histórico e
    processa a entrada do usuário. Ao receber uma mensagem, registra-a no
    histórico ANTES de chamar o agente (Requisito 1.4), chama
    ``recomendar_passeios`` dentro de um ``st.spinner`` e anexa a resposta como
    mensagem do assistente (Requisitos 2.3, 5.3). Erros são capturados e
    exibidos no próprio chat (Requisitos 1.1, 6.4).
    """
    st.set_page_config(page_title="ClimaTour", page_icon="🌤️")
    st.title("ClimaTour Agent")
    init_estado()
    render_historico()

    prompt = st.chat_input("Sobre qual cidade/estado quer planejar um passeio?")
    if prompt:
        # Requisito 1.4: registra a mensagem do usuário ANTES de gerar resposta
        st.session_state["mensagens"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Consultando clima, previsão e atrações..."):
                try:
                    fuso_nome, fuso_offset = obter_fuso_do_navegador()
                    resposta = recomendar_passeios(
                        st.session_state["mensagens"],
                        st.session_state["feedback"],
                        fuso_nome=fuso_nome,
                        fuso_offset_minutos=fuso_offset,
                    )
                    st.markdown(resposta)
                    st.session_state["mensagens"].append(
                        {"role": "assistant", "content": resposta}
                    )
                    # Re-renderiza p/ anexar os botões de feedback à nova resposta
                    st.rerun()
                except Exception as e:
                    # Requisito 6.4: erro exibido no próprio fluxo do chat
                    st.error(f"Erro ao gerar recomendação: {e}")


if __name__ == "__main__":
    main()