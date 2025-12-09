import yt_dlp
import os
import sys
import re
import json
import time
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to import clipboard support (optional)
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

# ========== COLORS FOR TERMINAL ==========
class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    DIM = '\033[2m'
    END = '\033[0m'

def print_banner():
    """Print a stylish and lovely banner"""
    banner = f"""
{Colors.MAGENTA}{Colors.BOLD}
    ♥ ═══════════════════════════════════════════════════════════════════ ♥
    ║                                                                     ║
    ║  {Colors.CYAN}✧･ﾟ: *✧･ﾟ:*{Colors.MAGENTA}    🎬  VIDEO DOWNLOADER PRO  🎬    {Colors.CYAN}*:･ﾟ✧*:･ﾟ✧{Colors.MAGENTA}  ║
    ║                                                                     ║
{Colors.END}{Colors.CYAN}    ║     ╭────────────────────────────────────────────────────╮     ║
    ║     │  {Colors.YELLOW}📺 YouTube{Colors.CYAN}  •  {Colors.MAGENTA}🎵 TikTok{Colors.CYAN}  •  {Colors.YELLOW}📸 Instagram{Colors.CYAN}           │     ║
    ║     │  {Colors.BLUE}🐦 Twitter/X{Colors.CYAN}  •  {Colors.GREEN}📋 Playlists{Colors.CYAN}  •  {Colors.RED}♥ More!{Colors.CYAN}         │     ║
    ║     ╰────────────────────────────────────────────────────╯     ║
{Colors.END}{Colors.GREEN}
    ║     ✨ Features: {Colors.YELLOW}Retry{Colors.GREEN} • {Colors.YELLOW}Concurrent{Colors.GREEN} • {Colors.YELLOW}Subtitles{Colors.GREEN} • {Colors.YELLOW}History{Colors.GREEN}    ║
{Colors.END}{Colors.MAGENTA}{Colors.BOLD}
    ║                                                                     ║
    ║              {Colors.RED}♥{Colors.YELLOW} Created with love by {Colors.CYAN}{Colors.UNDERLINE}ShoGenTheOne{Colors.END}{Colors.MAGENTA}{Colors.BOLD} {Colors.RED}♥{Colors.MAGENTA}               ║
    ║                                                                     ║
    ♥ ═══════════════════════════════════════════════════════════════════ ♥
{Colors.END}"""
    print(banner)


# ========== CONFIGURATION MANAGER ==========
class Config:
    """Manages persistent configuration"""
    DEFAULT_CONFIG = {
        'output_path': 'downloads',
        'default_quality': 'best',
        'max_retries': 3,
        'retry_delay': 2,
        'concurrent_downloads': 3,
        'download_subtitles': False,
        'subtitle_languages': 'all',  # Download all available languages
        'embed_subtitles': True,
        'max_filename_length': 200,
        'show_file_size': True,
    }
    
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.settings = self.load()
    
    def load(self):
        """Load configuration from file"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    # Merge with defaults to handle new settings
                    config = {**self.DEFAULT_CONFIG, **saved}
                    return config
            except (json.JSONDecodeError, IOError):
                return self.DEFAULT_CONFIG.copy()
        return self.DEFAULT_CONFIG.copy()
    
    def save(self):
        """Save configuration to file"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except IOError:
            return False
    
    def get(self, key, default=None):
        return self.settings.get(key, default)
    
    def set(self, key, value):
        self.settings[key] = value
        self.save()


# ========== DOWNLOAD HISTORY MANAGER ==========
class DownloadHistory:
    """Tracks download history to avoid re-downloads"""
    
    def __init__(self, history_path="history.json"):
        self.history_path = history_path
        self.history = self.load()
        self.lock = threading.Lock()
    
    def load(self):
        """Load history from file"""
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {'downloads': []}
        return {'downloads': []}
    
    def save(self):
        """Save history to file"""
        with self.lock:
            try:
                with open(self.history_path, 'w', encoding='utf-8') as f:
                    json.dump(self.history, f, indent=2, default=str)
                return True
            except IOError:
                return False
    
    def add_download(self, url, title, filepath, platform, success=True):
        """Add a download entry to history"""
        with self.lock:
            entry = {
                'url': url,
                'title': title,
                'filepath': filepath,
                'platform': platform,
                'timestamp': datetime.now().isoformat(),
                'success': success
            }
            self.history['downloads'].append(entry)
            self.save()
    
    def is_downloaded(self, url):
        """Check if URL was already downloaded successfully"""
        return any(
            d['url'] == url and d['success'] 
            for d in self.history['downloads']
        )
    
    def get_recent(self, count=10):
        """Get recent downloads"""
        return self.history['downloads'][-count:][::-1]
    
    def clear(self):
        """Clear download history"""
        self.history = {'downloads': []}
        self.save()


