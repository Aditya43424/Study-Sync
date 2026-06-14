import streamlit as st
import time
import requests
import json
import fitz  # PyMuPDF
import pandas as pd
import uuid  
from datetime import datetime, timedelta, time as dt_time 
from streamlit_lottie import st_lottie
import streamlit.components.v1 as components
from pydantic import BaseModel
from groq import Groq  

# 1. PAGE SETUP
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

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

# --- ENGINE ADVANCEMENT: SMART FILTERED AI DISPATCHER ---
def extract_syllabus_with_ai(condensed_syllabus_text, hours, intensity, no_weekends, start_hr, end_hr):
    try:
        client = Groq()
        weekend_rule = "STRICT RULE: Do not schedule any study blocks on Saturdays or Sundays." if no_weekends else "You can utilize weekends for study blocks."
        
        prompt = f"""
        You are an elite academic strategy coach. Analyze the filtered syllabus data and output a valid JSON string object.
        The JSON object must contain exactly two array fields:
        1. "tasks": an array of objects containing "n" (task name) and "d" (due date in YYYY-MM-DD).
        2. "study_plan": an array of objects containing:
           - "d": scheduled date (YYYY-MM-DD)
           - "t": time slot window
           - "f": focus topic (specific concept/chapter name)
           - "a": suggested actionable item
           - "h": hours allocated (integer)
        
        CRITICAL OUTPUT EXTRACTION RULES:
        - NEVER write generic placeholder lines like 'Read Unit-I' or 'Solve questions' repeatedly.
        - Look deeply into the syllabus text rows, extract the actual, specific, unique technical topic or lesson names (e.g., 'Object Oriented Inheritance', 'Matrix Inverses', 'Memory Management pointer layouts', 'SQL Join operations'), and space them out chronologically across separate days.
        - Generate a rich, long, continuous chain of daily study milestones tracing true academic progression.
        
        USER AVAILABILITY CONSTRAINTS:
        - Study window: strictly between {start_hr} and {end_hr}. Every 't' value must fall within this window.
        - Assume the current date is June 2026. Space rows out sequentially across separate months.
        - Capacity: {hours} hours per day at a '{intensity}' pace.
        - {weekend_rule}
        
        Syllabus Text:
        {condensed_syllabus_text}
        """

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an itemized academic extractor. You must build an extensive, highly specific calendar roadmap using the precise technical lesson concepts provided in the syllabus text. Avoid repeating template phrases. Output a valid compressed JSON object matching the requested schema rules perfectly."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}  
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"error_mode_active": True, "details": str(e)}

lottie_processing = load_lottie_url("https://assets8.lottiefiles.com/packages/lf20_vnikbe9e.json")

