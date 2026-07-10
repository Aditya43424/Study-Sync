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
from firebase_admin import credentials, firestore

# 1. PAGE SETUP & CONFIGURATION
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

# Persistent State Management Engine
if "user_uid" not in st.session_state:
    st.session_state["user_uid"] = None
if "user_email" not in st.session_state:
    st.session_state["user_email"] = None
if "username_val" not in st.session_state:
    st.session_state["username_val"] = "Aditya"
if "ai_data" not in st.session_state:
    st.session_state["ai_data"] = None
if "page_count" not in st.session_state:
    st.session_state["page_count"] = 0

# --- FIREBASE CLOUD CORE ROUTINES (CACHED TO PREVENT SEGFAULTS) ---
@st.cache_resource
def init_firebase():
    """Establishes connection to Google Cloud Firestore containers securely exactly once."""
    if not firebase_admin._apps:
        fb_credentials = dict(st.secrets["FIREBASE_SECRET"])
        cred = credentials.Certificate(fb_credentials)
        firebase_admin.initialize_app(cred)
    return firestore.client()

db = init_firebase()

# --- FIREBASE REST AUTHENTICATION SYSTEM ---
def firebase_auth_request(endpoint, email, password):
    """Routes validation checks to Google Cloud's Secure Identity Gateway REST API."""
    api_key = st.secrets["FIREBASE_WEB_API_KEY"]
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    
    response = requests.post(url, json=payload)
    return response.json()

