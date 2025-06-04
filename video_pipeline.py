import os
import re
import json
from pathlib import Path
from typing import Optional, Callable, Dict, Any
import hashlib
# Note: google.generativeai and jsonschema are imported conditionally in generate_gemini_script
# Note: kokoro-onnx and wave are imported conditionally in generate_tts_kokoro

# --- Global Variables & Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

expected_schema = {
    "type": "object",
    "properties": {
        "new_video_title": {"type": "string"},
        "script": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["new_video_title", "script", "keywords"]
}

BASE_INPUT_DIR = Path("input")
TEXT_SOURCES_DIR = BASE_INPUT_DIR / "text_sources"
LINK_SOURCES_DIR = BASE_INPUT_DIR / "link_sources"
CUSTOM_PROMPT_SOURCES_DIR = BASE_INPUT_DIR / "custom_prompt_sources"

BASE_LOGS_DIR = Path("logs")
USED_TEXT_LOG = BASE_LOGS_DIR / "used_text_sources.json"
USED_LINK_LOG = BASE_LOGS_DIR / "used_link_sources.json"

# --- Directory Ensure Function ---
def ensure_dir_exists(directory_path: str) -> None:
    Path(directory_path).mkdir(parents=True, exist_ok=True)

ensure_dir_exists(str(TEXT_SOURCES_DIR))
ensure_dir_exists(str(LINK_SOURCES_DIR))
ensure_dir_exists(str(CUSTOM_PROMPT_SOURCES_DIR))
ensure_dir_exists(str(BASE_LOGS_DIR))
ensure_dir_exists(str(BASE_INPUT_DIR))
ensure_dir_exists("workspace")

# --- Stub Functions & Helpers ---
def correct_text_spelling(text: str) -> str:
    return text

def normalize_text(script_text: str) -> str:
    return script_text

def check_artifact_exists(workspace_dir: Path, artifact_name: str) -> bool:
    return (workspace_dir / artifact_name).exists()

# --- Prompt Selection Functions ---
def get_default_script_prompt(text_content: str) -> str:
    prompt = f"""You are an expert content creator.
Here's the transcript: {text_content}
Please return a JSON object with "new_video_title", "script", and "keywords".
Example JSON:
{{
    "new_video_title": "Your catchy video title",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "script": "The generated content here"
}}
"""
    return prompt

def get_bible_story_script_prompt(text_content: str) -> str:
    # TODO: Define a specialized prompt for Bible stories
    prompt = f"""Create a script for a Bible story based on: {text_content}.
Return JSON: {{"new_video_title": "...", "keywords": [...], "script": "..."}}
"""
    return prompt

# --- Gemini Script Generation (Aggressively Stubbed) ---
def generate_gemini_script(source_text: str, prompt_function: callable) -> Optional[Dict[str, Any]]:
    global GEMINI_API_KEY, expected_schema
    if not GEMINI_API_KEY or GEMINI_API_KEY == "":
        print("[INFO] No GEMINI_API_KEY. generate_gemini_script will return DUMMY DATA.")
        return {
            "new_video_title": "Dummy Title - API Key Missing/Empty",
            "script": normalize_text(correct_text_spelling(f"Dummy script for: {source_text[:100]}")),
            "keywords": ["dummy", "test", "api_key_missing"]
        }
    try:
        import google.generativeai as genai
        from jsonschema import validate, ValidationError
        genai.configure(api_key=GEMINI_API_KEY)
    except ImportError as e:
        print(f"ERROR: Failed to import google.generativeai or jsonschema: {e}")
        return { "new_video_title": "Dummy Title - Import Error", "script": f"Dummy script for: {source_text[:100]}", "keywords": ["dummy", "import_error"]}
    except Exception as e:
        print(f"ERROR: Failed to configure Gemini API: {e}")
        return { "new_video_title": "Dummy Title - API Config Error", "script": f"Dummy script for: {source_text[:100]}", "keywords": ["dummy", "api_config_error"]}
    prompt_text = prompt_function(source_text)
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt_text)
    except Exception as e:
        print(f"ERROR: Gemini API call failed: {e}"); return None
    content = response.text
    json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
    if json_match: json_str = json_match.group(1)
    else:
        first_brace = content.find('{'); last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = content[first_brace:last_brace+1]
        else: print(f"ERROR: Could not find JSON in Gemini response. Raw: {content[:200]}..."); return None
    try: result = json.loads(json_str)
    except json.JSONDecodeError as e: print(f"ERROR: JSON decoding failed: {e}. String: {json_str[:200]}..."); return None
    try: validate(instance=result, schema=expected_schema)
    except ValidationError as e: print(f"ERROR: JSON validation failed: {e}"); return None
    new_video_title = result.get("new_video_title", "Untitled Video")
    script_text_content = result.get("script", "")
    keywords = result.get("keywords", [])
    script_text_content = normalize_text(script_text_content)
    script_text_content = script_text_content.replace("*", "")
    script_text_content = re.sub(r'\([^)]*\)', '', script_text_content).strip()
    print("[INFO] Successfully generated and processed video script.")
    return { "new_video_title": new_video_title, "script": script_text_content, "keywords": keywords }

