import os
import sys
import uuid
import json
import time
import glob
import threading
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, Response, stream_with_context
)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
MODEL_PATH = PROJECT_DIR / "best.pt"

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "uploads" / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

IMGSZ = 608

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from ultralytics import YOLO
                _model = YOLO(str(MODEL_PATH))
    return _model


_ffmpeg_bin = None

def get_ffmpeg_bin():
    global _ffmpeg_bin
    if _ffmpeg_bin is None:
        try:
            import imageio_ffmpeg
            _ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            _ffmpeg_bin = "ffmpeg"
    return _ffmpeg_bin


jobs = {}

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}


def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": f"Unsupported format. Use: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    conf = float(request.form.get("conf", 0.30))
    iou = float(request.form.get("iou", 0.50))

    conf = max(0.05, min(0.95, conf))
    iou = max(0.05, min(0.95, iou))

    job_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix
    input_path = UPLOAD_DIR / f"{job_id}_input{ext}"
    file.save(str(input_path))

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "total": 0,
        "message": "Video uploaded. Starting detection...",
        "output": None,
        "detections": {"fire": 0, "smoke": 0, "frames": 0},
        "conf": conf,
        "iou": iou,
    }

    thread = threading.Thread(target=process_video, args=(job_id, str(input_path), conf, iou))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/youtube", methods=["POST"])
def youtube_download():
    data = request.get_json()
    url = data.get("url", "").strip()
    conf = float(data.get("conf", 0.30))
    iou = float(data.get("iou", 0.50))

    conf = max(0.05, min(0.95, conf))
    iou = max(0.05, min(0.95, iou))

    if not url:
        return jsonify({"error": "No YouTube URL provided"}), 400

    job_id = str(uuid.uuid4())[:8]

    jobs[job_id] = {
        "status": "downloading",
        "progress": 0,
        "total": 0,
        "message": "Downloading YouTube video...",
        "output": None,
        "detections": {"fire": 0, "smoke": 0, "frames": 0},
        "conf": conf,
        "iou": iou,
    }

    thread = threading.Thread(target=download_and_process, args=(job_id, url, conf, iou))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    def generate():
        while True:
            if job_id not in jobs:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break

            job = jobs[job_id]
            yield f"data: {json.dumps(job)}\n\n"

            if job["status"] in ("done", "error"):
                break

            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(str(OUTPUT_DIR), filename)


def download_and_process(job_id, url, conf, iou):
    try:
        import yt_dlp

        input_path = str(UPLOAD_DIR / f"{job_id}_input.mp4")

        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": input_path,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

        jobs[job_id]["message"] = "Downloading video from YouTube..."
        jobs[job_id]["status"] = "downloading"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        actual_path = input_path
        if not os.path.exists(actual_path):
            candidates = glob.glob(str(UPLOAD_DIR / f"{job_id}_input.*"))
            if candidates:
                actual_path = candidates[0]
            else:
                raise FileNotFoundError("YouTube download failed — no file created.")

        jobs[job_id]["message"] = "Download complete. Starting detection..."
        process_video(job_id, actual_path, conf, iou)

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = f"Error: {str(e)}"


def process_video(job_id, input_path, conf, iou):
    try:
        import cv2

        jobs[job_id]["status"] = "processing"
        jobs[job_id]["message"] = "Loading model..."

        model = get_model()

        cap = cv2.VideoCapture(input_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        jobs[job_id]["total"] = total_frames
        jobs[job_id]["message"] = f"Processing {total_frames} frames..."

        output_filename = f"{job_id}_output.mp4"
        output_path = str(OUTPUT_DIR / output_filename)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        fire_count = 0
        smoke_count = 0
        frame_idx = 0

        results = model.predict(
            source=input_path,
            stream=True,
            imgsz=IMGSZ,
            conf=conf,
            iou=iou,
            verbose=False,
        )

        for result in results:
            frame_idx += 1

            if result.boxes is not None:
                for box in result.boxes:
                    cls_id = int(box.cls[0])
                    if cls_id == 0:
                        smoke_count += 1
                    elif cls_id == 1:
                        fire_count += 1

            annotated = result.plot(line_width=2, font_size=0.6)
            writer.write(annotated)

            if frame_idx % 5 == 0 or frame_idx == total_frames:
                jobs[job_id]["progress"] = frame_idx
                jobs[job_id]["detections"] = {
                    "fire": fire_count,
                    "smoke": smoke_count,
                    "frames": frame_idx,
                }
                pct = int(frame_idx / max(total_frames, 1) * 100)
                jobs[job_id]["message"] = f"Processing... {pct}% ({frame_idx}/{total_frames} frames)"

        writer.release()

        final_output = f"{job_id}_result.mp4"
        final_path = str(OUTPUT_DIR / final_output)
        try:
            import subprocess
            ffmpeg_bin = get_ffmpeg_bin()

            jobs[job_id]["message"] = "Finalizing video..."
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", output_path, "-c:v", "libx264",
                 "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", final_path],
                capture_output=True, timeout=600
            )
            if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                os.remove(output_path)
                output_filename = final_output
            else:
                output_filename = f"{job_id}_output.mp4"
        except Exception:
            output_filename = f"{job_id}_output.mp4"

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = total_frames
        jobs[job_id]["output"] = f"/outputs/{output_filename}"
        jobs[job_id]["message"] = "Detection complete!"
        jobs[job_id]["detections"] = {
            "fire": fire_count,
            "smoke": smoke_count,
            "frames": frame_idx,
        }

        try:
            os.remove(input_path)
        except OSError:
            pass

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = f"Processing error: {str(e)}"


if __name__ == "__main__":
    if not MODEL_PATH.exists():
        print(f"ERROR: Model not found at {MODEL_PATH}")
        print("Place best.pt in the fireGaurd_ai/ directory.")
        sys.exit(1)

    get_model()
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
