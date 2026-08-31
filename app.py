import streamlit as st
import asyncio
import os
import re
from datetime import datetime
from google import genai
from google.genai import types
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Weryfikator Kontrahentów", page_icon="🔍", layout="wide")

# --- SŁOWNIK PRIORYTETOWYCH REJESTRÓW (MOŻESZ TU DOPISYWAĆ KRAJE) ---
REJESTRY_KRAJOWE = {
    "Wielka Brytania": "https://find-and-update.company-information.service.gov.uk/",
    "UK": "https://find-and-update.company-information.service.gov.uk/",
    "Niemcy": "https://www.handelsregister.de/",
    "Szwajcaria": "https://www.zefix.ch/en/search/entity/welcome",
    "USA": "https://opencorporates.com/", # Domyślna otwarta baza ogólnoamerykańska
    # Tutaj możesz dopisywać kolejne kraje:
    # "Norwegia": "https://www.brreg.no/",
    # "Francja": "https://data.inpi.fr/",
}

# Kraje UE obsługiwane przez VIES
KRAJE_UE = [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI", 
    "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SK",
    "Austria", "Belgia", "Bułgaria", "Cypr", "Czechy", "Niemcy", "Dania", "Estonia", 
    "Grecja", "Hiszpania", "Finlandia", "Francja", "Chorwacja", "Węgry", "Irlandia", 
    "Włochy", "Litwa", "Luksemburg", "Łotwa", "Malta", "Holandia", "Polska", "Portugalia", "Rumunia", "Szwecja", "Słowacja"
]

# --- STRUKTURA DANYCH DLA AI ---
class ParsedCompanyData(BaseModel):
    nazwa: str = Field(description="Nazwa firmy")
    adres: str = Field(description="Adres firmy (ulica, kod, miasto)")
    kraj: str = Field(description="Kraj siedziby firmy")
    nip: str = Field(description="Numer NIP/Tax ID/VAT/EIN (z prefiksem lub bez)")

class VerificationResult(BaseModel):
    status: str = Field(description="Jeden z: 'ZIELONY', 'NIEBIESKI', 'ZOLTY', 'CZERWONY'")
    znaleziona_nazwa: str = Field(description="Nazwa odnaleziona w źródle")
    znaleziony_adres: str = Field(description="Adres odnaleziony w źródle")
    znaleziony_nip: str = Field(description="NIP/Tax ID odnaleziony w źródle")
    komunikat_roznice: str = Field(description="Opis drobnych różnic w zapisie (dla NIEBIESKIEGO) lub braków (dla ZOLTEGO)")
    opis_zrodla: str = Field(description="Krótkie wyjaśnienie co to za strona i jej poziom wiarygodności")
    cytat_oryginalny: str = Field(description="Oryginalny tekst ze strony w obcym języku")
    cytat_tlumaczenie: str = Field(description="Tłumaczenie cytatu na język polski")

# --- FUNKCJE POMOCNICZE ---
def format_filename(nazwa_firmy: str) -> str:
    czysta_nazwa = re.sub(r'[^a-zA-Z0-9_-]', '_', nazwa_firmy).strip('_')
    data_dzis = datetime.now().strftime("%Y-%m-%d")
    return f"{czysta_nazwa}_{data_dzis}.pdf"

# --- SPRAWDZANIE HASŁA ---
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

# --- GŁÓWNY INTERFEJS ---
st.title("🔍 Automatyczny Weryfikator Kontrahentów")
st.caption("Trójstopniowa weryfikacja: VIES ➔ Bazy państwowe / komercyjne ➔ Strona zleceniodawcy")

api_key = st.secrets.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None

wklejony_tekst = st.text_area(
    "Wklej dane kontrahenta (Nazwa, Adres, Kraj, NIP/Tax ID w dowolnym formacie):",
    height=150,
    placeholder="Przykład:\nAcme Global Ltd\n123 Business Road, London, EC1A 1BB\nUnited Kingdom\nVAT: GB123456789"
)