# --- FIREBASE FIRESTORE DATA COUPLERS ---
def save_schedule_to_firebase(profile_name, tasks_list, plan_list):
    """Commits user milestones directly to the specified username profile cell."""
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
        
        user_doc_ref = db.collection("users").document(profile_name)
        user_doc_ref.set({
            "tasks": clean_tasks,
            "study_plan": clean_plan,
            "last_updated": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        st.error(f"Cloud Storage Warning: {e}")
        return False

def load_schedule_from_firebase(profile_name):
    """Pulls persistent user records out of specific Firestore username profile paths."""
    try:
        user_doc_ref = db.collection("users").document(profile_name)
        doc = user_doc_ref.get()
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

# 2. CALENDAR GENERATION ROUTINE
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

# --- CHRONOLOGICAL EXPANSION GROQ ENGINE ---
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
            - You MUST generate your study plan row-by-row in the exact chronological order that the units/chapters/semesters appear in the text document. 
            
            🔥 ANTI-LAZINESS & VARIETY LAWS:
            - NEVER use generic words like 'Read', 'Study', 'Review', 'Practice', or 'Prepare' by themselves.
            - STRICTLY FORBIDDEN: Do not repeat the same prefix phrase style continuously across multiple rows. Avoid structural loops (like starting every row with 'Code development structures for' or 'Derive algorithms for').
            - Every single Suggested Action ('a') must be an organically phrased, unique instruction sentence tailored to the topic using diverse verbs.
            - Mix up sentence layouts. Use specific directives like: 'Build an script that handles...', 'Write code to execute...', 'Configure a clean environment layout for...', 'Trace execution outputs of...', 'Design an interactive setup demonstrating...', 'Analyze the performance properties of...', or 'Debug potential boundary faults within...'.
            - Generate between 80 to 120 separate row entries to match the granular course scope cleanly without truncating early.
            
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
                    {"role": "system", "content": "You are a versatile academic curriculum architect. You break down units into specific development assignments. You use high vocabulary variety and completely avoid repetitive phrase loops, templates, or the word 'Read'."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=6000  
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate_limit" in error_msg.lower():
                if attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
            return {"error_mode_active": True, "details": error_msg}

# 100% STABLE NATIVE BRAND CUSTOM WEB STYLING (PURE CSS ONLY - NO JAVASCRIPT)
st.html("""
<style>
    /* Premium Blue | Dark Blue | White Static Gradient Text */
    .main-title { 
        font-size: 3.8rem !important; 
        font-weight: 800; 
        background: linear-gradient(90deg, #0072FF 0%, #003399 50%, #FFFFFF 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 25px;
        display: inline-block;
    }

    /* Stable Custom Blue Interface Button Themes */
    div.stButton > button:first-child {
        background: linear-gradient(90deg, #0072FF, #003399) !important; 
        color: white !important; 
        border: none !important; 
        border-radius: 8px !important; 
        padding: 12px 24px !important;
        font-weight: 600 !important;
        width: 100% !important;
        transition: transform 0.2s ease, opacity 0.2s ease !important;
    }

    div.stButton > button:first-child:hover {
        opacity: 0.95 !important;
        transform: translateY(-1px);
    }

    .auth-container { max-width: 450px; margin: 60px auto; padding: 30px; background: #1E293B; border-radius: 12px; border: 1px solid rgba(0,198,255,0.2); }
</style>
""")

# ==========================================
# GATEWAY PHASE: CORE AUTHENTICATION UI
# ==========================================
if st.session_state["user_uid"] is None:
    st.markdown('<center><p class="main-title">Study Sync</p></center>', unsafe_allow_html=True)
    
    auth_tab1, auth_tab2 = st.tabs(["🔒 Secure Login", "📝 Create Account"])
    
    with auth_tab1:
        with st.form("login_form"):
            li_username = st.text_input("Username / Roll Number:", value="Aditya").strip()
            li_email = st.text_input("Email Address:")
            li_password = st.text_input("Password:", type="password")
            # ✨ FIXED: Changed use_container_width to modern width property
            submit_login = st.form_submit_button("Access Profile Console", width="stretch")
            
            if submit_login:
                if not li_username:
                    st.error("Please provide your profile Username / Roll Number.")
                else:
                    res = firebase_auth_request("signInWithPassword", li_email, li_password)
                    if "localId" in res:
                        st.session_state["user_uid"] = res["localId"]
                        st.session_state["user_email"] = res["email"]
                        st.session_state["username_val"] = li_username
                        
                        cloud_load = load_schedule_from_firebase(li_username)
                        if cloud_load:
                            st.session_state["ai_data"] = cloud_load
                        st.success("Verification confirmed! Redirecting...")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Authentication Failed: {res.get('error', {}).get('message', 'Unknown Verification Route Error')}")
                    
    with auth_tab2:
        with st.form("signup_form"):
            su_username = st.text_input("Choose Unique Username / Roll Number:").strip()
            su_email = st.text_input("Email Address Registration Target:")
            su_password = st.text_input("Configure Strong Password:", type="password", help="Must be minimum 6 characters long")
            # ✨ FIXED: Changed use_container_width to modern width property
            submit_signup = st.form_submit_button("Register Cloud Profile Key", width="stretch")
            
            if submit_signup:
                if not su_username:
                    st.error("Please specify a custom Username or Roll Number slot.")
                elif len(su_password) < 6:
                    st.error("Security Restriction: Passwords must contain at least 6 characters.")
                else:
                    existing_profile = load_schedule_from_firebase(su_username)
                    if existing_profile:
                        st.error("⚠️ This profile name already exists in Firebase! Please choose a unique layout.")
                    else:
                        res = firebase_auth_request("signUp", su_email, su_password)
                        if "localId" in res:
                            save_schedule_to_firebase(su_username, [], [])
                            st.success("Registration success! Cloud profile allocated. You can now login using the Login tab.")
                        else:
                            st.error(f"Registration Failed: {res.get('error', {}).get('message', 'Email profile conflict.')}")
    st.stop()

# ==========================================
# RUNTIME ENVIRONMENT: DASHBOARD LAYOUT
# ==========================================
st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)

profile_col1, profile_col2 = st.columns([5, 1])
profile_col1.markdown(f"👤 Connected Account: **{st.session_state['user_email']}**")
# ✨ FIXED: Changed use_container_width to modern width property
if profile_col2.button("🚪 Log Out", width="stretch"):
    st.session_state["user_uid"] = None
    st.session_state["user_email"] = None
    st.session_state["ai_data"] = None
    st.rerun()

st.markdown("---")

left_panel, right_panel = st.columns([1, 2], gap="large")

with left_panel:
    st.subheader("👤 Active Profile")
    st.info(f"Logged in as: **{st.session_state['username_val']}**")

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("⚙️ Schedule Parameters")
    with st.container(border=True):
        study_hours = st.slider("Daily Study Capacity (Hours)", 1, 8, 3)
        focus_level = st.select_slider("Target Study Intensity", options=["Casual", "Balanced", "Intense"])
        skip_weekends = st.toggle("Exclude Weekends")
        
    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("🕒 Time Horizon Window")
    with st.container(border=True):
        free_from = st.time_input("I am free from:", dt_time(17, 30))  
        free_until = st.time_input("I am free until:", dt_time(21, 30)) 
        string_from = free_from.strftime("%I:%M %p")
        string_until = free_until.strftime("%I:%M %p")

with right_panel:
    st.subheader("Drop your Syllabus PDF here")
    uploaded_file = st.file_uploader("Upload Document (PDF context data)", type=["pdf"])

    if uploaded_file is not None:
        st.success(f"⚡ Linked with compilation targets: **{uploaded_file.name}**")
        
        # ✨ FIXED: Changed use_container_width to modern width property
        if st.button("Generate Optimized Timeline", width="stretch"):
            start_minutes = free_from.hour * 60 + free_from.minute
            end_minutes = free_until.hour * 60 + free_until.minute
            available_duration_hours = (end_minutes - start_minutes) / 60
            
            if available_duration_hours < study_hours:
                st.error("❌ Configuration Error: Allotted duration window cannot compress below required study capacity hours.")
                st.stop()
            
            progress_bar = st.progress(0)
            
            st.markdown('🔄 Parsing PDF text metadata structures...')
            progress_bar.progress(25)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            st.session_state["page_count"] = doc.page_count
            full_text = "".join([page.get_text() for page in doc])
                
            filtered_lines = []
            academic_keywords = ["week", "unit", "chapter", "topic", "assignment", "exam", "quiz", "test", "project", "lab", "module", "semester", "course", "subject"]
            for line in full_text.split("\n"):
                clean_line = line.strip()
                if any(kw in clean_line.lower() for kw in academic_keywords) or (len(clean_line) > 12 and any(char.isdigit() for char in clean_line)):
                    filtered_lines.append(clean_line)
            
            condensed_syllabus = "\n".join(filtered_lines)
            if len(condensed_syllabus) > 14000:
                condensed_syllabus = condensed_syllabus[:14000]
            
            st.markdown('🚀 Dispatching datasets directly to Core hardware arrays...')
            progress_bar.progress(50)
            raw_ai_output = extract_syllabus_with_ai(condensed_syllabus, study_hours, focus_level, skip_weekends, string_from, string_until)
            
            if "error_mode_active" in raw_ai_output:
                st.error("❌ Engine Pipeline Execution Refusal Code:")
                st.code(raw_ai_output["details"])
                st.stop()
            
            st.markdown('📊 Inflating matrix shorthands to layout configurations...')
            progress_bar.progress(75)
            mapped_tasks = [{"task_name": item.get("n", "Milestone Target"), "due_date": item.get("d", "2026-06-15")} for item in raw_ai_output.get("tasks", [])]
            mapped_plan = [
                {
                    "Status": False,
                    "Scheduled Date": item.get("d", "2026-06-15"),
                    "Time Slot": item.get("t", f"{string_from} - {string_until}"),  
                    "Focus Topic": item.get("f", "Core Topic Review"),
                    "Suggested Action": item.get("a", "Review assigned reading segments"),
                    "Hours Allocated": item.get("h", int(study_hours))
                } for item in raw_ai_output.get("study_plan", [])
            ]
            
            st.session_state["ai_data"] = {"tasks": mapped_tasks, "study_plan": mapped_plan}
            
            save_schedule_to_firebase(st.session_state["username_val"], mapped_tasks, mapped_plan)
            
            progress_bar.progress(100)
            st.rerun()

    # --- MAIN VIEWING STAGE ---
    if st.session_state["ai_data"] is not None:
        total_tasks = len(st.session_state["ai_data"]["tasks"])
        total_rows = len(st.session_state["ai_data"]["study_plan"])
        
        m_col1, m_col2, m_col3 = st.columns(3)
        m_col1.container(border=True).metric(label="Total Pages Sparsed", value=f"{st.session_state['page_count']} Pages")
        m_col2.container(border=True).metric(label="Total Generated Milestones", value=f"{total_rows} Actions")
        m_col3.container(border=True).metric(label="Active Target Profile", value=st.session_state["username_val"])
        
        st.markdown("<br>", unsafe_allow_html=True)
        t_col1, t_col2 = st.columns([1, 2], gap="medium")
        
        with t_col1:
            st.markdown("#### 📅 Calendar Targets")
            # ✨ FIXED: Changed use_container_width to modern width property
            st.dataframe(st.session_state["ai_data"]["tasks"], width="stretch")
            
        with t_col2:
            st.markdown("#### 🔄 Dynamic Interactive Roadmap Checklist")
            roadmap_df = pd.DataFrame(st.session_state["ai_data"]["study_plan"])
            
            total_items = len(roadmap_df)
            completed_items = roadmap_df["Status"].sum() if total_items > 0 else 0
            completion_percentage = int((completed_items / total_items) * 100) if total_items > 0 else 0
            st.markdown(f"<p style='font-size:0.85rem; color:#A0AEC0;'>Tracker Completion: {completed_items}/{total_items} Items Completed ({completion_percentage}%)</p>", unsafe_allow_html=True)
            st.progress(completed_items / total_items if total_items > 0 else 0.0)
            
            # ✨ FIXED: Changed use_container_width to modern width property
            edited_roadmap = st.data_editor(
                roadmap_df,
                width="stretch",
                disabled=["Scheduled Date", "Time Slot", "Focus Topic", "Suggested Action", "Hours Allocated"],
                hide_index=True,
                key="roadmap_editor"
            )
            
            if not edited_roadmap.equals(roadmap_df):
                st.session_state["ai_data"]["study_plan"] = edited_roadmap.to_dict(orient="records")
                save_schedule_to_firebase(st.session_state["username_val"], st.session_state["ai_data"]["tasks"], st.session_state["ai_data"]["study_plan"])
                st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                # ✨ FIXED: Changed use_container_width to modern width property
                st.download_button(label="📅 Sync with Calendar (.ics)", data=generate_ics_file(edited_roadmap), file_name=f"{st.session_state['username_val']}_schedule.ics", mime="text/calendar", width="stretch")
            with d_col2:
                # ✨ FIXED: Changed use_container_width to modern width property
                st.download_button(label="📊 Export Spreadsheet (.csv)", data=edited_roadmap.to_csv(index=False).encode('utf-8'), file_name=f"{st.session_state['username_val']}_checklist.csv", mime="text/csv", width="stretch")