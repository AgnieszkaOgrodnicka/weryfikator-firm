import streamlit as st
import asyncio
import os
import re
import json
import subprocess
import requests
from datetime import datetime
import google.generativeai as genai
from playwright.async_api import async_playwright

# --- AUTOMATYCZNA INSTALACJA PRZEGLĄDARKI W CHMURZE ---
@st.cache_resource
def install_playwright_browsers():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.warning(f"Błąd instalacji Playwright: {e}")

install_playwright_browsers()

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Weryfikator Kontrahentów", page_icon="🔍", layout="wide")

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

def generuj_html_vies(kraj, nip, nazwa, adres, zrodlo):
    return f"""
    <div style="font-family: Arial, sans-serif; padding: 40px; color: #333;">
        <h2 style="color: #1e3a8a;">Potwierdzenie Aktywności VAT (UE)</h2>
        <hr>
        <p><b>Data weryfikacji:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p><b>Źródło:</b> {zrodlo}</p>
        <br>
        <h3 style="color: green;">STATUS: AKTYWNY (VALID)</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
            <tr style="border-bottom: 1px solid #ccc;">
                <td style="padding: 10px 0; width: 30%;"><b>Kraj:</b></td>
                <td style="padding: 10px 0;">{kraj}</td>
            </tr>
            <tr style="border-bottom: 1px solid #ccc;">
                <td style="padding: 10px 0;"><b>Numer VAT:</b></td>
                <td style="padding: 10px 0;">{nip}</td>
            </tr>
            <tr style="border-bottom: 1px solid #ccc;">
                <td style="padding: 10px 0;"><b>Zarejestrowana Nazwa:</b></td>
                <td style="padding: 10px 0;">{nazwa}</td>
            </tr>
            <tr style="border-bottom: 1px solid #ccc;">
                <td style="padding: 10px 0;"><b>Zarejestrowany Adres:</b></td>
                <td style="padding: 10px 0;">{adres}</td>
            </tr>
        </table>
    </div>
    """

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
st.caption("VIES API ➔ Bazy państwowe / komercyjne ➔ Strona zleceniodawcy")

api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
if not api_key:
    st.error("⚠️ Brak klucza GEMINI_API_KEY w Secrets!")
    st.stop()

genai.configure(api_key=api_key)
# Zmiana modelu na wersję z limitem 1500 zapytań dziennie
model = genai.GenerativeModel("gemini-1.0-pro")

wklejony_tekst = st.text_area(
    "Wklej dane kontrahenta (Nazwa, Adres, Kraj, NIP/Tax ID):",
    height=140,
    placeholder="Przykład:\nNYLON FRANCE\n123 RUE DE PARIS\nFrancja\nVAT: FR07883003964"
)

