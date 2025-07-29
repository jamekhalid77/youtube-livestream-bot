# Multi-Stream YouTube Livestream Bot with GitLab Integration
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os, threading, subprocess, time, json, uuid, requests
from werkzeug.utils import secure_filename
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max file size

# GitLab Configuration
GITLAB_PROJECT_ID = "72063753"  # Your youtube-url-processor project ID
GITLAB_API_BASE = "https://gitlab.com/api/v4"

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

def trigger_gitlab_extraction(youtube_url):
    """Trigger GitLab pipeline to extract YouTube URL using trigger token"""
    try:
        trigger_token = os.environ.get('GITLAB_TRIGGER_TOKEN')
        if not trigger_token:
            return {
                'success': False,
                'message': 'GitLab trigger token not configured'
            }
        
        # Use GitLab trigger API with form data
        trigger_data = {
            'token': trigger_token,
            'ref': 'master',
            'variables[YOUTUBE_URL]': youtube_url
        }
        
        response = requests.post(
            f"{GITLAB_API_BASE}/projects/{GITLAB_PROJECT_ID}/trigger/pipeline",
            data=trigger_data,  # Use form data instead of JSON
            timeout=10
        )
        
        if response.status_code == 201:
            pipeline_info = response.json()
            return {
                'success': True,
                'pipeline_id': pipeline_info['id'],
                'message': 'GitLab extraction started'
            }
        else:
            return {
                'success': False,
                'message': f'Failed to trigger GitLab pipeline: {response.status_code} - {response.text}'
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f'Error triggering GitLab extraction: {str(e)}'
        }

def wait_for_gitlab_result(pipeline_id, max_wait=120):
    """Wait for GitLab pipeline to complete and get result"""
    start_time = time.time()
    gitlab_token = os.environ.get('GITLAB_ACCESS_TOKEN')
    
    headers = {
        'Authorization': f'Bearer {gitlab_token}',
        'Content-Type': 'application/json'
    } if gitlab_token else {}
    
    while time.time() - start_time < max_wait:
        try:
            # Check pipeline status
            response = requests.get(
                f"{GITLAB_API_BASE}/projects/{GITLAB_PROJECT_ID}/pipelines/{pipeline_id}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                pipeline = response.json()
                status = pipeline.get('status')
                
                if status == 'success':
                    # Pipeline completed successfully, get the result
                    try:
                        result_response = requests.get(
                            f"https://jamekhalid77-group.gitlab.io/youtube-url-processor/stream_result.json",
                            timeout=10
                        )
                        
                        if result_response.status_code == 200:
                            result = result_response.json()
                            if result.get('success'):
                                return {
                                    'success': True,
                                    'direct_url': result['direct_url'],
                                    'info': {
                                        'title': result['title'],
                                        'duration': result['duration'],
                                        'channel': result['channel'],
                                        'quality': result['quality'],
                                        'type': 'YouTube (GitLab Processed)'
                                    }
                                }
                            else:
                                return {
                                    'success': False,
                                    'message': result.get('error', 'Unknown extraction error')
                                }
                    except:
                        pass
                        
                elif status == 'failed':
                    return {
                        'success': False,
                        'message': 'GitLab extraction pipeline failed'
                    }
                
                # Still running, wait a bit more
                time.sleep(5)
            
        except Exception as e:
            time.sleep(5)
            continue
    
    return {
        'success': False,
        'message': 'Timeout waiting for GitLab extraction'
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
    """Fetch YouTube video information using GitLab"""
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'success': False, 'message': 'URL is required'})
    
    # Trigger GitLab extraction
    trigger_result = trigger_gitlab_extraction(url)
    
    if not trigger_result['success']:
        return jsonify(trigger_result)
    
    # Wait for GitLab to process the URL
    result = wait_for_gitlab_result(trigger_result['pipeline_id'])
    
    if result['success']:
        return jsonify({
            'success': True,
            'info': result['info'],
            'direct_url': result['direct_url']
        })
    else:
        return jsonify({
            'success': False,
            'message': result['message']
        })

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
        
        # Automatically process YouTube URL through GitLab
        trigger_result = trigger_gitlab_extraction(youtube_url)
        
        if not trigger_result['success']:
            return jsonify({'success': False, 'message': f'Failed to process YouTube URL: {trigger_result["message"]}'})
        
        # Wait for GitLab processing
        result = wait_for_gitlab_result(trigger_result['pipeline_id'])
        
        if not result['success']:
            return jsonify({'success': False, 'message': f'YouTube processing failed: {result["message"]}'})
        
        source_path = result['direct_url']
        video_details = result['info']
    
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