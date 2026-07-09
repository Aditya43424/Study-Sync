import streamlit as st
import time
import requests
import json
import fitz  # PyMuPDF
import pandas as pd
import uuid  
from datetime import datetime, timedelta, time as dt_time 
from groq import Groq  
import firebase_admin
from firebase_admin import credentials, firestore, auth

# 1. PAGE SETUP & SESSION STATE INITIALIZATION
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

if "user_authenticated" not in st.session_state:
    st.session_state["user_authenticated"] = False
if "active_username" not in st.session_state:
    st.session_state["active_username"] = ""
if "ai_data" not in st.session_state:
    st.session_state["ai_data"] = None
if "page_count" not in st.session_state:
    st.session_state["page_count"] = 0

# --- GOOGLE FIREBASE CLOUD INITIALIZATION ---
def init_firebase():
    """Establishes a connection to your live Google Firebase Firestore container safely."""
    if not firebase_admin._apps:
        fb_credentials = dict(st.secrets["FIREBASE_SECRET"])
        cred = credentials.Certificate(fb_credentials)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# --- FIREBASE AUTHENTICATION UTILITIES ---
def register_cloud_user(email, password, username):
    """Creates a password-protected user profile inside Google Firebase Auth core."""
    try:
        user_doc = db.collection("users").document(username).get()
        if user_doc.exists:
            return False, "Username is already taken! Choose a unique handle."
            
        user = auth.create_user(email=email, password=password, display_name=username)
        
        db.collection("users").document(username).set({
            "tasks": [],
            "study_plan": [],
            "email": email,
            "created_at": firestore.SERVER_TIMESTAMP
        })
        return True, "Account registered successfully! Swap to Sign In tab."
    except Exception as e:
        return False, str(e).replace("AN_ERROR_OCCURRED:", "")

def verify_cloud_login(email, password):
    """Validates user passwords against Google Auth servers using the Web API secure gateway."""
    try:
        api_key = st.secrets["FIREBASE_WEB_API_KEY"]
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            user_record = auth.get_user(data["localId"])
            return True, user_record.display_name
        else:
            err_res = response.json()
            return False, err_res["error"]["message"].replace("_", " ")
    except Exception as e:
        return False, str(e)

# --- FIRESTORE DATA PERSISTENCE UTILITIES ---
def save_schedule_to_firebase(username, tasks_list, plan_list):
    try:
        clean_tasks = [{"task_name": t.get("task_name", "Unknown"), "due_date": t.get("due_date", "")} for t in tasks_list]
        clean_plan = [
            {
                "Status": True if item.get("Status") == True else False,
                "Scheduled Date": item.get("Scheduled Date", ""),
                "Time Slot": item.get("Time Slot", ""),
                "Focus Topic": item.get("Focus Topic", ""),
                "Suggested Action": item.get("Suggested Action", ""),
                "Hours Allocated": item.get("Hours Allocated", 2)
            } for item in plan_list
        ]
        db.collection("users").document(username).update({
            "tasks": clean_tasks,
            "study_plan": clean_plan,
            "last_updated": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        st.sidebar.error(f"Cloud Save Error: {e}")
        return False

def load_schedule_from_firebase(username):
    try:
        doc = db.collection("users").document(username).get()
        if doc.exists:
            data = doc.to_dict()
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
        return None

# --- ENGINE LOGIC & SCHEDULER ENGINE ---
def generate_ics_file(study_dataframe):
    nl = "\r\n"
    current_timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ics_text = f"BEGIN:VCALENDAR{nl}VERSION:2.0{nl}PRODID:-//Study Sync//Study Planner//EN{nl}CALSCALE:GREGORIAN{nl}"
    for _, row in study_dataframe.iterrows():
        date_str = str(row['Scheduled Date']).strip()
        try:
            start_dt = datetime.strptime(date_str, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=1)
            ics_text += f"BEGIN:VEVENT{nl}UID:{uuid.uuid4()}{nl}DTSTAMP:{current_timestamp}{nl}"
            ics_text += f"SUMMARY:📚 Focus [{row['Time Slot']}]: {row['Focus Topic']}{nl}"
            ics_text += f"DESCRIPTION:Action: {row['Suggested Action']} | Allocated: {row['Hours Allocated']} hours.{nl}"
            ics_text += f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}{nl}DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}{nl}END:VEVENT{nl}"
        except Exception:
            pass
    ics_text += f"END:VCALENDAR"
    return ics_text

