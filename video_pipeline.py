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
import math # For step_10 calculations
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
    logger.info(f"Called step_01_process_text_input with input: {input_text_path_str}")
    time.sleep(1)  # Simulate processing delay

    output_artifact_name = "processed_text.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    try:
        # Try to load the input as JSON (if it's a .json file)
        if input_text_path_str.lower().endswith(".json"):
            with open(input_text_path_str, "r", encoding="utf-8") as f:
                input_data = json.load(f)
            # If the JSON is a dict with a 'text' or 'content' field, use that, else use the whole object
            if isinstance(input_data, dict):
                processed_content = input_data.get("text") or input_data.get("content") or json.dumps(input_data)
            else:
                processed_content = json.dumps(input_data)
        else:
            # Otherwise, treat as plain text
            with open(input_text_path_str, "r", encoding="utf-8") as f:
                processed_content = f.read()
    except Exception as e:
        logger.error(f"Failed to load input text for step_01: {e}")
        processed_content = ""

    save_json_output(output_path, {
        "status": "success" if processed_content else "error",
        "input_received": input_text_path_str,
        "processed_content": processed_content
    })
    mark_step_complete(workspace_path, "processed_text")
    logger.info(f"step_01_process_text_input completed. Output: {str(output_path)}")
    return str(output_path)

def step_02_process_video_link_input(video_url_str: str, workspace_path: pathlib.Path, cookies_file_path: str | None = None) -> str | None:
    """
    Downloads video info (and optionally the video) using yt-dlp for a given URL.
    If video_url_str is a path to a file (e.g., in 'input/link_sources'), loads the first non-empty line as the URL.
    """
    logger.info(f"Called step_02_process_video_link_input with URL or file: {video_url_str}")
    time.sleep(1)  # Simulate processing delay

    if not yt_dlp:
        logger.warning("yt-dlp library not found. Step 02 cannot process video links.")
        output_artifact_name = "downloaded_video_info.json"
        output_path = workspace_path / output_artifact_name
        ensure_dir_exists(output_path.parent)
        save_json_output(output_path, {"status": "dummy output from placeholder step_02", "video_url": video_url_str, "comment": "yt-dlp missing or actual download skipped"})
        mark_step_complete(workspace_path, "downloaded_video_info")
        logger.info(f"step_02_process_video_link_input completed. Output: {str(output_path)}")
        return str(output_path)

    # If input is a file, load the first non-empty line as the URL
    url = video_url_str
    if os.path.isfile(video_url_str):
        with open(video_url_str, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    url = line
                    break
        logger.info(f"Loaded URL from file: {url}")

    output_artifact_name = "downloaded_video_info.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "forcejson": True,
        "simulate": True,
    }
    if cookies_file_path:
        ydl_opts["cookiefile"] = cookies_file_path
    elif YTDLP_COOKIES_FILE:
        ydl_opts["cookiefile"] = YTDLP_COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        save_json_output(output_path, {"status": "success", "video_url": url, "video_info": info})
        mark_step_complete(workspace_path, "downloaded_video_info")
        logger.info(f"step_02_process_video_link_input completed. Output: {str(output_path)}")
        return str(output_path)
    except Exception as e:
        logger.error(f"yt-dlp failed to extract info: {e}")
        save_json_output(output_path, {"status": "error", "video_url": url, "error": str(e)})
        mark_step_complete(workspace_path, "downloaded_video_info")
        return str(output_path)

# Updated schema for Gemini output
GEMINI_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "new_video_title": {"type": "string"},
        "script": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["new_video_title", "script", "keywords"]
}

