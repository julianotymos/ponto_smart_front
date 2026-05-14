import streamlit as st
from utils.db import db_cursor

st.set_page_config(
    page_title="Ponto Smart - Gestao",
    page_icon="clock3",
    layout="wide",
)

st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
@media (min-width: 768px) { .block-container { padding-top: 0.5rem !important; } }
h1, h2, h3 { margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { position: relative; }
header[data-testid="stHeader"]::after {
    content: "Ponto Smart";
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 1rem;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

st.title("Ponto Smart")
st.subheader("Sistema de Gestao de Ponto Eletronico")
st.markdown("---")

col_form, col_info = st.columns([1, 2])

with col_form:
    st.markdown("### Acesso")
    email_input = st.text_input(
        "Email da empresa",
        value=st.session_state.get("company_email", ""),
        placeholder="empresa@exemplo.com",
    )

    if st.button("Entrar", type="primary", use_container_width=True):
        if "@" not in email_input:
            st.error("Informe um email valido.")
        else:
            with db_cursor() as (_, cur):
                cur.execute(
                    "SELECT id, name FROM company WHERE email = %s AND status = 1 LIMIT 1",
                    (email_input,),
                )
                company = cur.fetchone()

            if company:
                st.session_state["company_email"] = email_input
                st.session_state["company_id"] = company["id"]
                st.session_state["company_name"] = company["name"]
                st.success(f"Bem-vindo! Empresa: **{company['name']}**")
                st.rerun()
            else:
                st.error("Empresa nao encontrada ou inativa.")

with col_info:
    st.markdown("### Navegacao")
    st.markdown("""
| Pagina | Descricao |
|--------|-----------|
| **Dashboard** | KPIs gerais, funcionarios no ponto e proximos aniversarios |
| **Relatorio de Ponto** | Historico de registros por periodo e funcionario |
| **Infracoes** | Visualizar e registrar advertencias e infracao |
| **Ajuste de Ponto** | Corrigir ou excluir registros manualmente |
| **Novo Funcionario** | Cadastrar novo colaborador na empresa |
""")

if "company_name" in st.session_state:
    st.info(f"Empresa ativa: **{st.session_state['company_name']}** ({st.session_state['company_email']})")
    st.markdown("Use o menu lateral esquerdo para navegar entre as secoes.")