def extract_syllabus_with_ai(condensed_text, hours, intensity, no_weekends, start_hr, end_hr):
    max_retries = 3
    base_delay = 4
    for attempt in range(max_retries):
        try:
            client = Groq(api_key=st.secrets["GROQ_API_KEY"])
            weekend_rule = "STRICT RULE: Do not schedule any study blocks on Saturdays or Sundays." if no_weekends else "You can utilize weekends for study blocks."
            prompt = f"""
            Analyze the filtered syllabus text and output a valid JSON string object containing exactly two array fields: 'tasks' and 'study_plan'.
            CRITICAL LINEAR SEQUENCE RULE: Read systematically from TOP TO BOTTOM. Map topics row-by-row in the exact chronological order they appear in the document text.
            STRICT FILLER BAN RULE: NEVER write vague placeholder labels like 'Review of all topics' or 'Introduction to new topics' repeatedly. Each row must extract a concrete technical concept item name. Generate between 80 to 120 rows to capture complete course depth.
            Constraints: Study windows strictly {start_hr} to {end_hr}. current date is June 2026. Capacity: {hours} hours/day at a '{intensity}' pace. {weekend_rule}
            Syllabus Text:\n{condensed_text}
            """
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a linear timeline sequence compiler outputting raw JSON arrays with compressed single-character keys matching the standard model design perfectly. Maximize row generation item parameters up to 120 unique cells."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=8192  
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                time.sleep(base_delay * (2 ** attempt))
                continue
            return {"error_mode_active": True, "details": error_msg}

# --- STAGE 1: SYSTEM AUTHENTICATION WALL CONTROLLER ---
if not st.session_state["user_authenticated"]:
    st.html("<style>.main-title { font-size: 3.6rem !important; font-weight: 800; background: linear-gradient(90deg, #00C6FF, #0072FF); -webkit-background-clip: text; -webkit-text-fill-color: transparent; text-align: center; margin-top: 5vh; }</style>")
    st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #A0AEC0;'>Production-Grade AI Academic Roadmap Synthesizer Gateway</p>", unsafe_allow_html=True)
    
    auth_container = st.container(border=True)
    with auth_container:
        tab_login, tab_signup = st.tabs(["🔐 Sign In", "📝 Register New Account"])
        
        with tab_login:
            log_email = st.text_input("Registered Email Address:", key="log_em").strip()
            log_pass = st.text_input("Password Secure Code:", type="password", key="log_pw").strip()
            if st.button("Access Dashboard Console", use_container_width=True):
                if log_email and log_pass:
                    success, username = verify_cloud_login(log_email, log_pass)
                    if success:
                        st.session_state["user_authenticated"] = True
                        st.session_state["active_username"] = username
                        cloud_data = load_schedule_from_firebase(username)
                        if cloud_data:
                            st.session_state["ai_data"] = cloud_data
                        st.success(f"Security Clearance Verified! Welcome back, {username}.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"Authentication Failure: {username}")
                else:
                    st.warning("All verification credentials parameters are required.")
                    
        with tab_signup:
            reg_user = st.text_input("Choose Unique Username / Roll No:", key="reg_un").strip()
            reg_email = st.text_input("Institutional Email Address:", key="reg_em").strip()
            reg_pass = st.text_input("Create Secure Password Asset:", type="password", key="reg_pw").strip()
            if st.button("Propose Account Registration", use_container_width=True):
                if reg_user and reg_email and reg_pass:
                    if len(reg_pass) < 6:
                        st.error("Security Policy Warning: Password must be at least 6 characters long.")
                    else:
                        success, message = register_cloud_user(reg_email, reg_pass, reg_user)
                        if success:
                            st.success(message)
                        else:
                            st.error(f"Registration Refused: {message}")
                else:
                    st.warning("All configuration parameter tracking cells are required.")
    st.stop()

# --- STAGE 2: SYSTEM INTERFACE APPLICATION WINDOW ---
user_id = st.session_state["active_username"]

st.html("""<style>
    .main-title { font-size: 3.6rem !important; font-weight: 800; background: linear-gradient(90deg, #00C6FF, #0072FF); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 25px; }
    [data-testid="stMetricSimpleValue"] { font-size: 1.8rem !important; color: #00C6FF !important; font-weight: 700; }
    div.stButton > button:first-child { background: linear-gradient(90deg, #00C6FF, #0072FF) !important; color: white !important; border: none !important; border-radius: 8px !important; padding: 12px 24px !important; font-weight: 600 !important; }
    div.stDownloadButton > button:first-child { background: #1E293B !important; color: #00C6FF !important; border: 1px solid rgba(0, 198, 255, 0.4) !important; border-radius: 8px !important; width: 100% !important; }
    .progress-status-text { font-family: system-ui, sans-serif; font-size: 0.95rem; color: #00C6FF; font-weight: 500; margin-bottom: 4px; }
</style>""")

st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)
st.markdown("---")

