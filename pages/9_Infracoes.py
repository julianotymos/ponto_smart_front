import streamlit as st
from utils.db import db_cursor
from datetime import date

st.set_page_config(page_title="Infracoes - Ponto Smart", layout="wide")
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


from utils.auth import require_login


require_login()

email = st.session_state["company_email"]

st.title("Gestao de Infracoes")
st.markdown("---")

# --- Selecionar funcionario ---
with db_cursor() as (_, cur):
    cur.execute(
        """
        SELECT e.id, e.first_name || ' ' || e.last_name AS nome
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1
        ORDER BY e.first_name ASC
        """,
        (email,),
    )
    funcionarios = cur.fetchall()

if not funcionarios:
    st.info("Nenhum funcionario ativo encontrado.")
    st.stop()

opcoes = {f["nome"]: f["id"] for f in funcionarios}
func_nome = st.selectbox("Selecione o Funcionario", list(opcoes.keys()))
func_id = opcoes[func_nome]

st.markdown("---")

tab_lista, tab_nova = st.tabs(["Infracoes Registradas", "Registrar Nova Infracao"])

# --- Aba: listar infracoes ---
with tab_lista:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT
                id,
                infraction_description AS descricao,
                TO_CHAR(infraction_date, 'DD/MM/YYYY') AS data_infracao,
                infraction_severity AS pontos,
                COALESCE(observation, '') AS observacao,
                TO_CHAR(insert_date, 'DD/MM/YYYY HH24:MI') AS registrado_em
            FROM employee_infractions
            WHERE employee = %s AND status = 1
            ORDER BY infraction_date DESC
            """,
            (func_id,),
        )
        infracoes = cur.fetchall()

    if infracoes:
        total_pontos = sum(r["pontos"] for r in infracoes)
        col_total, _ = st.columns([1, 3])
        col_total.metric("Total de Pontos de Penalidade", total_pontos)

        st.dataframe(
            [dict(r) for r in infracoes],
            column_config={
                "id": None,
                "descricao": "Descricao",
                "data_infracao": "Data",
                "pontos": "Pontos",
                "observacao": "Observacao",
                "registrado_em": "Registrado em",
            },
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")
        st.markdown("**Excluir infracao**")
        ids_disponiveis = {f"[{r['id']}] {r['descricao']} — {r['data_infracao']}": r["id"] for r in infracoes}
        infracao_excluir = st.selectbox("Selecione para excluir", list(ids_disponiveis.keys()), key="excluir_sel")

        if st.button("Excluir Infracao", type="secondary"):
            infracao_id = ids_disponiveis[infracao_excluir]
            with db_cursor() as (_, cur):
                cur.execute(
                    "UPDATE employee_infractions SET status = 2 WHERE id = %s AND employee = %s",
                    (infracao_id, func_id),
                )
            st.success("Infracao removida com sucesso.")
            st.rerun()
    else:
        st.info(f"Nenhuma infracao registrada para {func_nome}.")

# --- Aba: nova infracao ---
with tab_nova:
    st.markdown(f"**Registrar infracao para: {func_nome}**")

    with st.form("form_infracao"):
        descricao = st.text_area("Descricao da Infracao", placeholder="Descreva a infracao cometida...")
        col_data, col_pontos = st.columns(2)
        with col_data:
            data_inf = st.date_input("Data da Infracao", value=date.today())
        with col_pontos:
            severidade = st.selectbox(
                "Severidade (Pontos)",
                options=[1, 2, 3, 5, 10],
                format_func=lambda x: {1: "1 — Leve", 2: "2 — Moderada", 3: "3 — Grave", 5: "5 — Muito Grave", 10: "10 — Gravissima"}[x],
            )
        observacao = st.text_input("Observacao (opcional)")

        submitted = st.form_submit_button("Registrar Infracao", type="primary")

    if submitted:
        if not descricao.strip():
            st.error("A descricao da infracao e obrigatoria.")
        else:
            with db_cursor() as (_, cur):
                cur.execute(
                    """
                    INSERT INTO employee_infractions
                        (employee, infraction_description, infraction_date, infraction_severity, observation, status, insert_date)
                    VALUES (%s, %s, %s, %s, %s, 1, NOW())
                    """,
                    (func_id, descricao.strip(), data_inf, severidade, observacao.strip() or None),
                )
            st.success(f"Infracao registrada com sucesso para {func_nome}.")
            st.rerun()