# --- Text Source Processing ---
def process_text_source(text_file_path: Path, workspace_dir: Path, prompt_function_selector: callable) -> bool:
    print(f"[DEBUG process_text_source] Attempting to process file: {text_file_path}")
    try:
        with open(text_file_path, 'r', encoding='utf-8') as f:
            raw_content = f.read()
            print(f"[DEBUG process_text_source] Raw content of {text_file_path.name}: >>>{raw_content}<<<")
            data = json.loads(raw_content)
    except Exception as e:
        print(f"ERROR [process_text_source]: Could not read or parse JSON from {text_file_path}: {e}"); return False
    print(f"[DEBUG process_text_source] Parsed data type: {type(data)} for file {text_file_path.name}")
    if not isinstance(data, list):
        print(f"ERROR [process_text_source]: Data in {text_file_path.name} is not a list. Type: {type(data)}"); return False
    if not data:
        print(f"ERROR [process_text_source]: Data list in {text_file_path.name} is empty."); return False
    print(f"[DEBUG process_text_source] First element type: {type(data[0])} for file {text_file_path.name}")
    if not isinstance(data[0], str):
        print(f"ERROR [process_text_source]: First element in {text_file_path.name} is not a string. Type: {type(data[0])}"); return False
    if not data[0].strip():
         print(f"ERROR [process_text_source]: First string in {text_file_path.name} is empty or whitespace."); return False
    print(f"[DEBUG process_text_source] Validation PASSED for {text_file_path.name}.")
    first_paragraph = data[0]
    print(f"[INFO] Original first paragraph from {text_file_path.name}: \"{first_paragraph[:80]}...\"")
    corrected_paragraph = correct_text_spelling(first_paragraph)
    print(f"[INFO] Paragraph after (stubbed) spelling correction: \"{corrected_paragraph[:80]}...\"")
    generated_script_data = generate_gemini_script(corrected_paragraph, prompt_function_selector)
    if generated_script_data:
        ensure_dir_exists(str(workspace_dir))
        output_path = workspace_dir / "video_script.json"
        try:
            with open(output_path, 'w', encoding='utf-8') as f: json.dump(generated_script_data, f, indent=4)
            print(f"[INFO] Video script saved to {output_path}"); return True
        except Exception as e:
            print(f"ERROR: Could not save script to {output_path}: {e}"); return False
    else:
        print(f"ERROR: Failed to generate script for {text_file_path.name}"); return False