left_panel, right_panel = st.columns([1, 2], gap="large")

with left_panel:
    st.subheader("👤 Student Profile")
    st.info(f"Authenticated Live Session Account: **{user_id}**")
    if st.button("🚪 Log Out of Cloud Connection", use_container_width=True):
        st.session_state["user_authenticated"] = False
        st.session_state["active_username"] = ""
        st.session_state["ai_data"] = None
        st.rerun()

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
                st.error("❌ **Configuration Conflict Error:** Availability window is shorter than your required hours slider target.")
                st.stop()
            
            progress_bar = st.progress(0)
            status_message = st.empty()
            
            status_message.markdown('<p class="progress-status-text">🔄 [25%] Phase 1: Parsing PDF lines and compiling sequential matrix...</p>', unsafe_allow_html=True)
            progress_bar.progress(25)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            st.session_state["page_count"] = doc.page_count
            full_text = "".join([page.get_text() for page in doc])
                
            filtered_lines = []
            academic_keywords = ["week", "unit", "chapter", "topic", "assignment", "exam", "quiz", "test", "project", "lab", "module", "csa", "sec", "semester", "course", "subject"]
            for line in full_text.split("\n"):
                clean_line = line.strip()
                if any(kw in clean_line.lower() for kw in academic_keywords) or (len(clean_line) > 12 and any(char.isdigit() for char in clean_line)):
                    filtered_lines.append(clean_line)
            
            condensed_syllabus = "\n".join(filtered_lines)
            if len(condensed_syllabus) > 14000:
                condensed_syllabus = condensed_syllabus[:14000]
                
            if not condensed_syllabus.strip():
                progress_bar.empty(); status_message.empty()
                st.error("❌ **Unreadable PDF Error:** Could not parse clear structural milestones from this file.")
                st.stop()
            
            status_message.markdown('<p class="progress-status-text">🚀 [50%] Phase 2: Dispatching sequential dataset to Groq hardware clusters...</p>', unsafe_allow_html=True)
            progress_bar.progress(50)
            raw_ai_output = extract_syllabus_with_ai(condensed_syllabus, study_hours, focus_level, skip_weekends, string_from, string_until)
            
            if raw_ai_output is not None and "error_mode_active" in raw_ai_output:
                progress_bar.empty(); status_message.empty()
                st.error("❌ **Groq Core API Error:**"); st.code(raw_ai_output["details"], language="text"); st.stop()
            
            status_message.markdown('<p class="progress-status-text">📊 [75%] Phase 3: Inflating structural shorthand keys back to clear visual datagrides...</p>', unsafe_allow_html=True)
            progress_bar.progress(75)
            
            # --- ✨ CRITICAL FIX: HIGH-SECURITY TYPE-CHECKING ENGINE ---
            raw_tasks = raw_ai_output.get("tasks", []) if isinstance(raw_ai_output, dict) else []
            if not isinstance(raw_tasks, list):
                raw_tasks = []
                
            mapped_tasks = []
            for item in raw_tasks:
                if isinstance(item, dict):
                    mapped_tasks.append({
                        "task_name": item.get("n", "Course Milestone"),
                        "due_date": item.get("d", "2026-06-15")
                    })
                elif isinstance(item, str):
                    mapped_tasks.append({
                        "task_name": item,
                        "due_date": "2026-06-15"
                    })
                    
            raw_plan = raw_ai_output.get("study_plan", []) if isinstance(raw_ai_output, dict) else []
            if not isinstance(raw_plan, list):
                raw_plan = []
                
            mapped_plan = []
            for item in raw_plan:
                if isinstance(item, dict):
                    mapped_plan.append({
                        "Status": False,
                        "Scheduled Date": item.get("d", "2026-06-15"),
                        "Time Slot": item.get("t", f"{string_from} - {string_until}"),  
                        "Focus Topic": item.get("f", "Topic Review Module"),
                        "Suggested Action": item.get("a", "Review notes and practice core assignments"),
                        "Hours Allocated": item.get("h", int(study_hours))
                    })
            # -----------------------------------------------------------
            
            st.session_state["ai_data"] = {"tasks": mapped_tasks, "study_plan": mapped_plan}
            save_schedule_to_firebase(user_id, mapped_tasks, mapped_plan)
            
            status_message.markdown('<p class="progress-status-text">✨ [100%] Phase 4: Synchronizing interactive checklist frameworks...</p>', unsafe_allow_html=True)
            progress_bar.progress(100); time.sleep(0.3); progress_bar.empty(); status_message.empty()

    if st.session_state["ai_data"] is not None:
        st.html(f"""<div style="display: flex; align-items: center; background: rgba(0, 198, 255, 0.04); border: 1px solid rgba(0, 198, 255, 0.25); border-radius: 12px; padding: 20px 24px; margin-bottom: 32px;">
            <div style="background: #00C6FF; color: #0E1117; font-weight: bold; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 18px;">✓</div>
            <div>
                <h4 style="color: #FFFFFF !important; font-family: system-ui; font-size: 1.15rem !important; font-weight: 600 !important; margin: 0 0 4px 0 !important;">Cloud Database Synced Successfully</h4>
                <p style="color: #A0AEC0 !important; font-family: system-ui; font-size: 0.9rem !important; margin: 0 !important;">Roadmap records securely encrypted and locked under profile account node: {user_id}</p>
            </div>
        </div>""")
        
        total_tasks = len(st.session_state["ai_data"]["tasks"])
        total_rows = len(st.session_state["ai_data"]["study_plan"])
        
        st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1: st.container(border=True).metric(label="Pages Read", value=f"{st.session_state['page_count']} Pages")
        with m_col2: st.container(border=True).metric(label="AI Daily Milestones", value=f"{total_rows} Actions")
        with m_col3: st.container(border=True).metric(label="Active Account Holder", value=user_id)
        
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
                roadmap_df, use_container_width=True,
                disabled=["Scheduled Date", "Time Slot", "Focus Topic", "Suggested Action", "Hours Allocated"],
                hide_index=True, key="roadmap_editor"
            )
            if not edited_roadmap.equals(roadmap_df):
                st.session_state["ai_data"]["study_plan"] = edited_roadmap.to_dict(orient="records")
                save_schedule_to_firebase(user_id, st.session_state["ai_data"]["tasks"], st.session_state["ai_data"]["study_plan"])
                st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.download_button(label="📅 Export to Calendar (.ics)", data=generate_ics_file(edited_roadmap), file_name=f"{user_id}_schedule.ics", mime="text/calendar", use_container_width=True)
            with d_col2:
                st.download_button(label="📊 Download Spreadsheet (.csv)", data=edited_roadmap.to_csv(index=False).encode('utf-8'), file_name=f"{user_id}_checklist.csv", mime="text/csv", use_container_width=True)