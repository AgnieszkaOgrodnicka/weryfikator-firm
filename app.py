import streamlit as st
import json
import re
import google.generativeai as genai

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Weryfikator Kontrahentów", page_icon="🔍", layout="wide")

# --- LOGOWANIE ---
def check_password():
    app_password = st.secrets.get("APP_PASSWORD", "admin123")
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔒 Dostęp zablokowany")
        haslo = st.text_input("Podaj hasło dostępu:", type="password")
        if st.button("Zaloguj"):
            if haslo == app_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Nieprawidłowe hasło!")
        return False
    return True

if not check_password():
    st.stop()

# --- INTERFEJS GŁÓWNY ---
st.title("🔍 Szybki Weryfikator Kontrahentów")
st.caption("Ręczne wprowadzanie danych ➔ Wyszukiwanie w rejestrach i internecie")

api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
if not api_key:
    st.error("⚠️ Brak klucza GEMINI_API_KEY w Secrets!")
    st.stop()

genai.configure(api_key=api_key)
try:
    dostepne_modele = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    wybrany_model = "models/gemini-1.5-flash" if "models/gemini-1.5-flash" in dostepne_modele else dostepne_modele[0]
    model = genai.GenerativeModel(wybrany_model)
except Exception:
    model = genai.GenerativeModel("gemini-1.5-flash")

st.markdown("### 1. Wprowadź dane firmy")
col1, col2 = st.columns(2)
with col1:
    nazwa = st.text_input("Nazwa firmy")
    adres = st.text_input("Adres (wraz z miastem)")
with col2:
    nip = st.text_input("NIP / Tax ID")

if st.button("🚀 Szukaj informacji", type="primary"):
    if not nazwa and not nip:
        st.warning("Proszę podać przynajmniej nazwę firmy lub NIP!")
        st.stop()

    with st.spinner("Przeszukiwanie baz państwowych i stron internetowych..."):
        try:
            prompt = f"""
            Znajdź informacje o poniższej firmie. 
            Szukaj w pierwszej kolejności w oficjalnych państwowych bazach przedsiębiorstw, a jeśli tam nie ma - na oficjalnej stronie internetowej firmy.
            
            Szukana firma:
            Nazwa: {nazwa}
            Adres: {adres}
            NIP/Tax ID: {nip}

            Zwróć TYLKO czysty obiekt JSON (bez formatowania markdown), zawierający odnalezione dane:
            {{
                "znaleziona_nazwa": "...",
                "znaleziony_adres": "...",
                "znaleziony_nip": "...",
                "zrodlo_url": "dokładny adres www, skąd pochodzą dane (zaczynający się od http)",
                "typ_zrodla": "np. Rejestr państwowy, Strona internetowa"
            }}
            Jeśli nie możesz znaleźć danej informacji, wpisz "Brak danych".
            """
            odpowiedz = model.generate_content(prompt)
            
            wynik_json = re.search(r'\{.*\}', odpowiedz.text, re.DOTALL)
            if wynik_json:
                dane_ai = json.loads(wynik_json.group(0))
            else:
                dane_ai = {
                    "znaleziona_nazwa": "Brak", 
                    "znaleziony_adres": "Brak", 
                    "znaleziony_nip": "Brak", 
                    "zrodlo_url": "Brak", 
                    "typ_zrodla": "Błąd interpretacji"
                }

            st.markdown("---")
            st.subheader("📊 Wynik do ręcznego porównania")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("### 📋 Dane wpisane")
                st.write(f"**Nazwa:** {nazwa if nazwa else '-'}")
                st.write(f"**Adres:** {adres if adres else '-'}")
                st.write(f"**NIP:** {nip if nip else '-'}")
            
            with c2:
                st.markdown("### 🔎 Dane odnalezione")
                st.write(f"**Nazwa:** {dane_ai.get('znaleziona_nazwa', '-')}")
                st.write(f"**Adres:** {dane_ai.get('znaleziony_adres', '-')}")
                st.write(f"**NIP:** {dane_ai.get('znaleziony_nip', '-')}")
                
            st.markdown("### 🌐 Źródło")
            st.write(f"**Typ rejestru/strony:** {dane_ai.get('typ_zrodla', '-')}")
            url = dane_ai.get("zrodlo_url", "")
            if url and url.startswith("http"):
                st.write(f"**Link:** [{url}]({url})")
            else:
                st.write(f"**Link:** {url}")

        except Exception as e:
            st.error(f"Wystąpił błąd podczas wyszukiwania: {str(e)}")
