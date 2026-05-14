import os
import requests
import streamlit as st

BUCKET = "fotos-funcionarios"


def upload_photo(file_bytes: bytes, employee_code: str, content_type: str) -> str:
    """Faz upload da foto para o Supabase Storage e retorna a URL publica."""
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    file_name = f"{employee_code}.{ext}"

    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["service_key"]
    except Exception:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]

    endpoint = f"{url}/storage/v1/object/{BUCKET}/{file_name}"

    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        data=file_bytes,
    )

    if response.status_code not in (200, 201):
        raise Exception(f"Erro no upload: {response.status_code} — {response.text}")

    public_url = f"{url}/storage/v1/object/public/{BUCKET}/{file_name}"
    return public_url