# --- ASYNCHRONICZNA OBSŁUGA PRZEGLĄDARKI ---
async def weryfikuj_w_vies(kraj_kod: str, nip_clean: str, nazwa_pliku: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://ec.europa.eu/taxation_customs/vies/#/vat-validation", timeout=30000)
            await page.wait_for_selector("#select-country", timeout=10000)
            await page.select_option("#select-country", kraj_kod)
            await page.fill("#vat-number", nip_clean)
            await page.click("button[type='submit']")
            await page.wait_for_timeout(4000) # Czas na odpowiedź serwera VIES
            
            # Pobranie PDF z widoku strony
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            text_content = await page.inner_text("body")
            await browser.close()
            return pdf_bytes, text_content, "https://ec.europa.eu/taxation_customs/vies/"
        except Exception as e:
            await browser.close()
            return None, str(e), None

async def zrob_zrzut_url(url: str, nazwa_pliku: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000, wait_until="networkidle")
            # Dodanie paska ze stemplem czasu u góry
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
    if not api_key:
        st.error("Brak skonfigurowanego klucza GEMINI_API_KEY w Secrets!")
        st.stop()

    with st.spinner("1/3 Parsowanie danych wejściowych..."):
        parse_prompt = f"Wyodrębnij dane firmy z tekstu: {wklejony_tekst}"
        parse_resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=parse_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedCompanyData
            )
        )
        dane_firmy = ParsedCompanyData.model_validate_json(parse_resp.text)
        
        st.info(f"**Rozpoznano:** {dane_firmy.nazwa} | **Kraj:** {dane_firmy.kraj} | **NIP/Tax ID:** {dane_firmy.nip}")

    pdf_wynik = None
    zrodlo_url = ""
    surowy_tekst = ""
    nazwa_pliku = format_filename(dane_firmy.nazwa)

    # KROK 1: VIES (dla krajów UE)
    czy_ue = any(k.lower() in dane_firmy.kraj.lower() for k in KRAJE_UE)
    sukces_krok1 = False

    if czy_ue:
        with st.spinner("2/3 Sprawdzanie w rejestrze VIES..."):
            nip_clean = re.sub(r'^[A-Z]{2}', '', dane_firmy.nip.strip())
            kraj_kod = dane_firmy.nip[:2].upper() if len(dane_firmy.nip) > 2 and dane_firmy.nip[:2].isalpha() else "DE"
            pdf_bytes, raw_txt, url_vies = asyncio.run(weryfikuj_w_vies(kraj_kod, nip_clean, nazwa_pliku))
            
            if pdf_bytes and "valid" in raw_txt.lower() or "ważny" in raw_txt.lower() or "valide" in raw_txt.lower():
                pdf_wynik = pdf_bytes
                surowy_tekst = raw_txt
                zrodlo_url = url_vies
                sukces_krok1 = True

    # KROK 2 & 3: Wyszukiwanie rejestrów / strony www przez AI Search
    if not sukces_krok1:
        with st.spinner("2/3 Szukanie w rejestrach krajowych lub na oficjalnej stronie firmy..."):
            search_query = f"Official business registry or company website imprint terms contact for: {dane_firmy.nazwa}, {dane_firmy.kraj}, Tax ID: {dane_firmy.nip}"
            search_resp = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"Find the direct URL for legal imprint, company registry or terms of service page with company details for: {search_query}. Return ONLY the direct URL.",
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}]
                )
            )
            znaleziony_url = search_resp.text.strip().replace("`", "")
            match = re.search(r'https?://[^\s]+', znaleziony_url)
            if match:
                zrodlo_url = match.group(0)
                pdf_bytes, raw_txt = asyncio.run(zrob_zrzut_url(zrodlo_url, nazwa_pliku))
                if pdf_bytes:
                    pdf_wynik = pdf_bytes
                    surowy_tekst = raw_txt

    # KROK 4: Analiza zgodności danych przez AI
    with st.spinner("3/3 Generowanie raportu wiarygodności..."):
        eval_prompt = f"""
        Dane wklejone przez użytkownika:
        - Nazwa: {dane_firmy.nazwa}
        - Adres: {dane_firmy.adres}
        - NIP: {dane_firmy.nip}

        Treść odnaleziona na stronie ({zrodlo_url}):
        {surowy_tekst[:6000]}

        Oceń zgodność:
        - 'ZIELONY' jeśli 100% pełna zgodność (Nazwa, Adres, NIP).
        - 'NIEBIESKI' jeśli pełna zgodność, ale drobne różnice w zapisie (np. Sp. z o.o. vs Spółka z o.o.).
        - 'ZOLTY' jeśli znaleziono tylko część danych (np. brak NIP).
        - 'CZERWONY' jeśli brak zgodności lub nie znaleziono podmiotu.
        Podaj cytat w języku obcym i jego polskie tłumaczenie. Oceń wiarygodność źródła.
        """
        eval_resp = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=eval_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VerificationResult
            )
        )
        wynik = VerificationResult.model_validate_json(eval_resp.text)

    # --- PREZENTACJA WYNIKÓW ---
    st.markdown("---")
    st.subheader("📊 Wynik Weryfikacji")

    kolor_map = {
        "ZIELONY": ("🟢 PEŁNA ZGODNOŚĆ (100%)", "success"),
        "NIEBIESKI": ("🔵 PEŁNA ZGODNOŚĆ (Drobne różnice w zapisie)", "info"),
        "ZOLTY": ("🟡 CZĘŚCIOWA ZGODNOŚĆ (Braki w danych)", "warning"),
        "CZERWONY": ("🔴 BRAK POTWIERDZENIA", "error")
    }
    etykieta, typ_alertu = kolor_map.get(wynik.status, ("⚪ NIEZNANY", "info"))
    getattr(st, typ_alertu)(f"**Status:** {etykieta}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📋 Dane wklejone")
        st.write(f"**Nazwa:** {dane_firmy.nazwa}")
        st.write(f"**Adres:** {dane_firmy.adres}")
        st.write(f"**NIP / Tax ID:** {dane_firmy.nip}")
    with col2:
        st.markdown("### 🔎 Dane odnalezione w źródle")
        st.write(f"**Nazwa:** {wynik.znaleziona_nazwa}")
        st.write(f"**Adres:** {wynik.znaleziony_adres}")
        st.write(f"**NIP / Tax ID:** {wynik.znaleziony_nip}")

    if wynik.komunikat_roznice:
        st.info(f"**Uwagi do zgodności:** {wynik.komunikat_roznice}")

    st.markdown("### 🌐 Informacje o źródle i wiarygodności")
    st.write(f"**Źródło:** [{zrodlo_url}]({zrodlo_url})")
    st.write(f"**Ocena źródła:** {wynik.opis_zrodla}")

    if wynik.cytat_oryginalny:
        with st.expander("Zobacz oryginalny fragment ze strony oraz tłumaczenie"):
            st.write(f"**Oryginał:** {wynik.cytat_oryginalny}")
            st.write(f"**Tłumaczenie PL:** {wynik.cytat_tlumaczenie}")

    if pdf_wynik:
        st.markdown("### 📥 Plik dowodowy")
        st.download_button(
            label=f"⬇️ Pobierz potwierdzenie ({nazwa_pliku})",
            data=pdf_wynik,
            file_name=nazwa_pliku,
            mime="application/pdf"
        )
