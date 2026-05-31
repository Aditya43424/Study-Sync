import streamlit as st
import time
import requests
from streamlit_lottie import st_lottie
import streamlit.components.v1 as components

# Set up page configurations
st.set_page_config(page_title="Study Sync", page_icon="📅", layout="wide")

# Helper function to load Lottie animations from the web
def load_lottie_url(url: str):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

# Loading the processing animation
lottie_processing = load_lottie_url("https://assets8.lottiefiles.com/packages/lf20_vnikbe9e.json")

# 🎨 Custom CSS for the Dark/Neon Minimalist theme
st.html("""
<style>
    /* Gradient Typography for the Logo Header - Size optimized to 3.6rem */
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
    
    /* Neon glow effect for custom data cards */
    [data-testid="stMetricSimpleValue"] {
        font-size: 1.8rem !important;
        color: #00C6FF !important;
        font-weight: 700;
    }
    
    /* Smooth button overrides with glow behavior */
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
    
    /* Clean Success Card Animation */
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(12px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
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
    
    .success-text-container {
        display: flex;
        flex-direction: column;
    }
    
    .success-title {
        color: #FFFFFF !important;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        margin: 0 0 4px 0 !important;
        padding: 0 !important;
    }
    
    .success-subtitle {
        color: #A0AEC0 !important;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 0.9rem !important;
        margin: 0 !important;
        padding: 0 !important;
    }
</style>
""")

# --- APP LAYOUT ---

# Header section contains only the clean text title without an icon
st.markdown('<p class="main-title">Study Sync</p>', unsafe_allow_html=True)

st.markdown("---")

# Main Content Grid split into inputs and file drops
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
            
            # Clean Processing Stage
            processing_box = st.empty()
            with processing_box.container():
                st.markdown("""
                    <div style="padding: 10px 0px; margin-bottom: 10px;">
                        <p style="color: #A0AEC0; font-size: 0.95rem; font-family: system-ui; letter-spacing: 0.5px;">
                            Parsing curriculum structure and allocating optimal study blocks...
                        </p>
                    </div>
                """, unsafe_allow_html=True)
                
                if lottie_processing:
                    st_lottie(lottie_processing, height=140, key="proc_anim")
                time.sleep(2.2) 
                
            processing_box.empty() 
            
            # Clean & Minimalist Success Banner Display
            st.html("""
                <div class="clean-success-card">
                    <div class="success-icon">✓</div>
                    <div class="success-text-container">
                        <h4 class="success-title">Timeline Optimized Successfully</h4>
                        <p class="success-subtitle">Your personalized academic calendar has been generated based on your configuration rules.</p>
                    </div>
                </div>
            """)
            
            # Render Metrics Layout with renamed Header
            st.markdown("<p style='font-size: 1.1rem; font-weight: 600; color: #FFFFFF; margin-bottom: 15px;'>Summary</p>", unsafe_allow_html=True)
            m_col1, m_col2, m_col3 = st.columns(3)
            
            with m_col1:
                with st.container(border=True):
                    st.metric(label="Detected Tasks", value="14 Assignments")
            with m_col2:
                with st.container(border=True):
                    st.metric(label="Calculated Study Blocks", value="42 Slots")
            with m_col3:
                with st.container(border=True):
                    st.metric(label="Preparation Buffer", value="88%", delta="Safe")