import streamlit as st
import time
import requests
import json
import fitz  # PyMuPDF
import pandas as pd
import uuid  
from datetime import datetime, timedelta, time as dt_time # Added dt_time for default picker parameters
from streamlit_lottie import st_lottie
import streamlit.components.v1 as components
from pydantic import BaseModel
from google import genai
from google.genai import types

# 1. PAGE SETUP
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

# Initialize persistent memory state blocks
if "ai_data" not in st.session_state:
    st.session_state["ai_data"] = None
if "page_count" not in st.session_state:
    st.session_state["page_count"] = 0

# 2. HELPER FUNCTIONS
def load_lottie_url(url: str):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

def generate_ics_file(study_dataframe):
    nl = "\r\n"
    current_timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ics_text = f"BEGIN:VCALENDAR{nl}VERSION:2.0{nl}PRODID:-//Study Sync//Study Planner//EN{nl}CALSCALE:GREGORIAN{nl}"
    
    for _, row in study_dataframe.iterrows():
        date_str = str(row['Scheduled Date']).strip()
        try:
            start_dt = datetime.strptime(date_str, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=1)
            
            clean_start = start_dt.strftime("%Y%m%d")
            clean_end = end_dt.strftime("%Y%m%d")
            unique_event_id = str(uuid.uuid4())
            
            ics_text += f"BEGIN:VEVENT{nl}"
            ics_text += f"UID:{unique_event_id}{nl}"
            ics_text += f"DTSTAMP:{current_timestamp}{nl}"
            ics_text += f"SUMMARY:📚 Focus [{row['Time Slot']}]: {row['Focus Topic']}{nl}"
            ics_text += f"DESCRIPTION:Action: {row['Suggested Action']} | Allocated: {row['Hours Allocated']} hours.{nl}"
            ics_text += f"DTSTART;VALUE=DATE:{clean_start}{nl}"
            ics_text += f"DTEND;VALUE=DATE:{clean_end}{nl}"  
            ics_text += f"END:VEVENT{nl}"
        except Exception:
            clean_date = date_str.replace("-", "").strip()
            if len(clean_date) == 8 and clean_date.isdigit():
                unique_event_id = str(uuid.uuid4())
                ics_text += f"BEGIN:VEVENT{nl}"
                ics_text += f"UID:{unique_event_id}{nl}"
                ics_text += f"DTSTAMP:{current_timestamp}{nl}"
                ics_text += f"SUMMARY:📚 Focus: {row['Focus Topic']}{nl}"
                ics_text += f"DESCRIPTION:Action: {row['Suggested Action']}{nl}"
                ics_text += f"DTSTART;VALUE=DATE:{clean_date}{nl}"
                ics_text += f"DTEND;VALUE=DATE:{clean_date}{nl}"
                ics_text += f"END:VEVENT{nl}"
                
    ics_text += f"END:VCALENDAR"
    return ics_text

