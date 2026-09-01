import streamlit as st
import asyncio
import os
import re
import json
from datetime import datetime
import google.generativeai as genai
from playwright.async_api import async_playwright

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Weryfikator Kontrahentów", page_icon="🔍", layout="wide")

# Słownik rejestrów krajowych (możesz tu dopisywać państwa)
REJESTRY_KRAJOWE = {
    "Wielka Brytania": "https://find-and-update.company-information.service.gov.uk/",
    "UK": "https://find-and-update.company-information.service.gov.uk/",
    "Niemcy": "https://www.handelsregister.de/",
    "Szwajcaria": "https://www.zefix.ch/en/search/entity/welcome",
    "USA": "https://opencorporates.com/",
}

KRAJE_UE = [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI", 
    "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SK",
    "Austria", "Belgia", "Bułgaria", "Cypr", "Czechy", "Niemcy", "Dania", "Estonia", 
    "Grecja", "Hiszpania", "Finlandia", "Francja", "Chorwacja", "Węgry", "Irlandia", 
    "Włochy", "Litwa", "Luksemburg", "Łotwa", "Malta", "Holandia", "Polska", "Portugalia", "Rumunia", "Szwecja", "Słowacja"
]

def format_filename(nazwa_firmy: str) -> str:
    czysta_nazwa = re.sub(r'[^a-zA-Z0-9_-]', '_', nazwa_firmy).strip('_')
    data_dzis = datetime.now().strftime("%Y-%m-%d")
    return f"{czysta_nazwa}_{data_dzis}.pdf"

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
st.title("🔍 Automatyczny Weryfikator Kontrahentów")
st.caption("VIES ➔ Bazy państwowe / komercyjne ➔ Strona zleceniodawcy")

api_key = st.secrets.get("GEMINI_API_KEY", "").strip()

if not api_key:
    st.error("⚠️ Brak klucza GEMINI_API_KEY w Secrets! Dodaj go w ustawieniach Streamlit Settings -> Secrets.")
    st.stop()

# Konfiguracja Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-flash-latest")

wklejony_tekst = st.text_area(
    "Wklej dane kontrahenta (Nazwa, Adres, Kraj, NIP/Tax ID):",
    height=140,
    placeholder="Przykład:\nAcme Global Ltd\n123 Business Road, London, EC1A 1BB\nUnited Kingdom\nVAT: GB123456789"
)