# --- TTS Generation (Kokoro-ONNX) ---
def generate_tts_kokoro(script_text: str, output_wav_path: Path) -> bool:
    try:
        import kokoro_onnx
        print("[INFO] kokoro-onnx library imported successfully.")
        try:
            print(f"[INFO] Generating TTS (simulated by kokoro-onnx stub) for text: \"{script_text[:80]}...\"")
            dummy_placeholder_path = output_wav_path.with_suffix(".dummy_tts.txt") # Suffix for text dummy
            with open(dummy_placeholder_path, "w", encoding="utf-8") as f:
                f.write(f"Dummy TTS (kokoro-onnx imported but call is stubbed) for: {script_text[:100]}...")
            try: # Still create a silent WAV as the contract is for a WAV file
                import wave
                with wave.open(str(output_wav_path), 'w') as wf:
                    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
                    wf.writeframes(b'\x00\x00' * 100)
                print(f"[INFO] Created tiny dummy WAV at {output_wav_path} (kokoro-onnx simulation).")
            except Exception as e_wave_sim:
                print(f"ERROR: Could not create tiny dummy WAV during kokoro-onnx simulation: {e_wave_sim}")
            print(f"[INFO] TTS audio (simulated by kokoro-onnx stub) placeholder saved near {output_wav_path}"); return True
        except Exception as e_tts:
            print(f"ERROR: TTS generation with kokoro-onnx (simulated part) failed: {e_tts}"); return False
    except ImportError:
        print("ERROR: kokoro-onnx library not found. Creating DUMMY silent voiceover.wav.")
        try:
            import wave
            with wave.open(str(output_wav_path), 'w') as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
                wf.writeframes(b'\x00\x00' * int(22050 * 0.1))
            print(f"[INFO] Created dummy silent WAV file at {output_wav_path}"); return True
        except Exception as e_wave:
            print(f"ERROR: Could not create dummy WAV file: {e_wave}"); return False
    except Exception as e_import_other:
        print(f"ERROR: Unexpected error during kokoro-onnx import attempts: {e_import_other}"); return False

# --- Local Transcription (Stubbed) ---
def transcribe_locally(audio_path: Path, output_detailed_transcript_path: Path) -> bool:
    # Always use dummy data for this subtask, regardless of GEMINI_API_KEY
    print(f"[INFO] Simulating local transcription for {audio_path}.")
    dummy_detailed_content = [
        '0.0 5.54  This is a dummy transcript. [{"word": " This", "start": 0.0, "end": 0.5, "probability": 0.9}, {"word": " is", "start": 0.5, "end": 0.8, "probability": 0.9}, {"word": " a", "start": 0.8, "end": 1.0, "probability": 0.9}, {"word": " dummy", "start": 1.0, "end": 1.5, "probability": 0.9}, {"word": " transcript.", "start": 1.5, "end": 2.5, "probability": 0.9}]',
        '6.34 12.68  Second segment for testing. [{"word": " Second", "start": 6.34, "end": 7.0, "probability": 0.9}, {"word": " segment", "start": 7.0, "end": 7.5, "probability": 0.9}, {"word": " for", "start": 7.5, "end": 7.8, "probability": 0.9}, {"word": " testing.", "start": 7.8, "end": 8.5, "probability": 0.9}]'
    ]
    try:
        with open(output_detailed_transcript_path, 'w', encoding='utf-8') as f:
            for line in dummy_detailed_content:
                f.write(line + '\n')
        print(f"[INFO] Dummy detailed transcript saved to {output_detailed_transcript_path}")
        return True
    except Exception as e:
        print(f"ERROR: Could not write dummy detailed transcript: {e}")
        return False

# --- Orchestration Steps ---
def run_tts_step(workspace_dir: Path) -> bool:
    script_file_path = workspace_dir / "video_script.json"
    if not script_file_path.exists():
        print(f"ERROR: Script file not found at {script_file_path} for TTS."); return False
    try:
        with open(script_file_path, 'r', encoding='utf-8') as f: script_data = json.load(f)
        script_text_content = script_data.get("script")
        if not script_text_content or not isinstance(script_text_content, str):
            print(f"ERROR: No valid 'script' text in {script_file_path}."); return False
    except Exception as e:
        print(f"ERROR: Could not read/parse script from {script_file_path}: {e}"); return False
    output_wav_path = workspace_dir / "voiceover.wav"
    print(f"[INFO] Starting TTS step for script: \"{script_text_content[:80]}...\"")
    success = generate_tts_kokoro(script_text_content, output_wav_path)
    if success: print(f"[INFO] TTS step completed. Output: {output_wav_path}")
    else: print(f"ERROR: TTS generation failed for {workspace_dir}")
    return success

