# Multi-Stream YouTube Livestream Bot
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os, threading, subprocess, time, json, uuid
from werkzeug.utils import secure_filename
import yt_dlp
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# Global variables for multiple streams
active_streams = {}  # Dictionary to store all active streams
uploaded_videos = {}  # Store uploaded video info

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

class StreamManager:
    def __init__(self, stream_id, stream_name, source_type, source_path, stream_key, video_info=None):
        self.stream_id = stream_id
        self.stream_name = stream_name
        self.source_type = source_type  # 'upload' or 'youtube'
        self.source_path = source_path
        self.stream_key = stream_key
        self.video_info = video_info or {}
        self.process = None
        self.is_streaming = False
        self.start_time = None
        self.status = "Ready"
        
    def start_streaming(self):
        """Start FFmpeg streaming process"""
        if self.is_streaming:
            return False, "Stream already running"
        
        try:
            # FFmpeg command for YouTube livestreaming with loop
            ffmpeg_cmd = [
                'ffmpeg',
                '-re',  # Read input at native frame rate
                '-stream_loop', '-1',  # Loop indefinitely
                '-i', self.source_path,  # Input video file/URL
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
                f'rtmp://a.rtmp.youtube.com/live2/{self.stream_key}'  # YouTube RTMP URL
            ]
            
            # Start the streaming process
            self.process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
            )
            
            self.is_streaming = True
            self.start_time = datetime.now()
            self.status = "Streaming"
            return True, f"Stream '{self.stream_name}' started successfully"
            
        except Exception as e:
            self.status = "Error"
            return False, f"Error starting stream '{self.stream_name}': {str(e)}"
    
    def stop_streaming(self):
        """Stop the streaming process"""
        if not self.is_streaming or self.process is None:
            return False, "No active stream to stop"
        
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None
            self.is_streaming = False
            self.start_time = None
            self.status = "Stopped"
            return True, f"Stream '{self.stream_name}' stopped successfully"
        except Exception as e:
            self.status = "Error"
            return False, f"Error stopping stream '{self.stream_name}': {str(e)}"
    
    def get_duration(self):
        """Get streaming duration"""
        if self.start_time and self.is_streaming:
            delta = datetime.now() - self.start_time
            return str(delta).split('.')[0]  # Remove microseconds
        return "00:00:00"
    
    def to_dict(self):
        """Convert stream info to dictionary"""
        return {
            'stream_id': self.stream_id,
            'stream_name': self.stream_name,
            'source_type': self.source_type,
            'source_path': self.source_path,
            'video_info': self.video_info,
            'is_streaming': self.is_streaming,
            'status': self.status,
            'duration': self.get_duration(),
            'start_time': self.start_time.isoformat() if self.start_time else None
        }

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_youtube_info(url):
    """Extract YouTube video information"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get the best video format
            formats = info.get('formats', [])
            video_url = None
            quality = "Unknown"
            
            # Find best video+audio format
            for f in reversed(formats):
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    video_url = f['url']
                    quality = f.get('format_note', f.get('height', 'Unknown'))
                    break
            
            if not video_url:
                # Fallback to best video format
                video_url = info.get('url')
            
            return {
                'success': True,
                'info': {
                    'title': info.get('title', 'Unknown'),
                    'duration': str(info.get('duration', 'Unknown')) + 's' if info.get('duration') else 'Unknown',
                    'quality': str(quality),
                    'channel': info.get('uploader', 'Unknown'),
                    'views': info.get('view_count', 'Unknown'),
                    'url': video_url
                }
            }
    except Exception as e:
        return {
            'success': False,
            'message': f"Failed to extract video info: {str(e)}"
        }

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle video file upload"""
    if 'video' not in request.files:
        return jsonify({'success': False, 'message': 'No file selected'})
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'})
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to avoid conflicts
        timestamp = str(int(time.time()))
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Store video info
        video_id = str(uuid.uuid4())
        uploaded_videos[video_id] = {
            'id': video_id,
            'filename': filename,
            'original_name': file.filename,
            'filepath': filepath,
            'upload_time': datetime.now().isoformat(),
            'size': os.path.getsize(filepath)
        }
        
        return jsonify({
            'success': True, 
            'message': f'File {file.filename} uploaded successfully',
            'video_id': video_id,
            'video_info': uploaded_videos[video_id]
        })
    
    return jsonify({'success': False, 'message': 'Invalid file type'})