# ========== FILENAME SANITIZER ==========
def sanitize_filename(filename, max_length=200):
    """Remove invalid characters and limit filename length"""
    # Remove invalid characters for Windows/Unix
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    sanitized = re.sub(invalid_chars, '_', filename)
    
    # Replace multiple underscores/spaces
    sanitized = re.sub(r'[_\s]+', '_', sanitized)
    
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(' ._')
    
    # Limit length (preserve extension)
    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        max_name_len = max_length - len(ext)
        sanitized = name[:max_name_len] + ext
    
    return sanitized or 'video'


# ========== FORMAT FILE SIZE ==========
def format_size(bytes_size):
    """Format bytes to human readable size"""
    if bytes_size is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} PB"


# ========== PROGRESS BAR ==========
class ProgressTracker:
    """Thread-safe progress tracking"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.current_file = ""
        self.progress_data = {}
    
    def update(self, filename, data):
        with self.lock:
            self.current_file = filename
            self.progress_data[filename] = data
    
    def get_progress_string(self, d):
        """Format progress string with detailed info"""
        percent = d.get('_percent_str', 'N/A').strip()
        speed = d.get('_speed_str', 'N/A')
        eta = d.get('_eta_str', 'N/A')
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        
        size_info = ""
        if total:
            size_info = f" | {format_size(downloaded)}/{format_size(total)}"
        
        return f"⏬ {percent}{size_info} | ⚡ {speed} | ⏱️ ETA: {eta}"


# ========== MAIN DOWNLOADER CLASS ==========
class VideoDownloader:
    def __init__(self, config=None):
        """Initialize downloader with configuration"""
        self.config = config or Config()
        self.output_path = self.config.get('output_path', 'downloads')
        os.makedirs(self.output_path, exist_ok=True)
        
        self.history = DownloadHistory()
        self.downloaded_files = []
        self.progress = ProgressTracker()
        self.current_download_lock = threading.Lock()
    
    def progress_hook(self, d):
        """Custom progress hook for download progress"""
        if d['status'] == 'downloading':
            progress_str = self.progress.get_progress_string(d)
            sys.stdout.write(f"\r{Colors.CYAN}{progress_str}{Colors.END}   ")
            sys.stdout.flush()
        elif d['status'] == 'finished':
            filename = d.get('filename', '')
            # Show brief processing message (FFmpeg may still be working)
            print(f"\n{Colors.YELLOW}⏳ Processing video (FFmpeg)...{Colors.END}")
    
    def convert_srt_to_txt(self, d):
        """Convert SRT subtitle files to plain TXT format"""
        if d['status'] != 'finished':
            return
        
        # Look for SRT files in the output directory
        info = d.get('info_dict', {})
        requested_subtitles = info.get('requested_subtitles', {})
        
        if not requested_subtitles:
            return
        
        for lang, sub_info in requested_subtitles.items():
            srt_file = sub_info.get('filepath', '')
            if srt_file and os.path.exists(srt_file) and srt_file.endswith('.srt'):
                txt_file = srt_file.replace('.srt', '.txt')
                try:
                    with open(srt_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Parse SRT and extract text only (remove timing and numbers)
                    lines = content.split('\n')
                    text_lines = []
                    last_line = ""  # Track last line to avoid duplicates
                    
                    for line in lines:
                        line = line.strip()
                        # Skip empty lines, numbers, and timing lines
                        if not line:
                            continue
                        if line.isdigit():
                            continue
                        if '-->' in line:
                            continue
                        
                        # Skip consecutive duplicate lines (fix for YouTube auto-subs)
                        if line != last_line:
                            text_lines.append(line)
                            last_line = line
                    
                    # Write clean text to TXT file
                    with open(txt_file, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(text_lines))
                    
                    # Remove the SRT file, keep only TXT
                    os.remove(srt_file)
                    print(f"{Colors.GREEN}📝 Subtitles saved to: {os.path.basename(txt_file)}{Colors.END}")
                except Exception as e:
                    print(f"{Colors.YELLOW}⚠️ Could not convert subtitle to TXT: {e}{Colors.END}")

    def validate_url(self, url):
        """Validate if the input is a valid URL"""
        url_pattern = re.compile(
            r'^https?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
            r'localhost|'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
            r'(?::\d+)?'
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return url_pattern.match(url) is not None
    
    def get_base_options(self):
        """Get base options common to all downloads"""
        options = {
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [self.progress_hook],
            'noprogress': False,
            'restrictfilenames': False,
            'socket_timeout': 30,  # Prevent hanging on network issues
            'retries': 10,
            'fragment_retries': 10,
            'noplaylist': True,  # Don't extract playlist info for single videos
        }
        
        # Add subtitle options if enabled
        if self.config.get('download_subtitles'):
            options.update({
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': self.config.get('subtitle_languages', 'all'),
                'subtitlesformat': 'best',
                'ignore_no_formats_error': True,  # Don't fail if no subtitles available
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',  # First convert to SRT (cleaner format)
                }],
            })
            # Add a custom post-processor to convert SRT to TXT
            options['postprocessor_hooks'] = [self.convert_srt_to_txt]
        
        return options
    
    def get_youtube_options(self, quality="best"):
        """YouTube options for various quality levels"""
        format_options = {
            "8k": "bestvideo[height<=4320]+bestaudio/best[height<=4320]",
            "4k": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
            "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
            "best": "bestvideo+bestaudio/best"
        }
        
        options = self.get_base_options()
        options.update({
            'format': format_options.get(quality, format_options["best"]),
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(self.output_path, 'youtube_%(title)s.%(ext)s'),
        })
        return options
    
    def get_playlist_options(self, quality="best"):
        """Options for YouTube playlist downloads"""
        options = self.get_youtube_options(quality)
        options.update({
            'outtmpl': os.path.join(self.output_path, '%(playlist)s/%(playlist_index)s - %(title)s.%(ext)s'),
            'ignoreerrors': True,  # Continue on errors
        })
        return options
    
    def get_audio_options(self):
        """Options for audio-only download (MP3)"""
        options = self.get_base_options()
        options.update({
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.output_path, 'audio_%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
        })
        return options
    
    def get_tiktok_options(self):
        """TikTok options - improved compatibility with better headers"""
        options = self.get_base_options()
        options.update({
            'format': 'best',
            'outtmpl': os.path.join(self.output_path, 'tiktok_%(id)s.%(ext)s'),
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            'nocheckcertificate': True,  # Prevent SSL issues
            'no_post_overwrites': True,
        })
        # Remove postprocessors for TikTok - videos are already in correct format
        if 'postprocessors' in options:
            del options['postprocessors']
        if 'postprocessor_hooks' in options:
            del options['postprocessor_hooks']
        return options
    
    def get_instagram_options(self):
        """Instagram options for Reels and videos"""
        options = self.get_base_options()
        options.update({
            'format': 'best',
            'outtmpl': os.path.join(self.output_path, 'instagram_%(id)s.%(ext)s'),
        })
        return options
    
    def get_twitter_options(self):
        """Twitter/X options for video downloads"""
        options = self.get_base_options()
        options.update({
            'format': 'best',
            'outtmpl': os.path.join(self.output_path, 'twitter_%(id)s.%(ext)s'),
        })
        return options
    
    def get_generic_options(self):
        """Generic options for unsupported platforms"""
        options = self.get_base_options()
        options.update({
            'format': 'best',
            'outtmpl': os.path.join(self.output_path, '%(title)s.%(ext)s'),
        })
        return options
    
    def detect_platform(self, url):
        """Auto-detect platform from URL"""
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            if 'playlist' in url_lower or '&list=' in url_lower:
                return 'youtube_playlist'
            return 'youtube'
        elif 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'instagram.com' in url_lower:
            return 'instagram'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'twitter'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
            return 'facebook'
        elif 'vimeo.com' in url_lower:
            return 'vimeo'
        elif 'dailymotion.com' in url_lower:
            return 'dailymotion'
        elif 'twitch.tv' in url_lower:
            return 'twitch'
        else:
            return 'unknown'
    
    def get_video_info(self, url):
        """Get video information without downloading"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Check if it's a playlist
                if info.get('_type') == 'playlist':
                    entries = info.get('entries', [])
                    return {
                        'is_playlist': True,
                        'title': info.get('title', 'Unknown Playlist'),
                        'video_count': len(entries),
                        'uploader': info.get('uploader', 'Unknown'),
                        'entries': entries[:5],  # First 5 for preview
                    }
                
                # Get file size estimate
                filesize = info.get('filesize') or info.get('filesize_approx')
                
                return {
                    'is_playlist': False,
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'filesize': filesize,
                    'resolution': info.get('resolution', 'Unknown'),
                    'fps': info.get('fps', 'Unknown'),
                }
        except Exception as e:
            return None
    
    def download_with_retry(self, url, options, max_retries=None):
        """Download with retry logic and exponential backoff"""
        max_retries = max_retries or self.config.get('max_retries', 3)
        retry_delay = self.config.get('retry_delay', 2)
        
        last_error = None
        for attempt in range(max_retries):
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return info
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e)
                # Check if it's a subtitle-only error (429 on subtitles)
                if 'subtitle' in error_str.lower() and '429' in error_str:
                    print(f"\n{Colors.YELLOW}⚠️ Subtitle download failed (rate limited). Retrying without subtitles...{Colors.END}")
                    # Disable subtitles and try again
                    options_no_subs = options.copy()
                    options_no_subs['writesubtitles'] = False
                    options_no_subs['writeautomaticsub'] = False
                    options_no_subs['embedsubtitles'] = False
                    try:
                        with yt_dlp.YoutubeDL(options_no_subs) as ydl:
                            info = ydl.extract_info(url, download=True)
                            print(f"{Colors.GREEN}✅ Video downloaded successfully (without subtitles){Colors.END}")
                            return info
                    except Exception as e2:
                        last_error = e2
                        break
                
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"\n{Colors.YELLOW}⚠️ Attempt {attempt + 1} failed. Retrying in {wait_time}s...{Colors.END}")
                    time.sleep(wait_time)
            except Exception as e:
                last_error = e
                break
        
        raise last_error
    
    def download(self, url, quality="best", audio_only=False, skip_existing=True):
        """Download video from any supported platform"""
        # Validate URL
        if not self.validate_url(url):
            print(f"{Colors.RED}❌ Invalid URL format!{Colors.END}")
            return None
        
        # Check if already downloaded
        if skip_existing and self.history.is_downloaded(url):
            print(f"{Colors.YELLOW}⏭️ Already downloaded. Skipping...{Colors.END}")
            return "skipped"
        
        platform = self.detect_platform(url)
        
        # Show video info
        print(f"\n{Colors.YELLOW}🔍 Fetching video information...{Colors.END}")
        info = self.get_video_info(url)
        
        if info:
            if info.get('is_playlist'):
                print(f"{Colors.CYAN}📋 Playlist: {info['title']}")
                print(f"📹 Videos: {info['video_count']}")
                print(f"👤 By: {info['uploader']}{Colors.END}\n")
            else:
                duration = int(info['duration']) if info['duration'] else 0
                duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "N/A"
                filesize_str = format_size(info['filesize']) if info.get('filesize') else "Unknown"
                
                print(f"{Colors.CYAN}📌 Title: {info['title']}")
                print(f"👤 Uploader: {info['uploader']}")
                print(f"⏱️ Duration: {duration_str}")
                if info.get('view_count'):
                    print(f"👁️ Views: {info['view_count']:,}")
                if self.config.get('show_file_size'):
                    print(f"💾 Est. Size: {filesize_str}")
                print(f"📺 Resolution: {info.get('resolution', 'N/A')}{Colors.END}\n")
        
        # Select appropriate options
        if audio_only:
            options = self.get_audio_options()
            print(f"{Colors.BLUE}🎵 Downloading audio only (MP3 - 320kbps)...{Colors.END}")
        elif platform == 'youtube_playlist':
            return self.download_playlist(url, quality)
        elif platform == 'youtube':
            options = self.get_youtube_options(quality)
            print(f"{Colors.BLUE}📺 Downloading YouTube video ({quality} quality)...{Colors.END}")
        elif platform == 'tiktok':
            options = self.get_tiktok_options()
            print(f"{Colors.BLUE}🎵 Downloading TikTok video (no watermark)...{Colors.END}")
        elif platform == 'instagram':
            options = self.get_instagram_options()
            print(f"{Colors.BLUE}📸 Downloading Instagram video...{Colors.END}")
        elif platform == 'twitter':
            options = self.get_twitter_options()
            print(f"{Colors.BLUE}🐦 Downloading Twitter/X video...{Colors.END}")
        else:
            options = self.get_generic_options()
            print(f"{Colors.YELLOW}⚠️ Platform not recognized. Trying generic download...{Colors.END}")
        
        try:
            download_info = self.download_with_retry(url, options)
            
            with yt_dlp.YoutubeDL(options) as ydl:
                filename = ydl.prepare_filename(download_info)
            
            # Handle audio files (extension changes after conversion)
            if audio_only:
                filename = os.path.splitext(filename)[0] + '.mp3'
            
            # Sanitize filename
            directory = os.path.dirname(filename)
            base_name = sanitize_filename(
                os.path.basename(filename), 
                self.config.get('max_filename_length', 200)
            )
            filename = os.path.join(directory, base_name)
            
            self.downloaded_files.append(filename)
            
            # Add to history
            title = download_info.get('title', 'Unknown')
            self.history.add_download(url, title, filename, platform, success=True)
            
            print(f"{Colors.GREEN}{Colors.BOLD}✅ Successfully downloaded: {os.path.basename(filename)}{Colors.END}")
            print(f"{Colors.CYAN}📁 Location: {os.path.abspath(filename)}{Colors.END}")
            return filename
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)[:150]
            print(f"{Colors.RED}❌ Download Error: Video may be private, age-restricted, or unavailable{Colors.END}")
            print(f"{Colors.YELLOW}Details: {error_msg}...{Colors.END}")
            self.history.add_download(url, "Failed", "", platform, success=False)
            return None
        except Exception as e:
            print(f"{Colors.RED}❌ Unexpected Error: {str(e)}{Colors.END}")
            self.history.add_download(url, "Failed", "", platform, success=False)
            return None

    def download_playlist(self, url, quality="best"):
        """Download an entire YouTube playlist"""
        print(f"\n{Colors.MAGENTA}{Colors.BOLD}📋 PLAYLIST DOWNLOAD MODE{Colors.END}")
        
        options = self.get_playlist_options(quality)
        
        try:
            # Get playlist info first
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                playlist_info = ydl.extract_info(url, download=False)
            
            video_count = len(playlist_info.get('entries', []))
            print(f"{Colors.CYAN}📋 Playlist: {playlist_info.get('title', 'Unknown')}")
            print(f"📹 Total videos: {video_count}{Colors.END}\n")
            
            # Download with progress tracking
            downloaded = 0
            failed = 0
            
            def playlist_progress_hook(d):
                nonlocal downloaded, failed
                if d['status'] == 'finished':
                    downloaded += 1
                    print(f"\n{Colors.GREEN}✅ [{downloaded}/{video_count}] Downloaded{Colors.END}")
            
            options['progress_hooks'] = [playlist_progress_hook]
            
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
            
            print(f"\n{Colors.GREEN}{Colors.BOLD}✅ Playlist download complete!{Colors.END}")
            print(f"{Colors.CYAN}📁 Location: {os.path.abspath(self.output_path)}{Colors.END}")
            
            return True
            
        except Exception as e:
            print(f"{Colors.RED}❌ Playlist Error: {str(e)}{Colors.END}")
            return None

    def download_multiple(self, urls, quality="best", audio_only=False, concurrent=True):
        """Download multiple videos with optional concurrency"""
        results = []
        total = len(urls)
        successful = 0
        failed = 0
        skipped = 0
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}📥 Starting batch download of {total} videos...{Colors.END}")
        
        if concurrent and total > 1:
            max_workers = min(self.config.get('concurrent_downloads', 3), total)
            print(f"{Colors.YELLOW}⚡ Using {max_workers} concurrent downloads{Colors.END}\n")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_url = {
                    executor.submit(self.download, url.strip(), quality, audio_only): url 
                    for url in urls
                }
                
                for i, future in enumerate(as_completed(future_to_url), 1):
                    url = future_to_url[future]
                    try:
                        result = future.result()
                        results.append(result)
                        if result == "skipped":
                            skipped += 1
                        elif result:
                            successful += 1
                        else:
                            failed += 1
                    except Exception as e:
                        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.END}")
                        failed += 1
                        results.append(None)
                    
                    print(f"{Colors.DIM}[{i}/{total}] Processed{Colors.END}")
        else:
            for i, url in enumerate(urls, 1):
                print(f"\n{Colors.HEADER}{'='*60}")
                print(f"[{i}/{total}] Processing...")
                print(f"{'='*60}{Colors.END}")
                
                result = self.download(url.strip(), quality, audio_only)
                results.append(result)
                
                if result == "skipped":
                    skipped += 1
                elif result:
                    successful += 1
                else:
                    failed += 1
        
        # Summary
        print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*60}")
        print(f"📊 DOWNLOAD SUMMARY")
        print(f"{'='*60}{Colors.END}")
        print(f"{Colors.GREEN}✅ Successful: {successful}{Colors.END}")
        print(f"{Colors.YELLOW}⏭️ Skipped: {skipped}{Colors.END}")
        print(f"{Colors.RED}❌ Failed: {failed}{Colors.END}")
        print(f"{Colors.CYAN}📁 Output directory: {os.path.abspath(self.output_path)}{Colors.END}")
        
        return results

    def show_downloaded_files(self):
        """Display list of all downloaded files this session"""
        if not self.downloaded_files:
            print(f"{Colors.YELLOW}No files downloaded this session.{Colors.END}")
            return
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}📁 Downloaded Files This Session:{Colors.END}")
        for i, f in enumerate(self.downloaded_files, 1):
            size = format_size(os.path.getsize(f)) if os.path.exists(f) else "N/A"
            print(f"  {i}. {os.path.basename(f)} ({size})")
    
    def show_history(self, count=10):
        """Show recent download history"""
        recent = self.history.get_recent(count)
        
        if not recent:
            print(f"{Colors.YELLOW}No download history found.{Colors.END}")
            return
        
        print(f"\n{Colors.CYAN}{Colors.BOLD}📜 Recent Downloads:{Colors.END}")
        for i, entry in enumerate(recent, 1):
            status = f"{Colors.GREEN}✅" if entry['success'] else f"{Colors.RED}❌"
            print(f"  {i}. {status} {entry['title'][:50]}... ({entry['platform']}){Colors.END}")
            print(f"     {Colors.DIM}{entry['timestamp'][:19]}{Colors.END}")


