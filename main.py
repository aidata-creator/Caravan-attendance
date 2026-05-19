import streamlit as st
import pandas as pd
from PIL import Image
import json
import gspread
import time
from google.oauth2.service_account import Credentials
from google import genai
from google.genai.errors import APIError

# ==========================================
# 1. API & CREDENTIALS INITIALIZATION
# ==========================================

# Initialize the Gemini Client using Streamlit Secrets
if "GEMINI_API_KEY" in st.secrets:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("❌ Missing API Key: Please set your GEMINI_API_KEY in the Streamlit Secrets panel.")
    st.stop()

# Connect to Google Sheets via Service Account
def connect_to_sheets():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        # Pulls the dictionary directly from the streamlined TOML configuration
        secret_credentials = dict(st.secrets["gspread"]["service_account"])
        creds = Credentials.from_service_account_info(secret_credentials, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"❌ Failed to authenticate with Google Sheets API: {e}")
        st.info("Check if your secrets configuration under [gspread.service_account] has any missing fields.")
        return None

# ==========================================
# 2. STREAMLIT WEB UI SETUP
# ==========================================

st.set_page_config(page_title="Caravan Attendance Automation", layout="wide")

st.title("📋 Caravan Attendance Automation")
st.write("Upload an image of your handwritten sheet to instantly read and sync data with your Google Sheet.")
st.write("---")

# File uploader widget
uploaded_file = st.file_uploader("Upload Log Sheet Image (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📸 Uploaded Image")
        st.image(image, use_container_width=True)
        
    with col2:
        st.subheader("⚡ Automation Status")
        status_text = st.empty()
        status_text.info("Reading handwriting using Gemini... Please wait.")
        
        prompt = """
        You are a highly accurate handwritten document transcription engine.
        Look closely at this log sheet image and extract all entries.
        
        Extract the information and structure it strictly into this JSON format:
        {
          "date": "Extracted date at the top of the sheet",
          "records": [
             {"name": "TRANSCRIPTION OF NAME", "cp_no": "TRANSCRIPTION OF PHONE NUMBER"}
          ]
        }
        
        Rules:
        - Ensure names are in UPPERCASE if they appear written that way.
        - Clean up phone number formats so they match a standard structure.
        - Do not output markdown tags like ```json. Return the raw string directly.
        """
        
        # Implement a retry system for temporary 503 network hiccups
        response = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[image, prompt]
                )
                break 
            except APIError as e:
                if "503" in str(e) and attempt < max_retries - 1:
                    status_text.warning(f"⚠️ Server is busy (Attempt {attempt + 1}/{max_retries}). Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    st.error(f"❌ Google API Error: {e}")
                    st.stop()
            except Exception as e:
                st.error(f"❌ An unexpected error occurred: {e}")
                st.stop()
        
        if response:
            try:
                # Form clean JSON input from the raw response
                cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
                json_data = json.loads(cleaned_response)
                
                status_text.success("✨ Image Successfully Processed!")
                
                # Display Extracted Info Header
                st.metric(label="Detected Log Date", value=json_data.get("date", "Not Found"))
                
                # ==========================================
                # SAFE DATAFRAME PARSING ROUTINE
                # ==========================================
                raw_records = json_data.get("records", [])
                cleaned_records = []
                
                for record in raw_records:
                    name_val = record.get("name", "")
                    cp_val = record.get("cp_no", "")
                    
                    if isinstance(cp_val, list):
                        cp_val = ", ".join(str(x) for x in cp_val)
                    else:
                        cp_val = str(cp_val) if cp_val is not None else ""
                        
                    cleaned_records.append({
                        "Name": str(name_val).strip(),
                        "CP no.": cp_val.strip()
                    })

                df = pd.DataFrame(cleaned_records, dtype=str)
                
                # Data Preview Grid
                st.subheader("🔍 Parsed Data Preview")
                st.dataframe(df, use_container_width=True)
                
                # ==========================================
                # 3. GOOGLE SHEETS SYNC BUTTON
                # ==========================================
                if st.button("📤 Push Data to Caravan Attendance Google Sheet"):
                    with st.spinner("Syncing records into Google Sheets..."):
                        gc = connect_to_sheets()
                        if gc:
                            spreadsheet_id = "1bbJJY1XpuT-TZDoIQLiYQMMdmut85ewLneeD3CbbAIc"
                            
                            try:
                                sheet = gc.open_by_key(spreadsheet_id).get_worksheet(0)
                                rows_to_append = df[["Name", "CP no."]].values.tolist()
                                
                                sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
                                st.balloons()
                                st.success("🎉 Data successfully synced into your 'Caravan Attendance' spreadsheet!")
                                
                            except gspread.exceptions.SpreadsheetNotFound:
                                st.error("❌ Spreadsheet Not Found! Ensure your Google Cloud Service Account Email has been added as an 'Editor' on your Google Sheet sharing configurations.")
                            except Exception as e:
                                st.error(f"❌ Sync failed: {e}")
                                
            except json.JSONDecodeError:
                status_text.error("❌ Processing failed: The returned AI output wasn't cleanly structured. Please try uploading again.")
