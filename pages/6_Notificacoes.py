import streamlit as st
from utils.db import db_cursor
from datetime import date, datetime

st.set_page_config(page_title="Notificações - Ponto Smart", layout="wide")
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

SYSTEM_USER = 1

CATEGORIAS = {"Geral — todos os funcionários": "GENERAL", "Específica — funcionários selecionados": "SPECIFIC"}


def require_login():
    if "company_email" not in st.session_state:
        st.warning("Acesse a página inicial e informe o email da empresa.")
        st.stop()


require_login()
email = st.session_state["company_email"]
company_id = st.session_state["company_id"]

st.title("📣 Notificações")
st.markdown("---")

aba_cadastro, aba_lista = st.tabs(["➕ Nova Notificação", "📋 Notificações Cadastradas"])


# ─────────────────────────────────────────────
# ABA 1 — CADASTRO
# ─────────────────────────────────────────────
with aba_cadastro:
    st.subheader("Cadastrar nova notificação")

    # Busca funcionários da empresa para o seletor SPECIFIC
    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT id, first_name || ' ' || last_name AS nome
            FROM employee
            WHERE company = %s AND status = 1
            ORDER BY first_name
        """, (company_id,))
        funcionarios = cur.fetchall()

    opcoes_func = {f["nome"]: f["id"] for f in funcionarios}

    titulo = st.text_input("Título *", max_chars=200, placeholder="Ex: Atualização de política de ponto")
    corpo  = st.text_area("Mensagem *", placeholder="Digite o conteúdo da notificação...", height=120)

    col1, _ = st.columns(2)
    with col1:
        categoria_label = st.selectbox("Categoria *", list(CATEGORIAS.keys()))
    categoria = CATEGORIAS[categoria_label]

    funcionarios_selecionados = []
    if categoria == "SPECIFIC":
        funcionarios_selecionados = st.multiselect(
            "Funcionários *",
            list(opcoes_func.keys()),
            placeholder="Selecione os funcionários que receberão esta notificação",
        )

    st.markdown("##### Período de exibição")
    usa_fim = st.checkbox("Definir data fim")
    col3, col4 = st.columns(2)
    with col3:
        data_inicio = st.date_input("Data início *", value=date.today())
    with col4:
        data_fim = None
        if usa_fim:
            data_fim = st.date_input("Data fim", value=date.today(), key="data_fim")

    st.markdown("##### Regras de exibição")
    col5, col6, col7 = st.columns(3)
    with col5:
        max_por_dia    = st.number_input("Máx. por dia", min_value=1, max_value=99, value=1)
    with col6:
        max_por_semana = st.number_input("Máx. por semana", min_value=1, max_value=99, value=3)
    with col7:
        max_dias       = st.number_input("Por quantos dias", min_value=1, max_value=365, value=7)

    st.markdown("")
    submitted = st.button("Salvar Notificação", use_container_width=True, type="primary")

    if submitted:
        erros = []
        if not titulo.strip():
            erros.append("Título é obrigatório.")
        if not corpo.strip():
            erros.append("Mensagem é obrigatória.")
        if categoria == "SPECIFIC" and not funcionarios_selecionados:
            erros.append("Selecione pelo menos um funcionário para notificação específica.")
        if usa_fim and data_fim and data_fim < data_inicio:
            erros.append("Data fim não pode ser anterior à data início.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                with db_cursor() as (_, cur):
                    now = datetime.now()
                    cur.execute("""
                        INSERT INTO notification (
                            company, title, body, category,
                            start_date, end_date,
                            max_per_day, max_per_week, max_days,
                            insert_date, update_date, status, status_date, system_user
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s,
                            %s, %s, %s,
                            %s, %s, 1, %s, %s
                        ) RETURNING id
                    """, (
                        company_id, titulo.strip(), corpo.strip(), categoria,
                        data_inicio, data_fim,
                        max_por_dia, max_por_semana, max_dias,
                        now, now, now, SYSTEM_USER
                    ))
                    notif_id = cur.fetchone()["id"]

                    # Vincula funcionários se SPECIFIC
                    if categoria == "SPECIFIC":
                        for nome in funcionarios_selecionados:
                            emp_id = opcoes_func[nome]
                            cur.execute("""
                                INSERT INTO notification_employee (
                                    notification, employee,
                                    insert_date, update_date, status, status_date, system_user
                                ) VALUES (%s, %s, %s, %s, 1, %s, %s)
                            """, (notif_id, emp_id, now, now, now, SYSTEM_USER))

                st.success(f"Notificação **#{notif_id}** cadastrada com sucesso!")

            except Exception as ex:
                st.error(f"Erro ao salvar: {ex}")


# ─────────────────────────────────────────────
# ABA 2 — LISTAGEM
# ─────────────────────────────────────────────
with aba_lista:
    st.subheader("Notificações cadastradas")

    col_filtro1, col_filtro2 = st.columns([2, 1])
    with col_filtro1:
        filtro_status = st.selectbox("Status", ["Ativas", "Inativas", "Todas"], key="filtro_status")
    with col_filtro2:
        filtro_categoria = st.selectbox("Categoria", ["Todas", "GENERAL", "SPECIFIC"], key="filtro_cat")

    status_map = {"Ativas": "= 1", "Inativas": "= 2", "Todas": "IN (1, 2)"}
    where_status = status_map[filtro_status]
    where_cat = f"AND n.category = '{filtro_categoria}'" if filtro_categoria != "Todas" else ""

    with db_cursor() as (_, cur):
        cur.execute(f"""
            SELECT
                n.id,
                n.title                                        AS "Título",
                CASE n.category WHEN 'GENERAL' THEN 'Geral' ELSE 'Específica' END AS "Categoria",
                TO_CHAR(n.start_date, 'DD/MM/YYYY')           AS "Início",
                COALESCE(TO_CHAR(n.end_date, 'DD/MM/YYYY'), '—') AS "Fim",
                n.max_per_day                                  AS "Máx/dia",
                n.max_per_week                                 AS "Máx/sem",
                n.max_days                                     AS "Dias",
                CASE n.status WHEN 1 THEN 'Ativa' ELSE 'Inativa' END AS "Status",
                (SELECT COUNT(*) FROM notification_view nv WHERE nv.notification = n.id AND nv.confirmed = TRUE) AS "Confirmações"
            FROM notification n
            WHERE n.company = %s
              AND n.status {where_status}
              {where_cat}
            ORDER BY n.id DESC
        """, (company_id,))
        notificacoes = cur.fetchall()

    if not notificacoes:
        st.info("Nenhuma notificação encontrada.")
    else:
        dados = [dict(r) for r in notificacoes]
        ids = [d["id"] for d in dados]

        evento = st.dataframe(
            dados,
            use_container_width=True,
            hide_index=True,
            column_order=["Título", "Categoria", "Início", "Fim", "Máx/dia", "Máx/sem", "Dias", "Confirmações", "Status"],
            on_select="rerun",
            selection_mode="single-row",
        )

        linhas = evento.selection.rows if evento.selection else []

        if linhas:
            selecionado = dados[linhas[0]]
            notif_id_sel = ids[linhas[0]]

            st.markdown("---")
            st.markdown(f"**Selecionada:** #{notif_id_sel} — {selecionado['Título']}")

            # Busca dados completos da notificação selecionada
            with db_cursor() as (_, cur):
                cur.execute("""
                    SELECT title, body, category, start_date, end_date,
                           max_per_day, max_per_week, max_days, status
                    FROM notification WHERE id = %s
                """, (notif_id_sel,))
                detalhe = cur.fetchone()

            with db_cursor() as (_, cur):
                cur.execute("""
                    SELECT e.id, e.first_name || ' ' || e.last_name AS nome
                    FROM notification_employee ne
                    JOIN employee e ON e.id = ne.employee
                    WHERE ne.notification = %s AND ne.status = 1
                """, (notif_id_sel,))
                vinculados = cur.fetchall()
            nomes_vinculados = [r["nome"] for r in vinculados]

            aba_ver, aba_editar = st.tabs(["👁 Detalhes", "✏️ Editar"])

            # ── Detalhes ──
            with aba_ver:
                col_ver, col_desativar = st.columns([3, 1])
                with col_ver:
                    st.markdown(f"**Mensagem:** {detalhe['body']}")
                    if detalhe["category"] == "SPECIFIC" and nomes_vinculados:
                        st.markdown(f"**Funcionários:** {', '.join(nomes_vinculados)}")
                with col_desativar:
                    if detalhe["status"] == 1:
                        if st.button("🔴 Desativar", use_container_width=True, key="btn_desativar"):
                            with db_cursor() as (_, cur):
                                cur.execute("""
                                    UPDATE notification
                                    SET status = 2, update_date = NOW(), status_date = NOW()
                                    WHERE id = %s
                                """, (notif_id_sel,))
                            st.success("Notificação desativada.")
                            st.rerun()
                    else:
                        if st.button("🟢 Reativar", use_container_width=True, key="btn_reativar"):
                            with db_cursor() as (_, cur):
                                cur.execute("""
                                    UPDATE notification
                                    SET status = 1, update_date = NOW(), status_date = NOW()
                                    WHERE id = %s
                                """, (notif_id_sel,))
                            st.success("Notificação reativada.")
                            st.rerun()

            # ── Editar ──
            with aba_editar:
                e_titulo = st.text_input("Título *", value=detalhe["title"], max_chars=200, key="e_titulo")
                e_corpo  = st.text_area("Mensagem *", value=detalhe["body"], height=120, key="e_corpo")

                col_e1, _ = st.columns(2)
                with col_e1:
                    cats_labels = list(CATEGORIAS.keys())
                    cats_vals   = list(CATEGORIAS.values())
                    idx_cat = cats_vals.index(detalhe["category"]) if detalhe["category"] in cats_vals else 0
                    e_categoria_label = st.selectbox("Categoria *", cats_labels, index=idx_cat, key="e_cat")
                e_categoria = CATEGORIAS[e_categoria_label]

                e_funcionarios = []
                if e_categoria == "SPECIFIC":
                    e_funcionarios = st.multiselect(
                        "Funcionários *",
                        list(opcoes_func.keys()),
                        default=nomes_vinculados,
                        key="e_funcs",
                    )

                st.markdown("##### Período de exibição")
                e_usa_fim = st.checkbox("Definir data fim", value=detalhe["end_date"] is not None, key="e_usa_fim")
                col_e3, col_e4 = st.columns(2)
                with col_e3:
                    e_inicio = st.date_input("Data início *", value=detalhe["start_date"], key="e_inicio")
                with col_e4:
                    e_fim = None
                    if e_usa_fim:
                        e_fim = st.date_input("Data fim", value=detalhe["end_date"] or date.today(), key="e_fim")

                st.markdown("##### Regras de exibição")
                col_e5, col_e6, col_e7 = st.columns(3)
                with col_e5:
                    e_max_dia = st.number_input("Máx. por dia", min_value=1, max_value=99, value=detalhe["max_per_day"], key="e_mpd")
                with col_e6:
                    e_max_sem = st.number_input("Máx. por semana", min_value=1, max_value=99, value=detalhe["max_per_week"], key="e_mps")
                with col_e7:
                    e_max_dias = st.number_input("Por quantos dias", min_value=1, max_value=365, value=detalhe["max_days"], key="e_md")

                st.markdown("")
                if st.button("Salvar Alterações", type="primary", use_container_width=True, key="btn_salvar_edicao"):
                    erros_e = []
                    if not e_titulo.strip():
                        erros_e.append("Título é obrigatório.")
                    if not e_corpo.strip():
                        erros_e.append("Mensagem é obrigatória.")
                    if e_categoria == "SPECIFIC" and not e_funcionarios:
                        erros_e.append("Selecione pelo menos um funcionário.")
                    if e_usa_fim and e_fim and e_fim < e_inicio:
                        erros_e.append("Data fim não pode ser anterior à data início.")

                    if erros_e:
                        for err in erros_e:
                            st.error(err)
                    else:
                        try:
                            with db_cursor() as (_, cur):
                                cur.execute("""
                                    UPDATE notification SET
                                        title        = %s,
                                        body         = %s,
                                        category     = %s,
                                        start_date   = %s,
                                        end_date     = %s,
                                        max_per_day  = %s,
                                        max_per_week = %s,
                                        max_days     = %s,
                                        update_date  = NOW(),
                                        status_date  = NOW()
                                    WHERE id = %s
                                """, (
                                    e_titulo.strip(), e_corpo.strip(), e_categoria,
                                    e_inicio, e_fim,
                                    e_max_dia, e_max_sem, e_max_dias,
                                    notif_id_sel,
                                ))

                                # Atualiza vínculos SPECIFIC: desativa todos e reinsere
                                cur.execute("""
                                    UPDATE notification_employee
                                    SET status = 2, update_date = NOW(), status_date = NOW()
                                    WHERE notification = %s
                                """, (notif_id_sel,))

                                if e_categoria == "SPECIFIC":
                                    now = datetime.now()
                                    for nome in e_funcionarios:
                                        emp_id = opcoes_func[nome]
                                        cur.execute("""
                                            INSERT INTO notification_employee (
                                                notification, employee,
                                                insert_date, update_date, status, status_date, system_user
                                            ) VALUES (%s, %s, %s, %s, 1, %s, %s)
                                            ON CONFLICT DO NOTHING
                                        """, (notif_id_sel, emp_id, now, now, now, SYSTEM_USER))

                            st.success("Notificação atualizada com sucesso!")
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Erro ao salvar: {ex}")
