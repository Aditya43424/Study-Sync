import streamlit as st
import time
import requests
import json
import fitz  # PyMuPDF
from streamlit_lottie import st_lottie
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# 1. PAGE SETUP
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

# 2. HELPER FUNCTIONS
def load_lottie_url(url: str):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

# --- UPDATED: AI ENGINE NOW ACCEPTS CONFIGURATION INPUTS ---
def extract_syllabus_with_ai(raw_text, hours, intensity, no_weekends):
    client = genai.Client()
    
    # We build the custom user constraints dynamically right into the prompt system
    weekend_rule = "STRICT RULE: Do not allocate any study tasks on Saturdays or Sundays." if no_weekends else "You may utilize weekends for study blocks if necessary."
    
    prompt = f"""
    You are an expert academic coordinator and personal study coach. 
    Analyze the following syllabus text and extract all major assignments, quizzes, projects, and exams.
    
    For each task, identify its name and its explicit due date. If a year is not provided, assume it is 2026.
    
    CRITICAL USER CONSTRAINTS TO CONSIDER FOR PATTERNS:
    1. The student can only study for {hours} hours per day.
    2. The desired study intensity pace is '{intensity}'. 
    3. {weekend_rule}
    
    Syllabus Text:
    {raw_text}
    """
    
    class TaskSchema(types.BaseModel):
        task_name: str
        due_date: str

    class SyllabusOutput(types.BaseModel):
        tasks: list[TaskSchema]

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SyllabusOutput,
        ),
    )
    return json.loads(response.text)

lottie_processing = load_lottie_url("https://assets8.lottiefiles.com/packages/lf20_vnikbe9e.json")

# 3. GRAPHICS & THEME SYSTEM (CSS)
st.html("""
<style>
    .main-title {
        font-size: 3.6rem !important;
        font-weight: 800;
        background: linear-gradient(90deg, #00C6FF, #0072FF);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-top: 10px;
        margin-bottom: 25px;
        letter-spacing: -0.5px;
    }
    
    [data-testid="stMetricSimpleValue"] {
        font-size: 1.8rem !important;
        color: #00C6FF !important;
        font-weight: 700;
    }
    
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #00C6FF, #0072FF) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 12px 24px !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:first-child:hover {
        box-shadow: 0 0 20px rgba(0, 198, 255, 0.6) !important;
        transform: translateY(-2px);
    }
    
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(12px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .clean-success-card {
        display: flex;
        align-items: center;
        background: rgba(0, 198, 255, 0.04);
        border: 1px solid rgba(0, 198, 255, 0.25);
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 32px;
        animation: fadeInUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }
    
    .success-icon {
        background: #00C6FF;
        color: #0E1117;
        font-weight: bold;
        font-size: 1.1rem;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 18px;
        flex-shrink: 0;
        box-shadow: 0 0 12px rgba(0, 198, 255, 0.3);
    }
    
    .success-text-container { display: flex; flex-direction: column; }
    .success-title { color: #FFFFFF !important; font-family: system-ui; font-size: 1.15rem !important; font-weight: 600 !important; margin: 0 0 4px 0 !important; }
    .success-subtitle { color: #A0AEC0 !important; font-family: system-ui; font-size: 0.9rem !important; margin: 0 !important; }
</style>
""")

# 4. INTERFACE LAYOUT HEADER
st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)
st.markdown("---")

# 5. SPLIT PANEL CONTROL INTERFACES
left_panel, right_panel = st.columns([1, 2], gap="large")

with left_panel:
    st.subheader("⚙️ Configuration")
    with st.container(border=True):
        study_hours = st.slider("Daily Study Capacity (Hours)", 1, 8, 3)
        focus_level = st.select_slider("Target Study Intensity", options=["Casual", "Balanced", "Intense"])
        skip_weekends = st.toggle("Exclude Weekends")

with right_panel:
    st.subheader("Drop your PDF here")
    uploaded_file = st.file_uploader("Upload Course Syllabus (PDF format)", type=["pdf"])

    if uploaded_file is not None:
        st.success(f"⚡ Linked with sequence target: **{uploaded_file.name}**")
        
        if st.button("Generate Optimized Timeline", use_container_width=True):
            
            processing_box = st.empty()
            with processing_box.container():
                st.markdown("""
                    <div style="padding: 10px 0px; margin-bottom: 10px;">
                        <p style="color: #A0AEC0; font-size: 0.95rem; font-family: system-ui; letter-spacing: 0.5px;">
                            Reading document structure and deploying AI parsing routines...
                        </p>
                    </div>
                """, unsafe_allow_html=True)
                
                if lottie_processing:
                    st_lottie(lottie_processing, height=140, key="proc_anim")
                
                # A. Extract Text using PyMuPDF
                doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                page_count = doc.page_count
                full_text = ""
                for page in doc:
                    full_text += page.get_text()
                
                # B. Execute the AI Engine with LIVE control values passed through
                ai_data = extract_syllabus_with_ai(full_text, study_hours, focus_level, skip_weekends)
                total_tasks = len(ai_data["tasks"])
                
            processing_box.empty()
            
            st.html("""
                <div class="clean-success-card">
                    <div class="success-icon">✓</div>
                    <div class="success-text-container">
                        <h4 class="success-title">Timeline Optimized Successfully</h4>
                        <p class="success-subtitle">AI engine successfully processed core metrics and mapped task locations.</p>
                    </div>
                </div>
            """)
            
            # Summary Metrics Dashboard
            st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
            m_col1, m_col2, m_col3 = st.columns(3)
            
            with m_col1:
                with st.container(border=True):
                    st.metric(label="Pages Read", value=f"{page_count} Pages")
            with m_col2:
                with st.container(border=True):
                    st.metric(label="AI Detected Tasks", value=f"{total_tasks} Items")
            with m_col3:
                with st.container(border=True):
                    st.metric(label="Calculated Study Blocks", value=f"{total_tasks * study_hours} Slots")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Render Live Data Matrix
            st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>📅 Extracted Deadlines Matrix</p>", unsafe_allow_html=True)
            st.dataframe(ai_data["tasks"], use_container_width=True)