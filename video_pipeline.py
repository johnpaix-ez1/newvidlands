import os
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

# Placeholder imports for third-party libraries
try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
except ImportError:
    genai = None # Ensure genai is None if import fails
    HarmCategory = None
    HarmBlockThreshold = None
    print("Gemini library (google.generativeai) not found. Step 03 will be skipped or use placeholder logic.")

try:
    import jsonschema
except ImportError:
    jsonschema = None # Ensure jsonschema is None if import fails
    print("jsonschema library not found. JSON validation in Step 03 will be skipped.")

try:
    import kokoro_onnx.run as kokoro_speaker_module # Specific import based on usage
except ImportError:
    kokoro_speaker_module = None
    print("kokoro_onnx.run module not found. Kokoro TTS (Step 04) will use a dummy WAV file.")

try:
    import whisper # from openai_whisper
except ImportError:
    whisper = None
    print("OpenAI Whisper library not found. Transcription (Step 05) will use a dummy transcript.")

try:
    from spellchecker import SpellChecker
except ImportError:
    SpellChecker = None
    print("pyspellchecker library not found. Spell correction (Step 06) will be skipped.")

try:
    import websocket # For ComfyUI
    from PIL import Image, ImageDraw, ImageFont
    # No need to import io here as it's already imported at the top level
except ImportError:
    websocket = None
    Image = None
    ImageDraw = None
    ImageFont = None
    print("websocket-client or Pillow not found. ComfyUI image generation (Step 09) will use dummy images.")


try:
    import yt_dlp
except ImportError:
    pass
try:
    from moviepy.editor import (VideoFileClip, ImageClip, AudioFileClip, concatenate_videoclips,
                                TextClip, CompositeVideoClip, concatenate_audioclips)
    from moviepy.video.tools.subtitles import SubtitlesClip
except ImportError:
    pass
try:
    import kokoro_onnx.run
except ImportError:
    pass
try:
    import whisper
except ImportError:
    pass
try:
    from groq import Groq
except ImportError:
    pass
try:
    import websocket # for ComfyUI
except ImportError:
    pass
try:
    from PIL import Image
except ImportError:
    pass
try:
    import requests
except ImportError:
    pass
try:
    from spellchecker import SpellChecker
except ImportError:
    pass
try:
    from dotenv import load_dotenv
except ImportError:
    pass
try:
    from termcolor import cprint
except ImportError:
    pass

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
try:
    load_dotenv()
except NameError: # if dotenv is not installed
    logger.warning("dotenv library not found. API keys might not be loaded if not set in environment.")


# Global constants for paths
SCRIPT_DIR = pathlib.Path(__file__).parent.resolve()
INPUT_DIR = SCRIPT_DIR / "input"
WORKSPACE_DIR = SCRIPT_DIR / "workspace"
FINAL_VIDEO_DIR = SCRIPT_DIR / "final_videos"
LOG_DIR = SCRIPT_DIR / "logs"

# API Keys (loaded from .env or environment)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")
COMFYUI_SERVER_ADDRESS = os.getenv("COMFYUI_SERVER_ADDRESS", "127.0.0.1:8188") # Default if not in .env
COMFYUI_WORKFLOW_FILE = os.getenv("COMFYUI_WORKFLOW_FILE", str(SCRIPT_DIR / "assets/default_comfyui_workflow.json"))


# Helper functions
def ensure_dir_exists(path: pathlib.Path):
    """Creates a directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def get_source_id(source_path: str) -> str:
    """Creates a unique ID for each input source."""
    if urllib.parse.urlparse(source_path).scheme in ['http', 'https']:
        # For URLs, use a part of the URL to create a readable ID
        parsed_url = urllib.parse.urlparse(source_path)
        path_parts = [part for part in parsed_url.path.split('/') if part]
        if parsed_url.query:
             # Add query params like ?v= for youtube
            source_name = "_".join(path_parts) + "_" + parsed_url.query if path_parts else "url_" + parsed_url.query
        else:
            source_name = "_".join(path_parts) if path_parts else parsed_url.netloc
        # Limit length and sanitize
        source_name = re.sub(r'[^a-zA-Z0-9_-]', '_', source_name)[:50]
    else:
        # For local files, use the filename
        source_name = pathlib.Path(source_path).stem
    return f"{source_name}_{uuid.uuid4().hex[:8]}"

def get_workspace_path(source_id: str) -> pathlib.Path:
    """Gets the dedicated workspace for a source."""
    return WORKSPACE_DIR / source_id

def is_step_complete(workspace_path: pathlib.Path, artifact_name: str) -> bool:
    """Checks if a specific artifact (file or directory) exists, indicating step completion."""
    # Check for the ".complete" marker file first for explicit completion.
    marker_file = workspace_path / f"{artifact_name}.complete"
    if marker_file.exists():
        return True
    # If no marker, check if the artifact itself exists. This is useful if the step
    # directly creates the artifact and doesn't use a separate marker.
    # This might be too lenient for directories if they are created empty early on.
    # For critical directory checks, ensure a .complete marker is used.
    # return (workspace_path / artifact_name).exists()
    return False # Prefer explicit .complete markers


def mark_step_complete(workspace_path: pathlib.Path, artifact_name: str):
    """Creates a dummy file to mark step completion."""
    ensure_dir_exists(workspace_path)
    (workspace_path / f"{artifact_name}.complete").touch()
    logger.info(f"Marked step as complete by creating: {workspace_path / artifact_name}.complete")


def load_json_config(file_path: pathlib.Path) -> dict | None:
    """Loads a JSON configuration file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {file_path}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from file: {file_path}")
        return None

def save_json_output(file_path: pathlib.Path, data: dict):
    """Saves data to a JSON file."""
    ensure_dir_exists(file_path.parent)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    logger.info(f"Saved JSON output to: {file_path}")

def normalize_text(text: str) -> str:
    """Placeholder for text normalization."""
    text = text.replace("*", "") # Remove asterisks
    text = re.sub(r'\s+', ' ', text).strip() # Remove extra spaces
    # Add more normalization rules as needed
    return text

# --- Initialize directories ---
ensure_dir_exists(INPUT_DIR)
ensure_dir_exists(WORKSPACE_DIR)
ensure_dir_exists(FINAL_VIDEO_DIR)
ensure_dir_exists(LOG_DIR)

logger.info(f"Input directory: {INPUT_DIR}")
logger.info(f"Workspace directory: {WORKSPACE_DIR}")
logger.info(f"Final video directory: {FINAL_VIDEO_DIR}")
logger.info(f"Log directory: {LOG_DIR}")

