import streamlit as st
import pandas as pd
from PIL import Image
import json
import gspread
import time
from google.oauth2.service_account import Credentials
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

# ==========================================
# Pydantic Schemas for Structured Output
# ==========================================
class AttendanceRecord(BaseModel):
    name: str
    cp_no: str

class AttendanceLog(BaseModel):
    date: str
    records: list[AttendanceRecord]

# ==========================================
# 1. API & CREDENTIALS INITIALIZATION
# ==========================================

if "GEMINI_API_KEY" in st.secrets:
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("❌ Missing API Key: Please set your GEMINI_API_KEY in the Streamlit Secrets panel.")
    st.stop()

def connect_to_sheets():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        secret_credentials = dict(st.secrets["gspread"]["service_account"])
        creds = Credentials.from_service_account_info(secret_credentials, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"❌ Failed to authenticate with Google Sheets API: {e}")
        return None

# ==========================================
# 2. STREAMLIT WEB UI SETUP
# ==========================================

st.set_page_config(page_title="Caravan Attendance Automation", layout="wide")

st.title("📋 Caravan Attendance Automation")
st.write("---")

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
        
        prompt = """
        You are an expert handwriting transcription assistant. Look at the uploaded image and carefully extract all items.
        1. Find the log sheet date written at the top.
        2. Transcribe every single person's Name and their CP no. (Contact/Phone Number). 
        """
        
        # Explicitly targeted Gemini 3 model paths
        models_to_try = [
            "gemini-3.0-flash-preview-0514",
            "gemini-3.0-flash-lite-preview-0514"
        ]
        
        response = None
        success = False
        selected_model = ""
        
        # We will collect the real error tracking trace here
        error_logs = []
        
        for current_model in models_to_try:
            status_text.info(f"🔄 Attempting extraction using model: `{current_model}`...")
            
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=[image, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AttendanceLog,
                    ),
                )
                success = True
                selected_model = current_model
                break 
            except APIError as e:
                error_logs.append(f"APIError on `{current_model}`: {str(e)}")
            except Exception as e:
                error_logs.append(f"Unexpected Exception on `{current_model}`: {str(e)}")

        if not success or not response:
            st.error("❌ Execution Stopped: Code encountered deep execution errors.")
            st.subheader("🚨 Real Underlying Error Trace Logs:")
            for log in error_logs:
                st.code(log)
            st.stop()
            
        if response:
            try:
                json_data = json.loads(response.text)
                status_text.success(f"✨ Image Successfully Processed via `{selected_model}`!")
                
                st.metric(label="Detected Log Date", value=json_data.get("date", "Not Found"))
                
                raw_records = json_data.get("records", [])
                cleaned_records = []
                for record in raw_records:
                    cleaned_records.append({
                        "Name": str(record.get("name", "")).strip(),
                        "CP no.": str(record.get("cp_no", "")).strip()
                    })

                df = pd.DataFrame(cleaned_records, dtype=str)
                st.dataframe(df, use_container_width=True)
                
                if st.button("📤 Push Data to Caravan Attendance Google Sheet"):
                    with st.spinner("Syncing..."):
                        gc = connect_to_sheets()
                        if gc:
                            spreadsheet_id = "1bbJJY1XpuT-TZDoIQLiYQMMdmut85ewLneeD3CbbAIc"
                            try:
                                sheet = gc.open_by_key(spreadsheet_id).get_worksheet(0)
                                rows_to_append = df[["Name", "CP no."]].values.tolist()
                                sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
                                st.balloons()
                                st.success("🎉 Data successfully synced!")
                            except Exception as e:
                                st.error(f"❌ Sync failed: {e}")
                                
            except json.JSONDecodeError:
                status_text.error("❌ Processing failed: The returned AI output wasn't cleanly structured.")