def validate_json_structure(data, schema):
    """Validate JSON data against a schema."""
    if not jsonschema:
        logger.warning("jsonschema library not available. Skipping validation.")
        return True  # Assume valid if we can't check
    try:
        jsonschema.validate(instance=data, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        logger.error(f"Validation error: {e}")
        return False

def step_03_generate_gemini_script(processed_text_path_str: str, workspace_path: pathlib.Path, script_instructions: str | None = None) -> str | None:
    logger.info(f"Called step_03_generate_gemini_script with text: {processed_text_path_str}")
    time.sleep(3)  # Simulate processing delay

    if not genai:
        logger.error("Gemini library (google.generativeai) not found. Step 03 cannot proceed.")
        return None

    # Load processed text from step 1 and use as transcript
    try:
        with open(processed_text_path_str, "r", encoding="utf-8") as f:
            processed_data = json.load(f)
        transcript = processed_data.get("processed_content", "")
    except Exception as e:
        logger.error(f"Failed to load processed text for Gemini script generation: {e}")
        return None

    # Compose the prompt (use your detailed instructions)
    prompt = f"""You are an expert content creator for a YouTube channel that produces concise, engaging, and insightful videos. make it just 25 to 30 seconds (100 to 120 words) long. Your task is to analyze the provided transcript and transform it into an **exceptionally compelling and unforgettable YouTube script** that makes viewers feel they've stumbled upon something truly unique and insightful. The goal is to maximize deep engagement, watch time, and a desire to share.
    Your task is to analyze the provided transcript and transform it into an **exceptionally compelling and unforgettable YouTube script** that makes viewers feel they've stumbled upon something truly unique and insightful. The goal is to maximize deep engagement, watch time, and a desire to share.

    - **Craft an Electrifying Introduction:** Start with a hook that is not just attention-grabbing but *paradigm-shifting* for the viewer regarding the topic. This could be a startling reframe of a common assumption, a deeply counter-intuitive question, a bold, almost unbelievable claim (that the script will then substantiate), or a vivid, unexpected analogy related to the transcript's core message. Aim for immediate intrigue and a "I *need* to know more" reaction. Examples of powerful hook approaches (adapt to the content): 'What if everything you thought you knew about X was a carefully constructed illusion?', 'The one tiny detail about Y that changes absolutely everything...', 'Forget X, Y, and Z; the *real* story behind [topic] is far more [adjective] than anyone dares to admit.'

    - **Deliver Content as a Riveting Unveiling:** Present the information not just clearly, but as a journey of discovery. Employ dynamic, conversational language that feels like an insider sharing groundbreaking secrets.
        - Use leading phrases that build anticipation and a sense of unique insight: 'But here's where it gets truly mind-bending...', 'The hidden layer most people miss is...', 'Consider this unexpected connection...', 'What if the real story is far stranger/simpler/more profound than we're led to believe?'
        - Weave in moments of **dramatic emphasis, unexpected comparisons, or sharp contrasts** to make key points land with impact and stick in the viewer's mind.
        - The script must feel like a human sharing a passionate, almost urgent message, not a dry recitation of facts. Infuse it with genuine curiosity and a sense of wonder or revelation.

    - **Engineer Engagement:**
        - **Maximize Curiosity Gaps:** Strategically pose questions or hint at revelations that compel viewers to keep watching to find the answer.
        - **Introduce Unexpected Twists or Perspectives:** If the transcript allows, present information in a way that challenges common perceptions or reveals a surprising angle on the topic. This should be done without being misleading or resorting to clickbait.
        - **Amplify Emotional Resonance (Authentically):** Where appropriate to the content, connect with the viewer on an emotional level. This isn't about forced sentimentality, but about highlighting the human impact, the 'wow' factor, the profound implications, or the sheer fascination of the information. Use vivid, evocative language.
        - **Viral-Optimized Tone (Substance over Hype):** The tone should be compelling and shareable, like top-tier educational or insight-driven YouTube channels. Focus on making the *substance itself* feel shocking, surprising, or highly relevant, rather than just using superficial hype. Persuasive language should stem from the power of the ideas being presented.
        - **Narrative Drive:** Structure the script like an unfolding mystery, a compelling argument being built piece by piece, or a journey to an 'aha!' moment. Ensure each segment logically and excitingly leads to the next.

    - **Maintain Factual Integrity and Clarity:**
        - Use simple to understand english for the understanding of someone who english is not thier first language. Do not use terms thats that need a dictionary to get its meaning, rather simpler word used in day to day conversation which still perfectly delivers the message. 
        - Don't mention the transcript even if its the source from which you got this information explain. Stop mentioning the source.
        - If its a news, report it as news not as a story clearly articulating what the news said
        - Avoids repeating exact words from the transcript by using synonyms and expanding with related ideas or examples.
        - Examine the content and determine whether it qualifies as news or should be categorized as opinion, analysis, or feature. Consider factors like timeliness, factual accuracy, and relevance in your judgment.
        - As you generate the script, cross-check any factual claims, dates, figures, or reported events with your own knowledge and understanding. If the content appears outdated, inaccurate, or misleading, adjust it accordingly to ensure factual accuracy and clarity. Do not include unverifiable or misleading claims in the final script.
        - If the video transcript, the author mentioned his or her name, focus only on the script and don't mention the persons name in the generated script.

    The script should also adhere to these specific formatting and style points:
    - Do not include asterisks (*) or emojis.
    - Begin with one of your example hooks (e.g.,'Hey ...', or 'Stop scrolling ...', 'What if I told you...', 'Here is some breaking news...'), ensuring it aligns with the 'Electrifying Introduction' goal above.
    - Flow seamlessly from one point to the next with transitional phrases. If the original script implies or contains numbered points, you can structure the generated script with numbering (e.g., first on our list, second, third...).
    - **Conclude with Impact and a Compelling Call to Action:** End not just with an intriguing question, but with one that **challenges the viewer's perspective or ignites a desire for further exploration/discussion.** For the call to action, instead of a generic "subscribe," frame it uniquely. For example: "If you're ready to keep uncovering the [adjective, e.g., 'hidden truths', 'extraordinary insights'] behind [channel's general topic], make sure you join our community of curious minds by subscribing and hitting that notification bell – you won't want to miss what's next."
    
    Additionally, generate:
    - A **new video title** that is catchy, informative, and optimized for YouTube.
    - A list of **keywords** relevant to the video's topic to enhance SEO and discoverability.

    Here's the provided transcript:

    {transcript}

    Please return the output as a JSON object in the following format:
    {{
        "new_video_title": "Your catchy video title",
        "keywords": ["keyword1", "keyword2", "keyword3"],
        "script": "The generated content here"
    }}
    """

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        logger.info("Raw Gemini API Response: %s", response.text)
        content = response.text

        # Extract JSON from the response using regex
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = content.strip()

        result = json.loads(json_str)

        if validate_json_structure(result, GEMINI_SCRIPT_SCHEMA):
            # Normalize and clean up script
            script = normalize_text(result["script"])
            script = script.replace("*", "")
            script = re.sub(r'\([^)]*\)', '', script)
            result["script"] = script

            # Save output
            output_artifact_name = "generated_script_gemini.json"
            output_path = workspace_path / output_artifact_name
            ensure_dir_exists(output_path.parent)
            save_json_output(output_path, {"status": "success", "input_processed_text": processed_text_path_str, "script": result})
            mark_step_complete(workspace_path, "generated_script_gemini")
            logger.info(f"step_03_generate_gemini_script completed. Output: {str(output_path)}")
            return str(output_path)
        else:
            logger.error("Gemini output JSON validation failed.")
            return None

    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding error from Gemini response: {e}")
    except Exception as e:
        logger.error(f"Error during Gemini script generation: {e}")

    return None

def step_04_generate_tts_kokoro(script_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Called step_04_generate_tts_kokoro with script: {script_path_str}")
    time.sleep(1)  # Simulate minimal processing delay

    output_artifact_name = "voiceover.wav"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    # Load script text from step 3 output
    try:
        with open(script_path_str, "r", encoding="utf-8") as f:
            script_json = json.load(f)

        # Robust extraction of the script text
        script_text = ""
        if (
            isinstance(script_json, dict)
            and "script" in script_json
            and isinstance(script_json["script"], dict)
            and "script" in script_json["script"]
            and isinstance(script_json["script"]["script"], str)
        ):
            script_text = script_json["script"]["script"]

        if not script_text.strip():
            logger.error("Script text is empty or invalid in step 3 output.")
            return None
    except Exception as e:
        logger.error(f"Failed to load script for TTS: {e}")
        return None

    if not KOKORO_AVAILABLE:
        logger.error("Kokoro TTS not available. Cannot generate TTS.")
        return None

    try:
        from kokoro_onnx import Kokoro
        kokoro = Kokoro(KOKORO_MODEL_FILE_PATH, KOKORO_VOICES_FILE_PATH)
        # Uncomment to debug available voices
        print("Available voices:", kokoro.voices)
        samples, sample_rate = kokoro.create(
            script_text,
            voice="af_bella",    # Change as needed
            speed=1.0,           # Optional
            lang="en-us"         # Optional, set if needed
        )
        sf.write(str(output_path), samples, sample_rate)
        logger.info(f"Generated TTS WAV file: {output_path}")
    except Exception as e:
        logger.error(f"Error generating TTS with Kokoro ONNX: {e}.")
        return None

    mark_step_complete(workspace_path, "voiceover")
    logger.info(f"step_04_generate_tts_kokoro completed. Output: {str(output_path)}")
    return str(output_path)


def step_05_transcribe_audio_local_whisper(audio_file_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"===========Called step_05_transcribe_audio_local_whisper with audio: {audio_file_path_str}")
    time.sleep(5)  # Wait to ensure file is written
    logger.info(f"AUDIO HERE SEEEE==================== audio: {audio_file_path_str}")


    if not os.path.exists(audio_file_path_str):
        logger.error(f"WAV file does not exist at {audio_file_path_str} before transcription!")
        return None

    output_artifact_name = "voiceover_transcription_detailed.txt"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    if not whisper:
        logger.error("OpenAI Whisper library not found. Step 05 cannot proceed.")
        return None

    # Check if the audio file exists before attempting to transcribe
    if not os.path.exists(audio_file_path_str):
        logger.error(f"WAV file does not exist at {audio_file_path_str} before transcription!")
        return None

    try:
        model = whisper.load_model("base")
        result = model.transcribe(audio_file_path_str)
        transcript_text = result.get("text", "")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(transcript_text)
        logger.info(f"Created transcript file using Whisper: {output_path}")
    except Exception as e:
        logger.error(f"Error transcribing audio with Whisper for step_05: {e}.")
        return None

    mark_step_complete(workspace_path, "voiceover_transcription_detailed")
    logger.info(f"step_05_transcribe_audio_local_whisper completed. Output: {str(output_path)}")
    return str(output_path)

def step_06_correct_spelling(transcript_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f"Called step_06_correct_spelling with transcript: {transcript_path_str}")
    time.sleep(1)  # Minimal processing delay

    # Load the transcript from step 5
    try:
        with open(transcript_path_str, 'r', encoding='utf-8') as f:
            transcript_text = f.read()
    except Exception as e:
        logger.error(f"Could not read transcript at {transcript_path_str} for step_06: {e}")
        return None

    # Find the original script from step 3
    script_json_path = workspace_path / "generated_script_gemini.json"
    try:
        with open(script_json_path, 'r', encoding='utf-8') as f:
            script_json = json.load(f)
        # Robust extraction of the script text
        original_script = ""
        if (
            isinstance(script_json, dict)
            and "script" in script_json
            and isinstance(script_json["script"], dict)
            and "script" in script_json["script"]
            and isinstance(script_json["script"]["script"], str)
        ):
            original_script = script_json["script"]["script"]
    except Exception as e:
        logger.warning(f"Could not read original script at {script_json_path} for step_06: {e}")
        original_script = ""

    # If SpellChecker is available, compare and correct only words that differ from the original script
    if SpellChecker and original_script:
        spell = SpellChecker()
        original_words = set(original_script.split())
        transcript_words = transcript_text.split()
        corrected_words = []
        for word in transcript_words:
            # If the word is not in the original script and is misspelled, correct it
            if word not in original_words and word.lower() not in spell and word.isalpha():
                corrected_word = spell.correction(word)
                corrected_words.append(corrected_word if corrected_word else word)
            else:
                corrected_words.append(word)
        corrected_text = " ".join(corrected_words)
    else:
        corrected_text = transcript_text  # No correction if SpellChecker or original script is missing

    # Save the corrected transcript back to the same file
    try:
        with open(transcript_path_str, 'w', encoding='utf-8') as f:
            f.write(corrected_text)
        logger.info(f"Corrected transcript saved to: {transcript_path_str}")
    except Exception as e:
        logger.error(f"Error saving corrected transcript for step_06: {e}")
        return None

    mark_step_complete(workspace_path, "corrected_transcription")
    logger.info(f"step_06_correct_spelling completed. Output: {transcript_path_str}")
    return transcript_path_str

def step_07_parse_transcript_for_image_segments(corrected_transcript_path_str: str, workspace_path: pathlib.Path) -> str | None:
    """
    Parses the transcript into segments for image prompt generation and animation.
    Each segment contains a text chunk and its estimated duration in seconds.
    Segmentation logic: split transcript into sentences, then group sentences into segments
    of 4–8 seconds (based on average reading speed).
    """
    logger.info(f"Called step_07_parse_transcript_for_image_segments with transcript: {corrected_transcript_path_str}")
    time.sleep(1)  # Simulate processing delay

    output_artifact_name = "image_segments.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)

    # Load transcript text
    try:
        with open(corrected_transcript_path_str, 'r', encoding='utf-8') as f:
            transcript_text = f.read().strip()
    except Exception as e:
        logger.error(f"Could not read transcript at {corrected_transcript_path_str}: {e}")
        return None

    # Split transcript into sentences using regex (handles ., !, ?)
    sentences = re.split(r'(?<=[.!?])\s+', transcript_text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Parameters for segmentation
    avg_words_per_sec = 2.5  # ~150 wpm
    min_segment_sec = 4
    max_segment_sec = 8

    segments = []
    curr_segment = []
    curr_word_count = 0
    segment_start_time = 0.0

    for sent in sentences:
        sent_word_count = len(sent.split())
        curr_segment.append(sent)
        curr_word_count += sent_word_count
        est_duration = curr_word_count / avg_words_per_sec

        # If estimated duration exceeds min_segment_sec or this is the last sentence, create a segment
        if est_duration >= min_segment_sec or sent == sentences[-1]:
            # Clamp duration to max_segment_sec if needed
            segment_duration = min(est_duration, max_segment_sec)
            segment_text = " ".join(curr_segment)
            segment_end_time = segment_start_time + segment_duration
            segments.append({
                "segment_id": f"scene_001_seg_{len(segments)+1:03d}",
                "text_segment": segment_text,
                "start_time": round(segment_start_time, 2),
                "end_time": round(segment_end_time, 2),
                "image_keywords": []  # To be filled in step 8
            })
            segment_start_time = segment_end_time
            curr_segment = []
            curr_word_count = 0

    save_json_output(output_path, {"segments": segments})
    mark_step_complete(workspace_path, "image_segments")
    logger.info(f"step_07_parse_transcript_for_image_segments completed. Output: {str(output_path)}")
    return str(output_path)

def step_08_generate_image_prompts_groq(image_segments_path_str: str, workspace_path: pathlib.Path, gemini_script_path_str: str | None = None) -> str | None:
    logger.info(f" Called step_08_generate_image_prompts_groq with segments: {image_segments_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not Groq:
        logger.warning(" Groq library not found. Step 08 will produce dummy image prompts.")
    output_artifact_name = "image_prompts_groq.json"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    image_segments_json = load_json_config(pathlib.Path(image_segments_path_str))
    generated_prompts_list = []
    if image_segments_json and "segments" in image_segments_json:
        for seg in image_segments_json["segments"]:
            segment_id = seg.get("segment_id", f"unknown_seg_{len(generated_prompts_list)+1}")
            text_segment = seg.get("text_segment", "A generic placeholder scene.")
            generated_prompts_list.append({
                "prompt_id": segment_id, "prompt_text": f"Dummy prompt for {segment_id}: {text_segment[:50]}...",
                "original_text_segment": text_segment, "segment_id": segment_id
            })
    else:
        generated_prompts_list.append({
            "prompt_id": "fallback_seg_001", "prompt_text": "Fallback dummy prompt.",
            "original_text_segment": "No segment data.", "segment_id": "fallback_seg_001"
        })
    final_prompts_output = {"image_prompts": generated_prompts_list}
    save_json_output(output_path, final_prompts_output)
    mark_step_complete(workspace_path, "image_prompts_groq")
    logger.info(f" step_08_generate_image_prompts_groq completed. Output: {str(output_path)}")
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
    "zoom_out": 1.2,  # Starts zoomed in, so prepared image needs to be at that initial zoomed size
    "pan_left": 1.25,
    "pan_right": 1.25,
    "pan_up": 1.25,
    "pan_down": 1.25,
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
    input_text_path = "input/text.txt"  # Path to the input text file
    workspace_path = WORKSPACE_DIR / "main_pipeline_workspace"
    ensure_dir_exists(workspace_path)

    # Step 1: Process text input
    processed_text = step_01_process_text_input(input_text_path, workspace_path)
    if not processed_text:
        logger.error("Step 1 failed.")
        return

    # Step 2: (Optional) Process video link input
    # video_info = step_02_process_video_link_input("https://example.com/video", workspace_path)
    # if not video_info:
    #     logger.error("Step 2 failed.")
    #     return

    # Step 3: Generate Gemini script
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set. Please configure it in your .env file. Exiting.")
        sys.exit(1)
    script_path = step_03_generate_gemini_script(processed_text, workspace_path)
    if not script_path:
        logger.error("Step 3 failed.")
        return

    # Step 4: Generate TTS
    if KOKORO_AVAILABLE:
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
    if not COMFYUI_SERVER_ADDRESS:
        logger.error("COMFYUI_SERVER_ADDRESS is not set. Please configure it in your .env file. Exiting.")
        sys.exit(1)

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
