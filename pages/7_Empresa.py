import streamlit as st
from utils.db import db_cursor
from datetime import datetime
import time

st.set_page_config(page_title="Empresa - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; }
</style>
""", unsafe_allow_html=True)

SYSTEM_USER = 1

from utils.auth import require_login

require_login()
company_id = st.session_state["company_id"]

st.title("🏢 Configurações da Empresa")
st.markdown("---")

# Carrega dados atuais
with db_cursor() as (_, cur):
    cur.execute("""
        SELECT name, cnpj, company_code, address, house_number, additional_information,
               city, state, zip_code, phone_number, email,
               latitude, longitude, location_radius,
               tolerance_early_minutes, tolerance_late_minutes
        FROM company WHERE id = %s
    """, (company_id,))
    empresa = cur.fetchone()

if not empresa:
    st.error("Empresa não encontrada.")
    st.stop()

aba_dados, aba_localizacao, aba_tolerancia = st.tabs(["📋 Dados Cadastrais", "📍 Localização", "⏱ Tolerância de Ponto"])

# ─── ABA DADOS ───────────────────────────────────────────────
with aba_dados:
    st.subheader("Informações da empresa")

    col1, col2 = st.columns(2)
    with col1:
        nome         = st.text_input("Razão Social *", value=empresa["name"] or "", max_chars=200)
        cnpj         = st.text_input("CNPJ", value=empresa["cnpj"] or "", disabled=True)
        telefone     = st.text_input("Telefone", value=empresa["phone_number"] or "", max_chars=20)
    with col2:
        codigo       = st.text_input("Código da Empresa", value=empresa["company_code"] or "", disabled=True)
        email_emp    = st.text_input("E-mail", value=empresa["email"] or "", disabled=True)

    st.markdown("##### Endereço")
    col3, col4 = st.columns([3, 1])
    with col3:
        endereco     = st.text_input("Logradouro", value=empresa["address"] or "", max_chars=200)
    with col4:
        numero       = st.text_input("Número", value=empresa["house_number"] or "", max_chars=20)

    complemento  = st.text_input("Complemento", value=empresa["additional_information"] or "", max_chars=100)

    col5, col6, col7 = st.columns([3, 2, 1])
    with col5:
        cidade       = st.text_input("Cidade", value=empresa["city"] or "", max_chars=100)
    with col6:
        cep          = st.text_input("CEP", value=empresa["zip_code"] or "", max_chars=10)
    with col7:
        estado       = st.text_input("UF", value=empresa["state"] or "", max_chars=2)

    st.markdown("")
    if st.button("Salvar Dados", type="primary", use_container_width=True, key="btn_salvar_dados"):
        if not nome.strip():
            st.error("Razão Social é obrigatória.")
        else:
            try:
                with db_cursor() as (_, cur):
                    cur.execute("""
                        UPDATE company SET
                            name                   = %s,
                            phone_number           = %s,
                            address                = %s,
                            house_number           = %s,
                            additional_information = %s,
                            city                   = %s,
                            state                  = %s,
                            zip_code               = %s,
                            update_date            = NOW()
                        WHERE id = %s
                    """, (
                        nome.strip(), telefone.strip() or None,
                        endereco.strip() or None, numero.strip() or None,
                        complemento.strip() or None, cidade.strip() or None,
                        estado.strip() or None, cep.strip() or None,
                        company_id
                    ))
                st.success("Dados atualizados com sucesso!")
                time.sleep(2)
                st.rerun()
            except Exception as ex:
                st.error(f"Erro ao salvar: {ex}")


# ─── ABA LOCALIZAÇÃO ─────────────────────────────────────────
with aba_localizacao:
    st.subheader("Localização do local de trabalho")
    st.caption(
        "Configure as coordenadas para validar se o funcionário está no local correto ao registrar o ponto. "
        "Para encontrar as coordenadas, acesse [maps.google.com](https://maps.google.com), clique com o botão direito "
        "no local e copie a latitude e longitude."
    )

    col_lat, col_lng, col_raio = st.columns(3)
    with col_lat:
        latitude  = st.number_input("Latitude",  value=float(empresa["latitude"]) if empresa["latitude"] else 0.0,
                                    format="%.6f", step=0.000001, key="lat")
    with col_lng:
        longitude = st.number_input("Longitude", value=float(empresa["longitude"]) if empresa["longitude"] else 0.0,
                                    format="%.6f", step=0.000001, key="lng")
    with col_raio:
        raio = st.number_input("Perímetro (metros)", min_value=50, max_value=5000,
                               value=int(empresa["location_radius"]) if empresa["location_radius"] else 300,
                               step=50, key="raio")

    if latitude != 0.0 and longitude != 0.0:
        st.map({"lat": [latitude], "lon": [longitude]}, zoom=15, use_container_width=True)

    st.markdown("")
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        if st.button("Salvar Localização", type="primary", use_container_width=True, key="btn_salvar_loc"):
            try:
                with db_cursor() as (_, cur):
                    cur.execute("""
                        UPDATE company SET
                            latitude        = %s,
                            longitude       = %s,
                            location_radius = %s,
                            update_date     = NOW()
                        WHERE id = %s
                    """, (
                        latitude if latitude != 0.0 else None,
                        longitude if longitude != 0.0 else None,
                        raio, company_id
                    ))
                st.success("Localização atualizada com sucesso!")
                time.sleep(2)
                st.rerun()
            except Exception as ex:
                st.error(f"Erro ao salvar: {ex}")
    with col_clear:
        if st.button("Remover Localização", use_container_width=True, key="btn_clear_loc"):
            try:
                with db_cursor() as (_, cur):
                    cur.execute("""
                        UPDATE company SET latitude = NULL, longitude = NULL, update_date = NOW()
                        WHERE id = %s
                    """, (company_id,))
                st.success("Localização removida.")
                time.sleep(2)
                st.rerun()
            except Exception as ex:
                st.error(f"Erro: {ex}")


# ─── ABA TOLERÂNCIA ──────────────────────────────────────────
with aba_tolerancia:
    st.subheader("Janela de tolerância para registro de ponto")
    st.caption(
        "Define quantos minutos antes (adiantado) e depois (atrasado) do horário da escala "
        "o funcionário pode registrar a entrada sem precisar de aprovação do gestor."
    )

    col_early, col_late = st.columns(2)
    with col_early:
        tol_early = st.number_input(
            "Adiantado (minutos)",
            min_value=0, max_value=120,
            value=int(empresa["tolerance_early_minutes"]) if empresa["tolerance_early_minutes"] is not None else 15,
            step=5, key="tol_early",
            help="Minutos que o funcionário pode registrar ANTES do horário da escala.",
        )
    with col_late:
        tol_late = st.number_input(
            "Atrasado (minutos)",
            min_value=0, max_value=120,
            value=int(empresa["tolerance_late_minutes"]) if empresa["tolerance_late_minutes"] is not None else 15,
            step=5, key="tol_late",
            help="Minutos que o funcionário pode registrar DEPOIS do horário da escala.",
        )

    st.info(
        f"Com essa configuração, funcionários podem registrar a entrada entre "
        f"**{tol_early} min antes** e **{tol_late} min depois** do horário da escala. "
        f"Fora dessa janela, a solicitação vai para aprovação do gestor."
    )

    st.markdown("")
    if st.button("Salvar Tolerância", type="primary", use_container_width=True, key="btn_salvar_tol"):
        try:
            with db_cursor() as (_, cur):
                cur.execute("""
                    UPDATE company SET
                        tolerance_early_minutes = %s,
                        tolerance_late_minutes  = %s,
                        update_date             = NOW()
                    WHERE id = %s
                """, (tol_early, tol_late, company_id))
            st.success("Tolerância atualizada com sucesso!")
            time.sleep(2)
            st.rerun()
        except Exception as ex:
            st.error(f"Erro ao salvar: {ex}")
