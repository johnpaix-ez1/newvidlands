# Automated Video Generation Pipeline

**Table of Contents**
- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [Prerequisites](#prerequisites)
  - [Software](#software)
  - [External Services & Setups](#external-services--setups)
  - [Development Tools (Optional but Recommended)](#development-tools-optional-but-recommended)
- [Installation](#installation)
- [Usage](#usage)
  - [Running the Script](#running-the-script)
  - [Input Modes](#input-modes)
  - [Output](#output)
- [Troubleshooting](#troubleshooting)
  - [General Setup Issues](#general-setup-issues)
  - [API Key and External Service Issues](#api-key-and-external-service-issues)
  - [Library-Specific Issues](#library-specific-issues)
  - [Debugging Tips](#debugging-tips)
- [Recommended Environments](#recommended-environments)
  - [Operating System](#operating-system)
  - [Python Virtual Environments](#python-virtual-environments)
  - [Hardware Resources](#hardware-resources)
  - [Development & Experimentation](#development--experimentation)
- [Future Enhancements](#future-enhancements)

## Project Overview

This project is an automated video generation pipeline designed to transform various input sources into complete, engaging videos. Its primary purpose is to take textual content (from JSON files) or links to existing videos (e.g., YouTube) and process them through a series of steps to produce a final video that includes a synthesized voiceover, dynamically generated visuals, animations, and synchronized captions. The pipeline leverages a combination of cutting-edge AI services for content generation and local media processing libraries for audio-visual manipulation.

The system is built to be modular and resumable, allowing it to pick up from the last successfully completed step if interrupted. It manages its workspace by archiving intermediate files after processing, aiding in debugging and resource management.

## Key Features

The pipeline offers a comprehensive suite of capabilities to automate video creation:

*   **Multiple Input Sources:** Accepts input from:
    *   JSON text files (containing lists of text segments or structured content).
    *   Direct links to YouTube videos (for re-purposing or analysis-driven content generation).
*   **Automated Script Generation:** Utilizes the Gemini API to generate video scripts based on the input content.
*   **Text-to-Speech Voiceover:** Employs Kokoro-TTS (via `kokoro-onnx` and user-provided models) to create natural-sounding voiceovers from the generated scripts. Dummy TTS is used if models are not configured.
*   **Audio Transcription:** Integrates a local Whisper model (default: "base") for accurate audio transcription, including word-level timestamps. Falls back to dummy transcription if Whisper is unavailable.
*   **Spelling Correction:** Automatically corrects spelling errors in the generated transcripts using `pyspellchecker`. Continues with uncorrected text if the library is unavailable.
*   **Transcript Segmentation for Visuals:** Parses the transcript to define logical segments for timing image and animation sequences, using a customizable duration logic.
*   **AI-Powered Image Prompt Generation:** Leverages the Groq API (with Llama3-70b model by default) to create descriptive image prompts tailored to each text segment. Falls back to basic prompts if API access fails.
*   **Image Generation:** Interfaces with a ComfyUI server (via its API and WebSocket) to generate images based on the AI-generated prompts. Requires a user-configured ComfyUI instance and workflow. Falls back to dummy images if ComfyUI is not configured or fails.
*   **Dynamic Image Animation:** Animates still images using MoviePy with a diverse suite of randomized effects. Capabilities include static display, Ken Burns style zooms (in/out with easing), multi-directional pans (horizontal, vertical), diagonal pan/zoom combinations, rotations with zoom, and fade-ins. Animation parameters like zoom factor, angle, and easing functions are randomized for variety. Falls back to static animations if MoviePy has issues or if specific effects fail.
*   **Video Assembly:** Combines the synthesized voiceover, animated image clips, and optional background music (randomly selected from an `assets/bgsound` directory) into a cohesive video sequence using MoviePy.
*   **Automated Caption Generation:** Creates styled, segment-level captions from the transcript and overlays them onto the video, synchronized with the voiceover, using MoviePy. Font and basic styling are configurable. Falls back to video without captions if captioning fails.
*   **Customizable Endscreen:** Allows for the addition of a pre-defined endscreen video (configured via `.env`) to the final output. Skips if endscreen is not configured or invalid.
*   **Resumable Workflow:** Each major processing step marks its completion in the workspace, enabling the pipeline to resume from where it left off in case of interruptions.
*   **Automated Workspace Management:** Organizes all intermediate files for each source within a dedicated workspace directory. Upon successful completion of a source (or critical failure), this workspace is archived into the `logs/{source_id}/` directory for review, and the final video is moved to `final_videos/`.
*   **Batch Processing & Interactive Mode:**
    *   Prioritizes processing new text sources listed in `channeltopics.json`.
    *   Then processes new YouTube links listed in `input/Newlinks.txt`.
    *   Tracks processed items in log files (`logs/used_channeltopics.json`, `logs/used_newlinks.txt`) to avoid redundant work across sessions.
    *   If no pending batch items are found, an interactive menu allows for single file/link processing, re-checking batch queues, or exiting.
*   **Configuration via `.env`:** Key API credentials, paths to models/assets, and server addresses are managed through an environment file (`.env`) for security and ease of setup. Example batch files and asset placeholders are created on first run if missing.

This pipeline aims to significantly reduce the manual effort involved in creating short-form informational or entertainment videos.

## Prerequisites

### Software

*   **Python:** Python 3.10 or newer is recommended.
*   **FFmpeg:** Required by MoviePy (for video editing) and yt-dlp (for audio extraction from video links). FFmpeg must be installed on your system and accessible via the system's PATH. You can download it from [ffmpeg.org](https://ffmpeg.org/download.html).
*   **Git:** For cloning this repository and managing updates.

### External Services & Setups

*   **Google Gemini API Key:** Necessary for automated script generation (Step 03). The script will exit if not configured.
    *   Obtain an API key from [Google AI Studio](https://aistudio.google.com/app/apikey) or your Google Cloud Console project.
*   **Groq API Key:** Required for generating image prompts from text segments (Step 08). The script will exit if not configured.
    *   Obtain an API key from the [GroqCloud Console](https://console.groq.com/keys).
*   **ComfyUI Server:** A running instance of ComfyUI is essential for image generation (Step 09). The script will exit if the server address is not configured or the workflow file is missing/invalid.
    *   The server must be accessible via HTTP (for API calls like fetching history) and WebSocket (for real-time progress updates and image fetching). The `video_pipeline.py` script will prefix `http://` or `ws://` as needed, so provide only `host:port` (e.g., `127.0.0.1:8188`) in the `.env` configuration.
    *   For installation and setup instructions, refer to the [ComfyUI GitHub repository](https://github.com/comfyanonymous/ComfyUI).
    *   You will also need a ComfyUI workflow JSON file that is compatible with the API. A default placeholder is provided in `assets/default_comfyui_workflow.json`, but should be replaced with a functional workflow. The script will check for its existence.
*   **Kokoro TTS Models:** For actual Text-to-Speech generation with Kokoro-TTS (Step 04), you need the model and voices files. If the Kokoro library is available but these files are not found at the configured paths, the script will exit.
    *   Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [Kokoro-ONNX GitHub releases page](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
    *   These files need to be placed in a location accessible by the script, configured via `.env` variables (see Installation section). If not provided or found (and Kokoro is installed), dummy TTS audio will be generated.
*   **(Optional) YouTube Cookies:** If you plan to process age-restricted or login-required YouTube videos using `yt-dlp`, you may need to provide a browser cookie file.
    *   This can be configured via the `YTDLP_COOKIES_FILE` variable in your `.env` file.
    *   Refer to `yt-dlp` documentation for instructions on how to export cookies (e.g., using a browser extension).

### Development Tools (Optional but Recommended)

*   **Code Editor:** A modern code editor such as [Visual Studio Code](https://code.visualstudio.com/) is recommended for easier script modification and management.
*   **Terminal/Command Prompt:** For running the script, managing Python environments, and Git operations.

## Running in Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.google.com/github/johnpaix-ez1/newvidlands/blob/main/video_pipeline_colab.ipyn works:**

You can also run this video generation pipeline in a Google Colab notebook. This is useful for leveraging Google's free GPU resources (subject to availability and limits) for tasks like AI model inference and for an environment where Python and many common libraries are already accessible.

A dedicated Colab notebook, `video_pipeline_colab.ipynb`, is provided in this repository.

### Prerequisites for Colab

*   A Google Account.
*   Access to Google Drive.
*   It's recommended to clone this repository or at least download the `video_pipeline_colab.ipynb` file and the entire `assets/` directory.

### Setup and Usage in Colab

1.  **Upload to Google Drive:**
    *   Create a main project folder in your Google Drive, for example, `VideoPipelineProject`.
    *   Upload the `video_pipeline_colab.ipynb` notebook into this `VideoPipelineProject` folder (or directly to your Drive root if you prefer, but you'll need to adjust paths in the notebook).
    *   Upload the entire `assets/` directory (from this repository) into your `VideoPipelineProject` folder in Google Drive, so you have `VideoPipelineProject/assets/`.
        *   **Kokoro TTS Models:** You **must** obtain the Kokoro TTS model files (`kokoro-v1.0.onnx` and `voices-v1.0.bin` as mentioned in the main "Installation > Set Up Assets" section) and place them in a location accessible from your Drive, for example, within the `VideoPipelineProject/assets/kokoro_models/` directory. Then, ensure the paths in the "Configure External Services and Model Paths" setup cell in the notebook correctly point to these files.
    *   Upload your input files (e.g., text source JSON files) to the appropriate subdirectory within your `VideoPipelineProject` folder, for example, `VideoPipelineProject/input/text_sources/`.

2.  **Open and Configure Notebook:**
    *   Open Google Colab and upload/open the `video_pipeline_colab.ipynb` notebook from your Google Drive.
    *   Carefully follow the instructions in the **Setup** section at the beginning of the notebook:
        *   **(New) Clone Repository:** Run the cell that executes `!git clone ...` to download the repository files into your Colab environment. You'll need to replace the placeholder URL in that cell with the actual URL of this repository.
        *   **Run pip installs:** Execute the cell that installs all required Python packages.
        *   **Configure API Keys:** Enter your API keys for Google Gemini and Groq when prompted by the input fields (or modify the cells to use Colab UserData secrets).
        *   **Mount Google Drive:** Run the cell to mount your Google Drive. You'll need to authorize this.
        *   **Verify Paths:**
            *   Check and, if necessary, modify the `DRIVE_PROJECT_BASE_PATH` variable in the "Define File Paths" cell to match the location where you placed the `VideoPipelineProject` folder in your Drive (e.g., `/content/drive/MyDrive/VideoPipelineProject`).
            *   Verify that paths to assets like `COMFYUI_WORKFLOW_FILE`, `KOKORO_MODEL_FILE_PATH`, `ENDSCREEN_VIDEO_FILE` in the "Configure External Services and Model Paths" cell are correct based on where you uploaded the `assets` directory and Kokoro models.
        *   **ComfyUI Server:** If you plan to use ComfyUI, ensure the `COMFYUI_SERVER_ADDRESS` in the notebook is correctly set to your accessible ComfyUI instance (this might involve using ngrok if your ComfyUI is local).

3.  **Run the Pipeline:**
    *   Once the setup cells are executed and configured, you can proceed to run the subsequent cells containing the pipeline logic.
    *   The `main()` function cell defines an example `input_text_path`. You may need to modify this path to point to your specific input file within the `INPUT_DIR` on your Google Drive.
    *   Run the final cell that calls `main()` to start the video generation process.

4.  **Outputs:**
    *   Final videos and logs will be saved to the directories specified in the notebook's path definitions (e.g., `VideoPipelineProject/final_videos/` and `VideoPipelineProject/logs/` on your Google Drive).

### Notes for Colab Usage

*   **Resource Limits:** Be mindful of Colab's usage limits for CPU, GPU, RAM, and disk space. Long or complex video processing can be resource-intensive.
*   **Session Storage:** Files saved outside of your mounted Google Drive (e.g., directly in `/content/`) are temporary and will be deleted when the Colab session ends. The notebook is configured to save outputs to your Drive.
*   **Interactivity:** The Colab notebook runs the script non-interactively by default (executing the `main` function directly). The interactive menu from the original `video_pipeline.py` is not the primary mode of operation in the notebook.

[Link to the Colab Notebook: video_pipeline_colab.ipynb](./video_pipeline_colab.ipynb)

## Troubleshooting
### General Setup Issues

## Prerequisites

### Software

*   **Python:** Python 3.10 or newer is recommended.
*   **FFmpeg:** Required by MoviePy (for video editing) and yt-dlp (for audio extraction from video links). FFmpeg must be installed on your system and accessible via the system's PATH. You can download it from [ffmpeg.org](https://ffmpeg.org/download.html).
*   **Git:** For cloning this repository and managing updates.

### External Services & Setups

*   **Google Gemini API Key:** Necessary for automated script generation (Step 03). The script will exit if not configured.
    *   Obtain an API key from [Google AI Studio](https://aistudio.google.com/app/apikey) or your Google Cloud Console project.
*   **Groq API Key:** Required for generating image prompts from text segments (Step 08). The script will exit if not configured.
    *   Obtain an API key from the [GroqCloud Console](https://console.groq.com/keys).
*   **ComfyUI Server:** A running instance of ComfyUI is essential for image generation (Step 09). The script will exit if the server address is not configured or the workflow file is missing/invalid.
    *   The server must be accessible via HTTP (for API calls like fetching history) and WebSocket (for real-time progress updates and image fetching). The `video_pipeline.py` script will prefix `http://` or `ws://` as needed, so provide only `host:port` (e.g., `127.0.0.1:8188`) in the `.env` configuration.
    *   For installation and setup instructions, refer to the [ComfyUI GitHub repository](https://github.com/comfyanonymous/ComfyUI).
    *   You will also need a ComfyUI workflow JSON file that is compatible with the API. A default placeholder is provided in `assets/default_comfyui_workflow.json`, but should be replaced with a functional workflow. The script will check for its existence.
*   **Kokoro TTS Models:** For actual Text-to-Speech generation with Kokoro-TTS (Step 04), you need the model and voices files. If the Kokoro library is available but these files are not found at the configured paths, the script will exit.
    *   Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [Kokoro-ONNX GitHub releases page](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
    *   These files need to be placed in a location accessible by the script, configured via `.env` variables (see Installation section). If not provided or found (and Kokoro is installed), dummy TTS audio will be generated.
*   **(Optional) YouTube Cookies:** If you plan to process age-restricted or login-required YouTube videos using `yt-dlp`, you may need to provide a browser cookie file.
    *   This can be configured via the `YTDLP_COOKIES_FILE` variable in your `.env` file.
    *   Refer to `yt-dlp` documentation for instructions on how to export cookies (e.g., using a browser extension).

### Development Tools (Optional but Recommended)

*   **Code Editor:** A modern code editor such as [Visual Studio Code](https://code.visualstudio.com/) is recommended for easier script modification and management.
*   **Terminal/Command Prompt:** For running the script, managing Python environments, and Git operations.

## Installation

1.  **Clone the Repository:**
    Replace `<repository_url>` with the actual URL of this repository and `<repository_directory>` with your preferred local directory name.
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and Activate a Python Virtual Environment:**
    Using a virtual environment is highly recommended to manage dependencies.
    *   **Using `venv` (standard Python):**
        ```bash
        python -m venv venv
        ```
        Activate the environment:
        ```bash
        # On Windows
        venv\Scripts\activate
        ```
        ```bash
        # On macOS/Linux
        source venv/bin/activate
        ```
    *   **Alternative (e.g., `conda`):**
        If you prefer `conda`, you can create an environment with:
        ```bash
        conda create -n video_pipeline_env python=3.10
        conda activate video_pipeline_env
        ```

3.  **Install Dependencies:**
    Once your virtual environment is activated, install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    API keys, server addresses, and other configurations are managed via an `.env` file.
    *   Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    *   Edit the `.env` file with your actual credentials and settings.
    *   **Required Variables (must be filled):**
        *   `GEMINI_API_KEY`: Your API key for Google Gemini.
        *   `GROQ_API_KEY`: Your API key for GroqCloud.
        *   `COMFYUI_SERVER_ADDRESS`: The address of your running ComfyUI server (e.g., `127.0.0.1:8188`). **Important:** Do not include `http://` or `ws://` prefixes here; the script handles adding them.
    *   **Customizable Variables (have defaults but can be overridden):**
        *   `COMFYUI_WORKFLOW_FILE`: Path to your ComfyUI API workflow JSON.
            *   Default: `assets/default_comfyui_workflow.json`
        *   `ENDSCREEN_VIDEO_FILE`: Path to your endscreen video.
            *   Default: `assets/default_endscreen.mp4`
        *   `KOKORO_MODEL_FILE_PATH`: Path to the `kokoro-v1.0.onnx` model file.
            *   Default: `assets/kokoro_models/kokoro-v1.0.onnx`
        *   `KOKORO_VOICES_FILE_PATH`: Path to the `voices-v1.0.bin` voices file.
            *   Default: `assets/kokoro_models/voices-v1.0.bin`
        *   `YTDLP_COOKIES_FILE`: (Optional) Absolute or relative path to your `cookies.txt` file for `yt-dlp`.

5.  **Set Up Assets:**
    The pipeline expects certain assets to be present in the `assets/` directory. Default placeholder files are provided for some, and example batch files are created on first run.
    *   **ComfyUI Workflow (`assets/default_comfyui_workflow.json` or custom path):**
        *   The file specified by `COMFYUI_WORKFLOW_FILE` in your `.env` file must be a valid ComfyUI API workflow JSON.
        *   The default `assets/default_comfyui_workflow.json` is a **placeholder** and **must be replaced** with your own functional workflow designed for API use.
    *   **Kokoro TTS Models (`assets/kokoro_models/` or custom paths):**
        *   Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [Kokoro-ONNX GitHub releases](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
        *   Create a directory, e.g., `assets/kokoro_models/`.
        *   Place the downloaded `.onnx` and `.bin` files into this directory.
        *   If you use this recommended directory structure, the default paths for `KOKORO_MODEL_FILE_PATH` and `KOKORO_VOICES_FILE_PATH` in your `.env` file (copied from `.env.example`) will point to these files correctly.
        *   If you place the files elsewhere, you **must** update `KOKORO_MODEL_FILE_PATH` and `KOKORO_VOICES_FILE_PATH` in your `.env` file with the correct absolute or relative paths.
    *   **Fonts (`assets/fonts/`):**
        *   Place `.ttf` or `.otf` font files in this directory.
        *   A placeholder `LiberationSans-Regular.ttf` is included.
    *   **Background Sounds (`assets/bgsound/`):**
        *   Place background audio files (e.g., `.mp3`, `.wav`) here.
        *   A placeholder `dummy_bg.mp3` is included.
    *   **Endscreen Video (`assets/default_endscreen.mp4` or custom path):**
        *   The file specified by `ENDSCREEN_VIDEO_FILE` should be your desired endscreen video.
        *   The provided `assets/default_endscreen.mp4` is an empty placeholder.
    *   **Input Files (`input/text_sources/`, `input/Newlinks.txt`, `channeltopics.json`):**
        *   The script will create example versions of `channeltopics.json` (in the script root), `input/Newlinks.txt`, and dummy source files in `input/text_sources/` if they don't exist on first run. Edit these with your actual input topics and links.

## Usage

### Running the Script

Ensure your Python virtual environment is activated and all dependencies and configurations are set up as described above.

To run the pipeline, execute:
```bash
python video_pipeline.py
```
Upon running, the script will first attempt to process any pending items from the batch input files (`channeltopics.json` and `Newlinks.txt`). If no batch items are found, or after all batch items are processed, an interactive menu will appear, allowing you to choose further actions.

### Input Modes

The pipeline supports both batch and interactive input modes:

**Batch Processing (Automatic on Startup):**
*   The script automatically checks for and processes pending items from the following files in order:
    1.  **Text Sources (from `channeltopics.json`):**
        *   The script looks for `channeltopics.json` in its root directory.
        *   This file should contain a JSON list of topic names (strings). For each topic name, the script expects a corresponding JSON source file at `input/text_sources/{topic_name}.json`.
        *   Processed topics are logged in `logs/used_channeltopics.json` to avoid reprocessing in subsequent runs.
    2.  **Link Sources (from `Newlinks.txt`):**
        *   After processing all available text sources, the script checks `input/Newlinks.txt`.
        *   Each line in this file should be a direct YouTube video URL. Lines starting with `#` are ignored.
        *   Processed links are logged in `logs/used_newlinks.txt`.
*   The script will loop, prioritizing text sources, then link sources, until both queues are clear for the current session.

**Interactive Menu (Appears after batch processing or if queues are initially empty):**

1.  **Process a single Text File:**
    *   Prompts for the name of a JSON text file (e.g., `MyStory.json`) expected to be in the `input/text_sources/` directory. You can also provide a full or relative path.
    *   **Expected JSON Format:**
        *   A direct list of strings: `["Segment 1...", "Segment 2..."]`
        *   Or, an object with a "content" key: `{"title": "Title", "content": ["Segment 1...", "Segment 2..."]}`
2.  **Process a single YouTube Link:**
    *   Prompts for a full YouTube video URL.
3.  **Re-check Batch Items and Process:**
    *   This option will cause the script to return to the batch processing mode, re-scanning `channeltopics.json` and `Newlinks.txt` for any new items not yet logged as processed.
4.  **Exit Pipeline:**
    *   Terminates the script.

If an interactive processing option (1 or 2) or the re-check option (3) is chosen, the script will perform that action and then loop back to prioritize batch processing before potentially showing the menu again.

### Output

*   **Final Videos:**
    *   Successfully generated videos are saved in the `final_videos/` directory (path is configurable via `FINAL_VIDEO_DIR` in `video_pipeline.py`, default is relative to script location).
    *   Filenames typically include the unique `source_id` (e.g., `MyStory_json_xxxxxxx_final.mp4`).
*   **Logs and Archives:**
    *   **Workspace Archives:** For each processed source, all intermediate files are archived from `workspace/{source_id}/` to `logs/{source_id}/workspace_archive/`. This aids in debugging.
    *   **Application Log:** The script primarily logs to the console. Detailed step outputs and any errors can be found within the console output for a specific run. The `logs/` directory also contains `used_channeltopics.json`, `used_newlinks.txt` (tracking processed batch items), and a `cleanup_complete.marker` inside each source's archive directory upon successful cleanup.

This pipeline aims to significantly reduce the manual effort involved in creating short-form informational or entertainment videos.

## Troubleshooting

### General Setup Issues

*   **Problem:** `ModuleNotFoundError: No module named 'some_library'`
    *   **Solution:** Ensure you have activated your Python virtual environment (e.g., `source venv/bin/activate` or `venv\Scripts\activate`). Then, install all required dependencies by running `pip install -r requirements.txt` from the project's root directory.
*   **Problem:** `ffmpeg: command not found` (or similar errors from MoviePy or yt-dlp during video/audio processing).
    *   **Solution:** FFmpeg is a crucial dependency for video and audio manipulation. Install it from the official [FFmpeg website](https://ffmpeg.org/download.html) and ensure that the directory containing the `ffmpeg` (and `ffprobe`) executable is added to your system's PATH environment variable.
*   **Problem:** Script fails with `FileNotFoundError` for assets like workflows, fonts, or endscreen videos.
    *   **Solution:**
        *   Verify that all paths specified in your `.env` file (e.g., `COMFYUI_WORKFLOW_FILE`, `ENDSCREEN_VIDEO_FILE`, `KOKORO_MODEL_FILE_PATH`, `KOKORO_VOICES_FILE_PATH`) are correct.
        *   Ensure the `assets/` directory and its subdirectories (`fonts/`, `bgsound/`, `kokoro_models/`) are present in the project root and contain the necessary files.
        *   Always run `python video_pipeline.py` from the root directory of the project.

### API Key and External Service Issues

*   **Problem:** Errors related to the Google Gemini API (e.g., authentication, permission denied, quota exceeded).
    *   **Solution:** Double-check that your `GEMINI_API_KEY` in the `.env` file is correct and has been activated for use with the Gemini API. Ensure the API is enabled in your Google Cloud project associated with the key. Check your usage quotas in the Google AI Studio or Google Cloud Console.
*   **Problem:** Errors related to the Groq API (e.g., authentication, rate limits).
    *   **Solution:** Verify that the `GROQ_API_KEY` in your `.env` file is correct. Check the GroqCloud platform for API status, any potential rate limits, or issues with your account.
*   **Important Change: Stricter Configuration Enforcement**
    *   The pipeline will now terminate with an error if essential API keys (like `GEMINI_API_KEY`, `GROQ_API_KEY`) or critical configurations (such as `COMFYUI_SERVER_ADDRESS`, paths to Kokoro models if Kokoro library is present, or a valid ComfyUI workflow file) are not properly set in your `.env` file or if specified files are missing.
    *   This replaces previous behavior where some steps might have proceeded using placeholder or dummy data.
    *   Please ensure all required configurations are accurate in your `.env` file and that all necessary files (e.g., Kokoro models, ComfyUI workflow) are present at the specified paths to prevent interruption.
*   **Problem:** ComfyUI connection errors (e.g., `ConnectionRefusedError` when the script tries to connect to the ComfyUI server).
    *   **Solution:**
        *   Make sure your ComfyUI server instance is running.
        *   Confirm that it's accessible at the address specified in `COMFYUI_SERVER_ADDRESS` in your `.env` file (default `127.0.0.1:8188`). The script expects only `host:port`.
        *   If ComfyUI is running on a different machine or in a Docker container, ensure firewall rules and network configurations allow connections from where you're running the `video_pipeline.py` script.
*   **Problem:** ComfyUI reports errors during image generation (e.g., workflow validation errors, missing custom nodes, model load failures).
    *   **Solution:**
        *   The path specified in `COMFYUI_WORKFLOW_FILE` in your `.env` file must point to a valid ComfyUI API workflow JSON. The default one provided is a placeholder.
        *   Ensure that all custom nodes, models (checkpoints, LoRAs, VAEs, ControlNets, etc.), and any other dependencies required by your specific ComfyUI workflow are correctly installed and named within your ComfyUI server setup.
        *   It's highly recommended to test your workflow thoroughly in the ComfyUI web interface first to ensure it runs correctly and produces the desired type of images.
        *   Check the logs from your ComfyUI server console for more detailed error messages that can pinpoint the issue within the workflow or model loading.

### Library-Specific Issues

*   **Problem:** Errors from `kokoro-onnx` or `onnxruntime` during Text-to-Speech (TTS) generation, or dummy TTS is always used.
    *   **Solution:**
        *   Ensure `KOKORO_MODEL_FILE_PATH` and `KOKORO_VOICES_FILE_PATH` in your `.env` file correctly point to your downloaded `kokoro-v1.0.onnx` and `voices-v1.0.bin` files. If the Kokoro library itself is installed, the script will now exit if these files are not found at the specified paths.
        *   Verify the files were downloaded correctly and are not corrupted from the [Kokoro-ONNX GitHub releases](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
        *   These libraries can sometimes have specific compatibility requirements. Ensure you are using a compatible Python version. There might be version conflicts with `onnxruntime` or other dependencies. Check the `kokoro-onnx` GitHub repository for any reported issues.
        *   If the Kokoro library (`kokoro-onnx`) is not installed, the script will still fall back to dummy TTS.
*   **Problem:** Errors from `openai-whisper` during audio transcription (e.g., model download failure, `ffmpeg` not found by Whisper, CUDA errors if using GPU).
    *   **Solution:**
        *   A stable internet connection is needed when Whisper downloads a model for the first time.
        *   Whisper also relies on `ffmpeg` being accessible. Ensure FFmpeg is installed and in your system's PATH (see "General Setup Issues").
        *   If you have a compatible NVIDIA GPU and wish to use it, ensure your CUDA toolkit and cuDNN versions are correctly installed and compatible with PyTorch (which Whisper uses). If you don't intend to use GPU, Whisper will default to CPU.
        *   The script falls back to dummy transcription if Whisper encounters an error.
*   **Problem:** `yt-dlp` fails to download a video (e.g., "Video unavailable", "Access denied").
    *   **Solution:**
        *   The video might be private, members-only, age-restricted, or geographically restricted.
        *   For age-restricted or login-required content, providing a `YTDLP_COOKIES_FILE` path in your `.env` file can help. This file should be a `cookies.txt` exported from a browser where you are logged into YouTube.
        *   Check the specific error messages from `yt-dlp` in the console output for more clues. Sometimes, updating `yt-dlp` to the latest version (`pip install --upgrade yt-dlp`) can resolve issues with newly unsupported sites or formats.

### Debugging Tips

*   **Check Console Output & Logs:** The script logs information about each step, including warnings and errors, to the console. This is the primary place to look for issues.
*   **Examine Workspace Archives:** If a video generation process completes (even with fallbacks), the intermediate files for that source are archived in `logs/{source_id}/workspace_archive/` (where `LOG_DIR` is `logs/` by default). Inspecting the files here (e.g., downloaded audio, generated prompts, individual images, manifest files for each step) can help pinpoint where a problem occurred or why an output isn't as expected.
*   **Isolate Steps (For Developers):** If you are comfortable modifying the script, you can temporarily comment out later stages in `main_workflow` to run only the problematic step or the steps leading up to it. This can help focus debugging efforts.
*   **Test with Simple Inputs:** Use very short, simple text for text-based inputs, or try a very common, unrestricted YouTube link to see if the issue is with the input data itself or a core part of the pipeline.
*   **Verify Library Versions:** In rare cases, conflicts between the versions of different libraries can cause unexpected behavior. If you suspect this, consider creating a fresh Python virtual environment and reinstalling dependencies from `requirements.txt`. Check for any warnings during `pip install`.

## Recommended Environments

### Operating System

*   **Linux (Recommended):**
    *   Distributions like Ubuntu (e.g., Ubuntu 20.04 LTS or 22.04 LTS) are highly recommended.
    *   **Reasoning:** Linux environments generally offer better out-of-the-box support and stability for many AI/ML libraries (like PyTorch, TensorFlow, ONNX Runtime), media processing tools (FFmpeg), and GPU drivers (NVIDIA). Package management is often more straightforward for development dependencies.
*   **Windows / macOS:**
    *   The pipeline *can* run on Windows and macOS. However, users might encounter more setup hurdles, particularly with:
        *   **FFmpeg:** Ensuring it's correctly installed and in the system PATH.
        *   **GPU Drivers & AI Libraries:** Setting up NVIDIA drivers and CUDA for GPU acceleration with PyTorch (for Whisper) can be more complex.
        *   **Library Compatibility:** Some libraries, like `kokoro-onnx` or specific versions of `onnxruntime`, might have OS-specific considerations or precompiled binaries that work more smoothly on Linux.
    *   **WSL (Windows Subsystem for Linux):** For Windows users experiencing issues, using WSL 2 can provide a more Linux-like environment and often simplifies the setup for Python-based AI/ML projects.

### Python Virtual Environments

*   **Strongly Recommended:** Using Python virtual environments (e.g., `venv` module built into Python, or `conda`) is crucial.
*   **Benefits:**
    *   **Isolation:** Keeps project-specific dependencies separate from your global Python installation.
    *   **Conflict Avoidance:** Prevents version conflicts between packages required by this project and other Python projects.
    *   **Reproducibility:** Ensures that the project uses the specific library versions defined in `requirements.txt`.
*   Refer to the 'Installation' section for instructions on setting up `venv` or `conda`.

### Hardware Resources

*   **CPU:** A modern multi-core CPU (e.g., Intel Core i5/i7/i9, AMD Ryzen 5/7/9 from recent generations) is recommended for efficient general script execution and media processing tasks handled by MoviePy.
*   **RAM:**
    *   A minimum of **16GB RAM** is recommended, especially if you plan to run multiple services locally (like ComfyUI alongside the script) or use larger AI models (e.g., larger Whisper models).
    *   **32GB or more** is preferable for smoother operation when dealing with high-resolution video, complex animations, and potentially larger AI models in the future.
*   **GPU (Graphics Processing Unit):**
    *   **Highly Recommended for AI Tasks:** A dedicated NVIDIA GPU is highly beneficial for:
        *   **Local Whisper Transcription:** Significantly speeds up audio transcription if using GPU-accelerated Whisper.
        *   **Local ComfyUI:** If you run your ComfyUI server locally and use workflows that leverage Stable Diffusion or other GPU-intensive models.
    *   AI libraries like PyTorch (a dependency of Whisper and often used with ComfyUI backends) have the best support for NVIDIA GPUs (CUDA).
    *   **Not Required for Cloud Services:** The pipeline's use of cloud-based AI services (Google Gemini, Groq API) does not depend on your local GPU.
*   **Disk Space:**
    *   Ensure you have sufficient free disk space. Requirements can add up quickly:
        *   Python environment and dependencies (a few GBs).
        *   Downloaded source audio/video files.
        *   AI Models (e.g., Whisper models can range from ~70MB to several GBs; ComfyUI models can be many GBs each).
        *   Intermediate files generated by each step (audio segments, text files, individual images, animated clips).
        *   Final video outputs.
        *   Archived workspaces in the `logs/` directory.
    *   A starting point of **50-100GB of free space** is advisable. If you plan to process many videos or very long videos, or use many large ComfyUI models, significantly more space will be needed.

### Development & Experimentation

*   **Command-Line Interface (CLI):**
    *   The main `video_pipeline.py` script is designed to be run as a CLI application. This is the primary method for executing the full end-to-end video generation process.
*   **Jupyter Notebooks / IDEs:**
    *   Tools like Jupyter Notebooks, JupyterLab, or Integrated Development Environments (IDEs) such as VS Code (with its Python extension) are excellent for:
        *   **Development:** Iteratively developing and testing individual Python functions or specific steps of the pipeline in isolation.
        *   **Experimentation:** Trying out different library settings (e.g., various MoviePy animation parameters, different API prompts, ComfyUI workflow adjustments) before integrating them into the main script.
        *   **Visualization:** Displaying intermediate outputs like generated images, plotting audio data, or previewing short video clips.
    *   While invaluable for development, the entire automated pipeline is intended to be run via the CLI script.

## Future Enhancements

(Placeholder for potential future improvements)

*   More sophisticated error handling and recovery within steps.
*   Enhanced configuration options for each step (e.g., voice selection for TTS, model choice for Whisper/Gemini/Groq).
*   GUI interface.
*   Support for more input types.
*   More advanced animation and visual effect options.
*   Integration with stock media APIs.
*   Automated quality checks.
*   Distributed task processing.

[end of README.md]