async def generuj_pdf_z_html(html_content: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(html_content)
        pdf_bytes = await page.pdf(format="A4", print_background=True)
        await browser.close()
        return pdf_bytes

async def zrob_zrzut_url(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1080})
        try:
            await page.goto(url, timeout=15000, wait_until="load")
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
            
            wymiary = await page.evaluate("""() => {
                return {
                    width: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, 1280),
                    height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, 1080)
                }
            }""")
            
            pdf_bytes = await page.pdf(
                width=f"{wymiary['width']}px",
                height=f"{wymiary['height'] + 50}px",
                print_background=True
            )
            
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
        with st.spinner("1/3 Rozpoznawanie danych firmy..."):
            parse_prompt = f"""
            Wyodrębnij z poniższego tekstu dane firmy. Zwróć TYLKO czysty obiekt JSON (bez markdown) o strukturze:
            {{"nazwa": "...", "adres": "...", "kraj": "...", "nip": "..."}}
            Tekst: {wklejony_tekst}
            """
            parse_resp = model.generate_content(parse_prompt)
            czysty_json = re.search(r'\{.*\}', parse_resp.text, re.DOTALL)
            dane = json.loads(czysty_json.group(0)) if czysty_json else {"nazwa": wklejony_tekst[:30], "adres": "", "kraj": "", "nip": ""}

            nazwa = dane.get("nazwa", "")
            adres = dane.get("adres", "")
            kraj = dane.get("kraj", "")
            nip = dane.get("nip", "")
            st.info(f"**Rozpoznano:** {nazwa} | **Kraj:** {kraj} | **NIP:** {nip}")

        pdf_wynik = None
        zrodlo_url = ""
        surowy_tekst = ""
        nazwa_pliku = format_filename(nazwa)

        czy_ue = any(k.lower() in kraj.lower() for k in KRAJE_UE)
        sukces_vies = False

        if czy_ue and nip:
            with st.spinner("2/3 Weryfikacja NIP w bazach (UE / VATComply)..."):
                nip_clean = re.sub(r'[^0-9A-Za-z]', '', nip)
                match_prefix = re.search(r'^([A-Za-z]{2})', nip_clean)
                
                if match_prefix:
                    kraj_kod = match_prefix.group(1).upper()
                    nip_clean = nip_clean[2:]
                else:
                    kraj_kod = {"francja": "FR", "niemcy": "DE", "polska": "PL", "wlochy": "IT", "hiszpania": "ES"}.get(kraj.lower(), "FR")

                # Próba 1: API Oficjalne
                try:
                    url_vies = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
                    resp1 = requests.post(url_vies, json={"countryCode": kraj_kod, "vatNumber": nip_clean}, timeout=8)
                    if resp1.status_code == 200 and resp1.json().get("valid"):
                        vies_dane = resp1.json()
                        sukces_vies = True
                        zrodlo_url = "Oficjalna Baza API Komisji Europejskiej (VIES)"
                        nazwa_z_bazy = vies_dane.get('name') or "Brak udostępnionych danych"
                        adres_z_bazy = vies_dane.get('address') or "Brak udostępnionych danych"
                        surowy_tekst = f"Nazwa: {nazwa_z_bazy}. Adres: {adres_z_bazy}."
                        html_vies = generuj_html_vies(kraj_kod, nip_clean, nazwa_z_bazy, adres_z_bazy, zrodlo_url)
                        pdf_wynik = asyncio.run(generuj_pdf_z_html(html_vies))
                except Exception as e:
                    pass

                # Próba 2: VATComply (jeśli pierwsza zawiodła)
                if not sukces_vies:
                    try:
                        url_vat = f"https://api.vatcomply.com/vat?vat_number={kraj_kod}{nip_clean}"
                        resp2 = requests.get(url_vat, timeout=8)
                        if resp2.status_code == 200 and resp2.json().get("valid"):
                            vies_dane = resp2.json()
                            sukces_vies = True
                            zrodlo_url = "Baza VIES (przez darmowe API VATComply)"
                            nazwa_z_bazy = vies_dane.get('name') or "Brak udostępnionych danych"
                            adres_z_bazy = vies_dane.get('address') or "Brak udostępnionych danych"
                            surowy_tekst = f"Nazwa: {nazwa_z_bazy}. Adres: {adres_z_bazy}."
                            html_vies = generuj_html_vies(kraj_kod, nip_clean, nazwa_z_bazy, adres_z_bazy, zrodlo_url)
                            pdf_wynik = asyncio.run(generuj_pdf_z_html(html_vies))
                        else:
                            st.warning(f"⚠️ VIES/VATComply odrzuciło numer {kraj_kod}{nip_clean}. Prawdopodobna przyczyna: numer jest nieważny, usługa UE ma awarię lub jest to błędny format.")
                    except Exception as e:
                        st.warning(f"⚠️ Obie bramki VIES zawiodły. Przechodzę do wyszukiwarki. Szczegóły błędu: {e}")

        if not sukces_vies:
            with st.spinner("Szukanie na oficjalnej stronie firmy..."):
                search_prompt = f"Podaj bezpośredni adres URL strony głównej lub podstrony prawnej (Impressum/Legal/Contact/Terms) dla firmy: {nazwa}, {adres}, {kraj}. Zwróć TYLKO adres URL."
                search_resp = model.generate_content(search_prompt)
                match = re.search(r'https?://[^\s)"]+', search_resp.text)
                if match:
                    zrodlo_url = match.group(0)
                    pdf_bytes, raw_txt = asyncio.run(zrob_zrzut_url(zrodlo_url))
                    if pdf_bytes:
                        pdf_wynik = pdf_bytes
                        surowy_tekst = raw_txt

        with st.spinner("3/3 Przygotowanie raportu..."):
            eval_prompt = f"""
            Porównaj dane:
            Użytkownik: {nazwa}, {adres}, NIP: {nip}
            Źródło ({zrodlo_url}): {surowy_tekst[:5000]}
            Zwróć TYLKO JSON: {{"status": "ZIELONY / NIEBIESKI / ZOLTY / CZERWONY", "znaleziona_nazwa": "...", "znaleziony_adres": "...", "znaleziony_nip": "...", "komunikat_roznice": "...", "opis_zrodla": "..."}}
            """
            eval_resp = model.generate_content(eval_prompt)
            wynik_json = re.search(r'\{.*\}', eval_resp.text, re.DOTALL)
            raport = json.loads(wynik_json.group(0)) if wynik_json else {"status": "CZERWONY", "opis_zrodla": zrodlo_url, "komunikat_roznice": "Błąd interpretacji wyników."}

        st.markdown("---")
        st.subheader("📊 Wynik Weryfikacji")

        status_str = raport.get("status", "CZERWONY")
        kolor_map = {"ZIELONY": ("🟢 PEŁNA ZGODNOŚĆ (100%)", "success"), "NIEBIESKI": ("🔵 PEŁNA ZGODNOŚĆ (Drobne różnice w zapisie)", "info"), "ZOLTY": ("🟡 CZĘŚCIOWA ZGODNOŚĆ (Braki w danych)", "warning"), "CZERWONY": ("🔴 BRAK POTWIERDZENIA", "error")}
        etykieta, typ_alertu = kolor_map.get(status_str, ("🔴 BRAK POTWIERDZENIA", "error"))
        getattr(st, typ_alertu)(f"**Status:** {etykieta}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📋 Dane wklejone")
            st.write(f"**Nazwa:** {nazwa}\n**Adres:** {adres}\n**NIP / Tax ID:** {nip}")
        with col2:
            st.markdown("### 🔎 Dane odnalezione")
            st.write(f"**Nazwa:** {raport.get('znaleziona_nazwa', '-')}\n**Adres:** {raport.get('znaleziony_adres', '-')}\n**NIP / Tax ID:** {raport.get('znaleziony_nip', '-')}")

        if raport.get("komunikat_roznice"):
            st.info(f"**Uwagi:** {raport.get('komunikat_roznice')}")

        st.markdown("### 🌐 Informacje o źródle")
        if zrodlo_url:
            st.write(f"**Źródło:** [{zrodlo_url}]({zrodlo_url})")
        st.write(f"**Ocena wiarygodności:** {raport.get('opis_zrodla', '-')}")

        if pdf_wynik:
            st.markdown("### 📥 Plik dowodowy")
            st.download_button(label=f"⬇️ Pobierz potwierdzenie PDF ({nazwa_pliku})", data=pdf_wynik, file_name=nazwa_pliku, mime="application/pdf")

    except Exception as err:
        st.error(f"Wystąpił błąd: {str(err)}")
