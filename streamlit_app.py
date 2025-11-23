import streamlit as st
import os
import json
import requests
import tempfile
from openai import OpenAI
from pydub import AudioSegment
from io import BytesIO

# --- PAGE CONFIG ---
st.set_page_config(page_title="Auto SFX Studio", page_icon="🎬")

st.title("🎬 AI Sound Design Automator")
st.markdown("Upload a voiceover, and I will auto-detect silences, generate sound effects (ElevenLabs), and mix them in.")

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("API Keys")
    openai_key = st.text_input("OpenAI API Key", type="password")
    eleven_key = st.text_input("ElevenLabs API Key", type="password")
    
    st.header("Settings")
    silence_thresh = st.slider("Silence Detection (seconds)", 0.5, 3.0, 1.0)
    vol_ducking = st.slider("SFX Volume (dB)", -20, 0, -5)

# --- FUNCTIONS ---

def transcribe_and_map(client, audio_file):
    with st.status("Thinking: Transcribing & Mapping Silences...", expanded=True) as status:
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file, 
            response_format="verbose_json",
            timestamp_granularities=["word"] 
        )
        
        words = transcript.words
        sonic_map = ""
        last_end_time = 0.0
        
        # Calculate silences
        for word in words:
            start = word['start']
            gap = start - last_end_time
            if gap > silence_thresh:
                sonic_map += f"\n👉 [ ... {gap:.1f}s SILENCE ... ]\n"
            sonic_map += f"[{start:.2f}s] {word['word']} "
            last_end_time = word['end']
            
        status.update(label="✅ Transcription Complete", state="complete", expanded=False)
    return sonic_map

def design_sound_effects(client, sonic_map_str):
    with st.spinner("Thinking: Designing Soundscape..."):
        system_prompt = """
        You are a cinematic sound designer. Analyze the transcript timestamps and [SILENCE] markers.
        Return a JSON object with a list of 'effects'.
        Rules:
        1. Fill [SILENCE] gaps with context-appropriate sounds.
        2. Match actions in text (e.g., "I drank water" -> pouring water sfx).
        3. 'volume_adjustment': 0 is standard, -10 is background.
        
        Format: {"effects": [{"prompt": "wind", "timestamp": 2.5, "duration_seconds": 3.0, "volume_adjustment": -5}]}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Sonic Map:\n{sonic_map_str}"}
            ]
        )
        return json.loads(response.choices[0].message.content).get('effects', [])

def generate_sfx(api_key, prompt, duration):
    url = "https://api.elevenlabs.io/v1/sound-generation"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    data = {
        "text": prompt,
        "duration_seconds": min(max(duration, 0.5), 22.0),
        "prompt_influence": 0.4
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return BytesIO(response.content)
    except Exception as e:
        st.error(f"Failed to generate {prompt}: {e}")
        return None

# --- MAIN APP LOGIC ---

uploaded_file = st.file_uploader("Upload MP3/WAV Voiceover", type=["mp3", "wav"])

if uploaded_file and openai_key and eleven_key:
    client = OpenAI(api_key=openai_key)
    
    if st.button("🚀 Run Automation"):
        # 1. Analyze
        sonic_map = transcribe_and_map(client, uploaded_file)
        st.text_area("Sonic Map (Debug)", sonic_map, height=150)
        
        # 2. Plan
        sfx_plan = design_sound_effects(client, sonic_map)
        st.success(f"Plan created: {len(sfx_plan)} effects detected.")
        st.json(sfx_plan, expanded=False)
        
        # 3. Generate & Assemble
        uploaded_file.seek(0) # Reset pointer
        base_audio = AudioSegment.from_file(uploaded_file)
        sfx_layer = AudioSegment.silent(duration=len(base_audio) + 4000)
        
        progress_bar = st.progress(0)
        
        for i, effect in enumerate(sfx_plan):
            # Update Progress
            progress_bar.progress((i + 1) / len(sfx_plan))
            
            # Generate
            sfx_data = generate_sfx(eleven_key, effect['prompt'], effect.get('duration_seconds', 2.0))
            
            if sfx_data:
                sfx_clip = AudioSegment.from_file(sfx_data)
                
                # Apply Volume (Script logic + User global setting)
                vol_adj = effect.get('volume_adjustment', 0) + vol_ducking
                sfx_clip = sfx_clip + vol_adj
                
                # Overlay
                timestamp_ms = int(effect['timestamp'] * 1000)
                sfx_layer = sfx_layer.overlay(sfx_clip, position=timestamp_ms)
        
        # 4. Final Output
        final_mix = sfx_layer.overlay(base_audio, position=0)
        
        # Buffer for download
        buffer_mix = BytesIO()
        final_mix.export(buffer_mix, format="mp3")
        
        st.header("🎧 Results")
        st.audio(buffer_mix, format='audio/mp3')
        
        st.download_button(
            label="Download Final Mix",
            data=buffer_mix.getvalue(),
            file_name="auto_sfx_mix.mp3",
            mime="audio/mp3"
        )

elif uploaded_file:
    st.warning("Please enter your API keys in the sidebar to proceed.")