def run_voiceover_transcription_step(workspace_dir: Path) -> bool:
    audio_path = workspace_dir / "voiceover.wav"
    if not audio_path.exists():
        print(f"ERROR: Voiceover audio file not found at {audio_path}. Cannot transcribe.")
        return False
    detailed_transcript_path = workspace_dir / "voiceover_transcription_detailed.txt"
    print(f"[INFO] Starting voiceover transcription for {audio_path}...")
    success = transcribe_locally(audio_path, detailed_transcript_path)
    if success:
        print(f"[INFO] Voiceover transcription step completed. Output: {detailed_transcript_path}")
    else:
        print(f"ERROR: Voiceover transcription failed for {workspace_dir}")
    return success

# --- File/Path Helper Functions ---
def get_source_id(source_path: str) -> str:
    path_obj = Path(source_path); filename_stem = path_obj.stem
    return f"{filename_stem}_{hashlib.md5(str(path_obj.resolve()).encode()).hexdigest()[:6]}"

def get_workspace_path(base_workspace_dir: str, source_id: str) -> Path:
    workspace_path = Path(base_workspace_dir) / source_id
    ensure_dir_exists(str(workspace_path)); return workspace_path

def get_next_source(source_dir_str: str, used_log_file_str: str) -> Optional[Path]:
    source_path_obj = Path(source_dir_str); log_path_obj = Path(used_log_file_str)
    if not source_path_obj.is_dir(): print(f"ERROR: Source dir {source_dir_str} not found."); return None
    used_files = []
    if log_path_obj.exists():
        try:
            with open(log_path_obj, 'r', encoding='utf-8') as f: content = f.read().strip()
            if content: used_files = json.loads(content)
            if not isinstance(used_files, list): used_files = []
        except (json.JSONDecodeError, Exception) as e: print(f"WARN: Error reading {log_path_obj}: {e}. Treating as empty."); used_files = []
    for file_p in sorted(source_path_obj.iterdir()):
        if file_p.is_file() and not file_p.name.startswith('.') and file_p.name not in used_files: return file_p
    return None

def mark_source_as_used(source_file_path: Path, used_log_file_str: str) -> None:
    log_path_obj = Path(used_log_file_str); used_files = []
    if log_path_obj.exists() and log_path_obj.stat().st_size > 0:
        try:
            with open(log_path_obj, 'r', encoding='utf-8') as f: used_files = json.load(f)
            if not isinstance(used_files, list): used_files = []
        except (json.JSONDecodeError, Exception) as e: print(f"WARN: Error reading {log_path_obj} for mark_used: {e}. Init anew."); used_files = []
    if source_file_path.name not in used_files:
        used_files.append(source_file_path.name)
        try:
            with open(log_path_obj, 'w', encoding='utf-8') as f: json.dump(used_files, f, indent=4)
        except Exception as e: print(f"ERROR: Could not write to {log_path_obj}: {e}")

