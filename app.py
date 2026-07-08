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
import firebase_admin
from firebase_admin import credentials, firestore

# 1. PAGE SETUP & INITIALIZATION
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

if "ai_data" not in st.session_state:
    st.session_state["ai_data"] = None
if "page_count" not in st.session_state:
    st.session_state["page_count"] = 0

# --- FIREBASE CLOUD INITIALIZATION ROUTINE ---
def init_firebase():
    """Establishes a connection to your live Google Firebase Firestore container safely."""
    if not firebase_admin._apps:
        fb_credentials = dict(st.secrets["FIREBASE_SECRET"])
        cred = credentials.Certificate(fb_credentials)
        firebase_admin.initialize_app(cred)
    return firestore.client()

# Establish the global database pointer
db = init_firebase()

# --- FIREBASE CLOUD DATABASE HELPER FUNCTIONS ---
def save_schedule_to_firebase(username, tasks_list, plan_list):
    """Commits user milestones directly to live Firebase Cloud cells."""
    try:
        clean_tasks = [{"task_name": t.get("n", t.get("task_name", "Unknown")), "due_date": t.get("d", t.get("due_date", ""))} for t in tasks_list]
        clean_plan = [
            {
                "Status": True if item.get("Status") == True else False,
                "Scheduled Date": item.get("d", item.get("Scheduled Date", "")),
                "Time Slot": item.get("t", item.get("Time Slot", "")),
                "Focus Topic": item.get("f", item.get("Focus Topic", "")),
                "Suggested Action": item.get("a", item.get("Suggested Action", "")),
                "Hours Allocated": item.get("h", item.get("Hours Allocated", 2))
            } for item in plan_list
        ]
        
        user_doc_ref = db.collection("users").document(username)
        user_doc_ref.set({
            "tasks": clean_tasks,
            "study_plan": clean_plan,
            "last_updated": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        st.sidebar.error(f"Cloud Save Error: {e}")
        return False

def load_schedule_from_firebase(username):
    """Pulls persistent user records out of Firestore documents into memory arrays."""
    try:
        user_doc_ref = db.collection("users").document(username)
        doc = user_doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # Map database schema names back to interface labels
            tasks = [{"task_name": t["task_name"], "due_date": t["due_date"]} for t in data.get("tasks", [])]
            study_plan = [
                {
                    "Status": item["Status"],
                    "Scheduled Date": item["Scheduled Date"],
                    "Time Slot": item["Time Slot"],
                    "Focus Topic": item["Focus Topic"],
                    "Suggested Action": item["Suggested Action"],
                    "Hours Allocated": item["Hours Allocated"]
                } for item in data.get("study_plan", [])
            ]
            return {"tasks": tasks, "study_plan": study_plan}
        return None
    except Exception as e:
        st.sidebar.error(f"Cloud Load Error: {e}")
        return None

# 3. INTERFACE COMPONENT HELPER
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

# --- GROQ INTELLIGENCE CORE ROUTINE ---
def extract_syllabus_with_ai(condensed_text, hours, intensity, no_weekends, start_hr, end_hr):
    max_retries = 3
    base_delay = 4
    
    for attempt in range(max_retries):
        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            weekend_rule = "STRICT RULE: Do not schedule any study blocks on Saturdays or Sundays." if no_weekends else "You can utilize weekends for study blocks."
            
            prompt = f"""
            You are an elite academic strategy coach. Analyze the filtered syllabus data text and output a valid JSON string object.
            The JSON object must contain exactly two array fields:
            1. "tasks": an array of objects containing "n" (task name) and "d" (due date in YYYY-MM-DD).
            2. "study_plan": an array of objects containing:
               - "d": scheduled date (YYYY-MM-DD)
               - "t": time slot window string
               - "f": focus topic (precise conceptual chapter or lesson name extracted from the text layout)
               - "a": suggested actionable study item
               - "h": hours allocated (integer)
            
            CRITICAL LINEAR SEQUENCE RULE:
            - Read the provided Syllabus Text systematically from TOP TO BOTTOM.
            - You MUST generate your study plan row-by-row in the exact chronological order that the units/chapters appear in the text document. 
            - Start with the first topics listed in Unit 1 / Week 1, map those sequentially to your earliest calendar dates, and progressively move down through Unit 2, Unit 3, Unit 4 etc.
            - Never skip ahead to later concepts or mix future modules into earlier study dates. Keep the schedule as sequential as the syllabus text content flow.
            
            CRITICAL OUTPUT VOLUME RULES:
            - Avoid writing generic text blocks or placeholder labels like 'Read Unit-I' repeatedly.
            - Generate an extensive timeline containing between 80 to 120 separate individual entries inside the "study_plan" array to match the granular course scope without truncating early.
            
            USER AVAILABILITY CONSTRAINTS:
            - Study window: strictly between {start_hr} and {end_hr}. Every 't' value must fall within this window.
            - Assume the current date is June 2026. Space rows out sequentially across separate months.
            - Capacity: {hours} hours per day at a '{intensity}' pace.
            - {weekend_rule}
            - All dates must use 'YYYY-MM-DD' format.
            
            Syllabus Text:
            {condensed_text}
            """

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a linear timeline sequence compiler. You must output raw JSON arrays matching the requested compressed single-character field keys perfectly. Map topics from top to bottom in strict linear chronological order without skipping sections. Maximize row generation count up to 120 distinct items."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=8192  
            )
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower() or "limit" in error_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
            return {"error_mode_active": True, "details": error_msg}

lottie_processing = load_lottie_url("https://assets8.lottiefiles.com/packages/lf20_vnikbe9e.json")

# 4. GRAPHICS & THEME SYSTEM (CSS)
st.html("""
<style>
    .main-title { font-size: 3.6rem !important; font-weight: 800; background: linear-gradient(90deg, #00C6FF, #0072FF); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-top: 10px; margin-bottom: 25px; }
    [data-testid="stMetricSimpleValue"] { font-size: 1.8rem !important; color: #00C6FF !important; font-weight: 700; }
    div.stButton > button:first-child { background: linear-gradient(90deg, #00C6FF, #0072FF) !important; color: white !important; border: none !important; border-radius: 8px !important; padding: 12px 24px !important; font-weight: 600 !important; }
    div.stDownloadButton > button:first-child { background: #1E293B !important; color: #00C6FF !important; border: 1px solid rgba(0, 198, 255, 0.4) !important; border-radius: 8px !important; width: 100% !important; }
    .progress-status-text { font-family: system-ui, sans-serif; font-size: 0.95rem; color: #00C6FF; font-weight: 500; margin-bottom: 4px; }
</style>
""")

st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)
st.markdown("---")

