import os
import sys
import time
import json
import socket
import requests
import subprocess
import threading
import argparse
import platform
import glob
import psutil
import hashlib
import logging
import asyncio
import aiofiles
import weakref
import re
from datetime import datetime
from pathlib import Path
from multiprocessing import shared_memory
from collections import OrderedDict

# Import renderer modules
from renderers.nuke_renderer import NukeRenderer
from renderers.silhouette_renderer import SilhouetteRenderer

# Configure logging - set to WARNING to reduce log noise, or INFO for normal operation
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Disable urllib3 connection warnings to reduce log spam
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

def safe_path_resolve(path):
    """Safely resolve path without breaking network paths"""
    # Clean the path of any hidden unicode characters
    clean_path = path.strip()
    
    # Check for network path (UNC path)
    if clean_path.startswith('\\\\') or clean_path.startswith('//'):
        # Network path - return as-is, don't use abspath
        logger.info(f"Network path detected: {clean_path}")
        return clean_path
    else:
        # Local path - use abspath
        resolved = os.path.abspath(clean_path)
        logger.info(f"Local path resolved: {resolved}")
        return resolved

# Reduce logging frequency for repeated messages
import time
_last_log_times = {}

def log_with_throttle(message, level=logging.INFO, throttle_seconds=30):
    """Log message but throttle repeated messages"""
    current_time = time.time()
    if message not in _last_log_times or (current_time - _last_log_times[message]) > throttle_seconds:
        logger.log(level, message)
        _last_log_times[message] = current_time

class OptimizedAssetCache:
    """HIGH-PERFORMANCE asset cache with preloading"""
    
    def __init__(self, max_size_gb=32):
        self.cache = OrderedDict()
        self.max_size_bytes = max_size_gb * 1024**3
        self.current_size = 0
        self.access_times = {}
        self.hit_count = 0
        self.miss_count = 0
        self.lock = threading.RLock()
        self.preload_thread = None
        
        logger.info(f"Optimized asset cache: {max_size_gb}GB capacity")
    
    def get_file(self, file_path):
        """High-speed file retrieval"""
        with self.lock:
            if file_path in self.cache:
                self.cache.move_to_end(file_path)
                self.access_times[file_path] = time.time()
                self.hit_count += 1
                logger.debug(f"Cache HIT: {file_path}")
                return self.cache[file_path]
            
            # Cache miss - load file
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
                
                self._add_to_cache(file_path, data)
                self.miss_count += 1
                logger.debug(f"Cache MISS: {file_path} ({len(data)} bytes)")
                return data
                
            except Exception as e:
                logger.error(f"Failed to load file {file_path}: {e}")
                raise
    
    def _add_to_cache(self, file_path, data):
        """Optimized cache addition"""
        file_size = len(data)
        
        # Skip if file is too large for cache
        if file_size > self.max_size_bytes * 0.3:
            logger.warning(f"File too large for cache: {file_path} ({file_size} bytes)")
            return
        
        # Evict old files if needed
        while self.current_size + file_size > self.max_size_bytes and self.cache:
            self._evict_lru()
        
        try:
            # Add to cache first
            self.cache[file_path] = data
            self.access_times[file_path] = time.time()
            
            # Only update size AFTER successful addition
            self.current_size += file_size
            
            logger.debug(f"Cached: {file_path} ({file_size} bytes, {len(self.cache)} files, {self.current_size/1024**3:.2f}GB)")
            
        except Exception as e:
            # If cache addition fails, don't update size
            logger.error(f"Failed to cache {file_path}: {e}")
            if file_path in self.cache:
                del self.cache[file_path]
            if file_path in self.access_times:
                del self.access_times[file_path]
    
    def _evict_lru(self):
        """Fast LRU eviction"""
        if not self.cache:
            return
            
        oldest_path, oldest_data = self.cache.popitem(last=False)
        file_size = len(oldest_data)
        self.current_size -= file_size
        
        if oldest_path in self.access_times:
            del self.access_times[oldest_path]
        
        logger.debug(f"Evicted: {oldest_path} ({file_size} bytes)")
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total_requests = self.hit_count + self.miss_count
            hit_ratio = (self.hit_count / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'hit_count': self.hit_count,
                'miss_count': self.miss_count,
                'hit_ratio': hit_ratio,
                'cached_files': len(self.cache),
                'cache_size_gb': self.current_size / 1024**3,
                'cache_usage_percent': (self.current_size / self.max_size_bytes) * 100
            }
    
    def cleanup_old_entries(self):
        """Clean up old cache entries"""
        with self.lock:
            current_time = time.time()
            old_entries = []
            
            for path, access_time in self.access_times.items():
                if current_time - access_time > 3600:  # 1 hour
                    old_entries.append(path)
            
            for path in old_entries:
                if path in self.cache:
                    data = self.cache.pop(path)
                    self.current_size -= len(data)
                    del self.access_times[path]
    
    def preload_common_assets(self, asset_patterns):
        """Background preloading of common assets"""
        def preload_worker():
            for pattern in asset_patterns:
                try:
                    files = glob.glob(pattern)[:10]  # Limit to avoid memory overload
                    for file_path in files:
                        if os.path.getsize(file_path) < 100 * 1024 * 1024:  # <100MB
                            self.get_file(file_path)
                            time.sleep(0.1)  # Prevent CPU spike
                except Exception as e:
                    logger.warning(f"Preload error for {pattern}: {e}")
        
        if self.preload_thread is None:
            self.preload_thread = threading.Thread(target=preload_worker, daemon=True)
            self.preload_thread.start()