# --- AI ENGINE SYSTEM UPDATED TO ACCEPT USER AVAILABILITY WINDOWS ---
def extract_syllabus_with_ai(raw_text, hours, intensity, no_weekends, start_hr, end_hr):
    client = genai.Client()
    weekend_rule = "STRICT RULE: Do not schedule any study blocks on Saturdays or Sundays." if no_weekends else "You can utilize weekends for study blocks."
    
    prompt = f"""
    You are an elite academic strategy coach. Analyze the given syllabus text.
    
    STEP 1: Extract all major tasks (assignments, exams, quizzes, projects) with their due dates.
    STEP 2: Build a comprehensive, chronological daily/weekly study roadmap leading up to those dates.
    
    CRITICAL DESIGN RULES:
    - USER AVAILABILITY WINDOW: The student is ONLY free to study between {start_hr} and {end_hr}. 
    - Every generated 'time_slot' value MUST fall strictly within this window (e.g., if the window is 04:00 PM - 08:00 PM, a slot could be '04:30 PM - 06:30 PM').
    - Assume the current date is June 2026. Realistically space out individual study plan checkpoints across distinct days.
    - The student can only dedicate {hours} hours per day to studying.
    - Match the preparation pace to a '{intensity}' intensity level.
    - {weekend_rule}
    - All 'due_date' and 'scheduled_date' fields MUST use 'YYYY-MM-DD' format only.
    
    Syllabus Text:
    {raw_text}
    """
    
    class TaskSchema(BaseModel):
        task_name: str
        due_date: str

    class ScheduleSchema(BaseModel):
        scheduled_date: str
        time_slot: str  
        focus_topic: str
        suggested_action: str
        hours_allocated: int

    class SyllabusOutput(BaseModel):
        tasks: list[TaskSchema]
        study_plan: list[ScheduleSchema]

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
    }
    
    div.stDownloadButton > button:first-child {
        background: #1E293B !important;
        color: #00C6FF !important;
        border: 1px solid rgba(0, 198, 255, 0.4) !important;
        border-radius: 8px !important;
        width: 100% !important;
    }
    
    .progress-status-text {
        font-family: system-ui, sans-serif;
        font-size: 0.95rem;
        color: #00C6FF;
        font-weight: 500;
        margin-bottom: 4px;
    }
    
    .clean-success-card {
        display: flex;
        align-items: center;
        background: rgba(0, 198, 255, 0.04);
        border: 1px solid rgba(0, 198, 255, 0.25);
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 32px;
    }
    
    .success-icon {
        background: #00C6FF;
        color: #0E1117;
        font-weight: bold;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 18px;
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
        
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🕒 Availability Window")
    with st.container(border=True):
        # Interactive time picker elements allowing users to select free-time brackets
        free_from = st.time_input("I am free from:", dt_time(16, 0))  # Default: 4:00 PM
        free_until = st.time_input("I am free until:", dt_time(21, 0))  # Default: 9:00 PM
        
        # Format times cleanly into reader strings (e.g. "04:00 PM")
        string_from = free_from.strftime("%I:%M %p")
        string_until = free_until.strftime("%I:%M %p")

with right_panel:
    st.subheader("Drop your PDF here")
    uploaded_file = st.file_uploader("Upload Course Syllabus (PDF format)", type=["pdf"])

    if uploaded_file is not None:
        st.success(f"⚡ Linked with sequence target: **{uploaded_file.name}**")
        
        if st.button("Generate Optimized Timeline", use_container_width=True):
            progress_bar = st.progress(0)
            status_message = st.empty()
            
            # Phase 1: File Reading
            status_message.markdown('<p class="progress-status-text">🔄 [25%] Phase 1: Mapping lines and extracting PDF file bytes...</p>', unsafe_allow_html=True)
            progress_bar.progress(25)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            st.session_state["page_count"] = doc.page_count
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            time.sleep(0.4)
            
            # Phase 2: AI Core Handshake
            status_message.markdown('<p class="progress-status-text">🧠 [50%] Phase 2: Transmitting custom constraints to Gemini strategy networks...</p>', unsafe_allow_html=True)
            progress_bar.progress(50)
            
            # Pass our two new time-boundary strings into the algorithm executor
            raw_ai_output = extract_syllabus_with_ai(full_text, study_hours, focus_level, skip_weekends, string_from, string_until)
            
            # Phase 3: Matrix Restructuring
            status_message.markdown('<p class="progress-status-text">📊 [75%] Phase 3: Splitting dates and formatting custom clock slots...</p>', unsafe_allow_html=True)
            progress_bar.progress(75)
            st.session_state["ai_data"] = {
                "tasks": raw_ai_output["tasks"],
                "study_plan": [
                    {
                        "Status": False,
                        "Scheduled Date": item["scheduled_date"],
                        "Time Slot": item["time_slot"],  
                        "Focus Topic": item["focus_topic"],
                        "Suggested Action": item["suggested_action"],
                        "Hours Allocated": item["hours_allocated"]
                    } for item in raw_ai_output["study_plan"]
                ]
            }
            time.sleep(0.4)
            
            # Phase 4: Finalizing Layout
            status_message.markdown('<p class="progress-status-text">✨ [100%] Phase 4: Synchronizing interactive checklist frameworks...</p>', unsafe_allow_html=True)
            progress_bar.progress(100)
            time.sleep(0.3)
            
            progress_bar.empty()
            status_message.empty()

    # --- RENDERING ENGINE STAGE ---
    if st.session_state["ai_data"] is not None:
        st.html("""
            <div class="clean-success-card">
                <div class="success-icon">✓</div>
                <div class="success-text-container">
                    <h4 class="success-title">Timeline & Schedule Optimized Successfully</h4>
                    <p class="success-subtitle">Interactive roadmap loaded into dashboard memory. Schedule built using custom availability parameters.</p>
                </div>
            </div>
        """)
        
        total_tasks = len(st.session_state["ai_data"]["tasks"])
        
        st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            with st.container(border=True):
                st.metric(label="Pages Read", value=f"{st.session_state['page_count']} Pages")
        with m_col2:
            with st.container(border=True):
                st.metric(label="AI Detected Tasks", value=f"{total_tasks} Items")
        with m_col3:
            with st.container(border=True):
                st.metric(label="Daily Cap Target", value=f"{study_hours} Hours/Day")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        t_col1, t_col2 = st.columns([1, 2], gap="medium")
        
        with t_col1:
            st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>📅 Extracted Deadlines</p>", unsafe_allow_html=True)
            st.dataframe(st.session_state["ai_data"]["tasks"], use_container_width=True)
            
        with t_col2:
            st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 5px;'>🔄 Interactive Study Roadmap</p>", unsafe_allow_html=True)
            
            roadmap_df = pd.DataFrame(st.session_state["ai_data"]["study_plan"])
            
            total_items = len(roadmap_df)
            completed_items = roadmap_df["Status"].sum() if total_items > 0 else 0
            completion_percentage = int((completed_items / total_items) * 100) if total_items > 0 else 0
            
            st.markdown(f"<p style='font-size:0.85rem; color:#A0AEC0; margin-bottom:2px;'>Progress: {completed_items}/{total_items} Milestones Completed ({completion_percentage}%)</p>", unsafe_allow_html=True)
            st.progress(completed_items / total_items if total_items > 0 else 0.0)
            
            edited_roadmap = st.data_editor(
                roadmap_df,
                use_container_width=True,
                disabled=["Scheduled Date", "Time Slot", "Focus Topic", "Suggested Action", "Hours Allocated"],
                hide_index=True,
                key="roadmap_editor"
            )
            
            if not edited_roadmap.equals(roadmap_df):
                st.session_state["ai_data"]["study_plan"] = edited_roadmap.to_dict(orient="records")
                st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            d_col1, d_col2 = st.columns(2)
            
            with d_col1:
                calendar_data = generate_ics_file(edited_roadmap)
                st.download_button(
                    label="📅 Export to Calendar (.ics)",
                    data=calendar_data,
                    file_name="studysync_schedule.ics",
                    mime="text/calendar",
                    use_container_width=True
                )
            with d_col2:
                csv_data = edited_roadmap.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📊 Download Spreadsheet (.csv)",
                    data=csv_data,
                    file_name="studysync_checklist.csv",
                    mime="text/csv",
                    use_container_width=True
                )