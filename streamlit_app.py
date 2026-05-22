import streamlit as st
import requests
from streamlit_oauth import OAuth2Component
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
h1 { margin-bottom: 0 !important; }
h2, h3 { margin-top: 0 !important; margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("# Ponto Smart\n##### Sistema de Gestao de Ponto Eletronico\n---")

def login_empresa(email: str) -> bool:
    with db_cursor() as (_, cur):
        cur.execute(
            "SELECT id, name FROM company WHERE email = %s AND status = 1 LIMIT 1",
            (email,),
        )
        company = cur.fetchone()
    if company:
        st.session_state["company_email"] = email
        st.session_state["company_id"]    = company["id"]
        st.session_state["company_name"]  = company["name"]
        return True
    return False

# Se já está logado, mostra info e sai
if "company_name" in st.session_state:
    st.info(f"Empresa ativa: **{st.session_state['company_name']}** ({st.session_state['company_email']})")
    st.markdown("Use o menu lateral esquerdo para navegar entre as secoes.")
    st.stop()

col_form, col_info = st.columns([1, 2])

with col_form:
    st.markdown("### Acesso")

    # ── Login com Google ──────────────────────────────────
    oauth2 = OAuth2Component(
        client_id=st.secrets["google"]["client_id"],
        client_secret=st.secrets["google"]["client_secret"],
        authorize_endpoint="https://accounts.google.com/o/oauth2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        refresh_token_endpoint="https://oauth2.googleapis.com/token",
        revoke_token_endpoint="https://oauth2.googleapis.com/revoke",
    )

    result = oauth2.authorize_button(
        name="Entrar com Google",
        redirect_uri=st.secrets["google"]["redirect_uri"],
        scope="openid email profile",
        icon="https://www.google.com/favicon.ico",
        use_container_width=True,
        key="google_login",
    )

    if result and "token" in result:
        token = result["token"].get("access_token")
        if token:
            userinfo = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            ).json()
            email = userinfo.get("email", "")
            if login_empresa(email):
                st.rerun()
            else:
                st.error(f"Nenhuma empresa encontrada para o email **{email}**.")

    st.markdown("<div style='text-align:center;color:#aaa;font-size:12px;margin:8px 0'>ou</div>", unsafe_allow_html=True)

    # ── Login por email manual ────────────────────────────
    with st.expander("Entrar com email"):
        email_input = st.text_input(
            "Email da empresa",
            value=st.session_state.get("company_email", ""),
            placeholder="empresa@exemplo.com",
        )
        if st.button("Entrar", type="primary", use_container_width=True):
            if "@" not in email_input:
                st.error("Informe um email valido.")
            elif login_empresa(email_input):
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