class HighPerformanceRenderWorker:
    def __init__(self, server_url, worker_id=None, config_path="worker_config.json"):
        # Initialize heartbeat and metrics threads
        self.heartbeat_thread = None
        self.metrics_thread = None
        self.server_url = server_url.rstrip('/')
        self.worker_id = worker_id or socket.gethostname()
        self.hostname = socket.gethostname()
        self.ip_address = self.get_local_ip()
        self.running = False
        self.current_jobs = {}
        
        # High-performance session with connection pooling
        self.session = requests.Session()
        self.session.timeout = 5
        
        # Connection pooling for speed
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        retry_strategy = Retry(total=2, backoff_factor=0.1)
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.config = self.load_config(config_path)
        
        # Performance monitoring
        self.metrics_collector = SystemMetricsCollector()
        self.render_history = []
        
        # INSTANT NOTIFICATIONS: Redis pub/sub for instant job assignment
        self.notification_thread = None
        self.job_notification_received = threading.Event()  # Signal for instant job check
        self.notification_received_lock = threading.Lock()  # Thread safety for notifications
        self.notification_redis = None  # Shared Redis connection
        self.pubsub = None  # Pub/sub subscription
        self.notification_running = False  # Control flag for notification thread
        self.last_notification_id = 0  # Deduplication of rapid notifications
        self.notification_cooldown = 0  # Prevent notification spam
        
        # HIGH-PERFORMANCE caching
        available_ram_gb = psutil.virtual_memory().total / (1024**3)
        cache_size_gb = self.config.get('performance', {}).get('asset_cache_gb', 
                                       min(int(available_ram_gb * 0.7), 64))
        
        if available_ram_gb >= 32:
            cache_size_gb = min(int(available_ram_gb * 0.7), 64)
            logger.info(f"High-end system detected: {available_ram_gb:.1f}GB RAM, using {cache_size_gb}GB cache")
        else:
            cache_size_gb = min(int(available_ram_gb * 0.5), 16)
        
        self.asset_cache = OptimizedAssetCache(max_size_gb=cache_size_gb)
        
        # Enhanced buffer pool
        if available_ram_gb >= 32:
            buffer_size_mb = 4096
            max_buffers = 16
            logger.info(f"High-end buffer pool: {max_buffers} x {buffer_size_mb}MB buffers")
        else:
            buffer_size_mb = 2048
            max_buffers = 8
            
        self.render_buffer_pool = RenderBufferPool(buffer_size_mb=buffer_size_mb, max_buffers=max_buffers)
        self.async_file_manager = AsyncFileManager()
        self.memory_job_cache = {}
        
        # Output tracking
        self.output_locations = {}
        self.render_stats = {
            'jobs_completed': 0,
            'frames_rendered': 0,
            'total_render_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        # Setup directories - only log directory needed
        
        log_dir_config = self.config.get('paths', {}).get('log_directory')
        if not log_dir_config:
            raise ValueError("Missing required 'paths.log_directory' in worker config")
        self.log_dir = Path(log_dir_config)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create RAM disk if enabled
        if self.config.get('performance', {}).get('use_ram_disk', False):
            self.setup_ram_disk()
        
        # Worker capabilities with enhanced detection
        self.capabilities = self.detect_capabilities()
        
        # Preload common assets
        if self.config.get('performance', {}).get('preload_common_assets', False):
            self.preload_assets()
        
        # Initialize modular renderers
        self.nuke_renderer = NukeRenderer(
            config=self.config,
            asset_cache=self.asset_cache,
            monitor_process_func=self._monitor_process_with_activity,
            detect_output_files_func=self.detect_output_files,
            validate_frame_range_func=self.validate_nuke_frame_range,
            get_peak_memory_func=self.get_peak_memory_usage,
            render_stats=self.render_stats
        )
        
        self.silhouette_renderer = SilhouetteRenderer(
            config=self.config,
            asset_cache=self.asset_cache,
            monitor_process_func=self._monitor_process_with_activity,
            get_peak_memory_func=self.get_peak_memory_usage,
            render_stats=self.render_stats
        )
        
        logger.info(f"HIGH-PERFORMANCE worker initialized: {self.worker_id}")
        logger.info(f"Hostname: {self.hostname}, IP: {self.ip_address}")
        logger.info(f"Capabilities: {self.capabilities}")
        logger.info(f"Concurrency: {self.config.get('worker', {}).get('max_concurrent_jobs', 8)}")
        logger.info("Modular renderers initialized: Nuke, Silhouette")
    
    def setup_ram_disk(self):
        """Setup RAM disk for ultra-fast temp storage"""
        try:
            if platform.system() == "Windows":
                # Use configurable RAM disk path
                ram_disk_path = self.config.get('performance', {}).get('ram_disk_path', 'R:\\')
                if os.path.exists(ram_disk_path):
                    logger.info(f"RAM disk available: {ram_disk_path} (not used - Nuke handles own cache)")
            elif platform.system() == "Linux":
                # Use tmpfs
                ram_disk_path = "/tmp/render_ramdisk"
                if os.path.exists(ram_disk_path):
                    logger.info(f"tmpfs RAM disk available: {ram_disk_path} (not used - renderers handle own cache)")
        except Exception as e:
            logger.warning(f"RAM disk setup failed: {e}")
    
    def preload_assets(self):
        """Preload common render assets"""
        asset_patterns = [
            "\\\\*\\**\\*.exr",
            "\\\\*\\**\\*.dpx", 
            "\\\\*\\**\\*.tif",
            "\\\\*\\**\\*.mov"
        ]
        self.asset_cache.preload_common_assets(asset_patterns)
    
    # Silhouette helper methods moved to SilhouetteRenderer class
    
    def get_peak_memory_usage(self, job_id):
        """Get stored peak memory usage for job"""
        cache = getattr(self, '_peak_memory_cache', {})
        return cache.get(job_id, 0)
    
    def _monitor_process_with_activity(self, process, max_timeout):
        """Smart process monitoring - kill only if truly stuck (no activity)"""
        import psutil
        import threading
        
        try:
            # Get psutil process for monitoring
            ps_process = psutil.Process(process.pid)
            
            # Track activity
            idle_start_time = None
            max_idle_time = 180     # Was 600 (3 min instead of 10 min)
            check_interval = 10     # Was 30 (check every 10s instead of 30s)
            total_time = 0
            
            logger.info(f"[SMART_MONITOR] Monitoring process {process.pid} for activity")
            
            # Start thread to capture output
            output_queue = []
            
            def capture_output():
                try:
                    stdout, stderr = process.communicate()
                    output_queue.extend([stdout, stderr])
                except Exception as e:
                    output_queue.extend([b"", str(e).encode()])
            
            output_thread = threading.Thread(target=capture_output)
            output_thread.daemon = True
            output_thread.start()
            
            # Monitor process activity
            last_cpu_times = ps_process.cpu_times()
            
            while process.poll() is None and total_time < max_timeout:
                time.sleep(check_interval)
                total_time += check_interval
                
                try:
                    # Check CPU activity
                    current_cpu_times = ps_process.cpu_times()
                    cpu_delta = (current_cpu_times.user - last_cpu_times.user + 
                               current_cpu_times.system - last_cpu_times.system)
                    
                    # Check memory activity (memory usage changes indicate work)
                    memory_info = ps_process.memory_info()
                    
                    # Process is active if CPU time increased or high memory usage
                    is_active = (cpu_delta > 0.1 or memory_info.rss > 500 * 1024 * 1024)  # 500MB+
                    
                    if is_active:
                        # Process is working - reset idle timer
                        if idle_start_time:
                            logger.info(f"[SMART_MONITOR] Process {process.pid} resumed activity")
                            idle_start_time = None
                    else:
                        # Process appears idle
                        if idle_start_time is None:
                            idle_start_time = time.time()
                            logger.info(f"[SMART_MONITOR] Process {process.pid} appears idle, monitoring...")
                        else:
                            idle_duration = time.time() - idle_start_time
                            if idle_duration > max_idle_time:
                                logger.error(f"[SMART_MONITOR] Process {process.pid} stuck ({idle_duration:.0f}s idle) - killing")
                                process.kill()
                                break
                    
                    last_cpu_times = current_cpu_times
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process ended or can't access - break monitoring
                    break
            
            # Wait for output thread to complete (with timeout)
            output_thread.join(timeout=30)
            
            # Handle timeout case
            if process.poll() is None and total_time >= max_timeout:
                logger.error(f"[SMART_MONITOR] Process {process.pid} reached max timeout ({max_timeout}s) - killing")
                process.kill()
                process.wait(timeout=10)
                raise subprocess.TimeoutExpired(None, max_timeout, b"", b"Max timeout reached")
            
            # Return captured output
            if len(output_queue) >= 2:
                return output_queue[0], output_queue[1]
            else:
                stdout, stderr = process.communicate(timeout=10)
                return stdout, stderr
                
        except Exception as e:
            logger.error(f"[SMART_MONITOR] Error monitoring process: {e}")
            # Fallback to simple communicate
            try:
                return process.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(None, 60, stdout, stderr)
    
    def detect_output_files(self, script_path, frame_range, job_data):
        """
        Analyze render script to detect output files that would be rendered.
        Supports both Nuke and Silhouette render outputs.
        """
        try:
            if '-' in frame_range:
                start_frame, end_frame = map(int, frame_range.split('-'))
            else:
                start_frame = end_frame = int(frame_range)
            output_info = {
                'script': script_path,
                'frame_range': frame_range,
                'outputs': [],
                'total_files': 0,
                'total_size': 0,
                'renderer': job_data.get('renderer', 'unknown')
            }
            
            # Handle Silhouette project files
            if script_path.lower().endswith('.sfx'):
                # For Silhouette, we'll look for common output patterns
                script_dir = os.path.dirname(script_path)
                
                # Common Silhouette output patterns
                output_patterns = [
                    os.path.join(script_dir, '**', '*.tif'),
                    os.path.join(script_path, '..', '..', '*.tif'),  # Common pattern from logs
                    os.path.join(script_path, '..', '*.tif')
                ]
                
                # Look for existing output files matching the frame range
                import glob
                for pattern in output_patterns:
                    files = glob.glob(pattern, recursive=True)
                    if files:
                        # Get the most recently modified file as reference
                        ref_file = max(files, key=os.path.getmtime)
                        
                        # Extract frame number and pattern
                        frame_pattern = re.sub(r'\.(\d+)\.(?:tif|exr|dpx|png|jpg)', 
                                            r'.*\1.*\.\2', 
                                            os.path.basename(ref_file))
                        
                        # Create output pattern
                        output_dir = os.path.dirname(ref_file)
                        output_pattern = os.path.join(output_dir, frame_pattern)
                        
                        output_info['outputs'].append({
                            'node_index': 0,
                            'path_pattern': output_pattern.replace('\\', '/'),
                            'frame_pattern': output_pattern.replace('\\', '/'),
                            'expected_files': end_frame - start_frame + 1,
                            'found_files': len(files),
                            'size_bytes': sum(os.path.getsize(f) for f in files)
                        })
                        output_info['total_files'] += len(files)
                        output_info['total_size'] += sum(os.path.getsize(f) for f in files)
                        break
                
                # If no outputs found, make an educated guess
                if not output_info['outputs']:
                    output_dir = os.path.join(script_path, '..', 'output')
                    default_output = os.path.join(output_dir, 'output.####.tif')
                    output_info['outputs'].append({
                        'node_index': 0,
                        'path_pattern': default_output.replace('\\', '/'),
                        'frame_pattern': default_output.replace('\\', '/').replace('####', r'\\d+'),
                        'expected_files': end_frame - start_frame + 1,
                        'found_files': 0,
                        'size_bytes': 0
                    })
                    output_info['total_files'] = end_frame - start_frame + 1
            
            # Handle Nuke scripts
            else:
                # Extract output paths from Nuke script
                with open(script_path, 'r') as f:
                    script_content = f.read()
                    
                # Look for Write nodes in the script
                import re
                write_nodes = re.findall(r'Write \{\s+file (\S+?)(?:\s|\})', script_content, re.DOTALL)
                
                # Process each write node's output
                for i, file_path in enumerate(write_nodes):
                    # Clean up the path (remove quotes, etc.)
                    file_path = file_path.strip('\'"')
                    
                    # Handle frame number substitution
                    frame_pattern = re.sub(r'%0*\d+d', r'\\d+', file_path)
                    frame_pattern = re.sub(r'#+', r'\\d+', frame_pattern)
                    
                    # Count expected files
                    num_frames = end_frame - start_frame + 1
                    output_info['outputs'].append({
                        'node_index': i,
                        'path_pattern': file_path,
                        'frame_pattern': frame_pattern,
                        'expected_files': num_frames,
                        'found_files': 0,
                        'size_bytes': 0
                    })
                    output_info['total_files'] += num_frames
                
                # If we couldn't detect write nodes, make an educated guess based on common patterns
                if not output_info['outputs']:
                    script_dir = os.path.dirname(script_path)
                    script_name = os.path.splitext(os.path.basename(script_path))[0]
                    default_output = os.path.join(script_dir, 'output', f'{script_name}.####.exr')
                    output_info['outputs'].append({
                        'node_index': 0,
                        'path_pattern': default_output,
                        'frame_pattern': default_output.replace('####', r'\\d+'),
                        'expected_files': end_frame - start_frame + 1,
                        'found_files': 0,
                        'size_bytes': 0
                    })
                    output_info['total_files'] = end_frame - start_frame + 1
            
            return output_info
            
        except Exception as e:
            logger.error(f"Error detecting output files: {e}")
            return {
                'script': script_path,
                'frame_range': frame_range,
                'outputs': [],
                'total_files': 0,
                'total_size': 0,
                'error': str(e)
            }
    
    def validate_nuke_frame_range(self, project_file, requested_start, requested_end):
        """Validate frame range against actual Nuke project content"""
        try:
            # Read Nuke script to find actual frame range
            with open(project_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Look for frame range indicators in Nuke script
            import re
            
            # Common patterns in Nuke scripts for frame ranges
            frame_patterns = [
                r'first_frame\s+(\d+)',
                r'last_frame\s+(\d+)',
                r'frame_range\s+"(\d+)-(\d+)"',
                r'root\s*\{[^}]*first_frame\s+(\d+)[^}]*last_frame\s+(\d+)',
                r'Read\s*\{[^}]*first\s+(\d+)[^}]*last\s+(\d+)',
                r'Write\s*\{[^}]*first\s+(\d+)[^}]*last\s+(\d+)'
            ]
            
            project_start = None
            project_end = None
            
            # Try to find root node frame range first (most reliable)
            root_pattern = r'root\s*\{[^}]*first_frame\s+(\d+)[^}]*last_frame\s+(\d+)[^}]*\}'
            root_match = re.search(root_pattern, content, re.DOTALL)
            if root_match:
                project_start = int(root_match.group(1))
                project_end = int(root_match.group(2))
                logger.info(f"[INFO] Found Nuke root frame range: {project_start}-{project_end}")
            
            # If root not found, try other patterns
            if project_start is None or project_end is None:
                for pattern in frame_patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        if len(matches[0]) == 2:  # Pattern with both start and end
                            project_start = int(matches[0][0])
                            project_end = int(matches[0][1])
                            break
                        elif 'first' in pattern.lower():
                            project_start = int(matches[0])
                        elif 'last' in pattern.lower():
                            project_end = int(matches[0])
            
            # If we found the project's actual frame range
            if project_start is not None and project_end is not None:
                actual_frames = project_end - project_start + 1
                requested_frames = requested_end - requested_start + 1
                
                logger.info(f"[INFO] Nuke project frame range: {project_start}-{project_end} ({actual_frames} frames)")
                logger.info(f"[INFO] Requested frame range: {requested_start}-{requested_end} ({requested_frames} frames)")
                
                # Adjust requested range to fit within actual range
                adjusted_start = max(requested_start, project_start)
                adjusted_end = min(requested_end, project_end)
                
                if adjusted_start > adjusted_end:
                    return None, None, f"Requested frames {requested_start}-{requested_end} are outside project range {project_start}-{project_end}"
                
                if adjusted_start != requested_start or adjusted_end != requested_end:
                    logger.warning(f"[WARN] Nuke frame range adjusted: {requested_start}-{requested_end} -> {adjusted_start}-{adjusted_end}")
                    return adjusted_start, adjusted_end, f"Frame range adjusted to fit Nuke project: {adjusted_start}-{adjusted_end}"
                
                return adjusted_start, adjusted_end, "Nuke frame range validated"
            
            # If we couldn't determine project range, proceed with requested range but warn
            logger.warning(f"[WARN] Could not determine Nuke project frame range, proceeding with requested: {requested_start}-{requested_end}")
            return requested_start, requested_end, "Could not validate Nuke frame range - proceeding with requested"
            
        except Exception as e:
            logger.warning(f"[WARN] Nuke frame validation failed: {e}, proceeding with requested range")
            return requested_start, requested_end, f"Nuke frame validation error: {e}"

    # Silhouette frame validation moved to SilhouetteRenderer class

    # Renderer methods moved to separate modules (renderers/nuke_renderer.py and renderers/silhouette_renderer.py)
    
    def execute_render_job(self, job):
        """Execute render job with all features preserved"""
        logger.info(f"Starting job execution: {job}")
        
        try:
            # For test jobs, simulate realistic rendering
            if job.get('job_data', {}).get('type') == 'test' or job.get('renderer') == 'test':
                start_time = time.time()
                frame_range = job.get('frame_range', '1')
                
                # Parse frame range to get frame count
                if '-' in frame_range:
                    start_frame, end_frame = map(int, frame_range.split('-'))
                    frame_count = end_frame - start_frame + 1
                else:
                    frame_count = 1
                
                # Simulate realistic render time (1-3 seconds per frame)
                import random
                render_time = random.uniform(1.0, 3.0) * frame_count
                
                logger.info(f" Simulating test render: {frame_count} frames, estimated {render_time:.1f}s")
                time.sleep(render_time)
                
                success = True
                error_msg = None
                metrics = {
                    'render_time': render_time,
                    'frames_rendered': frame_count,
                    'fps': frame_count / render_time if render_time > 0 else 0,
                    'test_mode': True
                }
                
                logger.info(f"Test render completed: {frame_count} frames in {render_time:.1f}s")
            else:
                # Get job details from job structure or job_data
                job_data = job.get('job_data', job)
                frame_range = job['frame_range']
                file_path = job_data.get('file_path') or job.get('file_path')
                renderer = job_data.get('renderer') or job.get('renderer')
                batch_id = job['sub_job_id']  # Define batch_id for error logging
                
                # Update job status to running (job already added in main loop)
                with threading.Lock():
                    if job['sub_job_id'] in self.current_jobs:
                        self.current_jobs[job['sub_job_id']]['status'] = 'running'
                    else:
                        # Fallback if not added in main loop
                        self.current_jobs[job['sub_job_id']] = {
                            'status': 'running',
                            'start_time': time.time()
                        }
                
                # Execute render based on renderer type
                if renderer == 'nuke':
                    # Get executable path from job data - REQUIRED
                    executable_path = job_data.get('executable_path')
                    if not executable_path:
                        logger.error(f"Job {batch_id}: No executable_path provided in job data")
                        success = False
                        error_msg = "Missing executable_path in job data"
                        metrics = {}
                    else:
                        # Validate executable exists before attempting render
                        is_valid, validation_msg = self.validate_executable(executable_path)
                        if not is_valid:
                            logger.error(f"Job {batch_id}: Executable validation failed: {validation_msg}")
                            success = False
                            error_msg = f"Executable validation failed: {validation_msg}"
                            metrics = {}
                        else:
                            success, error_msg, metrics = self.nuke_renderer.render_nuke_optimized(
                                executable=executable_path,
                                project_file=file_path,
                                frame_range=frame_range,
                                job_data=job_data,
                                batch_id=job['sub_job_id']
                            )
                elif renderer == 'silhouette':
                    # Get executable path from job data - REQUIRED
                    executable_path = job_data.get('executable_path')
                    if not executable_path:
                        logger.error(f"Job {batch_id}: No executable_path provided in job data")
                        success = False
                        error_msg = "Missing executable_path in job data"
                        metrics = {}
                    
                    else:
                        # Validate executable exists before attempting render
                        is_valid, validation_msg = self.validate_executable(executable_path)
                        if not is_valid:
                            logger.error(f"Job {batch_id}: Executable validation failed: {validation_msg}")
                            success = False
                            error_msg = f"Executable validation failed: {validation_msg}"
                            metrics = {}
                        else:
                            success, error_msg, metrics = self.silhouette_renderer.render_silhouette_optimized(
                                executable=executable_path,
                                project_file=file_path,
                                frame_range=frame_range,
                                job_data=job_data,
                                batch_id=job['sub_job_id']
                            )
                else:
                    success = False
                    error_msg = f"Unsupported renderer: {renderer}"
                    metrics = {}
            
            # Report completion with retry logic
            max_retries = 3
            completion_reported = False
            for retry in range(max_retries):
                try:
                    response = self.session.post(
                        f"{self.server_url}/api/jobs/complete",
                        json={
                            'sub_job_id': job['sub_job_id'],
                            'success': success,
                            'error_message': error_msg,
                            'metrics': metrics
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        completion_reported = True
                        break
                    else:
                        logger.error(f"Failed to report job completion: HTTP {response.status_code}")
                        if retry < max_retries - 1:
                            time.sleep(5 * (retry + 1))
                        
                except requests.RequestException as e:
                    logger.error(f"Failed to report job completion (attempt {retry + 1}/{max_retries}): {e}")
                    if retry < max_retries - 1:
                        time.sleep(5 * (retry + 1))
            
            if not completion_reported:
                logger.error(f"Could not report job completion after {max_retries} attempts")
            
            # Remove from current jobs
            with threading.Lock():
                self.current_jobs.pop(job['sub_job_id'], None)
                
            # Force memory cleanup after job completion
            self.cleanup_after_job_completion(job['sub_job_id'])
            
            # Track completion time for smart waiting
            with threading.Lock():
                self.last_job_completion = time.time()
            # Enhanced batch logging
            batch_duration = time.time() - job.get('start_time', time.time())
            logger.info(f"[BATCH_COMPLETE] Worker {self.worker_id}: Batch {job['sub_job_id'][:8]} completed in {batch_duration:.1f}s")
            logger.info(f"[BATCH_METRICS] Frames: {job.get('frame_range', 'N/A')}, Success: {success}, Memory cleaned, ready for next")
                
        except Exception as e:
            logger.error(f"Job execution error: {e}")
            logger.exception("Full traceback:")
            
            # Report the failure to the server
            try:
                response = self.session.post(
                    f"{self.server_url}/api/jobs/complete",
                    json={
                        'sub_job_id': job['sub_job_id'],
                        'success': False,
                        'error_message': str(e),
                        'metrics': {}
                    },
                    timeout=30
                )
                if response.status_code == 200:
                    logger.info(f"Reported job failure to server: {job['sub_job_id'][:8]}")
                else:
                    logger.error(f"Failed to report job failure: HTTP {response.status_code}")
            except Exception as report_error:
                logger.error(f"Could not report job failure: {report_error}")
            
            # Remove from current jobs
            with threading.Lock():
                self.current_jobs.pop(job['sub_job_id'], None)

    def start(self):
        """Start optimized worker with all original features"""
        logger.info(f"Starting HIGH-PERFORMANCE worker {self.worker_id}")
        
        # Register with retry logic
        if not self.register_with_server():
            logger.error("Failed to register with server. Exiting.")
            return
        
        self.running = True
        
        # Start background threads
        self.start_background_threads()
        
        # INSTANT NOTIFICATIONS: Start Redis pub/sub listener for instant job notifications
        self.start_instant_job_notifications()
        
        logger.info("Worker online and ready for HIGH-PERFORMANCE rendering with INSTANT job notifications")
        
        # Main work loop with better error recovery
        consecutive_failures = 0
        max_failures = 10
        max_network_failures = 20  # Separate limit for network issues
        network_failures = 0
        
        while self.running:
            try:
                job = self.get_next_job()
                
                if job:
                    consecutive_failures = 0
                    network_failures = 0  # Reset on successful job retrieval
                    
                    # CRITICAL: Add job to current_jobs BEFORE starting thread to prevent race condition
                    with threading.Lock():
                        self.current_jobs[job['sub_job_id']] = {
                            'status': 'starting',
                            'start_time': time.time()
                        }
                    
                    logger.info(f"[JOB_START] Worker {self.worker_id}: Starting job {job['sub_job_id'][:8]}")
                    
                    # Execute in separate thread for better resource management
                    job_thread = threading.Thread(
                        target=self.execute_render_job,
                        args=(job,),
                        name=f"OptimizedRender-{job['sub_job_id']}"
                    )
                    job_thread.start()
                    
                    # Wait longer to ensure single job processing
                    time.sleep(3)  # Increased from 1s to ensure job thread starts
                else:
                    # No jobs available - INSTANT NOTIFICATION optimized waiting
                    with threading.Lock():
                        recently_completed = hasattr(self, 'last_job_completion') and (time.time() - self.last_job_completion) < 10
                    
                    if recently_completed:
                        # Just completed job - wait for instant notification or short timeout
                        logger.debug(f"[INSTANT_WAIT] Worker {self.worker_id}: Waiting for instant job notification...")
                        notification_received = self.job_notification_received.wait(timeout=0.5)  # 500ms max wait
                        
                        if notification_received:
                            logger.debug(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Received instant job notification!")
                            with self.notification_received_lock:
                                self.job_notification_received.clear()  # Thread-safe reset
                            continue  # Immediately check for jobs
                        else:
                            logger.debug(f"[INSTANT_WAIT] Worker {self.worker_id}: No instant notification, continuing polling")
                    else:
                        # No recent activity - longer wait with instant notifications
                        logger.debug(f"[IDLE_WAIT] Worker {self.worker_id}: Idle, waiting for instant job notification...")
                        notification_received = self.job_notification_received.wait(timeout=10.0)  # 10s max wait for production efficiency
                        
                        if notification_received:
                            logger.debug(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Received instant job notification during idle!")
                            with self.notification_received_lock:
                                self.job_notification_received.clear()  # Thread-safe reset  
                            continue  # Immediately check for jobs
                        else:
                            logger.debug(f"[IDLE_POLL] Worker {self.worker_id}: No instant notification, polling anyway")
                    
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                self.running = False
                break
            except requests.RequestException as e:
                # Network-specific error handling
                network_failures += 1
                logger.error(f"Network error ({network_failures}/{max_network_failures}): {e}")
                
                if network_failures >= max_network_failures:
                    logger.error("Too many network failures, shutting down")
                    self.running = False
                else:
                    # Longer wait for network issues
                    wait_time = min(300, network_failures * 30)  # Max 5 minutes
                    logger.info(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Worker error ({consecutive_failures}/{max_failures}): {e}")
                
                if consecutive_failures >= max_failures:
                    logger.error("Too many consecutive failures, shutting down")
                    self.running = False
                else:
                    time.sleep(min(60, consecutive_failures * 10))
        
        logger.info("High-performance worker shutdown complete")
    
    # Include ALL other necessary methods from original worker_node.py
    def load_config(self, config_path):
        """Load optimized worker configuration with all features"""
        # Start with minimal defaults
        default_config = {
            "heartbeat_interval": 15,
            "metrics_interval": 20,
            "retry_attempts": 2,
            "timeout_per_frame": 900,  # Reduced for speed
            "log_directory": "logs",
            "worker": {
                "max_concurrent_jobs": 8  # Increased for performance
            },
            "performance": {
                "asset_cache_gb": 32,
                "use_ram_disk": False,
                "max_render_threads": 16,
                "preload_common_assets": True
            },
            "resource_limits": {
                "max_memory_percent": 90,  # Increased for performance
                "max_cpu_percent": 95
            },
            "network": {
                "connection_pool_size": 20,
                "request_timeout": 5,
                "asset_download_threads": 4
            }
        }
        
        # Load user config first
        user_config = {}
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                    logger.info(f"Loaded user config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}, using optimized defaults")
        
        # Merge configs
        final_config = {**default_config}
        
        # Handle nested worker config
        if 'worker' in user_config:
            final_config['worker'].update(user_config['worker'])
            logger.info(f"Applied worker config: {user_config['worker']}")
        
        # Handle performance config
        if 'performance' in user_config:
            final_config['performance'].update(user_config['performance'])
            logger.info(f"Applied performance config: {user_config['performance']}")
        
        # Apply other top-level configs
        for key, value in user_config.items():
            if key not in ['worker', 'performance']:
                if key in final_config and isinstance(final_config[key], dict) and isinstance(value, dict):
                    final_config[key].update(value)
                else:
                    final_config[key] = value
        
        # Force single job per worker for production stability
        final_config['worker']['max_concurrent_jobs'] = 1
        logger.info(f"PRODUCTION MODE: Single job per worker enforced for maximum stability and performance")
        
        return final_config
    
    def detect_optimal_concurrency(self):
        """Enhanced concurrency detection for performance"""
        cpu_count = os.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3)
        
        memory_per_job_gb = 1.5  # Reduced for higher concurrency
        
        if memory_gb >= 32:
            memory_limit = max(int((memory_gb * 0.9) // memory_per_job_gb), 1)  # Use 90% RAM
            cpu_limit = max(int(cpu_count * 0.9), 2)  # Use 90% CPU cores
            max_concurrent = 32  # Increased maximum
            logger.info(f"High-end mode: Using 90% RAM, 90% CPU cores")
        else:
            memory_limit = max(int((memory_gb * 0.8) // memory_per_job_gb), 1)
            cpu_limit = max(int(cpu_count * 0.75), 1)
            max_concurrent = 16
        
        optimal_jobs = min(memory_limit, cpu_limit, max_concurrent)
        
        logger.info(f"Optimized concurrency: {optimal_jobs} jobs (Memory: {memory_gb:.1f}GB, CPUs: {cpu_count})")
        return optimal_jobs
    
    def get_local_ip(self):
        """Get local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def register_with_server(self):
        """Register with configurable retry and auto-reconnection"""
        connection_config = self.config.get('connection', {})
        max_retries = connection_config.get('max_registration_attempts', 3)
        auto_reconnect = connection_config.get('auto_reconnect', True)
        reconnect_interval = connection_config.get('reconnection_interval_seconds', 180)
        
        while True:
            for attempt in range(max_retries):
                try:
                    payload = {
                        'worker_id': self.worker_id,
                        'ip_address': self.ip_address,
                        'hostname': self.hostname,
                        'capabilities': self.capabilities
                    }
                    
                    response = self.session.post(
                        f"{self.server_url}/api/workers/register",
                        json=payload
                    )
                    
                    if response.status_code == 200:
                        logger.info("Successfully registered with server")
                        return True
                    else:
                        logger.error(f"Registration failed: HTTP {response.status_code}")
                        
                except requests.RequestException as e:
                    logger.error(f"Registration attempt {attempt + 1}/{max_retries} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))
            
            # If we reach here, all attempts failed
            if not auto_reconnect:
                logger.error("Registration failed after all attempts. Auto-reconnect disabled.")
                return False
            
            logger.info(f"Registration failed after {max_retries} attempts. Auto-reconnect enabled - waiting {reconnect_interval} seconds before retry cycle...")
            time.sleep(reconnect_interval)
    
    def get_next_job(self):
        """Get next job with single-job enforcement and ultra-fast response"""
        max_concurrent = 1  # ENFORCED: Single job per worker
        current_job_count = len(self.current_jobs)
        
        logger.debug(f"[JOB_REQUEST] Worker {self.worker_id}: {current_job_count}/{max_concurrent} jobs (SINGLE JOB MODE)")
        
        if current_job_count >= max_concurrent:
            active_jobs = list(self.current_jobs.keys())
            logger.debug(f"[JOB_SKIP] Worker {self.worker_id}: Processing current job, cannot accept new one. Active: {active_jobs}")
            return None
        
        if not self.check_resource_availability():
            logger.warning(f"[JOB_SKIP] Worker {self.worker_id}: System resources low, not requesting new jobs")
            return None
        
        max_retries = 2  # Reduced for speed
        for retry in range(max_retries):
            try:
                response = self.session.get(
                    f"{self.server_url}/api/jobs/next",
                    params={'worker_id': self.worker_id},
                    timeout=self.config.get('network', {}).get('request_timeout', 15)
                )
                
                if response.status_code == 200:
                    job = response.json()
                    logger.info(f"[JOB_ASSIGNED] Worker {self.worker_id}: Got job {job.get('sub_job_id', 'unknown')}")
                    return job
                elif response.status_code == 204:
                    # Use throttled logging to avoid spam - only log every 60 seconds
                    log_with_throttle(f"[JOB_NONE] Worker {self.worker_id}: No jobs available", logging.DEBUG, 60)
                    return None
                elif response.status_code in [400, 404]:
                    # Server doesn't recognize worker ID - likely server restarted
                    logger.warning(f"[JOB_ERROR] Server doesn't recognize worker {self.worker_id} (HTTP {response.status_code})")
                    logger.info(" Server may have restarted. Attempting to re-register...")
                    
                    if self.register_with_server():
                        logger.info(" Re-registered with server, will retry job request")
                        continue  # Retry the job request after successful re-registration
                    else:
                        logger.error("Failed to re-register with server")
                        return None
                else:
                    # Throttle HTTP errors too
                    log_with_throttle(f"[JOB_ERROR] Worker {self.worker_id}: Failed to get job: HTTP {response.status_code}", logging.ERROR, 180)
                    return None
                    
            except requests.RequestException as e:
                # Use throttled logging for network errors too to avoid spam
                log_with_throttle(f"[JOB_ERROR] Worker {self.worker_id}: Network error getting job (attempt {retry + 1}/{max_retries}): {e}", logging.WARNING, 120)
                if retry < max_retries - 1:
                    time.sleep(2 * (retry + 1))  # Faster retry
                    continue
                else:
                    # Suppressed: Failed to get next job logs to reduce noise
                    return None
        return None
    
    def check_resource_availability(self):
        """Check if system has resources for new job with optimized thresholds"""
        metrics = self.metrics_collector.get_current_metrics()
        limits = self.config.get('resource_limits', {})
        
        current_jobs = len(self.current_jobs)
        memory_limit = limits.get('max_memory_percent', 90)  # Increased for performance
        cpu_limit = limits.get('max_cpu_percent', 95)
        disk_limit = 5  # GB
        
        logger.debug(f"[RESOURCE_CHECK] Worker {self.worker_id}: Jobs={current_jobs}, Memory={metrics['memory_percent']:.1f}%, CPU={metrics['cpu_percent']:.1f}%, Disk={metrics['disk_free_gb']:.1f}GB")
        
        # More permissive limits for first job
        if current_jobs == 0:
            logger.debug(f"[RESOURCE_CHECK] Worker {self.worker_id}: No current jobs, accepting first job")
            return True  # Always accept first job
        
        # Check if we recently completed a job (memory should be freed by now)
        recently_completed = hasattr(self, 'last_job_completion') and (time.time() - self.last_job_completion) < 5
        
        # More lenient checks for high-performance workers
        max_concurrent = self.config.get('worker', {}).get('max_concurrent_jobs', 8)
        if max_concurrent > 4 and current_jobs < max_concurrent:
            # Relax limits for high-performance multi-job workers
            memory_limit = min(memory_limit + 5, 95)   # Allow up to 95% memory
            cpu_limit = min(cpu_limit + 3, 98)         # Allow up to 98% CPU
            logger.debug(f"[RESOURCE_CHECK] Worker {self.worker_id}: High-performance worker, relaxed limits: Memory<{memory_limit}%, CPU<{cpu_limit}%")
            
        if metrics['memory_percent'] > memory_limit:
            logger.warning(f"[RESOURCE_BLOCK] Worker {self.worker_id}: Memory usage too high: {metrics['memory_percent']:.1f}% > {memory_limit}%")
            return False
        
        if metrics['cpu_percent'] > cpu_limit:
            logger.warning(f"[RESOURCE_BLOCK] Worker {self.worker_id}: CPU usage too high: {metrics['cpu_percent']:.1f}% > {cpu_limit}%")
            return False
        
        if metrics['disk_free_gb'] < disk_limit:
            logger.warning(f"[RESOURCE_BLOCK] Worker {self.worker_id}: Low disk space: {metrics['disk_free_gb']:.1f}GB < {disk_limit}GB")
            return False
        
        logger.debug(f"[RESOURCE_OK] Worker {self.worker_id}: Resources available for new job")
        return True
    
    def cleanup_after_job_completion(self, sub_job_id):
        """Force memory cleanup after job completion to free resources quickly"""
        try:
            logger.debug(f"[CLEANUP] Worker {self.worker_id}: Starting memory cleanup after {sub_job_id}")
            
            # Force garbage collection
            import gc
            gc.collect()
            
            # Small delay to let OS release memory
            time.sleep(0.5)  # Reduced for speed
            
            # Get memory usage after cleanup
            memory_after = psutil.virtual_memory().percent
            logger.debug(f"[CLEANUP] Worker {self.worker_id}: Memory after cleanup: {memory_after:.1f}%")
            
            # Clear any cached assets if available
            if hasattr(self, 'asset_cache'):
                self.asset_cache.cleanup_old_entries()
            
            logger.debug(f"[CLEANUP] Worker {self.worker_id}: Cleanup completed, ready for next batch")
            
        except Exception as e:
            logger.warning(f"[CLEANUP] Worker {self.worker_id}: Cleanup error (non-critical): {e}")
    
    def _get_redis_connection(self):
        """Get or create shared Redis connection with connection pooling"""
        if self.notification_redis is None:
            try:
                import redis
                from redis.connection import ConnectionPool
                
                # Create connection pool for efficiency
                pool = ConnectionPool(
                    host='localhost',
                    port=6379,
                    db=0,
                    decode_responses=True,
                    socket_connect_timeout=5,  # Increased timeout
                    socket_timeout=5,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    health_check_interval=30,  # Health check every 30s
                    max_connections=2,  # Limit connections per worker
                    retry_on_timeout=True
                )
                
                self.notification_redis = redis.Redis(connection_pool=pool)
                
                # Test connection
                self.notification_redis.ping()
                logger.info(f"[REDIS_CONN] Worker {self.worker_id}: Redis connection established")
                return True
                
            except Exception as e:
                logger.error(f"[REDIS_CONN] Worker {self.worker_id}: Redis connection failed: {e}")
                self.notification_redis = None
                return False
        else:
            # Test existing connection
            try:
                self.notification_redis.ping()
                return True
            except Exception as e:
                logger.warning(f"[REDIS_CONN] Worker {self.worker_id}: Redis connection lost, reconnecting: {e}")
                self.notification_redis = None
                return self._get_redis_connection()  # Recursive retry
    
    def start_instant_job_notifications(self):
        """INSTANT NOTIFICATIONS: Start Redis pub/sub listener with robust error handling"""
        # Try to establish Redis connection
        if not self._get_redis_connection():
            logger.warning(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Could not connect to Redis, using polling fallback")
            return
        
        try:
            # Set running flag BEFORE starting thread to prevent race condition
            self.notification_running = True
            
            # Start notification listener thread
            self.notification_thread = threading.Thread(
                target=self._listen_for_job_notifications,
                name=f"InstantNotifications-{self.worker_id}",
                daemon=True
            )
            self.notification_thread.start()
            
            logger.info(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Started instant notification system")
            
        except Exception as e:
            logger.warning(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Could not start notifications (using polling): {e}")
            self.notification_running = False
            self.notification_redis = None
    
    def _listen_for_job_notifications(self):
        """ROBUST notification listener with error recovery and proper synchronization"""
        retry_count = 0
        max_retries = 5
        backoff_delay = 1
        
        while self.notification_running and self.running and retry_count < max_retries:
            try:
                # Ensure Redis connection is healthy
                if not self._get_redis_connection():
                    logger.warning(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Redis unavailable, retry {retry_count+1}/{max_retries}")
                    retry_count += 1
                    time.sleep(backoff_delay * retry_count)
                    continue
                
                # Create pub/sub subscription with timeout
                self.pubsub = self.notification_redis.pubsub()
                
                # Use unique channel per worker to reduce noise
                worker_channel = f'render:worker:jobs_available'  # Keep shared for now
                self.pubsub.subscribe(worker_channel)
                
                logger.info(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Subscribed to {worker_channel}")
                
                # CRITICAL: Send initial job check after subscription to prevent race condition
                # This ensures we don't miss jobs submitted between worker start and subscription
                time.sleep(0.1)  # Small delay to ensure subscription is active
                with self.notification_received_lock:
                    self.job_notification_received.set()
                logger.debug(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Initial job check triggered post-subscription")
                
                # Reset retry count on successful connection
                retry_count = 0
                backoff_delay = 1
                
                # Listen for notifications with timeout
                while self.notification_running and self.running:
                    try:
                        # Use get_message with timeout instead of blocking listen()
                        message = self.pubsub.get_message(timeout=5.0)
                        
                        if message is None:
                            # Timeout - check if we should continue
                            continue
                            
                        if message['type'] == 'message':
                            try:
                                import json
                                notification_data = json.loads(message['data'])
                                
                                batches_available = notification_data.get('batches_available', 0)
                                priority = notification_data.get('priority', 'normal')
                                notification_id = notification_data.get('notification_id', 0)
                                
                                # OPTIMIZATION: Deduplicate rapid notifications
                                current_time = time.time()
                                if (notification_id <= self.last_notification_id or 
                                    current_time < self.notification_cooldown):
                                    logger.debug(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Skipping duplicate/rapid notification")
                                    continue
                                
                                # Update tracking
                                self.last_notification_id = notification_id
                                self.notification_cooldown = current_time + 0.1  # 100ms cooldown
                                
                                logger.debug(f"[INSTANT_NOTIFY] Worker {self.worker_id}: {batches_available} batches available (priority: {priority})")
                                
                                # Thread-safe signal to main worker loop
                                with self.notification_received_lock:
                                    self.job_notification_received.set()
                                
                            except json.JSONDecodeError as e:
                                logger.warning(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Invalid JSON in notification: {e}")
                            except Exception as e:
                                logger.error(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Error processing notification: {e}")
                                
                    except Exception as e:
                        logger.warning(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Message receive error: {e}")
                        break  # Break inner loop to retry connection
                        
            except Exception as e:
                logger.error(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Connection error: {e}")
                retry_count += 1
                
                if retry_count < max_retries:
                    backoff_delay = min(backoff_delay * 2, 30)  # Exponential backoff, max 30s
                    logger.info(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Retrying in {backoff_delay}s (attempt {retry_count}/{max_retries})")
                    time.sleep(backoff_delay)
                else:
                    logger.error(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Max retries reached, falling back to polling only")
                    
            finally:
                # Cleanup pub/sub connection
                if hasattr(self, 'pubsub') and self.pubsub:
                    try:
                        self.pubsub.close()
                        self.pubsub = None
                    except:
                        pass
        
        logger.info(f"[INSTANT_NOTIFY] Worker {self.worker_id}: Notification listener stopped")
    
    def send_heartbeat(self):
        """Send heartbeat to server with status and metrics - Auto-reconnect on server restart"""
        max_retries = 2
        for retry in range(max_retries):
            try:
                payload = {
                    'worker_id': self.worker_id,
                    'timestamp': time.time(),
                    'status': 'active',
                    'metrics': self.metrics_collector.get_current_metrics(),
                    'current_jobs': list(self.current_jobs.keys())
                }
                
                response = self.session.post(
                    f"{self.server_url}/api/workers/heartbeat",
                    json=payload,
                    timeout=10  # Reduced timeout
                )
                
                if response.status_code == 200:
                    return  # Success
                elif response.status_code in [400, 404]:
                    # Server doesn't recognize worker ID - likely server restarted
                    logger.warning(f"Server doesn't recognize worker {self.worker_id} (HTTP {response.status_code})")
                    logger.info("Server may have restarted. Attempting to re-register...")
                    
                    if self.register_with_server():
                        logger.info(" Successfully re-registered with server after restart")
                        return  # Re-registration successful, heartbeat will succeed next time
                    else:
                        logger.error(" Failed to re-register with server")
                else:
                    logger.error(f"Heartbeat failed: HTTP {response.status_code}")
                    if retry < max_retries - 1:
                        time.sleep(1)  # Faster retry
                    
            except requests.RequestException as e:
                logger.error(f"Heartbeat error (attempt {retry + 1}/{max_retries}): {e}")
                # Check if it's a connection error (server may be down/restarting)
                if "Connection" in str(e) or "timeout" in str(e).lower():
                    logger.info(" Connection issues detected, server may be restarting...")
                if retry < max_retries - 1:
                    time.sleep(1)  # Faster retry

    def test_network_speed(self):
        """Test network connectivity and speed"""
        try:
            start_time = time.time()
            response = self.session.get(f"{self.server_url}/api/status")
            latency = (time.time() - start_time) * 1000
            return {
                "latency_ms": round(latency, 2),
                "status": "ok" if response.status_code == 200 else "error"
            }
        except:
            return {"latency_ms": 9999, "status": "error"}

    def detect_gpu_capabilities(self):
        """Detect GPU capabilities and information"""
        gpu_info = {
            'gpu_available': False,
            'gpu_name': None,
            'gpu_memory_gb': 0,
            'cuda_version': None,
            'gpu_count': 0
        }
        
        try:
            # Try to get GPU information using nvidia-smi
            result = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                if lines and lines[0]:
                    parts = lines[0].split(', ')
                    if len(parts) >= 2:
                        gpu_info['gpu_available'] = True
                        gpu_info['gpu_name'] = parts[0].strip()
                        gpu_info['gpu_memory_gb'] = round(int(parts[1]) / 1024, 1)
                        gpu_info['gpu_count'] = len(lines)
                        
                        # Default values for detected M4000
                        if 'M4000' in gpu_info['gpu_name']:
                            gpu_info['gpu_memory_gb'] = 8.0  # M4000 has 8GB
                        
                        logger.info(f"[GPU] Detected: {gpu_info['gpu_name']} ({gpu_info['gpu_memory_gb']}GB)")
            
            # Try to get CUDA version
            try:
                cuda_result = subprocess.run(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], 
                                           capture_output=True, text=True, timeout=5)
                if cuda_result.returncode == 0 and cuda_result.stdout.strip():
                    gpu_info['cuda_version'] = cuda_result.stdout.strip().split('\n')[0]
            except:
                gpu_info['cuda_version'] = '12.2'  # Default fallback
                
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            # Fallback for systems without nvidia-smi or GPU
            gpu_config = self.config.get('gpu', {})
            if gpu_config.get('force_enable', False):
                gpu_info.update({
                    'gpu_available': True,
                    'gpu_name': gpu_config.get('name', 'Quadro M4000'),
                    'gpu_memory_gb': gpu_config.get('memory_gb', 8),
                    'cuda_version': gpu_config.get('cuda_version', '12.2'),
                    'gpu_count': 1
                })
                logger.info("[GPU] GPU capabilities set from configuration")
            else:
                logger.debug("[GPU] No GPU detected - CPU-only rendering")
        
        return gpu_info

    def detect_capabilities(self):
        """Enhanced capability detection with performance metrics"""
        capabilities = {
            'platform': platform.system(),
            'hostname': self.hostname,
            'cpu_count': os.cpu_count(),
            'memory_gb': round(psutil.virtual_memory().total / (1024**3), 2),
            'disk_space_gb': round(psutil.disk_usage('.').free / (1024**3), 2),
            'renderers': self.detect_renderers(),
            'network_speed': self.test_network_speed(),
            'max_concurrent_jobs': self.config.get('worker', {}).get('max_concurrent_jobs', 8),
            'optimization_level': 'high_performance',
            'cache_size_gb': self.config.get('performance', {}).get('asset_cache_gb', 32),
            'max_render_threads': self.config.get('performance', {}).get('max_render_threads', 16),
            **self.detect_gpu_capabilities()
        }
        
        return capabilities
    
    def start_background_threads(self):
        """Start background monitoring threads with optimized intervals"""
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="HeartbeatThread",
            daemon=True
        )
        self.heartbeat_thread.start()
        
        # Start metrics collection thread
        self.metrics_thread = threading.Thread(
            target=self._metrics_loop,
            name="MetricsThread",
            daemon=True
        )
        self.metrics_thread.start()

        logger.info(" Worker online and ready for high-performance production")
        logger.info("Background threads started with optimized intervals")
    
    def _heartbeat_loop(self):
        """Background thread for sending heartbeats with faster interval"""
        while self.running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            time.sleep(self.config.get('heartbeat_interval', 15))  # Faster heartbeat
            
    def get_task_count(self):
        """Get current number of running tasks"""
        return len(self.current_jobs)
            
    def _metrics_loop(self):
        """Background thread for collecting metrics with faster interval"""
        while self.running:
            try:
                metrics = self.metrics_collector.get_current_metrics()
                logger.debug(f"System metrics: {metrics}")
            except Exception as e:
                logger.error(f"Metrics collection error: {e}")
            time.sleep(self.config.get('metrics_interval', 20))  # Faster metrics
    
    def stop(self):
        """Stop the worker gracefully with proper cleanup"""
        logger.info("Stopping high-performance worker...")
        self.running = False
        
        # CRITICAL: Stop instant notifications first
        self._stop_instant_notifications()
        
        # Wait for background threads
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
        if self.metrics_thread:
            self.metrics_thread.join(timeout=5)
            
        # Clean up resources
        if hasattr(self, 'render_buffer_pool'):
            self.render_buffer_pool.cleanup()
            
        logger.info("High-performance worker stopped")
    
    def _stop_instant_notifications(self):
        """CLEANUP: Properly stop instant notification system"""
        try:
            # Stop the notification thread
            self.notification_running = False
            
            # Signal any waiting threads to wake up and exit
            with self.notification_received_lock:
                self.job_notification_received.set()
            
            # Close pub/sub connection
            if hasattr(self, 'pubsub') and self.pubsub:
                try:
                    self.pubsub.unsubscribe()
                    self.pubsub.close()
                    self.pubsub = None
                    logger.debug(f"[CLEANUP] Worker {self.worker_id}: Pub/sub connection closed")
                except Exception as e:
                    logger.warning(f"[CLEANUP] Worker {self.worker_id}: Error closing pub/sub: {e}")
            
            # Close Redis connection
            if hasattr(self, 'notification_redis') and self.notification_redis:
                try:
                    self.notification_redis.close()
                    self.notification_redis = None
                    logger.debug(f"[CLEANUP] Worker {self.worker_id}: Redis notification connection closed")
                except Exception as e:
                    logger.warning(f"[CLEANUP] Worker {self.worker_id}: Error closing Redis: {e}")
            
            # Wait for notification thread to finish
            if hasattr(self, 'notification_thread') and self.notification_thread and self.notification_thread.is_alive():
                self.notification_thread.join(timeout=5)
                if self.notification_thread.is_alive():
                    logger.warning(f"[CLEANUP] Worker {self.worker_id}: Notification thread did not stop gracefully")
                else:
                    logger.info(f"[CLEANUP] Worker {self.worker_id}: Notification thread stopped")
            
        except Exception as e:
            logger.error(f"[CLEANUP] Worker {self.worker_id}: Error during notification cleanup: {e}")

    def detect_renderers(self):
        """Simple renderer validation - no auto-detection needed"""
        # Jobs specify exact executable paths, so we don't need to auto-detect
        # Just return basic capability info
        return {
            'validation': 'runtime',
            'note': 'Executables validated per-job based on job specification'
        }
    
    def validate_executable(self, executable_path):
        """Simple executable validation - just check if file exists and is executable"""
        try:
            if not executable_path:
                return False, "No executable path provided"
            
            if not os.path.exists(executable_path):
                return False, f"Executable not found: {executable_path}"
            
            if not os.path.isfile(executable_path):
                return False, f"Path is not a file: {executable_path}"
            
            # On Windows, check if it's an .exe file
            if os.name == 'nt' and not executable_path.lower().endswith('.exe'):
                return False, f"Not a Windows executable (.exe): {executable_path}"
            
            # Check if file is executable (on Unix systems)
            if os.name != 'nt' and not os.access(executable_path, os.X_OK):
                return False, f"File is not executable: {executable_path}"
            
            logger.info(f"+ Validated executable: {executable_path}")
            return True, "Valid executable"
            
        except Exception as e:
            return False, f"Error validating executable: {e}"

# Include ALL supporting classes from original implementation
class RenderBufferPool:
    """High-performance shared memory pool for render operations"""
    
    def __init__(self, buffer_size_mb=2048, max_buffers=16):  # Increased defaults
        self.buffer_size = buffer_size_mb * 1024 * 1024
        self.max_buffers = max_buffers
        self.available_buffers = []
        self.in_use_buffers = {}
        self.lock = threading.Lock()
        
        logger.info(f"High-performance render buffer pool initialized: {max_buffers} x {buffer_size_mb}MB buffers")
    
    def get_buffer(self, job_id):
        """Get a render buffer from pool"""
        with self.lock:
            if self.available_buffers:
                buffer = self.available_buffers.pop()
                logger.debug(f"Reusing buffer for job {job_id}")
            elif len(self.in_use_buffers) < self.max_buffers:
                try:
                    buffer = shared_memory.SharedMemory(
                        create=True, size=self.buffer_size
                    )
                    logger.debug(f"Created new buffer for job {job_id}")
                except Exception as e:
                    logger.warning(f"Failed to create shared memory buffer: {e}")
                    return None
            else:
                logger.warning(f"No buffers available for job {job_id}")
                return None
            
            self.in_use_buffers[job_id] = buffer
            return buffer
    
    def return_buffer(self, job_id):
        """Return buffer to pool"""
        with self.lock:
            if job_id in self.in_use_buffers:
                buffer = self.in_use_buffers.pop(job_id)
                self.available_buffers.append(buffer)
                logger.debug(f"Buffer returned from job {job_id}")
    
    def cleanup(self):
        """Clean up all buffers"""
        with self.lock:
            for buffer in self.available_buffers + list(self.in_use_buffers.values()):
                try:
                    buffer.close()
                    buffer.unlink()
                except:
                    pass
            self.available_buffers.clear()
            self.in_use_buffers.clear()

class SystemMetricsCollector:
    """Optimized system performance metrics collection"""
    
    def __init__(self):
        self.process = psutil.Process()
    
    def get_current_metrics(self):
        """Get current system metrics with fast collection"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)  # Faster collection
            cpu_count = psutil.cpu_count()
            
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_gb = memory.available / (1024**3)
            
            disk = psutil.disk_usage('.')
            disk_free_gb = disk.free / (1024**3)
            disk_percent = disk.percent
            
            network = psutil.net_io_counters()
            
            return {
                'cpu_percent': cpu_percent,
                'cpu_count': cpu_count,
                'memory_percent': memory_percent,
                'memory_available_gb': round(memory_available_gb, 2),
                'disk_free_gb': round(disk_free_gb, 2),
                'disk_percent': disk_percent,
                'network_bytes_sent': network.bytes_sent,
                'network_bytes_recv': network.bytes_recv,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")
            return {
                'cpu_percent': 0,
                'memory_percent': 0,
                'disk_free_gb': 0,
                'error': str(e)
            }

class AsyncFileManager:
    """High-performance async file operations and preloading"""
    
    def __init__(self):
        self.preloaded_assets = {}
        self.preload_lock = asyncio.Lock()

# Main function with all original features preserved
def main():
    # Import required modules at function level to ensure they're available in frozen executable
    import os
    import sys
    import json
    import logging
    import argparse
    from pathlib import Path
    
    # Auto-install service when running as executable
    if getattr(sys, 'frozen', False):  # Running as PyInstaller executable
        print("Installing Render Farm Worker Service...")
        try:
            import subprocess
            import os
            
            # Get the directory where the executable is located
            exe_dir = os.path.dirname(sys.executable)
            install_script = os.path.join(exe_dir, 'worker_install.bat')
            
            if os.path.exists(install_script):
                # Change to executable directory and run install script
                result = subprocess.run([install_script], 
                                      capture_output=True, text=True, shell=True, cwd=exe_dir)
                if result.returncode == 0:
                    print("Service installation completed successfully!")
                    if result.stdout:
                        print(result.stdout)
                else:
                    print(f"Service installation failed: {result.stderr}")
                    if result.stdout:
                        print(f"Output: {result.stdout}")
            else:
                print(f"Installation script not found at: {install_script}")
        except Exception as e:
            print(f"Service installation error: {e}")
        print()
    
    parser = argparse.ArgumentParser(description='High-Performance Render Farm Worker Node')
    parser.add_argument('--mode', choices=['worker', 'server'],
                       help='Operation mode (default: determined by executable name)')
    parser.add_argument('--server', required=False,
                       help='Server URL (e.g., http://ipaddress:8080)')
    parser.add_argument('--worker-id',
                       help='Worker ID (auto-generated if not provided)')
    parser.add_argument('--config', default='worker_config.json',
                       help='Configuration file path')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Logging level')

    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # When running as executable, look for config in executable directory
    config_path = args.config
    if getattr(sys, 'frozen', False) and not os.path.isabs(config_path):
        exe_dir = os.path.dirname(sys.executable)
        config_path = os.path.join(exe_dir, config_path)

    server_url = args.server
    if not server_url:
        try:
            # Try worker config first
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # Get server URL from the nested server object
                server_config = config.get('server', {})
                server_url = server_config.get('url')

            # If not in worker config, try server config
            if not server_url and os.path.exists('server_config.json'):
                with open('server_config.json', 'r') as f:
                    server_config = json.load(f)
                    host = server_config.get('host', '0.0.0.0')
                    port = server_config.get('port', 8080)
                    server_url = f"http://{host}:{port}"
            
            if not server_url:
                logger.error("REQUIRED: No server URL found in config files")
                logger.error("Worker cannot start without server URL configuration")
                raise ValueError("Missing server URL in configuration")
            
            logger.info(f"Using server URL from config: {server_url}")
        except Exception as e:
            logger.error(f"REQUIRED: Failed to load config: {e}")
            logger.error("Worker cannot start without proper server configuration")
            raise
    
    logger.info("="*60)
    logger.info(" HIGH-PERFORMANCE RENDER FARM WORKER NODE")
    logger.info("="*60)
    
    try:
        import psutil
    except ImportError:
        logger.error("psutil not installed. Run: pip install psutil")
        sys.exit(1)
    
    worker = HighPerformanceRenderWorker(server_url, args.worker_id, config_path)
    
    try:
        worker.start()
    except KeyboardInterrupt:
        worker.stop()
    except Exception as e:
        logger.error(f"Fatal worker error: {e}")
        worker.stop()
        sys.exit(1)

if __name__ == '__main__':
    main()