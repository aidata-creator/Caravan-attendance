import streamlit as st
import pandas as pd
from PIL import Image
import json
import gspread
from google.oauth2.service_account import Credentials
from google import genai

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
        # Parse the JSON string stored in secrets
        secret_credentials = json.loads(st.secrets["gspread"]["service_account"])
        creds = Credentials.from_service_account_info(secret_credentials, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"❌ Failed to authenticate with Google Sheets API: {e}")
        st.info("Check if your 'service_account' string in Streamlit Secrets is complete and valid JSON.")
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
    # Open and display the file
    image = Image.open(uploaded_file)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📸 Uploaded Image")
        st.image(image, use_container_width=True)
        
    with col2:
        st.subheader("⚡ Automation Status")
        status_text = st.empty()
        status_text.info("Reading handwriting using Gemini... Please wait.")
        
        # Crafting the exact schema matching your Google Sheet structure
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
        
        try:
            # Send image to the Gemini Flash vision pipeline
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[image, prompt]
            )
            
            # Form clean JSON input from the raw response
            cleaned_response = response.text.strip().replace("