# --- OBSŁUGA PRZEGLĄDARKI ---
async def weryfikuj_w_vies(kraj_kod: str, nip_clean: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://ec.europa.eu/taxation_customs/vies/#/vat-validation", timeout=30000)
            await page.wait_for_selector("#select-country", timeout=10000)
            await page.select_option("#select-country", kraj_kod)
            await page.fill("#vat-number", nip_clean)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(4000)
            
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            text_content = await page.inner_text("body")
            await browser.close()
            return pdf_bytes, text_content, "https://ec.europa.eu/taxation_customs/vies/"
        except Exception as e:
            await browser.close()
            return None, str(e), None

async def zrob_zrzut_url(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000, wait_until="networkidle")
            czas_teraz = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header_script = f"""
            const div = document.createElement('div');
            div.style.backgroundColor = '#1e293b';
            div.style.color = '#ffffff';
            div.style.padding = '10px 20px';
            div.style.fontSize = '14px';
            div.style.fontFamily = 'Arial, sans-serif';
            div.style.borderBottom = '2px solid #3b82f6';
            div.innerHTML = '<b>Zweryfikowano:</b> {czas_teraz} | <b>URL:</b> {url}';
            document.body.insertBefore(div, document.body.firstChild);
            """
            await page.evaluate(header_script)
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            text_content = await page.inner_text("body")
            await browser.close()
            return pdf_bytes, text_content
        except Exception as e:
            await browser.close()
            return None, str(e)

if st.button("🚀 Rozpocznij weryfikację", type="primary"):
    if not wklejony_tekst.strip():
        st.warning("Proszę wkleić dane firmy!")
        st.stop()

    try:
        # Krok 1: Parsowanie tekstu
        with st.spinner("1/3 Rozpoznawanie danych firmy..."):
            parse_prompt = f"""
            Wyodrębnij z poniższego tekstu dane firmy.
            Zwróć TYLKO czysty obiekt JSON (bez znaczników markdown) o strukturze:
            {{"nazwa": "...", "adres": "...", "kraj": "...", "nip": "..."}}

            Tekst:
            {wklejony_tekst}
            """
            parse_resp = model.generate_content(parse_prompt)
            
            czysty_json = re.search(r'\{.*\}', parse_resp.text, re.DOTALL)
            if czysty_json:
                dane = json.loads(czysty_json.group(0))
            else:
                dane = {"nazwa": wklejony_tekst[:30], "adres": "", "kraj": "", "nip": ""}

            nazwa = dane.get("nazwa", "")
            adres = dane.get("adres", "")
            kraj = dane.get("kraj", "")
            nip = dane.get("nip", "")

            st.info(f"**Rozpoznano:** {nazwa} | **Kraj:** {kraj} | **NIP/Tax ID:** {nip}")

        pdf_wynik = None
        zrodlo_url = ""
        surowy_tekst = ""
        nazwa_pliku = format_filename(nazwa)

        # Krok 2: Sprawdzenie w VIES
        czy_ue = any(k.lower() in kraj.lower() for k in KRAJE_UE)
        sukces_vies = False

        if czy_ue and nip:
            with st.spinner("2/3 Sprawdzanie w rejestrze VIES..."):
                nip_clean = re.sub(r'^[A-Z]{2}', '', nip.strip())
                kraj_kod = nip[:2].upper() if len(nip) > 2 and nip[:2].isalpha() else "DE"
                pdf_bytes, raw_txt, url_vies = asyncio.run(weryfikuj_w_vies(kraj_kod, nip_clean))
                
                if pdf_bytes and ("valid" in raw_txt.lower() or "ważny" in raw_txt.lower() or "valide" in raw_txt.lower()):
                    pdf_wynik = pdf_bytes
                    surowy_tekst = raw_txt
                    zrodlo_url = url_vies
                    sukces_vies = True

        # Krok 3: Rejestry krajowe / Strona WWW
        if not sukces_vies:
            with st.spinner("2/3 Szukanie w rejestrach lub na oficjalnej stronie firmy..."):
                search_prompt = f"""
                Podaj bezpośredni adres URL strony głównej lub podstrony prawnej (Impressum/Legal/Contact/Terms) dla firmy:
                Nazwa: {nazwa}
                Adres: {adres}
                Kraj: {kraj}
                Tax ID: {nip}
                Zwróć TYLKO bezpośredni adres URL zaczynający się od http:// lub https://.
                """
                search_resp = model.generate_content(search_prompt)
                match = re.search(r'https?://[^\s)"]+', search_resp.text)
                if match:
                    zrodlo_url = match.group(0)
                    pdf_bytes, raw_txt = asyncio.run(zrob_zrzut_url(zrodlo_url))
                    if pdf_bytes:
                        pdf_wynik = pdf_bytes
                        surowy_tekst = raw_txt

        # Krok 4: Analiza zgodności
        with st.spinner("3/3 Przygotowanie raportu..."):
            eval_prompt = f"""
            Porównaj dane wklejone przez użytkownika z tekstem pobranym ze strony.

            DANE UŻYTKOWNIKA:
            - Nazwa: {nazwa}
            - Adres: {adres}
            - NIP/Tax ID: {nip}

            TEKST ZE STRONY ({zrodlo_url}):
            {surowy_tekst[:5000]}

            Zwróć TYLKO czysty obiekt JSON (bez znaczników markdown ```json) w formacie:
            {{
                "status": "ZIELONY / NIEBIESKI / ZOLTY / CZERWONY",
                "znaleziona_nazwa": "...",
                "znaleziony_adres": "...",
                "znaleziony_nip": "...",
                "komunikat_roznice": "krótki opis różnic lub braków",
                "opis_zrodla": "krótki opis strony i ocena wiarygodności",
                "cytat_oryginalny": "fragment w języku obcym",
                "cytat_tlumaczenie": "tłumaczenie fragmentu na język polski"
            }}
            Reguły statusów:
            - ZIELONY: 100% zgodności
            - NIEBIESKI: pełna zgodność, ale drobne różnice w pisowni
            - ZOLTY: tylko część danych (brak NIP lub inny adres)
            - CZERWONY: brak potwierdzenia
            """
            eval_resp = model.generate_content(eval_prompt)
            
            wynik_json = re.search(r'\{.*\}', eval_resp.text, re.DOTALL)
            if wynik_json:
                raport = json.loads(wynik_json.group(0))
            else:
                raport = {
                    "status": "CZERWONY",
                    "znaleziona_nazwa": "Brak",
                    "znaleziony_adres": "Brak",
                    "znaleziony_nip": "Brak",
                    "komunikat_roznice": "Nie udało się sparsować odpowiedzi",
                    "opis_zrodla": zrodlo_url or "Nieznane",
                    "cytat_oryginalny": "",
                    "cytat_tlumaczenie": ""
                }

        # --- WYŚWIETLENIE RAPORTU ---
        st.markdown("---")
        st.subheader("📊 Wynik Weryfikacji")

        status_str = raport.get("status", "CZERWONY")
        kolor_map = {
            "ZIELONY": ("🟢 PEŁNA ZGODNOŚĆ (100%)", "success"),
            "NIEBIESKI": ("🔵 PEŁNA ZGODNOŚĆ (Drobne różnice w zapisie)", "info"),
            "ZOLTY": ("🟡 CZĘŚCIOWA ZGODNOŚĆ (Braki w danych)", "warning"),
            "CZERWONY": ("🔴 BRAK POTWIERDZENIA", "error")
        }
        etykieta, typ_alertu = kolor_map.get(status_str, ("🔴 BRAK POTWIERDZENIA", "error"))
        getattr(st, typ_alertu)(f"**Status:** {etykieta}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📋 Dane wklejone")
            st.write(f"**Nazwa:** {nazwa}")
            st.write(f"**Adres:** {adres}")
            st.write(f"**NIP / Tax ID:** {nip}")
        with col2:
            st.markdown("### 🔎 Dane odnalezione")
            st.write(f"**Nazwa:** {raport.get('znaleziona_nazwa', '-')}")
            st.write(f"**Adres:** {raport.get('znaleziony_adres', '-')}")
            st.write(f"**NIP / Tax ID:** {raport.get('znaleziony_nip', '-')}")

        if raport.get("komunikat_roznice"):
            st.info(f"**Uwagi:** {raport.get('komunikat_roznice')}")

        st.markdown("### 🌐 Informacje o źródle i wiarygodności")
        if zrodlo_url:
            st.write(f"**Źródło:** [{zrodlo_url}]({zrodlo_url})")
        st.write(f"**Ocena wiarygodności:** {raport.get('opis_zrodla', '-')}")

        if raport.get("cytat_oryginalny"):
            with st.expander("Zobacz oryginalny fragment ze strony oraz tłumaczenie"):
                st.write(f"**Oryginał:** {raport.get('cytat_oryginalny')}")
                st.write(f"**Tłumaczenie PL:** {raport.get('cytat_tlumaczenie')}")

        if pdf_wynik:
            st.markdown("### 📥 Plik dowodowy")
            st.download_button(
                label=f"⬇️ Pobierz potwierdzenie ({nazwa_pliku})",
                data=pdf_wynik,
                file_name=nazwa_pliku,
                mime="application/pdf"
            )

    except Exception as err:
        st.error(f"Wystąpił błąd podczas weryfikacji: {str(err)}")