# ========== CLIPBOARD HELPER ==========
def get_clipboard_url():
    """Get URL from clipboard if available"""
    if not CLIPBOARD_AVAILABLE:
        return None
    try:
        text = pyperclip.paste()
        if text and ('http://' in text or 'https://' in text):
            # Extract URL from text
            url_match = re.search(r'https?://[^\s<>"\']+', text)
            if url_match:
                return url_match.group(0)
    except:
        pass
    return None


# ========== SETTINGS MENU ==========
def settings_menu(config):
    """Interactive settings menu"""
    while True:
        print(f"\n{Colors.BOLD}{Colors.CYAN}═══════════════ SETTINGS ═══════════════{Colors.END}")
        print(f"  1. Output Directory: {Colors.YELLOW}{config.get('output_path')}{Colors.END}")
        print(f"  2. Default Quality: {Colors.YELLOW}{config.get('default_quality')}{Colors.END}")
        print(f"  3. Max Retries: {Colors.YELLOW}{config.get('max_retries')}{Colors.END}")
        print(f"  4. Concurrent Downloads: {Colors.YELLOW}{config.get('concurrent_downloads')}{Colors.END}")
        print(f"  5. Download Subtitles: {Colors.YELLOW}{config.get('download_subtitles')}{Colors.END}")
        print(f"  6. Show File Size: {Colors.YELLOW}{config.get('show_file_size')}{Colors.END}")
        print(f"  7. ← Back to Main Menu")
        print(f"{Colors.CYAN}{'='*42}{Colors.END}")
        
        choice = input(f"{Colors.GREEN}Select setting to change (1-7): {Colors.END}").strip()
        
        if choice == '1':
            new_path = input(f"{Colors.CYAN}Enter new output directory: {Colors.END}").strip()
            if new_path:
                config.set('output_path', new_path)
                os.makedirs(new_path, exist_ok=True)
                print(f"{Colors.GREEN}✅ Output directory updated!{Colors.END}")
        
        elif choice == '2':
            print("  1. best | 2. 8k | 3. 4k | 4. 1080p | 5. 720p | 6. 480p")
            q_choice = input(f"{Colors.GREEN}Select default quality (1-6): {Colors.END}").strip()
            quality_map = {'1': 'best', '2': '8k', '3': '4k', '4': '1080p', '5': '720p', '6': '480p'}
            if q_choice in quality_map:
                config.set('default_quality', quality_map[q_choice])
                print(f"{Colors.GREEN}✅ Default quality updated!{Colors.END}")
        
        elif choice == '3':
            try:
                retries = int(input(f"{Colors.CYAN}Enter max retries (1-10): {Colors.END}").strip())
                if 1 <= retries <= 10:
                    config.set('max_retries', retries)
                    print(f"{Colors.GREEN}✅ Max retries updated!{Colors.END}")
            except ValueError:
                print(f"{Colors.RED}Invalid number{Colors.END}")
        
        elif choice == '4':
            try:
                workers = int(input(f"{Colors.CYAN}Enter concurrent downloads (1-10): {Colors.END}").strip())
                if 1 <= workers <= 10:
                    config.set('concurrent_downloads', workers)
                    print(f"{Colors.GREEN}✅ Concurrent downloads updated!{Colors.END}")
            except ValueError:
                print(f"{Colors.RED}Invalid number{Colors.END}")
        
        elif choice == '5':
            current = config.get('download_subtitles')
            config.set('download_subtitles', not current)
            print(f"{Colors.GREEN}✅ Subtitles {'enabled' if not current else 'disabled'}!{Colors.END}")
        
        elif choice == '6':
            current = config.get('show_file_size')
            config.set('show_file_size', not current)
            print(f"{Colors.GREEN}✅ File size display {'enabled' if not current else 'disabled'}!{Colors.END}")
        
        elif choice == '7':
            break


