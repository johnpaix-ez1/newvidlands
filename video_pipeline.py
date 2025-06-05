import os
import sys # Added for sys.exit()
import json
import pathlib
import logging
import asyncio
import time
import re
import uuid
import urllib.parse
import io
import subprocess
import shutil # For step_15
import random # For step_10 animations
import math # For step_10 calculations and dummy TTS in step_04
from moviepy.editor import VideoFileClip


# --- Attempt to import third-party libraries, with fallbacks ---
try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
except ImportError:
    genai = None
    HarmCategory = None
    HarmBlockThreshold = None
    print("WARNING: Gemini library (google.generativeai) not found. Script generation (Step 03) will use placeholders or be skipped.")

try:
    import jsonschema
except ImportError:
    jsonschema = None
    print("WARNING: jsonschema library not found. JSON validation (e.g., in Step 03) will be skipped.")

try:
    from kokoro_onnx import Kokoro
    import soundfile as sf
    KOKORO_AVAILABLE = True
    print("INFO: Kokoro-ONNX and soundfile imported successfully for TTS.")
except ImportError:
    KOKORO_AVAILABLE = False
    TTS = None  # Define TTS as None if import fails
    sf = None
    print("WARNING: kokoro_onnx or soundfile library not found. Kokoro TTS (Step 04) will use a dummy WAV file.")

try:
    import whisper # from openai_whisper
except ImportError:
    whisper = None
    print("WARNING: OpenAI Whisper library not found. Transcription (Step 05) will use a dummy transcript.")

try:
    from spellchecker import SpellChecker
except ImportError:
    SpellChecker = None
    print("WARNING: pyspellchecker library not found. Spell correction (Step 06) will be skipped.")

try:
    from groq import Groq
except ImportError:
    Groq = None
    print("WARNING: Groq library not found. Image prompt generation (Step 08) will use dummy prompts.")

try:
    import websocket # For ComfyUI
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    websocket = None
    Image = None
    ImageDraw = None
    ImageFont = None
    print("WARNING: websocket-client or Pillow not found. ComfyUI image generation (Step 09) will use dummy images.")

try:
    import yt_dlp
except ImportError:
    yt_dlp = None
    print("WARNING: yt-dlp library not found. Video link processing (Step 02) will fail if attempted.")

# MoviePy imports are grouped and checked in the steps that use them directly
moviepy_ok = False
ImageClip_cls, CompositeVideoClip_cls, VideoFileClip_cls, AudioFileClip_cls = None, None, None, None
TextClip_cls, ColorClip_cls = None, None
concatenate_videoclips_func, concatenate_audioclips_func, CompositeAudioClip_cls = None, None, None
moviepy_vfx_all = None
try:
    from moviepy.editor import (VideoFileClip, ImageClip, AudioFileClip, concatenate_videoclips,
                                TextClip, CompositeVideoClip, concatenate_audioclips, ColorClip)
    import moviepy.video.fx.all as vfx
    from moviepy.audio.AudioClip import CompositeAudioClip
    ImageClip_cls = ImageClip
    CompositeVideoClip_cls = CompositeVideoClip
    VideoFileClip_cls = VideoFileClip
    AudioFileClip_cls = AudioFileClip
    TextClip_cls = TextClip
    ColorClip_cls = ColorClip
    concatenate_videoclips_func = concatenate_videoclips
    concatenate_audioclips_func = concatenate_audioclips
    CompositeAudioClip_cls = CompositeAudioClip
    moviepy_vfx_all = vfx # Store the imported vfx module
    moviepy_ok = True
    print("INFO: MoviePy library and components loaded successfully.")
except ImportError:
    print("WARNING: MoviePy library or its components not found. Video processing steps (animation, assembly, captioning) will use fallbacks or fail.")

# --- Load .env and Kokoro TTS model/voices paths ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("WARNING: python-dotenv library not found. .env file will not be loaded.")
except NameError: # if load_dotenv itself is not defined due to failed import
    pass

# Add these lines immediately after load_dotenv()
KOKORO_MODEL_FILE_PATH = os.getenv("KOKORO_MODEL_FILE_PATH")
KOKORO_VOICES_FILE_PATH = os.getenv("KOKORO_VOICES_FILE_PATH")

try:
    from termcolor import cprint
except ImportError:
    cprint = lambda text, color=None, on_color=None, attrs=None: print(text) # Basic print fallback
    print("WARNING: termcolor library not found. Console output will not be colored.")

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global constants for paths
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
INPUT_DIR = SCRIPT_DIR / "input"
WORKSPACE_DIR = SCRIPT_DIR / "workspace"
FINAL_VIDEO_DIR = SCRIPT_DIR / "final_videos"
LOG_DIR = SCRIPT_DIR / "logs"
ASSETS_DIR = SCRIPT_DIR / "assets"

# API Keys & Configuration (loaded from .env or environment, with defaults)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")
COMFYUI_SERVER_ADDRESS = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188")
COMFYUI_WORKFLOW_FILE = os.getenv("COMFYUI_WORKFLOW_FILE", str(ASSETS_DIR / "default_comfyui_workflow.json"))
ENDSCREEN_VIDEO_FILE = os.getenv("ENDSCREEN_VIDEO_FILE", str(ASSETS_DIR / "default_endscreen.mp4"))


