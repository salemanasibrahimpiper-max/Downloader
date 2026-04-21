from flask import Flask, render_template, request, send_file, jsonify, url_for
import yt_dlp
import os
import re
import threading
import uuid
import imageio_ffmpeg

PASSWORD = "Nigga"
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder='.')
download_status = {}

def clean_filename(title):
    return re.sub(r'[<>:"/\\|?*]', '', title).strip()

def progress_hook(status_dict, task_id):
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            if total and total > 0:
                progress = int(downloaded / total * 100)
                status_dict[task_id]['progress'] = progress
                status_dict[task_id]['message'] = f'Download {progress}%'
        elif d['status'] == 'finished':
            status_dict[task_id]['progress'] = 100
            status_dict[task_id]['message'] = 'Fertig!'
    return hook

def download_video_task(url, quality, password, status_dict, task_id):
    try:
        if quality == "1080p" and password != PASSWORD:
            status_dict[task_id] = {'status': 'error', 'message': 'Falsches Passwort'}
            return

        status_dict[task_id] = {'status': 'downloading', 'progress': 0, 'message': 'Analysiere...'}

        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        # yt-dlp Optionen mit Cookie-Unterstützung
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'progress_hooks': [progress_hook(status_dict, task_id)],
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_path,
            'cookiefile': 'cookies.txt',  # <-- Cookie-Datei für YouTube
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'extractor_args': {
                'youtube': {
                    'skip': ['webpage'],  # Umgeht einige Prüfungen
                }
            }
        }

        # Qualität spezifische Format-Auswahl
        if quality == "1080p":
            # Bevorzuge progressive (falls vorhanden), sonst beste Video+Audio Kombination
            ydl_opts['format'] = 'best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]'
        else:
            height = quality.replace('p', '')
            ydl_opts['format'] = f'best[height<={height}][ext=mp4]/bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]'

        # Merge-Einstellungen für den Fall, dass progressive nicht verfügbar ist
        ydl_opts['merge_output_format'] = 'mp4'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = clean_filename(info.get('title', 'video'))
            status_dict[task_id]['title'] = title
            status_dict[task_id]['message'] = f'Starte Download: {title}'
            ydl.download([url])

        # Finde die heruntergeladene Datei
        for f in os.listdir(DOWNLOAD_FOLDER):
            if f.startswith(title) and f.endswith('.mp4'):
                output_file = os.path.join(DOWNLOAD_FOLDER, f)
                break
        else:
            # Fallback: nehme die neueste MP4-Datei
            mp4_files = [os.path.join(DOWNLOAD_FOLDER, f) for f in os.listdir(DOWNLOAD_FOLDER) if f.endswith('.mp4')]
            if mp4_files:
                output_file = max(mp4_files, key=os.path.getctime)
            else:
                raise Exception("Keine MP4-Datei gefunden")

        status_dict[task_id] = {
            'status': 'done',
            'message': 'Fertig!',
            'file': output_file,
            'filename': os.path.basename(output_file)
        }
    except Exception as e:
        status_dict[task_id] = {'status': 'error', 'message': str(e)}

# ---------- Flask-Routen ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return {"status": "healthy"}, 200

@app.route('/download', methods=['POST'])
def start_download():
    url = request.form.get('url')
    quality = request.form.get('quality', '720p')
    password = request.form.get('password', '')
    if not url:
        return jsonify({'error': 'Keine URL'}), 400
    task_id = str(uuid.uuid4())
    download_status[task_id] = {'status': 'starting'}
    thread = threading.Thread(target=download_video_task, args=(url, quality, password, download_status, task_id))
    thread.start()
    return jsonify({'task_id': task_id}), 202

@app.route('/status/<task_id>')
def get_status(task_id):
    status = download_status.get(task_id, {'status': 'not_found'})
    if status.get('status') == 'done':
        status['download_url'] = url_for('download_file', filename=os.path.basename(status['file']))
    return jsonify(status)

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)