# 3. GRAPHICS & THEME SYSTEM (CSS)
st.html("""
<style>
    .main-title { font-size: 3.6rem !important; font-weight: 800; background: linear-gradient(90deg, #00C6FF, #0072FF); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-top: 10px; margin-bottom: 25px; }
    [data-testid="stMetricSimpleValue"] { font-size: 1.8rem !important; color: #00C6FF !important; font-weight: 700; }
    div.stButton > button:first-child { background: linear-gradient(90deg, #00C6FF, #0072FF) !important; color: white !important; border: none !important; border-radius: 8px !important; padding: 12px 24px !important; font-weight: 600 !important; }
    div.stDownloadButton > button:first-child { background: #1E293B !important; color: #00C6FF !important; border: 1px solid rgba(0, 198, 255, 0.4) !important; border-radius: 8px !important; width: 100% !important; }
    .progress-status-text { font-family: system-ui, sans-serif; font-size: 0.95rem; color: #00C6FF; font-weight: 500; margin-bottom: 4px; }
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
        free_from = st.time_input("I am free from:", dt_time(17, 30))  
        free_until = st.time_input("I am free until:", dt_time(21, 30)) 
        string_from = free_from.strftime("%I:%M %p")
        string_until = free_until.strftime("%I:%M %p")

with right_panel:
    st.subheader("Drop your PDF here")
    uploaded_file = st.file_uploader("Upload Course Syllabus (PDF format)", type=["pdf"])

    if uploaded_file is not None:
        st.success(f"⚡ Linked with sequence target: **{uploaded_file.name}**")
        
        if st.button("Generate Optimized Timeline", use_container_width=True):
            
            start_minutes = free_from.hour * 60 + free_from.minute
            end_minutes = free_until.hour * 60 + free_until.minute
            available_duration_hours = (end_minutes - start_minutes) / 60
            
            if available_duration_hours < study_hours:
                st.error(f"❌ **Configuration Conflict:** Your Availability Window ({available_duration_hours:.2f} hours) is shorter than your daily study target ({study_hours} hours).")
                st.stop()
            
            progress_bar = st.progress(0)
            status_message = st.empty()
            
            # Phase 1: File Reading & Keyword Context Condensing
            status_message.markdown('<p class="progress-status-text">🔄 [25%] Phase 1: Parsing pages and isolating key roadmap concepts...</p>', unsafe_allow_html=True)
            progress_bar.progress(25)
            
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            st.session_state["page_count"] = doc.page_count
            full_text = ""
            for page in doc:
                full_text += page.get_text()
            
            # --- THE MAGIC WORKHORSE: HIGH-DENSITY LINE FILTER ---
            filtered_lines = []
            academic_keywords = ["week", "unit", "chapter", "topic", "assignment", "exam", "quiz", "test", "project", "lab", "module", "csa", "sec"]
            
            for line in full_text.split("\n"):
                clean_line = line.strip()
                # Keep lines that match academic topics or lines that contain numbers/dates
                if any(kw in clean_line.lower() for kw in academic_keywords) or (len(clean_line) > 12 and any(char.isdigit() for char in clean_line)):
                    filtered_lines.append(clean_line)
            
            condensed_syllabus = "\n".join(filtered_lines)
            
            # Safe truncation constraint for Groq payload gate
            if len(condensed_syllabus) > 22000:
                condensed_syllabus = condensed_syllabus[:22000]
            
            time.sleep(0.4)
            
            if not condensed_syllabus.strip():
                progress_bar.empty()
                status_message.empty()
                st.error("❌ **Unreadable PDF Error:** Could not extract meaningful academic timeline blocks from this document structure.")
                st.stop()
            
            # Phase 2: Groq Engine Call
            status_message.markdown('<p class="progress-status-text">🚀 [50%] Phase 2: Dispatching dense dataset to high-speed Groq LPU cores...</p>', unsafe_allow_html=True)
            progress_bar.progress(50)
            
            raw_ai_output = extract_syllabus_with_ai(condensed_syllabus, study_hours, focus_level, skip_weekends, string_from, string_until)
            
            if raw_ai_output is not None and "error_mode_active" in raw_ai_output:
                progress_bar.empty()
                status_message.empty()
                st.error("❌ **Groq Core API Refusal Code:**")
                st.code(raw_ai_output["details"], language="text")
                st.stop()

            if raw_ai_output is None:
                progress_bar.empty()
                status_message.empty()
                st.error("⚠️ An unhandled exception occurred inside the Groq API gateway.")
                st.stop()
            
            # Phase 3: Matrix Restructuring
            status_message.markdown('<p class="progress-status-text">📊 [75%] Phase 3: Structuring deep lesson metrics and sorting clock slots...</p>', unsafe_allow_html=True)
            progress_bar.progress(75)
            
            mapped_tasks = [{"task_name": item.get("n", "Unknown Milestone"), "due_date": item.get("d", "2026-06-15")} for item in raw_ai_output.get("tasks", [])]
            
            mapped_plan = [
                {
                    "Status": False,
                    "Scheduled Date": item.get("d", "2026-06-15"),
                    "Time Slot": item.get("t", "06:00 PM - 08:00 PM"),  
                    "Focus Topic": item.get("f", "Topic Exploration"),
                    "Suggested Action": item.get("a", "Review lecture parameters"),
                    "Hours Allocated": item.get("h", 2)
                } for item in raw_ai_output.get("study_plan", [])
            ]
            
            st.session_state["ai_data"] = {
                "tasks": mapped_tasks,
                "study_plan": mapped_plan
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
            <div style="display: flex; align-items: center; background: rgba(0, 198, 255, 0.04); border: 1px solid rgba(0, 198, 255, 0.25); border-radius: 12px; padding: 20px 24px; margin-bottom: 32px;">
                <div style="background: #00C6FF; color: #0E1117; font-weight: bold; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 18px;">✓</div>
                <div style="display: flex; flex-direction: column;">
                    <h4 style="color: #FFFFFF !important; font-family: system-ui; font-size: 1.15rem !important; font-weight: 600 !important; margin: 0 0 4px 0 !important;">Timeline Optimized Successfully</h4>
                    <p style="color: #A0AEC0 !important; font-family: system-ui; font-size: 0.9rem !important; margin: 0 !important;">Detailed lesson roadmap successfully parsed via high-density context sorting.</p>
                </div>
            </div>
        """)
        
        total_tasks = len(st.session_state["ai_data"]["tasks"])
        
        st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.container(border=True).metric(label="Pages Read", value=f"{st.session_state['page_count']} Pages")
        with m_col2:
            st.container(border=True).metric(label="AI Detected Tasks", value=f"{total_tasks} Items")
        with m_col3:
            st.container(border=True).metric(label="Daily Cap Target", value=f"{study_hours} Hours/Day")
        
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