# ========== INTERACTIVE MENU ==========
def interactive_menu():
    """Interactive CLI menu for the downloader"""
    print_banner()
    
    config = Config()
    downloader = VideoDownloader(config=config)
    
    # Check clipboard for URL on startup
    clipboard_url = get_clipboard_url()
    if clipboard_url:
        print(f"{Colors.YELLOW}📋 URL detected in clipboard: {clipboard_url[:60]}...{Colors.END}")
    
    while True:
        print(f"\n{Colors.MAGENTA}{Colors.BOLD}  ♥ ═══════════════ MAIN MENU ═══════════════ ♥{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}                                          {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}1.{Colors.END} 📹 Download Video (Single)           {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}2.{Colors.END} 🎵 Download Audio Only (MP3)         {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}3.{Colors.END} 📋 Download Playlist                 {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}4.{Colors.END} 📥 Batch Download (Multiple URLs)    {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}5.{Colors.END} 📁 View Downloaded Files             {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}6.{Colors.END} 📜 View Download History             {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.CYAN}7.{Colors.END} ⚙️  Settings                          {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.RED}8.{Colors.END} ❌ Exit                              {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}║{Colors.END}                                          {Colors.MAGENTA}║{Colors.END}")
        if clipboard_url:
            print(f"  {Colors.MAGENTA}║{Colors.END}  {Colors.DIM}[Press 'c' to use clipboard URL]{Colors.END}       {Colors.MAGENTA}║{Colors.END}")
        print(f"  {Colors.MAGENTA}♥ ════════════════════════════════════════ ♥{Colors.END}")
        
        choice = input(f"\n  {Colors.GREEN}✨ Enter your choice (1-8): {Colors.END}").strip().lower()
        
        # Handle clipboard shortcut
        if choice == 'c' and clipboard_url:
            url = clipboard_url
            print(f"\n{Colors.CYAN}Using clipboard URL: {url}{Colors.END}")
            quality = config.get('default_quality', 'best')
            downloader.download(url, quality)
            clipboard_url = get_clipboard_url()  # Refresh
            continue
        
        if choice == '1':
            url = input(f"\n{Colors.CYAN}Enter video URL: {Colors.END}").strip()
            if not url:
                print(f"{Colors.RED}❌ No URL provided!{Colors.END}")
                continue
            
            print(f"\n{Colors.YELLOW}Select quality:{Colors.END}")
            print("  1. Best (Maximum quality)")
            print("  2. 8K (4320p)")
            print("  3. 4K (2160p)")
            print("  4. 1080p (Full HD)")
            print("  5. 720p (HD)")
            print("  6. 480p (SD)")
            
            quality_choice = input(f"{Colors.GREEN}Enter choice (1-6, default=1): {Colors.END}").strip() or '1'
            quality_map = {'1': 'best', '2': '8k', '3': '4k', '4': '1080p', '5': '720p', '6': '480p'}
            quality = quality_map.get(quality_choice, 'best')
            
            downloader.download(url, quality)
        
        elif choice == '2':
            url = input(f"\n{Colors.CYAN}Enter video URL to extract audio: {Colors.END}").strip()
            if not url:
                print(f"{Colors.RED}❌ No URL provided!{Colors.END}")
                continue
            downloader.download(url, audio_only=True)
        
        elif choice == '3':
            url = input(f"\n{Colors.CYAN}Enter playlist URL: {Colors.END}").strip()
            if not url:
                print(f"{Colors.RED}❌ No URL provided!{Colors.END}")
                continue
            
            print(f"\n{Colors.YELLOW}Select quality for all videos:{Colors.END}")
            print("  1. Best | 2. 4K | 3. 1080p | 4. 720p | 5. 480p")
            quality_choice = input(f"{Colors.GREEN}Enter choice (1-5, default=1): {Colors.END}").strip() or '1'
            quality_map = {'1': 'best', '2': '4k', '3': '1080p', '4': '720p', '5': '480p'}
            quality = quality_map.get(quality_choice, 'best')
            
            downloader.download_playlist(url, quality)

        
        elif choice == '4':
            print(f"\n{Colors.CYAN}Enter video URLs (one per line, empty line to finish):{Colors.END}")
            urls = []
            while True:
                url = input().strip()
                if not url:
                    break
                urls.append(url)
            
            if not urls:
                print(f"{Colors.RED}❌ No URLs provided!{Colors.END}")
                continue
            
            audio_choice = input(f"{Colors.YELLOW}Download audio only? (y/N): {Colors.END}").strip().lower()
            audio_only = audio_choice == 'y'
            
            concurrent_choice = input(f"{Colors.YELLOW}Use concurrent downloads? (Y/n): {Colors.END}").strip().lower()
            concurrent = concurrent_choice != 'n'
            
            if not audio_only:
                print(f"\n{Colors.YELLOW}Select quality for all videos:{Colors.END}")
                print("  1. Best | 2. 8K | 3. 4K | 4. 1080p | 5. 720p | 6. 480p")
                quality_choice = input(f"{Colors.GREEN}Enter choice (1-6, default=1): {Colors.END}").strip() or '1'
                quality_map = {'1': 'best', '2': '8k', '3': '4k', '4': '1080p', '5': '720p', '6': '480p'}
                quality = quality_map.get(quality_choice, 'best')
            else:
                quality = 'best'
            
            downloader.download_multiple(urls, quality, audio_only, concurrent)
        
        elif choice == '5':
            downloader.show_downloaded_files()
        
        elif choice == '6':
            downloader.show_history()
            
            clear_choice = input(f"\n{Colors.YELLOW}Clear history? (y/N): {Colors.END}").strip().lower()
            if clear_choice == 'y':
                downloader.history.clear()
                print(f"{Colors.GREEN}✅ History cleared!{Colors.END}")
        
        elif choice == '7':
            settings_menu(config)
            # Reload downloader with new config
            downloader = VideoDownloader(config=config)
        
        elif choice == '8':
            print(f"\n{Colors.MAGENTA}{Colors.BOLD}  ♥ ═══════════════════════════════════════════════ ♥{Colors.END}")
            print(f"  {Colors.MAGENTA}║{Colors.END}                                                   {Colors.MAGENTA}║{Colors.END}")
            print(f"  {Colors.MAGENTA}║{Colors.END}   {Colors.CYAN}👋 Thanks for using Video Downloader Pro!{Colors.END}     {Colors.MAGENTA}║{Colors.END}")
            print(f"  {Colors.MAGENTA}║{Colors.END}   {Colors.YELLOW}✨ Created with love by ShoGenTheOne ✨{Colors.END}     {Colors.MAGENTA}║{Colors.END}")
            print(f"  {Colors.MAGENTA}║{Colors.END}                                                   {Colors.MAGENTA}║{Colors.END}")
            print(f"  {Colors.MAGENTA}♥ ═══════════════════════════════════════════════ ♥{Colors.END}\n")
            break
        
        else:
            print(f"{Colors.RED}❌ Invalid choice. Please enter 1-8.{Colors.END}")


