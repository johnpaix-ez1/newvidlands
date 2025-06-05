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
    logger.info(f" Called step_03_generate_gemini_script with text: {processed_text_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not genai:
        logger.warning(" Gemini library (google.generativeai) not found. Step 03 will produce minimal dummy script.")
    output_artifact_name = "generated_script_gemini.json" # As per plan
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    dummy_script_content = {
        "title": "Dummy Title from Placeholder",
        "scenes": [
            {"scene_number": 1, "narration": "This is a dummy narration for scene 1.", "visual_description": "A placeholder visual for scene 1."},
            {"scene_number": 2, "narration": "This is another dummy narration for scene 2.", "visual_description": "A placeholder visual for scene 2."}
        ]
    }
    save_json_output(output_path, {"status": "dummy output from placeholder step_03", "input_processed_text": processed_text_path_str, "script": dummy_script_content})
    mark_step_complete(workspace_path, "generated_script_gemini")
    logger.info(f" step_03_generate_gemini_script completed. Output: {str(output_path)}")
    return str(output_path)

def step_04_generate_tts_kokoro(script_path_str: str, workspace_path: pathlib.Path) -> str | None:
    logger.info(f" Called step_04_generate_tts_kokoro with script: {script_path_str}")
    time.sleep(3)  # Critical point: simulate processing delay
    if not KOKORO_AVAILABLE:
        logger.warning(" Kokoro TTS library not available. Step 04 will create a dummy WAV file.")
    output_artifact_name = "voiceover.wav"
    output_path = workspace_path / output_artifact_name
    ensure_dir_exists(output_path.parent)
    try:
        output_path.touch() # Create an empty file
        logger.info(f" Created dummy WAV file: {output_path}")
    except Exception as e:
        logger.error(f" Error creating dummy WAV for step_04: {e}.")
        return None
    mark_step_complete(workspace_path, "voiceover")
    logger.info(f" step_04_generate_tts_kokoro completed. Output: {str(output_path)}")
    return str(output_path)

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
    script_path = step_03_generate_gemini_script(processed_text, workspace_path)
    if not script_path:
        logger.error("Step 3 failed.")
        return

    # Step 4: Generate TTS
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
    image_prompts = step_08_generate_image_prompts_groq(image_segments, workspace_path)
    if not image_prompts:
        logger.error("Step 8 failed.")
        return

    # Step 9: Generate images
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