# Placeholder functions for pipeline steps
def step_01_process_text_input(source_file_path: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_01_process_text_input for {source_file_path}")
    artifact_name = "input_content.txt"
    content_file = workspace_path / artifact_name
    try:
        # This step's output is the content itself, also saved to a file.
        # The completion marker refers to the successful execution of this step.
        if is_step_complete(workspace_path, artifact_name): # checks input_content.txt.complete
            logger.info("Text input processing already complete.")
            return content_file.read_text(encoding='utf-8') if content_file.exists() else None

        with open(source_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        normalized_content = normalize_text(content)
        with open(content_file, 'w', encoding='utf-8') as f:
            f.write(normalized_content)

        mark_step_complete(workspace_path, artifact_name)
        logger.info(f"Processed text input saved to {content_file}")
        return normalized_content
    except Exception as e:
        logger.error(f"Error in step_01_process_text_input: {e}")
        return None

def step_02_process_video_link_input(video_link: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_02_process_video_link_input for {video_link}")
    artifact_name = "downloaded_audio.wav"  # Output as WAV
    audio_file_path = workspace_path / artifact_name

    # Resumability is handled by get_or_run_step in main_workflow

    logger.info(f"Attempting to download audio from: {video_link}")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',  # Convert to WAV
            'preferredquality': '192', # Standard quality
        }],
        'outtmpl': str(audio_file_path.with_suffix('')), # yt-dlp adds extension, so provide path without it initially
        'noplaylist': True, # Download only the video, not playlist if URL is part of one
        'quiet': False, # Set to False to see yt-dlp output, True for less verbose
        'noprogress': True, # Set to False to see progress bar, True for less verbose
        # 'verbose': True, # Uncomment for debugging yt-dlp issues
    }

    if YTDLP_COOKIES_FILE:
        if pathlib.Path(YTDLP_COOKIES_FILE).exists():
            ydl_opts['cookiefile'] = YTDLP_COOKIES_FILE
            logger.info(f"Using cookies file for yt-dlp: {YTDLP_COOKIES_FILE}")
        else:
            logger.warning(f"YTDLP_COOKIES_FILE specified but not found at: {YTDLP_COOKIES_FILE}. Proceeding without cookies.")

    try:
        # Ensure target directory exists
        ensure_dir_exists(workspace_path)

        # Check if the file already exists (e.g. from a previous partial download by yt-dlp that didn't complete our marker)
        # yt-dlp might create .part files or temporary files.
        # We want to ensure the final .wav file is there.
        # If audio_file_path.exists(), yt-dlp might overwrite or skip.
        # For simplicity, if it exists, we assume it's valid if this function is called again
        # without our .complete marker. Or, we could delete it before redownloading.
        # For now, let yt-dlp handle it.

        logger.info(f"yt-dlp options: {ydl_opts}") # Log options for debugging
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_link])

        # After download, yt-dlp should have created downloaded_audio.wav
        if audio_file_path.exists() and audio_file_path.is_file():
            logger.info(f"Audio successfully downloaded and converted to WAV: {audio_file_path}")
            # The mark_step_complete is handled by get_or_run_step in main_workflow
            return str(audio_file_path)
        else:
            # This case might occur if yt-dlp finishes but the file isn't where expected
            # or if the postprocessing failed to produce the .wav
            logger.error(f"yt-dlp download reported success, but output file {audio_file_path} not found.")
            # Try to find if it was saved with a different extension or if there's a .temp file
            possible_temp_files = list(workspace_path.glob(f"{audio_file_path.stem}*"))
            if possible_temp_files:
                logger.error(f"Found these related files in workspace: {possible_temp_files}. Manual check might be needed.")
            return None

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: Failed to download audio from {video_link}. Error: {e}")
        # More specific error parsing can be done here if needed
        if "Unsupported URL" in str(e):
            logger.error(f"The URL {video_link} is not supported by yt-dlp.")
        elif "Video unavailable" in str(e):
            logger.error(f"The video at {video_link} is unavailable.")
        # You can add more specific checks based on typical yt-dlp errors
        return None
    except Exception as e:
        # This catches other errors, e.g., issues with FFmpeg during postprocessing
        logger.error(f"An unexpected error occurred during video link processing for {video_link}: {e}", exc_info=True)
        return None

def step_03_generate_gemini_script(input_content: str, workspace_path: pathlib.Path, is_video_source: bool = False) -> str | None:
    logger.info(f"Starting step_03_generate_gemini_script. Video source: {is_video_source}")
    artifact_name = "generated_script.json" # Output is now a JSON file
    output_json_path = workspace_path / artifact_name

    # Schema for validating Gemini's output
    expected_schema = {
        "type": "object",
        "properties": {
            "new_video_title": {"type": "string"},
            "script": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["new_video_title", "script", "keywords"]
    }

    def validate_json_structure(data, schema):
        if not jsonschema:
            logger.warning("jsonschema library not available, skipping JSON validation.")
            return True # Skip validation if library is missing
        try:
            jsonschema.validate(instance=data, schema=schema)
            return True
        except jsonschema.exceptions.ValidationError as e:
            logger.error(f"JSON validation failed: {e.message}")
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during JSON validation: {e}")
            return False

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY not found. Cannot generate script with Gemini.")
        # Fallback to placeholder if API key is missing, to allow pipeline to proceed if desired for other steps.
        # This behavior can be changed to a hard stop if Gemini is essential.
        logger.warning("GEMINI_API_KEY is missing. Creating a placeholder for generated_script.json.")
        placeholder_data = {
            "title": "Placeholder Title (Gemini API Key Missing)",
            "script": f"This is a placeholder script because the Gemini API key was not provided. Original input was: {input_content[:150]}...",
            "keywords": ["placeholder", "gemini_api_key_missing"]
        }
        save_json_output(output_json_path, placeholder_data)
        # mark_step_complete is handled by get_or_run_step
        return str(output_json_path)


    if not genai:
        logger.error("Google Generative AI library (google.generativeai) is not installed. Cannot proceed with Gemini script generation.")
        # Similar fallback to placeholder
        logger.warning("google.generativeai library missing. Creating a placeholder for generated_script.json.")
        placeholder_data = {
            "title": "Placeholder Title (Gemini Library Missing)",
            "script": f"This is a placeholder script because the google.generativeai library is not installed. Original input was: {input_content[:150]}...",
            "keywords": ["placeholder", "gemini_library_missing"]
        }
        save_json_output(output_json_path, placeholder_data)
        return str(output_json_path)

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')

        # Construct the prompt (using the user-provided template style)
        # Assuming input_content is the 'transcript' or main text body.
        prompt = f"""
You are an AI assistant helping a content creator develop a script for a new YouTube video.
Based on the following input text (which could be a raw transcript, a topic idea, or existing content),
generate a concise and engaging video script.

Input Text:
\"\"\"
{input_content}
\"\"\"

Your output MUST be a JSON object adhering to the following schema:
{{
  "new_video_title": "A catchy and SEO-friendly title for the video.",
  "script": "The full video script, formatted for narration. Ensure it's engaging and well-paced. Do not include parenthetical remarks like (laughs) or (smiles). Remove any asterisks.",
  "keywords": ["keyword1", "keyword2", "keyword3", "up to 5 relevant keywords"]
}}

Ensure the script is ready for text-to-speech generation.
The tone should be informative yet entertaining.
Focus on clarity and directness in the script.
Do not use markdown like ```json at the start or end of your response, just the pure JSON object.
"""

        logger.info("Generating script with Gemini...")
        # Generation configuration
        generation_config = genai.types.GenerationConfig(
            temperature=0.7,
            top_p=0.95,
            # top_k=40, # Optional, can be added
            # max_output_tokens=2048, # Optional, can be adjusted
        )
        # Safety settings - adjust as needed
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }

        response = model.generate_content(
            prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )

        raw_response_text = response.text
        logger.debug(f"Raw Gemini response: {raw_response_text}")

        # Attempt to parse JSON from the response
        json_data = None
        try:
            # Try to extract JSON from within triple backticks if present
            match = re.search(r'```json\s*(.*?)\s*```', raw_response_text, re.DOTALL | re.IGNORECASE)
            if match:
                json_str = match.group(1)
                logger.info("Extracted JSON from backticks.")
            else:
                json_str = raw_response_text
                logger.info("No backticks found, attempting to parse entire response as JSON.")

            json_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from Gemini response: {e}")
            logger.error(f"Problematic JSON string: {json_str}")
            return None

        if not validate_json_structure(json_data, expected_schema):
            logger.error("Gemini response did not match the expected JSON schema.")
            return None

        new_video_title = json_data.get("new_video_title", "Untitled Video")
        script_text = json_data.get("script", "")
        keywords = json_data.get("keywords", [])

        # Apply specific normalizations to the script
        script_text = normalize_text(script_text) # General normalization (spaces, etc.)
        script_text = script_text.replace("*", "") # Remove asterisks
        script_text = re.sub(r'\([^)]*\)', '', script_text).strip() # Remove text in parentheses & strip again

        if not script_text:
            logger.warning("Gemini generated an empty script.")
            # Potentially return None or handle as an error depending on strictness
            # For now, allow empty script to proceed.

        output_data = {
            "title": new_video_title,
            "script": script_text,
            "keywords": keywords
        }
        save_json_output(output_json_path, output_data)
        logger.info(f"Gemini script generated and saved to {output_json_path}")
        return str(output_json_path)

    except genai.types.BlockedPromptException as e: # Specific exception for blocked prompts
        logger.error(f"Gemini prompt was blocked. Details: {e}")
        # Log response parts if available for debugging why it was blocked
        if response and response.prompt_feedback:
             logger.error(f"Prompt Feedback: {response.prompt_feedback}")
        return None
    except genai.types.StopCandidateException as e: # Specific exception for stop candidate issues
        logger.error(f"Gemini generation stopped unexpectedly (candidate issue). Details: {e}")
        if response and response.candidates:
             logger.error(f"Candidate data: {response.candidates}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during Gemini script generation: {e}", exc_info=True)
        return None