# ========== COMMAND LINE HELP ==========
def print_help():
    """Print command line usage help"""
    help_text = f"""
{Colors.CYAN}{Colors.BOLD}Universal Video Downloader Pro - Command Line Usage{Colors.END}

{Colors.YELLOW}Usage:{Colors.END}
  python "youtube downloader.py" [URL] [OPTIONS]

{Colors.YELLOW}Options:{Colors.END}
  URL                 Video or playlist URL to download
  QUALITY             Video quality: best, 8k, 4k, 1080p, 720p, 480p
  --audio, -a         Download audio only (MP3)
  --playlist, -p      Force playlist download mode
  --no-retry          Disable retry on failure
  --help, -h          Show this help message

{Colors.YELLOW}Examples:{Colors.END}
  python "youtube downloader.py" https://youtube.com/watch?v=xxx
  python "youtube downloader.py" https://youtube.com/watch?v=xxx 1080p
  python "youtube downloader.py" https://youtube.com/watch?v=xxx --audio
  python "youtube downloader.py" https://youtube.com/playlist?list=xxx --playlist

{Colors.YELLOW}Interactive Mode:{Colors.END}
  Run without arguments to start the interactive menu.
"""
    print(help_text)


# ========== MAIN ENTRY POINT ==========
if __name__ == "__main__":
    # Check for help flag
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        sys.exit(0)
    
    # Check if URL provided as command line argument
    if len(sys.argv) > 1:
        # Command line mode
        url = sys.argv[1]
        
        # Parse quality from args
        quality = 'best'
        for arg in sys.argv[2:]:
            if arg in ['best', '8k', '4k', '1080p', '720p', '480p', '360p']:
                quality = arg
                break
        
        audio_only = '--audio' in sys.argv or '-a' in sys.argv
        force_playlist = '--playlist' in sys.argv or '-p' in sys.argv
        no_retry = '--no-retry' in sys.argv
        
        config = Config()
        if no_retry:
            config.settings['max_retries'] = 1
        
        downloader = VideoDownloader(config=config)
        
        if force_playlist:
            downloader.download_playlist(url, quality)
        else:
            downloader.download(url, quality, audio_only)
    else:
        # Interactive mode
        try:
            interactive_menu()
        except KeyboardInterrupt:
            print(f"\n\n{Colors.CYAN}👋 Download cancelled. Goodbye!{Colors.END}\n")
            sys.exit(0)
