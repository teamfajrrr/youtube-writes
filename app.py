import os
import re
import requests
import socket
import platform
from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api._api import YouTubeTranscriptApi as OriginalYTAPI
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for n8n requests

# Custom YouTube API class with proper headers to avoid blocking
class CustomYouTubeTranscriptApi(OriginalYTAPI):
    @classmethod
    def _get_http_session(cls):
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        return session

# Health check endpoint
@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'YouTube Transcript API',
        'version': '1.0.0',
        'endpoints': {
            'transcript': '/transcript?url=YOUTUBE_URL',
            'languages': '/transcript/languages?url=YOUTUBE_URL',
            'debug': '/debug'
        }
    })

# Add /api/health endpoint (same as root)
@app.route('/api/health', methods=['GET'])
def api_health_check():
    return health_check()

# Debug endpoint to check server environment
@app.route('/debug', methods=['GET'])
def debug_info():
    try:
        server_ip = socket.gethostbyname(socket.gethostname())
    except:
        server_ip = "Unable to determine"
    
    return jsonify({
        'server_ip': server_ip,
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'environment': os.environ.get('FLASK_ENV', 'production'),
        'working_locally': False,
        'railway_deployment': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

@app.route('/transcript', methods=['GET'])
def get_transcript():
    try:
        # Get parameters from URL query string
        video_url = request.args.get('url')
        language = request.args.get('language', 'en')
        format_type = request.args.get('format', 'json')  # json or text
        
        # Validate required parameters
        if not video_url:
            return jsonify({
                'success': False,
                'error': 'URL parameter is required',
                'example': '/transcript?url=https://www.youtube.com/watch?v=VIDEO_ID'
            }), 400
        
        # Extract video ID from URL
        video_id = extract_video_id(video_url)
        if not video_id:
            return jsonify({
                'success': False,
                'error': 'Invalid YouTube URL format',
                'provided_url': video_url
            }), 400
        
        logger.info(f"Fetching transcript for video: {video_id}")
        
        # Fetch transcript from YouTube using custom API class
        transcript_list = CustomYouTubeTranscriptApi.get_transcript(
            video_id, 
            languages=[language, 'en']  # Try requested language, fallback to English
        )
        
        # Format response based on requested format
        if format_type == 'text':
            # Return as plain text
            formatter = TextFormatter()
            formatted_transcript = formatter.format_transcript(transcript_list)
            response_data = {
                'success': True,
                'video_id': video_id,
                'language': language,
                'format': 'text',
                'transcript': formatted_transcript,
                'word_count': len(formatted_transcript.split()),
                'duration_seconds': transcript_list[-1]['start'] + transcript_list[-1]['duration'] if transcript_list else 0
            }
        else:
            # Return as JSON with timestamps (default)
            total_duration = transcript_list[-1]['start'] + transcript_list[-1]['duration'] if transcript_list else 0
            word_count = sum(len(item['text'].split()) for item in transcript_list)
            
            response_data = {
                'success': True,
                'video_id': video_id,
                'language': language,
                'format': 'json',
                'transcript': transcript_list,
                'word_count': word_count,
                'duration_seconds': total_duration,
                'segments_count': len(transcript_list)
            }
        
        logger.info(f"Successfully fetched transcript for {video_id}")
        return jsonify(response_data)
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error fetching transcript: {error_message}")
        
        # Handle specific YouTube API errors
        if "No transcripts were found" in error_message:
            return jsonify({
                'success': False,
                'error': 'No transcripts available for this video',
                'error_type': 'no_transcript',
                'video_id': video_id if 'video_id' in locals() else None,
                'debug_info': 'This video may not have captions enabled or may be restricted in this region'
            }), 404
        elif "Video unavailable" in error_message:
            return jsonify({
                'success': False,
                'error': 'Video is unavailable or private',
                'error_type': 'unavailable',
                'video_id': video_id if 'video_id' in locals() else None
            }), 404
        elif "Subtitles are disabled" in error_message:
            return jsonify({
                'success': False,
                'error': 'Subtitles are disabled for this video',
                'error_type': 'subtitles_disabled',
                'video_id': video_id if 'video_id' in locals() else None,
                'debug_info': 'Try a different video with captions enabled'
            }), 404
        else:
            return jsonify({
                'success': False,
                'error': error_message,
                'error_type': 'unknown',
                'debug_info': 'This might be a regional restriction or server IP blocking issue'
            }), 500

@app.route('/transcript/languages', methods=['GET'])
def get_available_languages():
    """Get available transcript languages for a video"""
    try:
        video_url = request.args.get('url')
        if not video_url:
            return jsonify({
                'success': False,
                'error': 'URL parameter is required',
                'example': '/transcript/languages?url=https://www.youtube.com/watch?v=VIDEO_ID'
            }), 400
        
        video_id = extract_video_id(video_url)
        if not video_id:
            return jsonify({
                'success': False,
                'error': 'Invalid YouTube URL format',
                'provided_url': video_url
            }), 400
        
        # Get available transcript languages using custom API class
        transcript_list = CustomYouTubeTranscriptApi.list_transcripts(video_id)
        
        languages = []
        for transcript in transcript_list:
            languages.append({
                'language': transcript.language,
                'language_code': transcript.language_code,
                'is_generated': transcript.is_generated,
                'is_translatable': transcript.is_translatable
            })
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'available_languages': languages,
            'total_languages': len(languages)
        })
        
    except Exception as e:
        logger.error(f"Error fetching available languages: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': 'language_fetch_error',
            'debug_info': 'This might be a regional restriction or server IP blocking issue'
        }), 500

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:youtube\.com\/shorts\/)([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
