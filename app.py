# YouTube Livestream Bot
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os, threading, subprocess, time, json
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# Global variables
streaming_process = None
is_streaming = False
current_video = None
current_stream_key = None

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def start_streaming(video_path, stream_key):
    """Start FFmpeg streaming process"""
    global streaming_process, is_streaming
    
    if is_streaming:
        return False, "Stream already running"
    
    try:
        # FFmpeg command for YouTube livestreaming with loop
        ffmpeg_cmd = [
            'ffmpeg',
            '-re',  # Read input at native frame rate
            '-stream_loop', '-1',  # Loop indefinitely
            '-i', video_path,  # Input video file
            '-c:v', 'libx264',  # Video codec
            '-preset', 'veryfast',  # Encoding speed
            '-maxrate', '3000k',  # Max bitrate
            '-bufsize', '6000k',  # Buffer size
            '-pix_fmt', 'yuv420p',  # Pixel format
            '-g', '50',  # GOP size
            '-c:a', 'aac',  # Audio codec
            '-b:a', '160k',  # Audio bitrate
            '-ac', '2',  # Audio channels
            '-ar', '44100',  # Audio sample rate
            '-f', 'flv',  # Output format
            f'rtmp://a.rtmp.youtube.com/live2/{stream_key}'  # YouTube RTMP URL
        ]
        
        # Start the streaming process
        streaming_process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        
        is_streaming = True
        return True, "Streaming started successfully"
        
    except Exception as e:
        return False, f"Error starting stream: {str(e)}"

def stop_streaming():
    """Stop the streaming process"""
    global streaming_process, is_streaming
    
    if not is_streaming or streaming_process is None:
        return False, "No active stream to stop"
    
    try:
        streaming_process.terminate()
        streaming_process.wait(timeout=10)
        streaming_process = None
        is_streaming = False
        return True, "Stream stopped successfully"
    except Exception as e:
        return False, f"Error stopping stream: {str(e)}"

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle video file upload"""
    global current_video
    
    if 'video' not in request.files:
        return jsonify({'success': False, 'message': 'No file selected'})
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        current_video = filepath
        return jsonify({'success': True, 'message': f'File {filename} uploaded successfully'})
    
    return jsonify({'success': False, 'message': 'Invalid file type'})

@app.route('/start_stream', methods=['POST'])
def start_stream():
    """Start the livestream"""
    global current_stream_key
    
    data = request.get_json()
    stream_key = data.get('stream_key', '').strip()
    
    if not stream_key:
        return jsonify({'success': False, 'message': 'Stream key is required'})
    
    if not current_video or not os.path.exists(current_video):
        return jsonify({'success': False, 'message': 'Please upload a video file first'})
    
    current_stream_key = stream_key
    success, message = start_streaming(current_video, stream_key)
    
    return jsonify({'success': success, 'message': message})

@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    """Stop the livestream"""
    success, message = stop_streaming()
    return jsonify({'success': success, 'message': message})

@app.route('/status')
def get_status():
    """Get current streaming status"""
    return jsonify({
        'is_streaming': is_streaming,
        'has_video': current_video is not None and os.path.exists(current_video) if current_video else False,
        'video_name': os.path.basename(current_video) if current_video else None
    })

@app.route('/health')
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)