def step_04_generate_tts_kokoro(script_text: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_04_generate_tts_kokoro for script: '{script_text[:100]}...'")
    artifact_name = "voiceover.wav"  # Standardized name for the voiceover file
    output_wav_path = workspace_path / artifact_name

    use_dummy_wav = False
    if kokoro_speaker_module:
        try:
            logger.info("Attempting TTS generation with Kokoro ONNX...")
            # Ensure the workspace directory exists for kokoro to write the file
            ensure_dir_exists(workspace_path)

            # Initialize the speaker. This might load models and could take time on first run.
            # Research specific voice/model selection if needed. Default for now.
            # Example from thewh1teagle/kokoro-onnx might use kokoro_onnx.run.Speaker()
            speaker = kokoro_speaker_module.Speaker()

            logger.info(f"Generating speech for text: \"{script_text}\"")
            speaker.predict_speech(text=script_text, output_wav_path=str(output_wav_path))

            if output_wav_path.exists() and output_wav_path.stat().st_size > 0:
                logger.info(f"Kokoro TTS generated successfully: {output_wav_path}")
                return str(output_wav_path)
            else:
                logger.error(f"Kokoro TTS generation seemed to succeed but the output file is missing or empty: {output_wav_path}")
                use_dummy_wav = True
        except Exception as e:
            logger.error(f"Error during Kokoro TTS generation: {e}", exc_info=True)
            logger.warning("Falling back to dummy WAV file due to Kokoro TTS error.")
            use_dummy_wav = True
    else:
        logger.warning("Kokoro ONNX library not available. Falling back to dummy WAV file.")
        use_dummy_wav = True

    if use_dummy_wav:
        try:
            logger.info(f"Creating dummy silent WAV file at {output_wav_path}")
            # Parameters for a 1-second silent WAV file
            sample_rate = 22050  # Hz
            duration_seconds = 1
            num_channels = 1
            sample_width_bytes = 2  # 16-bit
            num_frames = sample_rate * duration_seconds

            ensure_dir_exists(workspace_path) # Ensure directory exists before writing
            import wave # Standard library
            import struct # Standard library

            with wave.open(str(output_wav_path), 'wb') as wf:
                wf.setnchannels(num_channels)
                wf.setsampwidth(sample_width_bytes)
                wf.setframerate(sample_rate)

                # Write silent frames
                silent_frame = struct.pack('<h', 0)  # '<h' for little-endian 16-bit signed integer
                for _ in range(num_frames):
                    wf.writeframes(silent_frame)

            if output_wav_path.exists() and output_wav_path.stat().st_size > 0:
                 logger.info(f"Dummy silent WAV file created successfully: {output_wav_path}")
                 return str(output_wav_path)
            else:
                logger.error(f"Failed to create or verify dummy WAV file at: {output_wav_path}")
                return None # Critical failure if even dummy can't be made.

        except Exception as e:
            logger.error(f"Error creating dummy WAV file: {e}", exc_info=True)
            return None # If dummy creation fails, something is very wrong.

    # Should not be reached if logic is correct, but as a fallback:
    return None


def step_05_transcribe_audio_local_whisper(audio_path: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_05_transcribe_audio_local_whisper for {audio_path}")
    artifact_name = "detailed_transcript.json"
    log_artifact_name = "transcript_log.txt" # For human-readable log

    output_json_path = workspace_path / artifact_name
    output_log_path = workspace_path / log_artifact_name

    # --- Dummy Data Creation Function ---
    def create_dummy_transcript(reason_message: str):
        logger.warning(f"{reason_message}. Creating dummy transcript files.")
        dummy_data = {
            "text": reason_message, # Full text for easy debugging
            "segments": [{
                "text": reason_message,
                "start": 0.0, "end": 1.0,
                "words": [{"word": "Dummy", "start": 0.0, "end": 0.5, "probability": 1.0},
                          {"word": "Transcript", "start": 0.5, "end": 1.0, "probability": 1.0}]
            }]
        }
        save_json_output(output_json_path, dummy_data)
        with open(output_log_path, 'w', encoding='utf-8') as f:
            f.write(f"{reason_message}\n0.0 1.0 {reason_message}\n")
            f.write(json.dumps([{"word": "Dummy", "start": 0.0, "end": 0.5, "probability": 1.0},
                                {"word": "Transcript", "start": 0.5, "end": 1.0, "probability": 1.0}]) + "\n")
        return str(output_json_path)

    # --- Audio File Check ---
    audio_file = pathlib.Path(audio_path)
    if not audio_file.exists() or audio_file.stat().st_size == 0:
        # Check if it's the known placeholder name from yt-dlp step (if that step is a placeholder)
        if audio_file.name == "downloaded_audio.wav" or audio_file.name == "downloaded_audio.mp3":
            return create_dummy_transcript(f"Audio file '{audio_path}' not found or is empty. Likely an issue with video download (Step 02).")
        elif audio_file.name == "voiceover.wav": # This is the output from step_04 (TTS)
             return create_dummy_transcript(f"TTS output audio file '{audio_path}' not found or is empty. Likely an issue with TTS generation (Step 04).")
        else: # Some other unexpected missing audio file
            logger.error(f"Critical: Audio file for transcription '{audio_path}' not found or is empty.")
            return None # Hard stop if an unexpected audio file is missing

    # --- Whisper Transcription ---
    use_dummy = False
    if whisper:
        try:
            model_name = "base" # Or "tiny", "small", "medium", "large"
            logger.info(f"Loading Whisper model: {model_name}")
            model = whisper.load_model(model_name)
            logger.info(f"Transcribing audio file: {audio_path} with Whisper...")

            # Transcribe with word timestamps
            result = model.transcribe(str(audio_path), word_timestamps=True, language="en") # Specify language if known

            # Process Whisper output
            processed_segments = []
            full_text_log = []

            for segment in result["segments"]:
                segment_text = segment.get("text", "").strip()
                start_time = segment.get("start", 0.0)
                end_time = segment.get("end", 0.0)

                words_data = []
                if "words" in segment and segment["words"]: # Ensure 'words' key exists and is not empty
                    for word_info in segment["words"]:
                        words_data.append({
                            "word": word_info.get("word", "").strip(),
                            "start": word_info.get("start", 0.0),
                            "end": word_info.get("end", 0.0),
                            "probability": word_info.get("probability", 0.0)
                        })

                processed_segments.append({
                    "text": segment_text,
                    "start": start_time,
                    "end": end_time,
                    "words": words_data
                })

                full_text_log.append(f"{start_time:.2f} {end_time:.2f} {segment_text}")
                if words_data: # Add word details to log if available
                    full_text_log.append(json.dumps(words_data))
                full_text_log.append("") # Newline for readability

            final_transcript_data = {
                "text": result.get("text", "").strip(), # Overall transcript text
                "segments": processed_segments
            }

            save_json_output(output_json_path, final_transcript_data)
            with open(output_log_path, 'w', encoding='utf-8') as f:
                f.write(f"Full Transcript Text:\n{final_transcript_data['text']}\n\n")
                f.write("Segments & Word Timestamps:\n")
                f.write("\n".join(full_text_log))

            logger.info(f"Whisper transcription complete. Detailed transcript: {output_json_path}, Log: {output_log_path}")
            return str(output_json_path)

        except Exception as e:
            logger.error(f"Error during Whisper transcription: {e}", exc_info=True)
            logger.warning("Falling back to dummy transcript due to Whisper error.")
            use_dummy = True
    else:
        logger.warning("OpenAI Whisper library not available.")
        use_dummy = True

    if use_dummy:
        return create_dummy_transcript("Whisper transcription was skipped or failed")

    return None # Should not be reached


def step_06_correct_spelling(transcript_path: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_06_correct_spelling for {detailed_transcript_path}")
    artifact_name = "corrected_transcript.json"
    output_json_path = workspace_path / artifact_name

    source_transcript_path = pathlib.Path(detailed_transcript_path)

    if not source_transcript_path.exists():
        logger.error(f"Detailed transcript file not found: {source_transcript_path}")
        return None

    # Load the transcript data
    transcript_data = load_json_config(source_transcript_path)
    if not transcript_data or "segments" not in transcript_data:
        logger.error(f"Invalid or empty transcript data in {source_transcript_path}. Missing 'segments'.")
        # Fallback: copy original if structure is bad but file exists
        if source_transcript_path.exists():
            logger.warning("Copying original transcript due to invalid structure.")
            import shutil
            shutil.copy(source_transcript_path, output_json_path)
            return str(output_json_path)
        return None

    use_fallback = False
    if SpellChecker:
        try:
            spell = SpellChecker()
            words_corrected_count = 0

            corrected_segments = []
            new_full_text_parts = []

            for segment_idx, segment in enumerate(transcript_data.get("segments", [])):
                if "words" not in segment or not isinstance(segment["words"], list):
                    logger.warning(f"Segment {segment_idx} is missing 'words' list or it's not a list. Skipping.")
                    corrected_segments.append(segment) # Keep original segment
                    new_full_text_parts.append(segment.get("text",""))
                    continue

                corrected_word_objects = []
                segment_has_changes = False

                for word_obj in segment["words"]:
                    original_word_text = word_obj.get("word", "")

                    # Regex to separate leading/trailing punctuation from the core word
                    # \w includes alphanumeric and underscore.
                    match = re.match(r'^([^\w]*)([\w\'’-]*)([^\w]*)$', original_word_text, re.UNICODE)
                    if not match: # If word is purely punctuation or unusual format
                        corrected_word_objects.append(word_obj)
                        continue

                    leading_punc, core_word, trailing_punc = match.groups()

                    corrected_core_word = core_word
                    # Only attempt to correct if core_word is not empty and seems like a word
                    if core_word and core_word.isalpha(): # Check if it's purely alphabetic
                        if spell.unknown([core_word.lower()]): # Spell check in lowercase
                            correction = spell.correction(core_word.lower())
                            if correction and correction != core_word.lower():
                                # Preserve original casing if first letter was uppercase
                                if core_word[0].isupper() and len(correction) > 0:
                                    corrected_core_word = correction[0].upper() + correction[1:]
                                else:
                                    corrected_core_word = correction
                                words_corrected_count += 1
                                segment_has_changes = True

                    # Reconstruct the word
                    final_word_text = leading_punc + corrected_core_word + trailing_punc

                    # Create a new word object to avoid modifying the original list directly during iteration if issues arise
                    new_word_obj = word_obj.copy()
                    new_word_obj["word"] = final_word_text
                    corrected_word_objects.append(new_word_obj)

                # Update segment with corrected words
                segment["words"] = corrected_word_objects

                # Reconstruct segment text from corrected words
                reconstructed_segment_text = " ".join(wo["word"] for wo in corrected_word_objects)
                # Basic re-punctuation for common cases, can be much more sophisticated
                reconstructed_segment_text = reconstructed_segment_text.replace(" .", ".").replace(" ,", ",").replace(" ?", "?").replace(" !", "!")
                segment["text"] = reconstructed_segment_text

                corrected_segments.append(segment)
                new_full_text_parts.append(reconstructed_segment_text)

            # Update the main transcript_data structure
            transcript_data["segments"] = corrected_segments
            transcript_data["text"] = " ".join(new_full_text_parts).strip() # Reconstruct full text

            logger.info(f"Spell check complete. Total words corrected: {words_corrected_count}")
            save_json_output(output_json_path, transcript_data)

        except Exception as e:
            logger.error(f"Error during spelling correction: {e}", exc_info=True)
            logger.warning("Falling back to using original (uncorrected) transcript.")
            use_fallback = True
    else:
        logger.warning("pyspellchecker library not available. Skipping spelling correction.")
        use_fallback = True

    if use_fallback:
        try:
            import shutil
            shutil.copy(source_transcript_path, output_json_path)
            logger.info(f"Copied original transcript to {output_json_path} as fallback.")
        except Exception as copy_e:
            logger.error(f"Failed to copy original transcript as fallback: {copy_e}")
            return None # If copy fails, then we can't produce the artifact

    return str(output_json_path)


def step_07_parse_transcript_for_image_segments(detailed_transcript_path: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_07_parse_transcript_for_image_segments for {detailed_transcript_path}")
    artifact_name = "image_segments.json"
    image_segments_file = workspace_path / artifact_name

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Image segment parsing already complete.")
        return str(image_segments_file) if image_segments_file.exists() else None

    if not pathlib.Path(detailed_transcript_path).exists():
        logger.error(f"Detailed transcript not found for segment parsing: {detailed_transcript_path}")
        return None

    logger.warning("step_07_parse_transcript_for_image_segments is a placeholder.")
    simulated_segments = [{"segment_id": "seg_1", "text": "Segment 1 text", "start_time": 0, "end_time": 5, "image_prompt_text": "text for image prompt 1"}]
    save_json_output(image_segments_file, {"segments": simulated_segments})
    mark_step_complete(workspace_path, artifact_name)
    return str(image_segments_file)

def step_08_generate_image_prompts_groq(image_segments_path: str, full_transcript_text: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_08_generate_image_prompts_groq for {image_segments_path}")
    artifact_name = "image_prompts.json"
    image_prompts_file = workspace_path / artifact_name

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Image prompt generation with Groq already complete.")
        return str(image_prompts_file) if image_prompts_file.exists() else None

    if not pathlib.Path(image_segments_path).exists():
        logger.error(f"Image segments file not found: {image_segments_path}")
        return None

    logger.warning("step_08_generate_image_prompts_groq is a placeholder.")
    segments_data = load_json_config(pathlib.Path(image_segments_path))
    if not segments_data or "segments" not in segments_data:
         logger.error(f"Invalid or empty image segments data in {image_segments_path}")
         return None

    simulated_prompts = [{"segment_id": s["segment_id"], "prompt": f"Groq prompt for {s.get('image_prompt_text', s['text'])}"} for s in segments_data["segments"]]
    save_json_output(image_prompts_file, {"prompts": simulated_prompts})
    mark_step_complete(workspace_path, artifact_name)
    return str(image_prompts_file)

def step_09_generate_images_comfyui(image_prompts_path: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_09_generate_images_comfyui for {image_prompts_path}")
    # This step produces a directory of images. The artifact name is the directory name.
    artifact_name = "generated_images"
    generated_images_dir = workspace_path / artifact_name

    if is_step_complete(workspace_path, artifact_name): # Checks for generated_images.complete
        logger.info("Image generation with ComfyUI already complete.")
        return str(generated_images_dir) if generated_images_dir.is_dir() else None

    if not pathlib.Path(image_prompts_path).exists():
        logger.error(f"Image prompts file not found: {image_prompts_path}")
        return None

    logger.warning("step_09_generate_images_comfyui is a placeholder.")
    ensure_dir_exists(generated_images_dir)
    prompts_data = load_json_config(pathlib.Path(image_prompts_path))
    if not prompts_data or "prompts" not in prompts_data:
        logger.error(f"Invalid or empty prompts data in {image_prompts_path}")
        return None

    for i, prompt_item in enumerate(prompts_data["prompts"]):
        segment_id = prompt_item.get("segment_id", f"img_{i}")
        dummy_image_path = generated_images_dir / f"{segment_id}.png"
        with open(dummy_image_path, 'w') as f: # Create tiny dummy file
            f.write("dummy image data")

    mark_step_complete(workspace_path, artifact_name)
    return str(generated_images_dir)

def step_10_animate_images(generated_images_dir_str: str, image_segments_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_10_animate_images for {generated_images_dir_str}")
    artifact_name = "animated_clips"
    animated_clips_dir = workspace_path / artifact_name

    generated_images_dir = pathlib.Path(generated_images_dir_str)
    image_segments_path = pathlib.Path(image_segments_path_str)

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Image animation already complete.")
        return str(animated_clips_dir) if animated_clips_dir.is_dir() else None

    if not generated_images_dir.is_dir():
        logger.error(f"Generated images directory not found: {generated_images_dir}")
        return None
    if not image_segments_path.exists():
        logger.error(f"Image segments file not found for animation timing: {image_segments_path}")
        return None

    logger.warning("step_10_animate_images is a placeholder.")
    ensure_dir_exists(animated_clips_dir)
    segments_data = load_json_config(image_segments_path)
    if not segments_data or "segments" not in segments_data:
        logger.error(f"Invalid image segments data in {image_segments_path}")
        return None

    for segment in segments_data["segments"]:
        segment_id = segment["segment_id"]
        # Assume an image exists for each segment from step 9
        if (generated_images_dir / f"{segment_id}.png").exists():
            dummy_clip_path = animated_clips_dir / f"clip_{segment_id}.mp4"
            with open(dummy_clip_path, 'w') as f: # Create dummy file
                f.write("dummy video data")

    mark_step_complete(workspace_path, artifact_name)
    return str(animated_clips_dir)

def step_11_assemble_video_moviepy(voiceover_path_str: str, animated_clips_dir_str: str, image_segments_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info("Starting step_11_assemble_video_moviepy")
    artifact_name = "raw_video.mp4"
    raw_video_file = workspace_path / artifact_name

    voiceover_path = pathlib.Path(voiceover_path_str)
    animated_clips_dir = pathlib.Path(animated_clips_dir_str)
    image_segments_path = pathlib.Path(image_segments_path_str)

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Video assembly with MoviePy already complete.")
        return str(raw_video_file) if raw_video_file.exists() else None

    if not voiceover_path.exists():
        logger.error(f"Voiceover audio file not found: {voiceover_path}")
        # If this is the downloaded audio placeholder that was never created, handle it
        if "downloaded_audio.mp3" in voiceover_path_str and not voiceover_path.exists():
            logger.warning(f"Voiceover {voiceover_path} (likely placeholder) not found. Creating dummy for assembly.")
            voiceover_path.touch() # Create empty dummy file
            # Ideally, a silent audio track or proper handling in MoviePy would be needed.
            # For placeholder, an empty file might cause MoviePy to fail.
            # A better placeholder might be a very short silent WAV.
            # For now, we proceed, MoviePy step will likely log an error.

    if not animated_clips_dir.is_dir():
        logger.error(f"Animated clips directory not found: {animated_clips_dir}")
        return None
    if not image_segments_path.exists():
        logger.error(f"Image segments file not found for assembly: {image_segments_path}")
        return None

    logger.warning("step_11_assemble_video_moviepy is a placeholder.")
    with open(raw_video_file, 'w') as f: # Create dummy file
        f.write("simulated raw video data")
    mark_step_complete(workspace_path, artifact_name)
    return str(raw_video_file)

def step_12_generate_captions_moviepy(raw_video_path_str: str, detailed_transcript_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_12_generate_captions_moviepy for {raw_video_path_str}")
    artifact_name = "captioned_video.mp4"
    captioned_video_file = workspace_path / artifact_name

    raw_video_path = pathlib.Path(raw_video_path_str)
    detailed_transcript_path = pathlib.Path(detailed_transcript_path_str)

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Caption generation with MoviePy already complete.")
        return str(captioned_video_file) if captioned_video_file.exists() else None

    if not raw_video_path.exists():
        logger.error(f"Raw video file not found for captioning: {raw_video_path}")
        return None
    if not detailed_transcript_path.exists():
        logger.error(f"Detailed transcript not found for captioning: {detailed_transcript_path}")
        return None

    logger.warning("step_12_generate_captions_moviepy is a placeholder.")
    with open(captioned_video_file, 'w') as f: # Create dummy file
        f.write("simulated captioned video data")
    mark_step_complete(workspace_path, artifact_name)
    return str(captioned_video_file)

def step_13_add_endscreen_moviepy(captioned_video_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Starting step_13_add_endscreen_moviepy for {captioned_video_path_str}")
    artifact_name = "final_video_with_endscreen.mp4"
    final_video_ws_file = workspace_path / artifact_name

    captioned_video_path = pathlib.Path(captioned_video_path_str)

    if is_step_complete(workspace_path, artifact_name):
        logger.info("Endscreen addition already complete.")
        return str(final_video_ws_file) if final_video_ws_file.exists() else None

    if not captioned_video_path.exists():
        logger.error(f"Captioned video file not found for endscreen: {captioned_video_path}")
        return None

    logger.warning("step_13_add_endscreen_moviepy is a placeholder.")
    with open(final_video_ws_file, 'w') as f: # Create dummy file
        f.write("simulated final video data with endscreen")
    mark_step_complete(workspace_path, artifact_name)
    return str(final_video_ws_file)

def step_14_finalize_video(final_video_path_ws_str: str, source_id: str, final_video_output_dir: pathlib.Path) -> str | None:
    logger.info(f"Starting step_14_finalize_video for {final_video_path_ws_str}")
    ensure_dir_exists(final_video_output_dir)

    final_video_ws_path = pathlib.Path(final_video_path_ws_str)
    final_video_name = f"{source_id}_final.mp4" # Consistent naming
    final_dest_path = final_video_output_dir / final_video_name

    # This step's completion is primarily the existence of the file in the *final* directory.
    # We can also add a marker in the workspace for internal tracking if desired.
    workspace_marker_name = f"{final_video_name}.finalized"

    if final_dest_path.exists(): # Primary check
         logger.info(f"Final video already exists at {final_dest_path}. Skipping finalization.")
         if not is_step_complete(get_workspace_path(source_id), workspace_marker_name):
             mark_step_complete(get_workspace_path(source_id), workspace_marker_name) # Mark it if not already
         return str(final_dest_path)

    if not final_video_ws_path.exists():
        logger.error(f"Video file to be finalized not found in workspace: {final_video_ws_path}")
        return None

    try:
        final_video_ws_path.rename(final_dest_path)
        logger.info(f"Final video moved to: {final_dest_path}")
        mark_step_complete(get_workspace_path(source_id), workspace_marker_name)
        return str(final_dest_path)
    except Exception as e:
        logger.error(f"Error finalizing video (moving file): {e}")
        return None

def step_15_cleanup_workspace(workspace_path: pathlib.Path, source_id: str, log_dir_base: pathlib.Path):
    logger.info(f"Starting step_15_cleanup_workspace for {workspace_path}")
    artifact_name = "workspace_cleaned.done"

    if is_step_complete(workspace_path, artifact_name):
        logger.info(f"Workspace cleanup for {source_id} was already marked as complete.")
        return

    logger.warning(f"step_15_cleanup_workspace is a placeholder. Workspace at {workspace_path} would be cleaned/archived.")
    # Actual cleanup (e.g., shutil.rmtree(workspace_path)) should be implemented with caution.
    # For now, just create the marker.
    mark_step_complete(workspace_path, artifact_name)
    logger.info(f"Marked workspace cleanup as complete for {source_id}")


def main_workflow(source_input: str, source_type: str):
    logger.info(f"Starting main_workflow for source: {source_input} (type: {source_type})")

    source_id = get_source_id(source_input)
    workspace_path = get_workspace_path(source_id)
    ensure_dir_exists(workspace_path)
    logger.info(f"Generated Source ID: {source_id}")
    logger.info(f"Workspace: {workspace_path}")

    # Helper to get artifact path if step was complete, or run step
    def get_or_run_step(step_func, artifact_name_check, *args, **kwargs):
        # artifact_name_check is the primary artifact this step produces (e.g., "gemini_script.txt")
        # The .complete marker is derived from this (e.g., "gemini_script.txt.complete")

        # Check if the .complete marker exists
        if is_step_complete(workspace_path, artifact_name_check):
            logger.info(f"Step for '{artifact_name_check}' already complete. Loading artifact.")
            # Construct path to the artifact itself (not the .complete file)
            artifact_path = workspace_path / artifact_name_check
            if artifact_path.exists():
                # For file artifacts, read content if it's a text-based file (common case for this script)
                # For directory artifacts, just return path string
                if artifact_path.is_file():
                    # Specific handling for known return types if needed (e.g. JSON)
                    if artifact_name_check.endswith(".json"):
                        return load_json_config(artifact_path) # Returns dict or None
                    elif artifact_name_check.endswith(".txt"):
                         return artifact_path.read_text(encoding='utf-8')
                    else: # Other files (wav, mp4, etc.) just return path
                        return str(artifact_path)
                elif artifact_path.is_dir():
                    return str(artifact_path) # Return path for directories
            else:
                # This case (complete marker exists but artifact doesn't) indicates an issue.
                logger.error(f"Step for '{artifact_name_check}' marked complete, but artifact file/dir missing at {artifact_path}. Retrying step.")
                # Fall through to run the step again.

        # If not complete or artifact missing, run the step
        logger.info(f"Running step for '{artifact_name_check}'.")
        return step_func(*args, **kwargs)


    # --- Pipeline Execution ---
    input_content_for_script = None
    script_text_for_tts = None
    # tts_audio_path_for_assembly: Path to audio used for final video (original from link, or new TTS)
    tts_audio_path_for_assembly = None
    # audio_to_transcribe: Path to audio that needs transcription (could be same as tts_audio_path_for_assembly or different)
    audio_to_transcribe = None

    if source_type == 'text':
        input_content_for_script = get_or_run_step(step_01_process_text_input, "input_content.txt", source_input, workspace_path)
        if not input_content_for_script: logger.error("P1: Failed to process text input."); return

        # For text input, the script is generated, then TTS, then this TTS audio is transcribed
        # Step 03 now returns a path to a JSON file.
        generated_script_json_path = get_or_run_step(step_03_generate_gemini_script,
                                                     "generated_script.json",
                                                     input_content_for_script, workspace_path, is_video_source=False)
        if not generated_script_json_path or not pathlib.Path(generated_script_json_path).exists():
            logger.error("P1: Failed to generate Gemini script or script JSON file missing."); return

        script_data = load_json_config(pathlib.Path(generated_script_json_path))
        if not script_data or "script" not in script_data or not script_data["script"]:
            logger.error(f"P1: Script content not found or empty in {generated_script_json_path}."); return
        script_text_for_tts = script_data["script"]
        # We could also pass title and keywords to later steps if needed, e.g., for metadata or endscreen.
        # video_title_from_gemini = script_data.get("title", "Untitled Video")


        tts_audio_path_for_assembly = get_or_run_step(step_04_generate_tts_kokoro, "voiceover.wav", script_text_for_tts, workspace_path)
        if not tts_audio_path_for_assembly: logger.error("P1: Failed to generate TTS."); return
        audio_to_transcribe = tts_audio_path_for_assembly

    elif source_type == 'link':
        # For a video link, first "process" it (placeholder for download audio)
        downloaded_audio_path_str = get_or_run_step(step_02_process_video_link_input, "downloaded_audio.mp3", source_input, workspace_path)
        if not downloaded_audio_path_str :
             logger.warning(f"P2: Video link processing did not produce audio path for {source_input}. Transcription may use placeholder.")
             # Allow to proceed, step_05 handles missing audio file by creating dummy transcript.

        # Decision: Do we generate a new script for the video, or use its existing audio/transcript?
        # Current setup: Assume we always try to generate a new script (e.g., summary, different angle).
        # The `input_content_for_script` for a link could be the link itself, or fetched metadata. Here, it's the link.
        input_content_for_script = source_input
            generated_script_json_path_link = get_or_run_step(step_03_generate_gemini_script,
                                                              "generated_script.json",
                                                              input_content_for_script, workspace_path, is_video_source=True)
            if not generated_script_json_path_link or not pathlib.Path(generated_script_json_path_link).exists():
                logger.error("P2: Failed to generate Gemini script for video link or script JSON file missing."); return

            script_data_link = load_json_config(pathlib.Path(generated_script_json_path_link))
            if not script_data_link or "script" not in script_data_link or not script_data_link["script"]:
                 logger.error(f"P2: Script content not found or empty in {generated_script_json_path_link} for video link."); return
            script_text_for_tts_link = script_data_link["script"]
            # video_title_from_gemini_link = script_data_link.get("title", "Untitled Video")


        # Generate new TTS for the new script.
            new_tts_for_link_video = get_or_run_step(step_04_generate_tts_kokoro, "kokoro_tts.wav", script_text_for_tts_link, workspace_path)
        if not new_tts_for_link_video: logger.error("P2: Failed to generate TTS for new script."); return

        tts_audio_path_for_assembly = new_tts_for_link_video # This new TTS will be used for the final video
        audio_to_transcribe = new_tts_for_link_video # Transcribe the new TTS for captions

        # If the goal was to use video's ORIGINAL audio & transcribe THAT:
        # audio_to_transcribe = downloaded_audio_path_str
        # tts_audio_path_for_assembly = downloaded_audio_path_str
        # And step_03, step_04 might be skipped or conditional.
        # The current flow re-voices the video with a new script and TTS.
    else:
        logger.error(f"Invalid source_type: {source_type}. Aborting."); return

    if not audio_to_transcribe:
        logger.error("No audio designated for transcription. Aborting."); return

    transcript_path_for_spellcheck = get_or_run_step(step_05_transcribe_audio_local_whisper, "whisper_transcript.json", audio_to_transcribe, workspace_path)
    if not transcript_path_for_spellcheck: logger.error("Failed to transcribe audio."); return

    # The transcript_path_for_spellcheck is a path string. Load its content for next step if needed by that step directly.
    # Or, the step itself loads it. step_06_correct_spelling expects a path.
    corrected_transcript_path = get_or_run_step(step_06_correct_spelling, "corrected_transcript.json", transcript_path_for_spellcheck, workspace_path)
    if not corrected_transcript_path: logger.error("Failed to correct spelling."); return

    image_segments_path = get_or_run_step(step_07_parse_transcript_for_image_segments, "image_segments.json", corrected_transcript_path, workspace_path)
    if not image_segments_path: logger.error("Failed to parse transcript for image segments."); return

    # For step 8, we need the full transcript text from the corrected transcript JSON.
    full_transcript_text = ""
    if corrected_transcript_path and pathlib.Path(corrected_transcript_path).exists():
        corrected_transcript_data = load_json_config(pathlib.Path(corrected_transcript_path))
        if corrected_transcript_data and "text" in corrected_transcript_data:
            full_transcript_text = corrected_transcript_data["text"]
        else:
            logger.warning(f"Could not extract 'text' from corrected transcript at {corrected_transcript_path}")
    else:
        logger.error(f"Corrected transcript file missing at {corrected_transcript_path}, cannot get full text for Groq.")
        # Potentially abort if full_transcript_text is critical for step_08 and not handled by placeholder
        # return

    image_prompts_path = get_or_run_step(step_08_generate_image_prompts_groq, "image_prompts.json", image_segments_path, full_transcript_text, workspace_path)
    if not image_prompts_path: logger.error("Failed to generate image prompts."); return

    generated_images_dir = get_or_run_step(step_09_generate_images_comfyui, "generated_images", image_prompts_path, workspace_path)
    if not generated_images_dir: logger.error("Failed to generate images."); return # generated_images_dir is a path string

    animated_clips_dir = get_or_run_step(step_10_animate_images, "animated_clips", generated_images_dir, image_segments_path, workspace_path)
    if not animated_clips_dir: logger.error("Failed to animate images."); return

    if not tts_audio_path_for_assembly: # Should have been set based on source_type
        logger.error("TTS audio path for assembly not available. Cannot assemble video."); return

    raw_video_path = get_or_run_step(step_11_assemble_video_moviepy, "raw_video.mp4", tts_audio_path_for_assembly, animated_clips_dir, image_segments_path, workspace_path)
    if not raw_video_path: logger.error("Failed to assemble video."); return

    captioned_video_path = get_or_run_step(step_12_generate_captions_moviepy, "captioned_video.mp4", raw_video_path, corrected_transcript_path, workspace_path)
    if not captioned_video_path: logger.error("Failed to generate captions."); return

    final_video_ws_path = get_or_run_step(step_13_add_endscreen_moviepy, "final_video_with_endscreen.mp4", captioned_video_path, workspace_path)
    if not final_video_ws_path: logger.error("Failed to add endscreen."); return

    # Finalization step: check based on final destination
    final_video_name_for_check = f"{source_id}_final.mp4"
    final_dest_output_path = FINAL_VIDEO_DIR / final_video_name_for_check
    finalized_video_actual_path = None

    # Check if the final video already exists in the destination.
    # The finalize step also has an internal workspace marker "final_video_name.finalized.complete"
    ws_finalize_marker = f"{final_video_name_for_check}.finalized"

    if not final_dest_output_path.exists() or not is_step_complete(workspace_path, ws_finalize_marker) :
        finalized_video_actual_path = step_14_finalize_video(final_video_ws_path, source_id, FINAL_VIDEO_DIR)
        if not finalized_video_actual_path:
            logger.error("Failed to finalize video (move to output directory).")
            # Don't return, cleanup should still run.
        else:
            logger.info(f"Workflow complete! Final video at: {finalized_video_actual_path}")
    else:
        finalized_video_actual_path = str(final_dest_output_path)
        logger.info(f"Workflow complete! Final video was already at: {finalized_video_actual_path}")


    get_or_run_step(step_15_cleanup_workspace, "workspace_cleaned.done", workspace_path, source_id, LOG_DIR)
    logger.info(f"Main workflow finished for source ID: {source_id}")


async def main():
    ensure_dir_exists(INPUT_DIR)
    ensure_dir_exists(WORKSPACE_DIR)
    ensure_dir_exists(FINAL_VIDEO_DIR)
    ensure_dir_exists(LOG_DIR)

    # Ensure channeltopics.json and Newlinks.txt exist with example content if not present
    # This is for easier first run for the user.
    example_topics_file = SCRIPT_DIR / "channeltopics.json"
    if not example_topics_file.exists():
        save_json_output(example_topics_file, {"topics": [{"name": "Example Topic - AI Future"}]})
        logger.info(f"Created example channeltopics.json. Please create '{INPUT_DIR / 'Example Topic - AI Future.txt'}' to process it.")
        # Create a dummy input file for this example topic
        ensure_dir_exists(INPUT_DIR)
        with open(INPUT_DIR / "Example Topic - AI Future.txt", "w", encoding="utf-8") as f:
            f.write("This is an example topic about the future of AI. It can be multiple sentences long.")
        logger.info(f"Created example input file: {INPUT_DIR / 'Example Topic - AI Future.txt'}")


    example_links_file = INPUT_DIR / "Newlinks.txt"
    if not example_links_file.exists():
        ensure_dir_exists(INPUT_DIR)
        with open(example_links_file, "w", encoding="utf-8") as f:
            f.write("# Add YouTube video links here, one per line\n")
            f.write("# https://www.youtube.com/watch?v=exampledQw4w9WgXcQ\n") # Example, do not use real shorteners
        logger.info(f"Created example Newlinks.txt in {INPUT_DIR}. Add video links to process.")


    while True:
        print("\nSelect an option:")
        cprint("1. Process a text file from the input directory", "cyan")
        cprint("2. Process a YouTube video link", "cyan")
        cprint("3. Process all topics from channeltopics.json", "cyan")
        cprint("4. Process all links from Newlinks.txt", "cyan")
        cprint("5. (Placeholder) Generate Bible story videos", "yellow")
        cprint("0. Exit", "green")

        choice = input("Enter your choice: ")

        if choice == '1':
            text_file_name = input(f"Enter the name of the text file in '{INPUT_DIR}' (e.g., 'MyStory.txt'): ")
            source_file_path = INPUT_DIR / text_file_name.strip()
            if source_file_path.exists() and source_file_path.is_file():
                main_workflow(str(source_file_path), 'text')
            else:
                logger.error(f"File not found or is not a file: {source_file_path}")

        elif choice == '2':
            video_link = input("Enter the YouTube video link: ").strip()
            if video_link.startswith("http") and ("youtube.com/watch?v=" in video_link or "youtu.be/" in video_link) :
                main_workflow(video_link, 'link')
            else:
                logger.error("Invalid YouTube video link provided. Ensure it's a full watch URL (e.g., https://www.youtube.com/watch?v=...).")

        elif choice == '3':
            topics_file = SCRIPT_DIR / "channeltopics.json"
            if topics_file.exists():
                topics_data = load_json_config(topics_file)
                if topics_data and "topics" in topics_data:
                    for i, topic_item in enumerate(topics_data["topics"]):
                        topic_name = topic_item.get("name")
                        if topic_name:
                            sanitized_topic_name = re.sub(r'[^\w\s-]', '', topic_name).strip()
                            # Default to using .txt extension, can be configured in channeltopics.json if needed
                            topic_filename = topic_item.get("filename", f"{sanitized_topic_name}.txt")
                            source_file_path = INPUT_DIR / topic_filename

                            cprint(f"\nProcessing topic {i+1}/{len(topics_data['topics'])}: '{topic_name}' from file '{source_file_path}'", "magenta")
                            if source_file_path.exists() and source_file_path.is_file():
                                main_workflow(str(source_file_path), 'text')
                            else:
                                logger.error(f"Text file for topic '{topic_name}' not found at {source_file_path}. Please create it or check 'filename' in channeltopics.json.")
                        else:
                            logger.warning(f"Found a topic without a 'name' in {topics_file} at index {i}.")
                else:
                    logger.error(f"Could not load topics from {topics_file} or format is incorrect (expected {{'topics': [{{'name': '...'}}]}}).")
            else:
                logger.error(f"{topics_file} not found.")

        elif choice == '4':
            links_file = INPUT_DIR / "Newlinks.txt"
            if links_file.exists():
                with open(links_file, 'r', encoding='utf-8') as f:
                    video_links = [line.strip() for line in f if line.strip().startswith("http") and not line.strip().startswith("#")]
                if not video_links:
                    logger.warning(f"{links_file} contains no valid video links (must start with http and not be comments).")

                for i, link in enumerate(video_links):
                    cprint(f"\nProcessing link {i+1}/{len(video_links)}: {link}", "magenta")
                    if "youtube.com/watch?v=" in link or "youtu.be/" in link:
                         main_workflow(link, 'link')
                    else:
                         logger.warning(f"Skipping invalid or non-YouTube link: {link}")
            else:
                logger.error(f"{links_file} not found in {INPUT_DIR}")

        elif choice == '5':
            logger.warning("Bible story generation is not implemented yet.")
            # Example:
            # bible_stories_config = SCRIPT_DIR / "bible_stories.json"
            # if bible_stories_config.exists():
            #     stories = load_json_config(bible_stories_config)
            #     # process stories...
            # else:
            #    logger.error("bible_stories.json not found.")

        elif choice == '0':
            logger.info("Exiting application.")
            break
        else:
            logger.warning("Invalid choice. Please try again.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user. Exiting.")
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}", exc_info=True)
    finally:
        logging.shutdown()
        print("Application has shut down.")