# Helper functions (ensure these are defined before use in steps)
# ... (ensure_dir_exists, get_source_id, get_workspace_path, is_step_complete, mark_step_complete, load_json_config, save_json_output, normalize_text are defined as before) ...
def ensure_dir_exists(path: pathlib.Path):
    """Creates a directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def get_source_id(source_path: str) -> str:
    """Creates a unique ID for each input source."""
    if urllib.parse.urlparse(source_path).scheme in ['http', 'https']:
        parsed_url = urllib.parse.urlparse(source_path)
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if parsed_url.query:
            source_name = "_".join(path_parts) + "_" + parsed_url.query if path_parts else "url_" + parsed_url.query
        else:
            source_name = "_".join(path_parts) if path_parts else parsed_url.netloc
        source_name = re.sub(r'[^a-zA-Z0-9_-]', '_', source_name)[:50]
    else:
        source_name = pathlib.Path(source_path).stem
    return f"{source_name}_{uuid.uuid4().hex[:8]}"

def get_workspace_path(source_id: str) -> pathlib.Path:
    """Gets the dedicated workspace for a source."""
    return WORKSPACE_DIR / source_id

# --- Expected Schema for Step 03 (Gemini Script Generation) ---
expected_schema = {
    "type": "object",
    "properties": {
        "new_video_title": {"type": "string"},
        "script": {"type": "string"}, # This will be mapped to "script_content" in output JSON
        "keywords": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["new_video_title", "script", "keywords"]
}

# --- JSON Validation Helper ---
def validate_json_structure(data, schema_to_validate_against): # Renamed schema to schema_to_validate_against
    """Validates a JSON data object against a given jsonschema."""
    if not jsonschema: # Check if jsonschema library is available
        logger.warning("jsonschema library not available, skipping schema validation.")
        # Basic check for required keys if jsonschema is not available
        if not all(key in data for key in schema_to_validate_against.get("required", [])):
            logger.error(f"Basic validation failed: Missing one or more required keys: {schema_to_validate_against.get('required', [])}")
            return False
        return True # Passed basic check

    try:
        jsonschema.validate(instance=data, schema=schema_to_validate_against)
        logger.info("JSON structure validation successful.")
        return True
    except jsonschema.exceptions.ValidationError as e:
        logger.error(f"JSON structure validation error: {e.message}") # Using e.message for a cleaner error
        return False
    except Exception as e_val: # Catch other potential errors during validation
        logger.error(f"An unexpected error occurred during JSON validation: {e_val}")
        return False

def is_step_complete(workspace_path: pathlib.Path, artifact_name: str) -> bool:
    """Checks if the .complete marker file for an artifact exists."""
    marker_file = workspace_path / f"{artifact_name}.complete"
    return marker_file.exists()

def mark_step_complete(workspace_path: pathlib.Path, artifact_name: str):
    """Creates a .complete marker file for an artifact."""
    ensure_dir_exists(workspace_path)
    (workspace_path / f"{artifact_name}.complete").touch()
    logger.info(f"Marked step as complete by creating: {workspace_path / artifact_name}.complete")

def load_json_config(file_path: pathlib.Path) -> dict | list | None: # Can be list for some inputs
    """Loads a JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"JSON file not found: {file_path}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from file: {file_path}")
        return None

def save_json_output(file_path: pathlib.Path, data): # data can be dict or list
    """Saves data to a JSON file."""
    ensure_dir_exists(file_path.parent)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    logger.info(f"Saved JSON output to: {file_path}")

def normalize_text(text: str) -> str:
    """Basic text normalization: remove asterisks, multiple spaces."""
    text = text.replace("*", "")
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- Initialize base directories ---
ensure_dir_exists(INPUT_DIR)
ensure_dir_exists(WORKSPACE_DIR)
ensure_dir_exists(FINAL_VIDEO_DIR)
ensure_dir_exists(LOG_DIR)
ensure_dir_exists(ASSETS_DIR)
ensure_dir_exists(ASSETS_DIR / "fonts")
ensure_dir_exists(ASSETS_DIR / "bgsound")

logger.info(f"Input directory: {INPUT_DIR}")
logger.info(f"Workspace directory: {WORKSPACE_DIR}")
logger.info(f"Final video directory: {FINAL_VIDEO_DIR}")
logger.info(f"Log directory: {LOG_DIR}")
logger.info(f"Assets directory: {ASSETS_DIR}")


# --- Pipeline Step Implementations ---
# (step_01 to step_09 as previously implemented and refined)
# ... (step_01_process_text_input) ...
# ... (step_02_process_video_link_input) ...
# ... (step_03_generate_gemini_script) ...
# ... (step_04_generate_tts_kokoro) ...
# ... (step_05_transcribe_audio_local_whisper) ...
# ... (step_06_correct_spelling) ...
# ... (step_07_parse_transcript_for_image_segments and its helper _extract_transcript_segments_image_vid) ...
# ... (step_08_generate_image_prompts_groq and its helpers GROQ_EXPECTED_SCHEMA_ITEM, _validate_groq_item_structure, _generate_image_prompts_batch_groq_helper) ...
# ... (step_09_generate_images_comfyui and its helpers _comfyui_load_workflow, _comfyui_queue_prompt, _comfyui_get_image_data, _comfyui_get_history, _comfyui_fetch_images_from_history_ws, _create_dummy_comfyui_images_and_manifest) ...

# --- Placeholder Pipeline Step Implementations (01-11) ---