# --- Main Workflow ---
def main_workflow(choices: Optional[list[str]] = None):
    print("[Workflow] Starting main workflow...")
    interactive_mode = choices is None; choice_iterator = iter(choices) if choices else None
    while True:
        choice = ''
        if interactive_mode:
            try: choice = input("\nChoose source type (1:Text, 2:Link, 3:Exit): ")
            except EOFError: print("EOFError. Exiting."); break
        else:
            try: choice = next(choice_iterator) # type: ignore
            except StopIteration: print("[Workflow] Finished all provided choices."); break

        print(f"\n[Workflow] Processing choice: {choice}")
        if choice == '1':
            print("\n[Workflow] Processing Text Files...")
            while True:
                next_source_file = get_next_source(str(TEXT_SOURCES_DIR), str(USED_TEXT_LOG))
                if not next_source_file: print("[Workflow] All text sources processed."); break

                source_id = get_source_id(str(next_source_file))
                workspace_dir = get_workspace_path("workspace", source_id)
                print(f"[Workflow] Processing source: {next_source_file.name} in workspace: {workspace_dir}")

                source_fully_processed = False # Renamed for clarity
                script_generation_ok = False
                tts_ok = False
                transcription_ok = False

                # --- Script Generation Stage ---
                script_artifact_name = "video_script.json"
                if check_artifact_exists(workspace_dir, script_artifact_name):
                    print(f"[INFO] '{script_artifact_name}' already exists. Skipping script generation.")
                    script_generation_ok = True
                else:
                    print(f"[INFO] '{script_artifact_name}' not found. Starting script generation...")
                    script_generation_ok = process_text_source(next_source_file, workspace_dir, get_default_script_prompt)

                # --- TTS Generation Stage ---
                if script_generation_ok:
                    print(f"[INFO] Script stage completed for {workspace_dir}")
                    tts_artifact_name = "voiceover.wav"
                    if check_artifact_exists(workspace_dir, tts_artifact_name):
                        print(f"[INFO] '{tts_artifact_name}' already exists. Skipping TTS generation.")
                        tts_ok = True
                    else:
                        print(f"[INFO] '{tts_artifact_name}' not found. Starting TTS generation...")
                        tts_ok = run_tts_step(workspace_dir)
                else:
                    print(f"ERROR: Script generation failed for {next_source_file.name}, skipping subsequent steps.")

                # --- Voiceover Transcription Stage ---
                if tts_ok: # Only proceed if TTS was successful (or artifact existed)
                    print(f"[INFO] TTS stage completed for {workspace_dir}")
                    transcription_artifact_name = "voiceover_transcription_detailed.txt"
                    if check_artifact_exists(workspace_dir, transcription_artifact_name):
                        print(f"[INFO] '{transcription_artifact_name}' already exists. Skipping voiceover transcription.")
                        transcription_ok = True
                    else:
                        print(f"[INFO] '{transcription_artifact_name}' not found. Starting voiceover transcription...")
                        transcription_ok = run_voiceover_transcription_step(workspace_dir)
                else:
                    if script_generation_ok: # Only print TTS error if script part was okay
                         print(f"ERROR: TTS failed for {next_source_file.name}, skipping transcription.")

                # --- Final Status Check & Mark Used ---
                if script_generation_ok and tts_ok and transcription_ok:
                    source_fully_processed = True # Update this if more steps are added

                if source_fully_processed:
                    if next_source_file.parent.name == TEXT_SOURCES_DIR.name:
                         mark_source_as_used(next_source_file, str(USED_TEXT_LOG))
                         print(f"[INFO] Successfully processed (up to transcription) and marked {next_source_file.name} as used.")
                else:
                     print(f"ERROR: Full processing up to transcription failed for {next_source_file.name}. Not marked as used.")
        elif choice == '2':
            print("\n[Workflow] Processing Link Files (stub)...")
            while True:
                next_link_file = get_next_source(str(LINK_SOURCES_DIR), str(USED_LINK_LOG))
                if not next_link_file: print("[Workflow] All link sources processed."); break
                print(f"[Workflow] Stub processing link: {next_link_file.name}")
                mark_source_as_used(next_link_file, str(USED_LINK_LOG))
        elif choice == '3': print("[Workflow] Exiting."); break
        else: print("[Workflow] Invalid choice.")

if __name__ == '__main__':
    print("[Main] Script execution started.")
    # Clear logs for a clean test run
    if Path(USED_TEXT_LOG).exists(): Path(USED_TEXT_LOG).unlink()
    if Path(USED_LINK_LOG).exists(): Path(USED_LINK_LOG).unlink()

    # Ensure dummy input files are created for testing
    ensure_dir_exists(str(TEXT_SOURCES_DIR))
    text1_path = TEXT_SOURCES_DIR / "text1.json"
    text2_path = TEXT_SOURCES_DIR / "text2.json"
    if not text1_path.exists():
        with open(text1_path, "w", encoding='utf-8') as f:
            json.dump(["This is text1. It has one paragraph."], f, indent=4)
    if not text2_path.exists():
        with open(text2_path, "w", encoding='utf-8') as f:
            json.dump(["This is text2, also one paragraph for simplicity."], f, indent=4)

    ensure_dir_exists(str(LINK_SOURCES_DIR))
    link1_path = LINK_SOURCES_DIR / "links1.txt"
    if not link1_path.exists():
        with open(link1_path, "w", encoding='utf-8') as f:
            f.write("http://example.com/link1\n")

    test_choices = ['1', '1', '1', '2', '3'] # Attempt to process up to 2 text files, 1 link file
    main_workflow(choices=test_choices)
    print("[Main] Script execution finished.")
