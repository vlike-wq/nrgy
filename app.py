import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from ddgs import DDGS
import json
import io
import os

# ==========================================
# Configuration & API Keys
# ==========================================
# Safely pull the key from Streamlit's secrets manager
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)

EXCLUSIONS_FILE = "exclusions.json"
DEFAULT_EXCLUSIONS = [
    "facebook.com", "twitter.com", "linkedin.com", 
    "instagram.com", "reddit.com", "wikipedia.org", "youtube.com", "gem.wiki", "grokipedia.com", "rome2rio.com", "test.com"
]

# ==========================================
# Session State Initialization (The "Memory" Vault)
# ==========================================
if "research_results" not in st.session_state:
    st.session_state.research_results = None
if "excel_file" not in st.session_state:
    st.session_state.excel_file = None
if "report" not in st.session_state:
    st.session_state.report = None
if "current_query" not in st.session_state:
    st.session_state.current_query = ""
# NEW: A memory vault just for the status logs!
if "research_logs" not in st.session_state:
    st.session_state.research_logs = []

# ==========================================
# JSON File Management Functions
# ==========================================
def load_exclusions():
    if not os.path.exists(EXCLUSIONS_FILE):
        with open(EXCLUSIONS_FILE, 'w') as f:
            json.dump(DEFAULT_EXCLUSIONS, f, indent=4)
    with open(EXCLUSIONS_FILE, 'r') as f:
        return json.load(f)

def save_exclusions(exclusions_list):
    with open(EXCLUSIONS_FILE, 'w') as f:
        json.dump(exclusions_list, f, indent=4)

# ==========================================
# Core Functions
# ==========================================
def search_duckduckgo(query, exclusions_list, target_num_results=3):
    try:
        with DDGS(timeout=20) as ddgs:
            raw_results = list(ddgs.text(query, max_results=15))
            clean_links = []
            for item in raw_results:
                url = item.get('href', '')
                is_excluded = any(domain.lower() in url.lower() for domain in exclusions_list)
                if not is_excluded:
                    clean_links.append(url)
                if len(clean_links) == target_num_results:
                    break
            return clean_links
    except Exception as e:
        st.error(f"DuckDuckGo Search failed: {e}")
        return []

def scrape_website_text(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=10) 
        response.raise_for_status() 
        soup = BeautifulSoup(response.text, 'html.parser')
        paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3'])
        text = " ".join([p.get_text(strip=True) for p in paragraphs])
        return text[:15000] 
    except Exception:
        return None