def step_01_process_text_input(input_text_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_01_process_text_input with input: {input_text_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    output_artifact_name = "processed_text.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    save_json_output(output_path, {"status": "dummy output from placeholder step_01", "input_received": input_text_path_str, "processed_content": "Placeholder processed text."})
    mark_step_complete(workspace_path, "processed_text")
    logger.info(f" step_01_process_text_input completed. Output: {str(output_path)}")
    return str(output_path)

def step_02_process_video_link_input(video_url_str: str, workspace_path: pathlib.Path, cookies_file_path: str | None = None) -> str | None:
    logger.info(f" Called step_02_process_video_link_input with URL: {video_url_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not yt_dlp:
        logger.warning(" yt-dlp library not found. Step 02 cannot process video links.")
    output_artifact_name = "downloaded_video_info.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    save_json_output(output_path, {"status": "dummy output from placeholder step_02", "video_url": video_url_str, "comment": "yt-dlp missing or actual download skipped"})
    mark_step_complete(workspace_path, "downloaded_video_info")
    logger.info(f" step_02_process_video_link_input completed. Output: {str(output_path)}")
    return str(output_path)

def step_03_generate_gemini_script(processed_text_path_str: str, workspace_path: pathlib.Path, script_instructions: str | None = None) -> str | None:
    logger.info(f"Starting Step 03: Generate Gemini Script from: {processed_text_path_str}")
    output_artifact_name = "generated_script_gemini.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    # Fallback dummy content generation function
    def _save_dummy_script(reason: str, error_details: str = ""):
        dummy_content = {
            "title": f"Dummy Title ({reason})",
            "keywords": ["dummy", "placeholder", "error"],
            "script_content": f"This is a dummy script. Reason: {reason}. Details: {error_details}"
        }
        save_json_output(output_path, dummy_content)
        mark_step_complete(workspace_path, "generated_script_gemini")
        logger.warning(f"Step 03: Saved dummy script to {output_path} due to: {reason}. Details: {error_details}")
        return str(output_path)

    if not genai or not HarmCategory or not HarmBlockThreshold: # Check if the genai library and its types were imported
        return _save_dummy_script("Gemini SDK not available", "google.generativeai library or its components failed to import.")

    processed_text_data = load_json_config(pathlib.Path(processed_text_path_str))
    if not processed_text_data or "processed_content" not in processed_text_data:
        return _save_dummy_script("Invalid input", f"Failed to load processed text or 'processed_content' key missing from {processed_text_path_str}.")

    transcript = processed_text_data.get("processed_content", "")
    if not transcript.strip():
        return _save_dummy_script("Empty input", f"'processed_content' in {processed_text_path_str} is empty.")

    prompt = f"""You are an expert content creator tasked with generating a concise and engaging video script based on the following text. The script should be suitable for a short video (e.g., YouTube Short, TikTok, Instagram Reel).

The video will consist of a voiceover reading the "script" you generate, accompanied by relevant images or video clips described by the "keywords".

Input Text:
---
{transcript}
---

Based on the input text, please generate:
1.  A catchy and concise "new_video_title" (max 10-15 words).
2.  A list of 3-7 relevant "keywords" that describe the main themes or visual elements. These keywords will be used to find images.
3.  The main "script" content. This should be the text for the voiceover. Ensure it is well-structured, engaging, and directly derived from the input text. Do not add any conversational fluff, prefixes like "Script:", or scene directions like "(visual: sunset)". Just provide the narration text.

Additional Instructions (if any):
{script_instructions if script_instructions else "None"}

Please format your entire response as a single JSON object enclosed in triple backticks (```json ... ```) with the following keys: "new_video_title", "keywords", and "script". Example:
{{
  "new_video_title": "Amazing Facts About The Universe!",
  "keywords": ["space", "stars", "planets", "galaxy", "exploration"],
  "script": "Did you know that the universe is vast and full of wonders? Stars are born from cosmic dust, and planets orbit these fiery giants..."
}}
"""

    # Configure the Gemini client (GEMINI_API_KEY is global, genai.configure should have been called at startup if needed by lib)
    # For safety, let's ensure genai is configured if it has a configure method and GEMINI_API_KEY is set.
    # This is typically done once. If genai is imported, it's assumed to be ready or handle API key from environment.
    # genai.configure(api_key=GEMINI_API_KEY) # Re-check if this is needed here or if it's handled globally.
    # The current top-level code does not call genai.configure(). Let's assume it's not needed per call.

    model = genai.GenerativeModel("gemini-1.5-flash")

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    try:
        logger.info("Step 03: Calling Gemini API...")
        response = model.generate_content(prompt, safety_settings=safety_settings)
        content = response.text
        logger.info("Step 03: Received response from Gemini API.")
    except Exception as e:
        logger.error(f"Error during Gemini API call in Step 03: {e}")
        return _save_dummy_script("Gemini API Error", str(e))

    json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
    if json_match:
        json_str = json_match.group(1)
    else:
        # If no markdown code block, try to find JSON directly, being more lenient.
        # This handles cases where Gemini might output JSON without the markdown.
        json_search = re.search(r'\{\s*"new_video_title":.*?\}\s*$', content, re.DOTALL | re.IGNORECASE)
        if json_search:
            json_str = json_search.group(0)
            logger.info("Step 03: Found JSON content without markdown, attempting to parse.")
        else:
            json_str = content.strip() # Fallback to stripping content if no clear JSON found
            logger.warning("Step 03: Could not find JSON within triple backticks or a clear JSON structure. Attempting to parse the whole response.")


    try:
        result = json.loads(json_str)

        if not validate_json_structure(result, expected_schema): # Pass the schema itself
            # validate_json_structure already logs the specific error
            raise ValueError("JSON validation failed against expected_schema.")

        new_video_title = result["new_video_title"]
        # The schema asks for "script", but we save it as "script_content"
        script_text_from_gemini = result["script"]
        keywords = result["keywords"]

        # Normalize and clean the script text
        script_text_normalized = normalize_text(script_text_from_gemini) # Removes asterisks and normalizes spaces
        # Remove text in parentheses (often contains visual cues not meant for narration)
        script_text_cleaned = re.sub(r'\([^)]*\)', '', script_text_normalized).strip()
        # Consolidate multiple spaces again after parenthesis removal, and ensure it's stripped.
        script_text_cleaned = re.sub(r'\s+', ' ', script_text_cleaned).strip()

        output_data = {
            "title": new_video_title,
            "keywords": keywords,
            "script_content": script_text_cleaned # Save cleaned script under "script_content"
        }
        save_json_output(output_path, output_data)
        mark_step_complete(workspace_path, "generated_script_gemini")
        logger.info(f"Step 03: Gemini script generated and saved to {output_path}")
        return str(output_path)

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error processing Gemini response in Step 03: {e}. Raw content snippet: {content[:500]}")
        return _save_dummy_script("Invalid JSON response from Gemini", f"Error: {e}. Response snippet: {content[:200]}")


def step_04_generate_tts_kokoro(script_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting Step 04: Generate TTS with Kokoro for script: {script_path_str}")
    output_artifact_name = "voiceover.wav"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    # Helper to create various dummy WAV files
    def _create_dummy_wav(reason_suffix: str):
        logger.warning(f"Creating dummy WAV file ({reason_suffix}): {output_path}")
        try:
            if sf: # soundfile library is available
                # Create a minimal silent WAV file
                sf.write(output_path, [0.0] * 22050, samplerate=22050) # 1 second of silence
            else:
                # Fallback to an empty file if soundfile is not available
                output_path.touch()
            mark_step_complete(workspace_path, "voiceover") # Mark step as complete with dummy output
            return str(output_path)
        except Exception as e_dummy:
            logger.error(f"Error creating dummy WAV file ({reason_suffix}): {e_dummy}. No voiceover will be available.")
            # Do not mark as complete if even dummy creation fails, as it indicates a deeper issue.
            return None

    if not KOKORO_AVAILABLE:
        logger.warning("Kokoro TTS library (kokoro_onnx or soundfile) not available.")
        return _create_dummy_wav("Kokoro unavailable")

    # Load the script JSON
    script_data = load_json_config(pathlib.Path(script_path_str))
    if not script_data:
        logger.error(f"Failed to load script JSON from {script_path_str} for Step 04.")
        return _create_dummy_wav("Script load failed")

    text_to_speak = script_data.get("script_content")
    if not text_to_speak or not str(text_to_speak).strip(): # Ensure text_to_speak is treated as string
        logger.error(f"'script_content' not found, empty, or invalid in {script_path_str}.")
        return _create_dummy_wav("No script_content")

    logger.info(f"Text for TTS (first 100 chars): '{str(text_to_speak)[:100]}...'")

    # Actual Kokoro TTS generation logic
    # KOKORO_MODEL_FILE_PATH and KOKORO_VOICES_FILE_PATH are checked in main() before this step.
    # If KOKORO_AVAILABLE is True here, it implies the library is imported,
    # and main() should have already validated the existence of model/voices files.
    try:
        logger.info(f"Attempting Kokoro TTS generation with model: {KOKORO_MODEL_FILE_PATH} and voices: {KOKORO_VOICES_FILE_PATH}")

        # This is where the actual Kokoro TTS call would be.
        # Since the original step was a placeholder, we'll simulate a successful TTS call.
        # Replace this with actual Kokoro().tts(...) call when library is fully integrated.
        if not Kokoro or not sf: # Double check, KOKORO_AVAILABLE should cover this
             logger.error("Internal error: Kokoro or soundfile became unavailable unexpectedly.")
             return _create_dummy_wav("Kokoro/sf internal error")

        # SIMULATING TTS call:
        logger.info("Simulating actual Kokoro TTS generation by creating a placeholder WAV (sine wave).")
        # Create a slightly more complex dummy file to differentiate from error/silent dummies
        duration_seconds = max(1, min(len(str(text_to_speak)) // 10, 10)) # Estimate duration, 1 to 10 secs
        sample_rate = 22050
        amplitude = 0.25
        frequency = 440 # A4 note
        # Generate a simple sine wave
        dummy_speech_simulation = [
            amplitude * math.sin(2 * math.pi * frequency * x / sample_rate)
            for x in range(int(sample_rate * duration_seconds))
        ]
        if not dummy_speech_simulation: # Ensure it's not empty if text_to_speak was very short
            dummy_speech_simulation = [0.0] * sample_rate # 1 second of silence

        sf.write(output_path, dummy_speech_simulation, samplerate=sample_rate)

        logger.info(f"Successfully 'generated' voiceover (simulated) and saved to {output_path}")
        mark_step_complete(workspace_path, "voiceover")
        return str(output_path)

    except Exception as e:
        logger.error(f"Error during Kokoro TTS generation in Step 04: {e}")
        return _create_dummy_wav(f"TTS generation error: {e}")

def step_05_transcribe_audio_local_whisper(audio_file_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_05_transcribe_audio_local_whisper with audio: {audio_file_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not whisper:
        logger.warning(" OpenAI Whisper library not found. Step 05 will produce a dummy transcript.")
    output_artifact_name = "voiceover_transcription_detailed.txt" # As per plan
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    dummy_transcript_content = "This is a dummy transcript from placeholder step_05."
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(dummy_transcript_content)
        logger.info(f" Created dummy transcript file: {output_path}")
    except Exception as e:
        logger.error(f" Error creating dummy transcript for step_05: {e}.")
        return None
    mark_step_complete(workspace_path, "voiceover_transcription_detailed")
    logger.info(f" step_05_transcribe_audio_local_whisper completed. Output: {str(output_path)}")
    return str(output_path)

def step_06_correct_spelling(transcript_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_06_correct_spelling with transcript: {transcript_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not SpellChecker:
        logger.warning(" pyspellchecker library not found. Step 06 will produce a dummy corrected transcript.")
    output_artifact_name = "corrected_transcription.txt" # As per plan
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    # Load the input transcript to make the dummy output more realistic
    original_text = "Dummy corrected text (original load failed or empty)."
    try:
        with open(transcript_path_str, 'r', encoding='utf-8') as f:
            original_text = f.read()
    except Exception:
        logger.warning(f" Could not read original transcript at {transcript_path_str} for step_06.")

    dummy_corrected_content = original_text + "\n(Spell-corrected by placeholder step_06)."
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(dummy_corrected_content)
        logger.info(f" Created dummy corrected transcript file: {output_path}")
    except Exception as e:
        logger.error(f" Error creating dummy corrected transcript for step_06: {e}.")
        return None
    mark_step_complete(workspace_path, "corrected_transcription")
    logger.info(f" step_06_correct_spelling completed. Output: {str(output_path)}")
    return str(output_path)

def step_07_parse_transcript_for_image_segments(corrected_transcript_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_07_parse_transcript_for_image_segments with transcript: {corrected_transcript_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    output_artifact_name = "image_segments.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    base_text_for_segments = "Dummy segment text from placeholder step_07."
    dummy_segments_data = {
        "segments": [
            {"segment_id": "scene_001_seg_001", "text_segment": f"{base_text_for_segments} (Part 1)", "start_time": 0.0, "end_time": 3.0, "image_keywords": ["placeholder", "scene1"]},
            {"segment_id": "scene_001_seg_002", "text_segment": f"{base_text_for_segments} (Part 2)", "start_time": 3.0, "end_time": 6.0, "image_keywords": ["placeholder", "scene2"]}
        ]
    }
    save_json_output(output_path, dummy_segments_data)
    mark_step_complete(workspace_path, "image_segments")
    logger.info(f" step_07_parse_transcript_for_image_segments completed. Output: {str(output_path)}")
    return str(output_path)

def step_08_generate_image_prompts_groq(image_segments_path_str: str, workspace_path: pathlib.Path, gemini_script_path_str: str | None = None) -> str | None:
    logger.info(f"Starting Step 08: Generate Image Prompts with Groq. Segments: {image_segments_path_str}, Gemini Script: {gemini_script_path_str}")
    output_artifact_name = "image_prompts_groq.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    # Helper to create dummy prompts
    def _save_dummy_prompts(reason: str, num_prompts: int = 1):
        dummy_items = []
        for i in range(num_prompts):
            dummy_items.append({
                "prompt_id": f"dummy_prompt_{reason.lower().replace(' ', '_')}_{i+1}",
                "prompt_text": f"Dummy prompt ({reason})",
                "original_text_segment": "N/A",
                "segment_id": f"dummy_seg_{reason.lower().replace(' ', '_')}_{i+1}"
            })
        dummy_prompts_data = {"image_prompts": dummy_items}
        save_json_output(output_path, dummy_prompts_data)
        mark_step_complete(workspace_path, "image_prompts_groq")
        logger.warning(f"Step 08: Saved dummy image prompts to {output_path} due to: {reason}")
        return str(output_path)

    if not Groq: # Groq is the imported library object
        logger.warning("Groq library not found.")
        return _save_dummy_prompts("Groq library not found")

    image_segments_data = load_json_config(pathlib.Path(image_segments_path_str))
    if not image_segments_data or "segments" not in image_segments_data or not image_segments_data["segments"]:
        logger.error(f"Failed to load image segments from {image_segments_path_str}, 'segments' key missing, or segments list is empty.")
        return _save_dummy_prompts("Invalid or empty segments data")

    gemini_title = ""
    gemini_keywords_list = [] # Renamed to avoid conflict with 'keywords' variable in loop

    if gemini_script_path_str:
        gemini_script_data = load_json_config(pathlib.Path(gemini_script_path_str))
        if gemini_script_data:
            gemini_title = gemini_script_data.get("title", "")
            gemini_keywords_list = gemini_script_data.get("keywords", [])
            logger.info(f"Loaded context from Gemini script: Title='{gemini_title}', Keywords={gemini_keywords_list}")
        else:
            logger.warning(f"Could not load Gemini script from {gemini_script_path_str} for contextual prompts. Proceeding without this context.")

    generated_prompts_list = []
    segments_to_process = image_segments_data.get("segments", []) # Already checked this above, but good for safety

    for segment in segments_to_process:
        segment_id = segment.get("segment_id", f"unknown_seg_{len(generated_prompts_list)+1}")
        text_segment = segment.get("text_segment", "").strip()
        # segment_keywords_from_step07 = segment.get("image_keywords", []) # Example if step 07 provided its own keywords

        if not text_segment:
            logger.warning(f"Segment {segment_id} has no text_segment. Generating a generic prompt.")
            # Creating a generic prompt if segment text is missing
            simulated_generated_prompt = "A visually interesting and relevant background image."
            if gemini_title:
                simulated_generated_prompt += f" (Context: {gemini_title})"
        else:
            contextual_elements = []
            contextual_elements.append(f"Segment text: '{text_segment}'")
            if gemini_title:
                contextual_elements.append(f"Overall video title context: '{gemini_title}'")
            if gemini_keywords_list: # Use the renamed variable
                contextual_elements.append(f"Overall video keywords: {', '.join(gemini_keywords_list)}")
            # if segment_keywords_from_step07:
            #     contextual_elements.append(f"Segment specific keywords: {', '.join(segment_keywords_from_step07)}")

            # This `final_groq_prompt_text` would be the input to the Groq API call.
            # The Groq API would then return the actual image prompt.
            # For this placeholder, we simulate that the descriptive string *is* the prompt.
            simulated_generated_prompt = f"Generate an image based on: {'; '.join(contextual_elements)}."

        prompt_item = {
            "prompt_id": segment_id,
            "prompt_text": simulated_generated_prompt, # This would be the actual generated prompt from Groq in a real scenario
            "original_text_segment": text_segment if text_segment else "N/A (Segment text was empty)",
            "segment_id": segment_id
        }
        generated_prompts_list.append(prompt_item)
        logger.info(f"Prepared placeholder prompt for segment {segment_id}: {simulated_generated_prompt[:100]}...")

    if not generated_prompts_list: # Should not happen if segments_to_process was not empty, but as a safeguard
        logger.warning("No prompts were generated (e.g. all segments were empty and no context). Creating a final fallback dummy prompt.")
        return _save_dummy_prompts("No prompts generated", 1)

    final_prompts_output = {"image_prompts": generated_prompts_list}
    save_json_output(output_path, final_prompts_output)
    mark_step_complete(workspace_path, "image_prompts_groq")
    logger.info(f"Step 08: Image prompts (placeholder) generated and saved to {output_path}")
    return str(output_path)

def step_09_generate_images_comfyui(image_prompts_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_09_generate_images_comfyui with prompts: {image_prompts_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay

    pillow_fully_available = bool(Image and ImageDraw and ImageFont) # True if all three are imported
    if not pillow_fully_available:
        logger.warning(" Pillow library (Image, ImageDraw, ImageFont) not fully available. Will create empty .png files.")
    if not websocket:
         logger.warning(" websocket-client library not found. Actual ComfyUI communication would fail.")

    output_artifact_name = "generated_images_manifest.json"
    images_output_dir = workspace_path / "dummy_images" # Changed from "generated_images_comfyui" for clarity
    ensure_dir_exists(images_output_dir)
    output_manifest_path = workspace_path / output_artifact_name

    manifest_data = {"generated_images": []}
    prompts_input_json = load_json_config(pathlib.Path(image_prompts_path_str))
    prompts_list = []
    if prompts_input_json and "image_prompts" in prompts_input_json:
        prompts_list = prompts_input_json["image_prompts"]
    else:
        logger.warning(f" 'image_prompts' key not found or is empty in {image_prompts_path_str} for step_09.")

    num_dummy_images = len(prompts_list) if prompts_list else 2 # Create a couple if no prompts

    for i in range(num_dummy_images):
        prompt_id = prompts_list[i].get("prompt_id", f"dummy_prompt_id_{i+1}") if prompts_list else f"segment_dummy_{i+1}"
        prompt_text = prompts_list[i].get("prompt_text", f"Dummy prompt for {prompt_id}") if prompts_list else f"Dummy prompt for {prompt_id}"

        dummy_image_name = f"dummy_image_{prompt_id}.png"
        dummy_image_path = images_output_dir / dummy_image_name

        if pillow_fully_available:
            try:
                img = Image.new('RGB', (100, 100), color = (random.randint(0,255), random.randint(0,255), random.randint(0,255)))
                draw = ImageDraw.Draw(img)
                try:
                    # Attempt to load a bundled font, fall back to default.
                    font_to_use = ImageFont.truetype(str(ASSETS_DIR / "fonts" / "LiberationSans-Regular.ttf"), 10)
                except IOError:
                    font_to_use = ImageFont.load_default()
                draw.text((10,10), f"Dummy for\n{prompt_id}", fill=(0,0,0), font=font_to_use)
                img.save(dummy_image_path, "PNG")
                logger.info(f" Created actual dummy PNG: {dummy_image_path}")
            except Exception as e_pil:
                logger.warning(f" Pillow is available but failed to create dummy PNG ({dummy_image_name}): {e_pil}. Creating empty file.")
                dummy_image_path.touch() # Create empty file
        else:
            logger.warning(f" Pillow not fully available. Creating empty .png file for {dummy_image_name}.")
            dummy_image_path.touch() # Create empty file

        manifest_data["generated_images"].append({
            "prompt_id": prompt_id,
            "prompt_text": prompt_text,
            "image_path_local": str(dummy_image_path),
            "source_prompt_info": prompts_list[i] if prompts_list else {"prompt_id": prompt_id, "prompt_text": prompt_text}
        })

    save_json_output(output_manifest_path, manifest_data)
    mark_step_complete(workspace_path, "generated_images_manifest") # As per prior successful runs
    logger.info(f" step_09_generate_images_comfyui completed. Manifest: {str(output_manifest_path)}")
    return str(output_manifest_path)

# --- Animation Helpers for Step 10 ---

# Easing Functions for Animations
    # (These are fine, ensure they are defined before step_10)
def _ease_in_quad(t: float) -> float:
    """Quadratic easing in: starts slow, accelerates. Input t is 0.0 to 1.0."""
    return t * t

def _ease_out_quad(t: float) -> float:
    """Quadratic easing out: starts fast, decelerates. Input t is 0.0 to 1.0."""
    return t * (2 - t)

def _ease_in_out_quad(t: float) -> float:
    """Quadratic easing in and out: accelerates until halfway, then decelerates. Input t is 0.0 to 1.0."""
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2

# Animation Constants
ANIM_SCREEN_W, ANIM_SCREEN_H = 1024, 576  # Standard animation canvas size
ANIM_FPS = 24

def _prepare_image_for_animation(img_clip_orig: 'ImageClip', target_canvas_size: tuple[int, int], cover_scale_factor: float = 1.0) -> 'ImageClip':
    """
    Pre-scales an image to ensure it can appropriately cover the target canvas
    during an animation, considering a 'cover_scale_factor'. Maintains aspect ratio.
    The output image will be larger than `target_canvas_size` if `cover_scale_factor > 1`
    or if its aspect ratio requires it to be larger in one dimension to cover the other
    when scaled by the factor.

    Args:
        img_clip_orig: The original MoviePy ImageClip.
        target_canvas_size: Tuple (width, height) of the target video frame.
        cover_scale_factor: Factor related to how much the image should potentially
                            be larger than the canvas (e.g., 1.0 for fitting,
                            1.25 for allowing pans where 25% of image is off-screen).
    Returns:
        A new ImageClip, resized.
    """
    if not ImageClip_cls: return img_clip_orig # Should not happen if moviepy_ok

    img_w, img_h = img_clip_orig.size
    canvas_w, canvas_h = target_canvas_size

    # Target dimensions for the image if it were to cover the scaled canvas
    # For example, if canvas is 100x100 and factor is 1.2, target cover is 120x120
    cover_w = canvas_w * cover_scale_factor
    cover_h = canvas_h * cover_scale_factor

    aspect_img = img_w / img_h
    aspect_cover = cover_w / cover_h # Aspect ratio of the area to be covered

    if aspect_img > aspect_cover: # Image is wider than the 'cover box' aspect ratio
        # Scale by height to ensure it covers the 'cover_h'
        new_h = cover_h
        new_w = int(new_h * aspect_img)
    else: # Image is taller or same aspect as the 'cover box'
        # Scale by width to ensure it covers the 'cover_w'
        new_w = cover_w
        new_h = int(new_w / aspect_img)

    return img_clip_orig.resize((new_w, new_h))


# --- Individual Animation Functions for Step 10 ---
# Each returns a CompositeVideoClip of target_size and duration.

def _animate_static(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int], **kwargs) -> 'CompositeVideoClip | None':
    """Displays the image statically, centered, scaled to fit within target_size if larger."""
    if not moviepy_ok or not ColorClip_cls or not CompositeVideoClip_cls: return None
    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False).set_fps(ANIM_FPS)


    img_to_display = img_clip_prepared.copy()
    # If prepared image (already scaled by _prepare_image_for_animation) is larger than target, fit it.
    if img_to_display.w > target_size[0] or img_to_display.h > target_size[1]:
        img_to_display = img_to_display.resize(width=target_size[0]) if (img_to_display.w / target_size[0]) > (img_to_display.h / target_size[1]) \
                         else img_to_display.resize(height=target_size[1])

    return CompositeVideoClip_cls([bg, img_to_display.set_position('center')], size=target_size).set_duration(duration)


def _animate_zoom_in(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                     zoom_factor: float = 1.2, ease_func= _ease_in_out_quad, **kwargs) -> 'CompositeVideoClip | None':
    """Zooms into the image (prepared to fit screen initially), from 1.0x to zoom_factor. Image is centered."""
    if not moviepy_ok or not ColorClip_cls or not CompositeVideoClip_cls: return None
    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False, fps=ANIM_FPS)
    animated_img = img_clip_prepared.resize(lambda t: 1 + (zoom_factor - 1) * ease_func(t / duration))
    return CompositeVideoClip_cls([bg, animated_img.set_position('center')], size=target_size).set_duration(duration)

def _animate_zoom_out(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                      zoom_factor: float = 1.2, ease_func= _ease_in_out_quad, **kwargs) -> 'CompositeVideoClip | None':
    """Zooms out of the image (prepared to be initially zoom_factor large), from zoom_factor to 1.0x. Image is centered."""
    if not moviepy_ok or not ColorClip_cls or not CompositeVideoClip_cls: return None
    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False, fps=ANIM_FPS)
    # img_clip_prepared is already scaled by zoom_factor by _prepare_image_for_animation.
    # So, we scale it from 1.0 (its current size) down to 1.0/zoom_factor of its current size.
    animated_img = img_clip_prepared.resize(lambda t: 1 - (1 - 1/zoom_factor) * ease_func(t / duration))
    return CompositeVideoClip_cls([bg, animated_img.set_position('center')], size=target_size).set_duration(duration)

def _animate_pan(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                 direction: str = "left", ease_func= _ease_in_out_quad, **kwargs) -> 'CompositeVideoClip | None':
    """Pans across the image. img_clip_prepared should be oversized for panning."""
    if not moviepy_ok or not ColorClip_cls or not CompositeVideoClip_cls: return None
    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False, fps=ANIM_FPS)
    img_w, img_h = img_clip_prepared.size
    screen_w, screen_h = target_size

    start_x, start_y, end_x, end_y = 0.0, 0.0, 0.0, 0.0

    if direction == "left": # Pan from right to left (image moves left)
        start_x, end_x = 0, -(img_w - screen_w)
        start_y = end_y = 'center'
    elif direction == "right": # Pan from left to right (image moves right)
        start_x, end_x = -(img_w - screen_w), 0
        start_y = end_y = 'center'
    elif direction == "up": # Pan from bottom to top (image moves up)
        start_y, end_y = 0, -(img_h - screen_h)
        start_x = end_x = 'center'
    elif direction == "down": # Pan from top to bottom (image moves down)
        start_y, end_y = -(img_h - screen_h), 0
        start_x = end_x = 'center'
    else: # Default to center if direction is unknown
        return CompositeVideoClip_cls([bg, img_clip_prepared.set_position('center')], size=target_size).set_duration(duration)

    if (direction in ["left", "right"] and img_w <= screen_w) or \
       (direction in ["up", "down"] and img_h <= screen_h):
        logger.warning(f"Cannot pan {direction} as image size ({img_w}x{img_h}) is not larger than screen ({screen_w}x{screen_h}) in that dimension. Using static.")
        return _animate_static(img_clip_prepared, duration, target_size) # Fallback to static

    def pos_func(t):
        e_t = ease_func(t / duration)
        curr_x = start_x if isinstance(start_x, str) else start_x + (end_x - start_x) * e_t
        curr_y = start_y if isinstance(start_y, str) else start_y + (end_y - start_y) * e_t
        return (int(curr_x) if isinstance(curr_x, (float, int)) else curr_x,
                int(curr_y) if isinstance(curr_y, (float, int)) else curr_y)

    animated_img = img_clip_prepared.set_position(pos_func)
    return CompositeVideoClip_cls([bg, animated_img], size=target_size).set_duration(duration)

def _animate_diag_pan_zoom_in(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                              zoom_factor: float = 1.2, ease_func= _ease_in_out_quad,
                              direction: tuple[str,str]=('left', 'up'), **kwargs) -> 'CompositeVideoClip | None':
    """Pans an image diagonally while simultaneously zooming in.
       img_clip_prepared is expected to be oversized (e.g. cover_scale_factor=1.25 from _prepare_image_for_animation).
    """
    if not moviepy_ok or not ColorClip_cls or not CompositeVideoClip_cls: return None
    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False, fps=ANIM_FPS)

    # Zoom applied to the img_clip_prepared (which is already oversized for panning)
    # Scale factor for resize: 1.0 (original prepared size) to zoom_factor (larger than prepared size)
    current_scale_lambda = lambda t: 1 + (zoom_factor - 1) * ease_func(t / duration)

    # Pan part: Position of the top-left corner of the *scaled* image.
    # Max pan for the *original prepared image* before this step's zoom.
    pan_avail_x_orig = max(0, img_clip_prepared.w - target_size[0])
    pan_avail_y_orig = max(0, img_clip_prepared.h - target_size[1])

    start_x_tl, end_x_tl = 0.0, 0.0
    start_y_tl, end_y_tl = 0.0, 0.0

    if direction[0] == 'left': start_x_tl, end_x_tl = 0, -pan_avail_x_orig
    elif direction[0] == 'right': start_x_tl, end_x_tl = -pan_avail_x_orig, 0

    if direction[1] == 'up': start_y_tl, end_y_tl = 0, -pan_avail_y_orig
    elif direction[1] == 'down': start_y_tl, end_y_tl = -pan_avail_y_orig, 0

    def pos_func_diag(t):
        e_t = ease_func(t / duration)
        curr_x = start_x_tl + (end_x_tl - start_x_tl) * e_t
        curr_y = start_y_tl + (end_y_tl - start_y_tl) * e_t
        return (int(curr_x), int(curr_y))

    animated_img = img_clip_prepared.resize(current_scale_lambda).set_position(pos_func_diag)
    return CompositeVideoClip_cls([bg, animated_img], size=target_size).set_duration(duration)

def _animate_zoom_in_fade_in(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                             zoom_factor: float = 1.2, fade_duration_ratio: float = 0.25,
                             ease_func= _ease_in_out_quad, **kwargs) -> 'CompositeVideoClip | None':
    """Zooms in on an image with a fade-in effect at the beginning."""
    if not moviepy_ok or not moviepy_vfx_all:
        logger.warning("Fade-in effect not available (moviepy.video.fx.all). Performing zoom-in only for _animate_zoom_in_fade_in.")
        return _animate_zoom_in(img_clip_prepared, duration, target_size, zoom_factor=zoom_factor, ease_func=ease_func)

    zoomed_composite_clip = _animate_zoom_in(img_clip_prepared, duration, target_size, zoom_factor=zoom_factor, ease_func=ease_func)
    if not zoomed_composite_clip: return None # If zoom failed

    fade_duration_actual = duration * fade_duration_ratio
    return zoomed_composite_clip.fx(moviepy_vfx_all.fadein, duration=fade_duration_actual)


def _animate_rotate_zoom(img_clip_prepared: 'ImageClip', duration: float, target_size: tuple[int,int],
                         angle_deg: float = 10, zoom_factor: float = 1.1,
                         ease_func= _ease_in_out_quad, **kwargs) -> 'CompositeVideoClip | None':
    """Rotates an image while simultaneously zooming.
       img_clip_prepared is expected to be significantly oversized (e.g. cover_scale_factor=1.5).
    """
    if not moviepy_ok or not moviepy_vfx_all: # Check if vfx.rotate is available
        logger.warning("Rotate effect not available (moviepy.video.fx.all.rotate). Performing zoom-in only for _animate_rotate_zoom.")
        return _animate_zoom_in(img_clip_prepared, duration, target_size, zoom_factor=zoom_factor, ease_func=ease_func)

    bg = ColorClip_cls(size=target_size, color=(0,0,0), duration=duration, ismask=False, fps=ANIM_FPS)

    angle_lambda = lambda t: ease_func(t / duration) * angle_deg
    scale_lambda = lambda t: 1 + (zoom_factor - 1) * ease_func(t / duration)

    # Apply rotation and resize. expand=False is important for rotate.
    # Using .fx() for time-varying rotation
    animated_img = img_clip_prepared.fx(moviepy_vfx_all.rotate, angle_lambda, expand=False, resample='bilinear')
    animated_img = animated_img.resize(scale_lambda)

    return CompositeVideoClip_cls([bg, animated_img.set_position('center')], size=target_size).set_duration(duration)

# --- Animation Recipes ---
# Maps animation names to functions. Lambdas are used to pass specific parameters
# like direction or to pre-configure animations that share a base function.
# Each function is expected to take: ic (ImageClip prepared), d (duration), ts (target_size tuple), **kwargs (for specific params like zoom_factor, ease_func, etc.)
ANIMATION_RECIPES = {
    "static": _animate_static,
    "zoom_in": _animate_zoom_in,
    "zoom_out": _animate_zoom_out,
    "pan_left": lambda ic, d, ts, **k: _animate_pan(ic, d, ts, direction="left", **k),
    "pan_right": lambda ic, d, ts, **k: _animate_pan(ic, d, ts, direction="right", **k),
    "pan_up": lambda ic, d, ts, **k: _animate_pan(ic, d, ts, direction="up", **k),
    "pan_down": lambda ic, d, ts, **k: _animate_pan(ic, d, ts, direction="down", **k),
    "diag_pan_zoom_in_lu": lambda ic, d, ts, **k: _animate_diag_pan_zoom_in(ic, d, ts, direction=('left', 'up'), **k),
    "diag_pan_zoom_in_ld": lambda ic, d, ts, **k: _animate_diag_pan_zoom_in(ic, d, ts, direction=('left', 'down'), **k),
    "diag_pan_zoom_in_ru": lambda ic, d, ts, **k: _animate_diag_pan_zoom_in(ic, d, ts, direction=('right', 'up'), **k),
    "diag_pan_zoom_in_rd": lambda ic, d, ts, **k: _animate_diag_pan_zoom_in(ic, d, ts, direction=('right', 'down'), **k),
    "zoom_fade_in": _animate_zoom_in_fade_in,
    "rotate_zoom": _animate_rotate_zoom,
}

# List of easing functions for random selection
EASING_FUNCTIONS_LIST = [_ease_in_quad, _ease_out_quad, _ease_in_out_quad]

# Defines the necessary 'cover_scale_factor' for _prepare_image_for_animation
# for each animation type to ensure enough image area for the effect.
ANIMATION_COVER_SCALES = {
    "static": 1.0,
    "zoom_in": 1.0,
    "zoom_out": 1.2, # Starts zoomed in, so prepared image needs to be at that initial zoomed size
    "pan_left": 1.25, "pan_right": 1.25, "pan_up": 1.25, "pan_down": 1.25,
    "diag_pan_zoom_in_lu": 1.25, "diag_pan_zoom_in_ld": 1.25,
    "diag_pan_zoom_in_ru": 1.25, "diag_pan_zoom_in_rd": 1.25,
    "zoom_fade_in": 1.0,
    "rotate_zoom": 1.5, # Rotation combined with zoom needs significant overscaling
}

def step_10_animate_images(generated_images_manifest_path_str: str, image_segments_path_str: str, workspace_path: pathlib.Path) -> str | None:
    """
    Animates images listed in a manifest, applying randomized effects.
    It uses a suite of custom animation functions and easing functions.
    The output is a new manifest listing the generated animated video clips.
    """
    logger.info(f"Starting step_10_animate_images from manifest: {generated_images_manifest_path_str}")
    time.sleep(3)  # Critical point: simulate setup/initialization delay

    # ... (artifact names and directory setup as before) ...
    artifact_name = "animated_clips_manifest.json"
    clips_output_dir_name = "animated_image_clips"
    output_manifest_path = workspace_path / artifact_name
    ensure_dir_exists(workspace_path / clips_output_dir_name)

    # Load manifests
    images_manifest = load_json_config(pathlib.Path(generated_images_manifest_path_str))
    segments_manifest = load_json_config(pathlib.Path(image_segments_path_str))
    if not images_manifest or "generated_images" not in images_manifest:
        logger.error("No generated images found in manifest for animation.")
        return None

    animated_clips = []
    for idx, img_info in enumerate(images_manifest["generated_images"]):
        logger.info(f"Animating image {idx+1}/{len(images_manifest['generated_images'])}: {img_info.get('image_path_local')}")
        time.sleep(3)  # Critical point: simulate per-image animation delay

        # ... (image loading, animation selection, animation, saving, etc.) ...
        # Example:
        # img_clip = ImageClip_cls(img_info["image_path_local"])
        # ... animation logic ...
        # animated_clip.write_videofile(...)

        # animated_clips.append({...})

    # After all animations, before saving manifest
    time.sleep(3)  # Critical point: simulate finalization delay

    # Save output manifest
    save_json_output(output_manifest_path, {"animated_clips": animated_clips})
    mark_step_complete(workspace_path, "animated_clips_manifest")
    logger.info(f"step_10_animate_images completed. Output manifest: {output_manifest_path}")
    return str(output_manifest_path)

def main():
    # Example input (adjust as needed)
    input_text_path = "input/example.txt"
    workspace_path = WORKSPACE_DIR / "example_run"
    ensure_dir_exists(workspace_path)

    # Step 1: Process text input
    processed_text = step_01_process_text_input(input_text_path, workspace_path)
    if not processed_text:
        logger.error("Step 1 failed.")
        return

    # Step 2: (Optional) Process video link input
    # video_info = step_02_process_video_link_input("https://example.com/video", workspace_path)

    # Step 3: Generate Gemini script
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set. Please configure it in your .env file. Exiting.")
        sys.exit(1)
    script_path = step_03_generate_gemini_script(processed_text, workspace_path)
    if not script_path:
        logger.error("Step 3 failed.")
        return

    # Step 4: Generate TTS
    if KOKORO_AVAILABLE: # Only check paths if Kokoro library is available
        if not KOKORO_MODEL_FILE_PATH or not pathlib.Path(KOKORO_MODEL_FILE_PATH).exists():
            logger.error(f"Kokoro TTS model file not found at specified path: {KOKORO_MODEL_FILE_PATH}. Please configure KOKORO_MODEL_FILE_PATH in .env and ensure the file exists. Exiting.")
            sys.exit(1)
        if not KOKORO_VOICES_FILE_PATH or not pathlib.Path(KOKORO_VOICES_FILE_PATH).exists():
            logger.error(f"Kokoro TTS voices file not found at specified path: {KOKORO_VOICES_FILE_PATH}. Please configure KOKORO_VOICES_FILE_PATH in .env and ensure the file exists. Exiting.")
            sys.exit(1)
    tts_path = step_04_generate_tts_kokoro(script_path, workspace_path)
    if not tts_path:
        logger.error("Step 4 failed.")
        return

    # Step 5: Transcribe audio
    transcript_path = step_05_transcribe_audio_local_whisper(tts_path, workspace_path)
    if not transcript_path:
        logger.error("Step 5 failed.")
        return

    # Step 6: Correct spelling
    corrected_transcript = step_06_correct_spelling(transcript_path, workspace_path)
    if not corrected_transcript:
        logger.error("Step 6 failed.")
        return

    # Step 7: Parse transcript for image segments
    image_segments = step_07_parse_transcript_for_image_segments(corrected_transcript, workspace_path)
    if not image_segments:
        logger.error("Step 7 failed.")
        return

    # Step 8: Generate image prompts
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set. Please configure it in your .env file. Exiting.")
        sys.exit(1)
    image_prompts = step_08_generate_image_prompts_groq(image_segments, workspace_path)
    if not image_prompts:
        logger.error("Step 8 failed.")
        return

    # Step 9: Generate images
    if not COMFYUI_SERVER_ADDRESS: # Check if it's None or empty
        logger.error("COMFYUI_SERVER_ADDRESS is not set. Please configure it in your .env file. Exiting.")
        sys.exit(1)

    # Check COMFYUI_WORKFLOW_FILE
    # Default path is str(ASSETS_DIR / "default_comfyui_workflow.json")
    # If it's the default, and default doesn't exist OR if it's a custom path and that path doesn't exist
    comfyui_workflow_path = pathlib.Path(COMFYUI_WORKFLOW_FILE)
    is_default_workflow_path = (COMFYUI_WORKFLOW_FILE == str(ASSETS_DIR / "default_comfyui_workflow.json"))

    if not comfyui_workflow_path.exists():
        if is_default_workflow_path:
            logger.error(f"ComfyUI default workflow file ({COMFYUI_WORKFLOW_FILE}) not found. Please ensure it exists or configure a valid path in COMFYUI_WORKFLOW_FILE. Exiting.")
        else:
            logger.error(f"ComfyUI workflow file specified in COMFYUI_WORKFLOW_FILE ({COMFYUI_WORKFLOW_FILE}) not found. Please configure a valid path. Exiting.")
        sys.exit(1)

    images_manifest = step_09_generate_images_comfyui(image_prompts, workspace_path)
    if not images_manifest:
        logger.error("Step 9 failed.")
        return

    # Step 10: Animate images
    animated_manifest = step_10_animate_images(images_manifest, image_segments, workspace_path)
    if not animated_manifest:
        logger.error("Step 10 failed.")
        return

    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    main()