@app.route('/fetch_youtube_info', methods=['POST'])
def fetch_youtube_info():
    """Fetch YouTube video information"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'message': 'URL is required'})
    
    result = get_youtube_info(url)
    return jsonify(result)

@app.route('/create_stream', methods=['POST'])
def create_stream():
    """Create a new stream configuration"""
    data = request.get_json()
    
    stream_name = data.get('stream_name', '').strip()
    stream_key = data.get('stream_key', '').strip()
    source_type = data.get('source_type', 'upload')
    
    if not stream_name or not stream_key:
        return jsonify({'success': False, 'message': 'Stream name and key are required'})
    
    # Generate unique stream ID
    stream_id = str(uuid.uuid4())
    
    # Handle different source types
    if source_type == 'upload':
        video_id = data.get('video_id')
        if not video_id or video_id not in uploaded_videos:
            return jsonify({'success': False, 'message': 'Please select a valid uploaded video'})
        
        video_info = uploaded_videos[video_id]
        source_path = video_info['filepath']
        video_details = {
            'title': video_info['original_name'],
            'type': 'Upload',
            'size': f"{video_info['size'] / (1024*1024):.2f} MB",
            'duration': 'Unknown'
        }
        
    elif source_type == 'youtube':
        youtube_url = data.get('youtube_url', '').strip()
        if not youtube_url:
            return jsonify({'success': False, 'message': 'YouTube URL is required'})
        
        # Get YouTube video info
        result = get_youtube_info(youtube_url)
        if not result['success']:
            return jsonify(result)
        
        source_path = result['info']['url']
        video_details = result['info']
        video_details['type'] = 'YouTube'
    
    else:
        return jsonify({'success': False, 'message': 'Invalid source type'})
    
    # Create stream manager
    stream = StreamManager(
        stream_id=stream_id,
        stream_name=stream_name,
        source_type=source_type,
        source_path=source_path,
        stream_key=stream_key,
        video_info=video_details
    )
    
    active_streams[stream_id] = stream
    
    return jsonify({
        'success': True,
        'message': f'Stream "{stream_name}" created successfully',
        'stream': stream.to_dict()
    })

@app.route('/start_stream/<stream_id>', methods=['POST'])
def start_specific_stream(stream_id):
    """Start a specific stream"""
    if stream_id not in active_streams:
        return jsonify({'success': False, 'message': 'Stream not found'})
    
    stream = active_streams[stream_id]
    success, message = stream.start_streaming()
    
    return jsonify({'success': success, 'message': message})

@app.route('/stop_stream/<stream_id>', methods=['POST'])
def stop_specific_stream(stream_id):
    """Stop a specific stream"""
    if stream_id not in active_streams:
        return jsonify({'success': False, 'message': 'Stream not found'})
    
    stream = active_streams[stream_id]
    success, message = stream.stop_streaming()
    
    return jsonify({'success': success, 'message': message})

@app.route('/delete_stream/<stream_id>', methods=['DELETE'])
def delete_stream(stream_id):
    """Delete a stream configuration"""
    if stream_id not in active_streams:
        return jsonify({'success': False, 'message': 'Stream not found'})
    
    stream = active_streams[stream_id]
    
    # Stop stream if running
    if stream.is_streaming:
        stream.stop_streaming()
    
    # Remove from active streams
    del active_streams[stream_id]
    
    return jsonify({'success': True, 'message': f'Stream "{stream.stream_name}" deleted successfully'})

@app.route('/streams')
def get_all_streams():
    """Get all stream configurations and their status"""
    streams_data = []
    for stream in active_streams.values():
        streams_data.append(stream.to_dict())
    
    return jsonify({
        'streams': streams_data,
        'total_streams': len(active_streams),
        'active_streams': sum(1 for s in active_streams.values() if s.is_streaming)
    })

@app.route('/uploaded_videos')
def get_uploaded_videos():
    """Get all uploaded videos"""
    return jsonify({'videos': list(uploaded_videos.values())})

@app.route('/status')
def get_status():
    """Get overall system status"""
    total_streams = len(active_streams)
    active_count = sum(1 for s in active_streams.values() if s.is_streaming)
    
    return jsonify({
        'total_streams': total_streams,
        'active_streams': active_count,
        'uploaded_videos': len(uploaded_videos),
        'system_status': 'healthy'
    })

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)