def extract_energy_data_with_llm(text, url):
    prompt = f"""
    Read the following text extracted from a website and extract the specified information about the energy project/company.
    If a piece of information is not mentioned, write "Not Mentioned".
    
    Website URL: {url}
    Text: {text}
    
    Return the result strictly as JSON with these keys:
    "URL", "Energy Type", "Owner", "Establishment Date", "Inauguration Date", "Capacity", "Current Production"
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text)
        data['URL'] = url 
        return data
    except Exception:
        return {"URL": url, "Energy Type": "Error/Failed", "Owner": "Error", "Establishment Date": "Error", "Inauguration Date": "Error", "Capacity": "Error", "Current Production": "Error"}

def generate_ai_report(data_list, query):
    clean_data = [d for d in data_list if d.get("Energy Type") not in ["Error", "Error/Failed"]]
    if not clean_data:
        return "Could not generate report: No valid data was successfully extracted."
        
    prompt = f"""
    You are an expert energy sector analyst. I have researched '{query}' and extracted the following data from various sources:
    {json.dumps(clean_data, indent=2)}
    
    Write a brief, professional executive summary report (2-3 paragraphs) synthesizing this information. 
    Highlight key facts like capacity, ownership, and energy type. Do not invent information; rely only on the provided JSON data.
    """
    try:
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        return response.text
    except Exception as e:
        return f"Failed to generate report: {e}"

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Energy Data')
    return output.getvalue()

# ==========================================
# Streamlit Web UI & Navigation
# ==========================================
st.set_page_config(page_title="Energy Project Researcher", layout="wide", page_icon="⚡")

st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to:", ["🔍 Research Dashboard", "⚙️ Manage Site Filters"])

if page == "⚙️ Manage Site Filters":
    st.title("⚙️ Manage Site Filters")
    st.write("These domains will be automatically ignored during searches.")
    
    current_exclusions = load_exclusions()
    exclusions_text = "\n".join(current_exclusions)
    new_exclusions_input = st.text_area("Blacklisted Domains (one per line):", value=exclusions_text, height=300)
    
    if st.button("💾 Save Changes", type="primary"):
        updated_list = [domain.strip() for domain in new_exclusions_input.split('\n') if domain.strip()]
        save_exclusions(updated_list)
        st.success("Filters successfully saved to exclusions.json!")

elif page == "🔍 Research Dashboard":
    st.title("⚡ Automated Energy Project Researcher")

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_input("Enter Search Keywords:", value=st.session_state.current_query)
    with col2:
        num_results = st.number_input("Clean websites to check", min_value=1, max_value=10, value=3)

    btn_col1, btn_col2 = st.columns([1, 8])
    with btn_col1:
        start_btn = st.button("Start Research", type="primary")
    with btn_col2:
        if st.button("🔄 Clear & Refresh"):
            st.session_state.research_results = None
            st.session_state.excel_file = None
            st.session_state.report = None
            st.session_state.current_query = ""
            st.session_state.research_logs = [] # Clear logs on refresh
            st.rerun()

    st.markdown("---")

    # --- THE RESEARCH EXECUTION BLOCK ---
    if start_btn:
        if not query:
            st.warning("Please enter a keyword first.")
        elif GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
            st.error("Please insert your actual Gemini API key.")
        else:
            st.session_state.current_query = query 
            st.session_state.research_logs = [] # Reset logs for new run
            custom_exclusions = load_exclusions() 
            
            with st.status("Initializing research workflow...", expanded=True) as status:
                
                # Helper function to write to screen AND save to memory
                def log_step(msg):
                    st.write(msg)
                    st.session_state.research_logs.append(msg)

                log_step(f"🔍 Fetching results for: '{query}'...")
                urls = search_duckduckgo(query, custom_exclusions, num_results)
                
                if not urls:
                    status.update(label="No clean results found.", state="error")
                else:
                    log_step(f"🛡️ Applied filters. Found {len(urls)} clean targets.")
                    extracted_data_list = []
                    
                    for i, url in enumerate(urls):
                        log_step(f"📄 [{i+1}/{len(urls)}] Reading: {url}")
                        page_text = scrape_website_text(url)
                        if page_text:
                            data = extract_energy_data_with_llm(page_text, url)
                            extracted_data_list.append(data)
                        else:
                            log_step(f"❌ Failed to read {url}. Website might have bot protection.")
                    
                    st.session_state.research_results = extracted_data_list
                    
                    if extracted_data_list:
                        df = pd.DataFrame(extracted_data_list)
                        st.session_state.excel_file = to_excel(df)
                    
                    status.update(label="Research Complete!", state="complete")
                    st.rerun() 

    # --- THE RESULTS DISPLAY BLOCK ---
    if st.session_state.research_results:
        
        # 1. Display the Permanent Logs first
        with st.expander("🕵️‍♂️ View Research Logs (Manual Verification)"):
            for log_message in st.session_state.research_logs:
                st.markdown(log_message)
                
        st.subheader("📊 Research Results")
        
        # 2. Display Data Table
        df = pd.DataFrame(st.session_state.research_results)
        
        # Removed display_text so the actual URL is shown
        st.dataframe(
            df, 
            column_config={
                "URL": st.column_config.LinkColumn("Source Link") 
            },
            hide_index=True, 
            use_container_width=True
        )
        
        # 3. Action Buttons
        action_col1, action_col2 = st.columns([2, 8])
        
        with action_col1:
            st.download_button(
                label="📥 Download Excel",
                data=st.session_state.excel_file,
                file_name=f"{st.session_state.current_query.replace(' ', '_')}_data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        with action_col2:
            if st.button("✨ Generate AI Research Report"):
                with st.spinner("Writing report..."):
                    report_text = generate_ai_report(st.session_state.research_results, st.session_state.current_query)
                    st.session_state.report = report_text 
        
        # 4. Display Report
        if st.session_state.report:
            st.markdown("### 📝 AI Executive Summary")
            st.info(st.session_state.report)
