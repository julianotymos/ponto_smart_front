import streamlit as st
from streamlit_cookies_controller import CookieController


def require_login():
    if "company_name" not in st.session_state:
        try:
            cookies = CookieController()
            saved_email = cookies.get("ps_email")
            saved_id    = cookies.get("ps_id")
            saved_name  = cookies.get("ps_name")
            if saved_email and saved_id and saved_name:
                st.session_state["company_email"] = saved_email
                st.session_state["company_id"]    = int(saved_id)
                st.session_state["company_name"]  = saved_name
        except Exception:
            pass

    if "company_email" not in st.session_state:
        st.warning("Acesse a página inicial e informe o email da empresa.")
        st.stop()