# 5. SPLIT PANEL CONTROL INTERFACES
left_panel, right_panel = st.columns([1, 2], gap="large")
with left_panel:
    st.subheader("👤 Student Profile")
    
    # Track the active profile in session state so it can update dynamically
    if "username_val" not in st.session_state:
        st.session_state["username_val"] = "Aditya"
        
    user_id = st.text_input("Active Profile Name:", value=st.session_state["username_val"]).strip()
    st.session_state["username_val"] = user_id  # Sync text box changes instantly

    # Button A: Load existing profiles from the cloud
    if st.button("📂 Load From Cloud Database", use_container_width=True):
        cloud_data = load_schedule_from_firebase(user_id)
        if cloud_data:
            st.session_state["ai_data"] = cloud_data
            st.success(f"Loaded records securely for user: **{user_id}**")
            st.rerun()
        else:
            st.warning("No saved profile records found in Firestore for this user.")

    # ✨ NEW USER PERSPECTIVE: Native Cloud Profile Registration Window
    with st.popover("🆕 Create New Profile", use_container_width=True):
        st.markdown("### Create New Profile")
        new_username = st.text_input("Choose Unique Username / Roll No:", key="new_reg_field").strip()
        
        if st.button("🚀 Register & Save in Cloud", use_container_width=True):
            if new_username:
                # Security Check: Ensure they don't overwrite an existing user's data
                existing_profile = load_schedule_from_firebase(new_username)
                if existing_profile:
                    st.error("⚠️ This profile name already exists in Firebase! Please choose a unique name.")
                else:
                    # Create a fresh, empty document slot in your live Firestore database instantly
                    save_success = save_schedule_to_firebase(new_username, [], [])
                    if save_success:
                        st.session_state["username_val"] = new_username  # Set as active profile
                        st.success(f"🎉 Profile '{new_username}' registered successfully in Firebase!")
                        time.sleep(1.5)
                        st.rerun()
            else:
                st.warning("Please type a valid name string.")

    st.markdown("<br>", unsafe_allow_html=True)
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
                st.error(f"❌ **Configuration Conflict Error:** Availability window is shorter than your required hours slider target.")
                st.stop()
            
            progress_bar = st.progress(0)
            status_message = st.empty()
            
            # Phase 1: Ingestion & High-Density Line Filter
            status_message.markdown('<p class="progress-status-text">🔄 [25%] Phase 1: Parsing PDF lines and compiling sequential matrix...</p>', unsafe_allow_html=True)
            progress_bar.progress(25)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            st.session_state["page_count"] = doc.page_count
            full_text = ""
            for page in doc:
                full_text += page.get_text()
                
            filtered_lines = []
            academic_keywords = ["week", "unit", "chapter", "topic", "assignment", "exam", "quiz", "test", "project", "lab", "module", "csa", "sec"]
            
            for line in full_text.split("\n"):
                clean_line = line.strip()
                if any(kw in clean_line.lower() for kw in academic_keywords) or (len(clean_line) > 12 and any(char.isdigit() for char in clean_line)):
                    filtered_lines.append(clean_line)
            
            condensed_syllabus = "\n".join(filtered_lines)
            
            # Defense Cutoff: Solves HTTP 413 payload rejections permanently
            if len(condensed_syllabus) > 7000:
                condensed_syllabus = condensed_syllabus[:7000]
                
            time.sleep(0.4)
            
            if not condensed_syllabus.strip():
                progress_bar.empty()
                status_message.empty()
                st.error("❌ **Unreadable PDF Error:** Could not parse clear structural milestones from this file.")
                st.stop()
            
            # Phase 2: Groq Call
            status_message.markdown('<p class="progress-status-text">🚀 [50%] Phase 2: Dispatching sequential dataset to Groq hardware clusters...</p>', unsafe_allow_html=True)
            progress_bar.progress(50)
            
            raw_ai_output = extract_syllabus_with_ai(condensed_syllabus, study_hours, focus_level, skip_weekends, string_from, string_until)
            
            if raw_ai_output is not None and "error_mode_active" in raw_ai_output:
                progress_bar.empty()
                status_message.empty()
                st.error("❌ **Groq Core API Error:**")
                st.code(raw_ai_output["details"], language="text")
                st.stop()
            
            # Phase 3: Matrix Expansion
            status_message.markdown('<p class="progress-status-text">📊 [75%] Phase 3: Inflating structural shorthand keys back to clear visual datagrides...</p>', unsafe_allow_html=True)
            progress_bar.progress(75)
            
            mapped_tasks = [{"task_name": item.get("n", "Course Milestone"), "due_date": item.get("d", "2026-06-15")} for item in raw_ai_output.get("tasks", [])]
            mapped_plan = [
                {
                    "Status": False,
                    "Scheduled Date": item.get("d", "2026-06-15"),
                    "Time Slot": item.get("t", f"{string_from} - {string_until}"),  
                    "Focus Topic": item.get("f", "Topic Review Module"),
                    "Suggested Action": item.get("a", "Review notes and practice core assignments"),
                    "Hours Allocated": item.get("h", int(study_hours))
                } for item in raw_ai_output.get("study_plan", [])
            ]
            
            st.session_state["ai_data"] = {
                "tasks": mapped_tasks,
                "study_plan": mapped_plan
            }
            
            # AUTOMATED CLOUD FIREBASE BACKEND PERSISTENCE
            save_schedule_to_firebase(user_id, mapped_tasks, mapped_plan)
            time.sleep(0.4)
            
            # Phase 4: Sync Interfaces
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
                    <p style="color: #A0AEC0 !important; font-family: system-ui; font-size: 0.9rem !important; margin: 0 !important;">Active data profile synced and loaded live via Google Cloud Firestore cells.</p>
                </div>
            </div>
        """)
        
        total_tasks = len(st.session_state["ai_data"]["tasks"])
        total_rows = len(st.session_state["ai_data"]["study_plan"])
        
        st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.container(border=True).metric(label="Pages Read", value=f"{st.session_state['page_count']} Pages")
        with m_col2:
            st.container(border=True).metric(label="AI Daily Milestones", value=f"{total_rows} Actions")
        with m_col3:
            st.container(border=True).metric(label="User Identifier Profile", value=user_id)
        
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
                # PERSIST INTERACTIVE LIVE CHECKBOX UPDATES TO THE FIREBASE CLOUD INSTANTLY
                save_schedule_to_firebase(user_id, st.session_state["ai_data"]["tasks"], st.session_state["ai_data"]["study_plan"])
                st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            d_col1, d_col2 = st.columns(2)
            
            with d_col1:
                calendar_data = generate_ics_file(edited_roadmap)
                st.download_button(label="📅 Export to Calendar (.ics)", data=calendar_data, file_name=f"{user_id}_schedule.ics", mime="text/calendar", use_container_width=True)
            with d_col2:
                csv_data = edited_roadmap.to_csv(index=False).encode('utf-8')
                st.download_button(label="📊 Download Spreadsheet (.csv)", data=csv_data, file_name=f"{user_id}_checklist.csv", mime="text/csv", use_container_width=True)