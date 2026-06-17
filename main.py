import streamlit as st
import pandas as pd
from PIL import Image
import io
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
st.write("Upload an image, double-click cells to fix any handwriting misreads, and sync live to Google Sheets.")
st.write("---")

uploaded_file = st.file_uploader("Upload Log Sheet Image (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    raw_image = Image.open(uploaded_file)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📸 Uploaded Image")
        st.image(raw_image, use_container_width=True)
        
    with col2:
        st.subheader("⚡ Automation Status")
        status_text = st.empty()
        status_text.info("Optimizing image and connecting to Gemini 2.5 Flash...")
        
        try:
            img_buffer = io.BytesIO()
            if raw_image.mode in ("RGBA", "P"):
                processing_img = raw_image.convert("RGB")
            else:
                processing_img = raw_image
                
            processing_img.save(img_buffer, format="JPEG", quality=75, optimize=True)
            optimized_image = Image.open(img_buffer)
        except Exception as e:
            st.warning(f"⚠️ Image compression skipped: {e}")
            optimized_image = raw_image

        prompt = """
        You are an expert handwriting transcription assistant. Look at the uploaded image and carefully extract all items.
        1. Find the log sheet date written at the top.
        2. Transcribe every single person's Name and their CP no. (Contact/Phone Number). 
        
        Ensure names are capitalized exactly as written and phone numbers are cleaned into a standard numerical string format.
        """
        
        # Initialize session state tracking variables so edits persist across button clicks
        if "parsed_df" not in st.session_state:
            st.session_state.parsed_df = None
        if "detected_date" not in st.session_state:
            st.session_state.detected_date = "Not Found"
        if "last_uploaded_file" not in st.session_state or st.session_state.last_uploaded_file != uploaded_file.name:
            st.session_state.parsed_df = None
            st.session_state.last_uploaded_file = uploaded_file.name

        # Only trigger the API call if we haven't read this specific image yet
        if st.session_state.parsed_df is None:
            response = None
            max_retries = 3
            wait_time = 15 
            
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model='gemini-3-flash-preview',
                        contents=[optimized_image, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=AttendanceLog,
                        ),
                    )
                    break 
                except APIError as e:
                    if ("429" in str(e) or "503" in str(e)) and attempt < max_retries - 1:
                        status_text.warning(f"⚠️ Request cooling window active. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        wait_time *= 2
                    else:
                        st.error(f"❌ Google API Error: {e}")
                        st.stop()
                except Exception as e:
                    st.error(f"❌ An unexpected error occurred: {e}")
                    st.stop()
            
            if response:
                try:
                    json_data = json.loads(response.text)
                    st.session_state.detected_date = json_data.get("date", "Not Found")
                    
                    raw_records = json_data.get("records", [])
                    cleaned_records = []
                    
                    for record in raw_records:
                        cleaned_records.append({
                            "Name": str(record.get("name", "")).strip(),
                            "CP no.": str(record.get("cp_no", "")).strip()
                        })

                    st.session_state.parsed_df = pd.DataFrame(cleaned_records, dtype=str)
                    status_text.success("✨ Image Successfully Processed!")
                except json.JSONDecodeError:
                    status_text.error("❌ Processing failed: The returned AI output wasn't cleanly structured.")
                    st.stop()

        # Display results and enable inline data modifications
        if st.session_state.parsed_df is not None:
            st.metric(label="Detected Log Date", value=st.session_state.detected_date)
            
            st.subheader("📝 Live Data Review (Double-click any cell to edit)")
            
            # 🛠️ LIVE DATA EDITOR WIDGET
            # num_rows="dynamic" lets you manually add or delete rows right from the UI
            edited_df = st.data_editor(
                st.session_state.parsed_df, 
                use_container_width=True, 
                num_rows="dynamic"
            )
            
            # ==========================================
            # 3. GOOGLE SHEETS SYNC BUTTON
            # ==========================================
            if st.button("📤 Push Final Edited Data to Google Sheet"):
                with st.spinner("Syncing data into Google Sheets..."):
                    gc = connect_to_sheets()
                    if gc:
                        spreadsheet_id = "1bbJJY1XpuT-TZDoIQLiYQMMdmut85ewLneeD3CbbAlc"
                        
                        try:
                            sheet = gc.open_by_key(spreadsheet_id).get_worksheet(0)
                            # Pull rows from edited_df instead of original parsed trace data
                            rows_to_append = edited_df[["Name", "CP no."]].values.tolist()
                            
                            sheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
                            st.balloons()
                            st.success("🎉 Final edited data successfully synced into your spreadsheet!")
                            
                        except gspread.exceptions.SpreadsheetNotFound:
                            st.error("❌ Spreadsheet Not Found! Verify email editing permissions.")
                        except Exception as e:
                            st.error(f"❌ Sync failed: {e}")
