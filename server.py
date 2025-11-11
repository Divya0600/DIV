#!/usr/bin/env python3
"""
Redis-Enhanced Worker Server with Web UI Support
Complete Redis backend for high-performance rendering
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import urllib.parse
import threading
import sys
import signal
import os
import mimetypes
from pathlib import Path

# Import the Redis job manager
from redis_job_manager import redis_manager
import time

# Log throttling for server endpoints
_last_log_times = {}
def log_with_throttle(message, level="INFO", throttle_seconds=30):
    """Log message but throttle repeated messages"""
    current_time = time.time()
    if message not in _last_log_times or (current_time - _last_log_times[message]) > throttle_seconds:
        print(f"[{level}] {message}")
        _last_log_times[message] = current_time

# Future: WebSocket job push system (to be implemented)
# connected_workers = {}  # worker_id -> websocket connection

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server that handles multiple connections properly"""
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 500  # Increased for 20+ workers (was 100)

class EnhancedAPIHandler(BaseHTTPRequestHandler):
    """Enhanced API handler with Redis backend"""
    
    def __init__(self, request, client_address, server):
        # Add connection tracking and cleanup
        self._start_time = time.time()
        self._request_count = 0
        super().__init__(request, client_address, server)
    
    def handle_one_request(self):
        """Override to add connection cleanup"""
        try:
            super().handle_one_request()
        except Exception as e:
            print(f"[ERROR] Request handling failed: {e}")
            # Ensure connection is closed even on error
            try:
                self.connection.close()
            except:
                pass
    
    def get_server_ip(self):
        """Get server IP address"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "localhost"
    
    def load_web_config(self):
        """Load web configuration from file"""
        config_file = Path(__file__).parent / 'web_config.json'
        
        # Default fallback config
        default_config = {
            'paths': {
                'networkShare': '\\\\localhost\\temp',
                'tempDirectory': '\\\\localhost\\temp'
            },
            'renderers': {
                'nuke': {
                    'Nuke 16': 'C:\\Program Files\\Nuke16.0v4\\Nuke16.0.exe'
                },
                'silhouette': {
                    'Silhouette 2023': 'C:\\Program Files\\BorisFX\\Silhouette 2023.0\\sfxcmd.exe'
                }
            },
            'defaults': {
                'renderer': 'nuke',
                'nukeVersion': 'Nuke 16',
                'silhouetteVersion': 'Silhouette 2023',
                'batchSize': 1,
                'priority': 'High',
                'enablePathTranslation': True,
                'outputPathTranslation': True
            }
        }
        
        try:
            print(f"[CONFIG] Looking for config file at: {config_file}")
            print(f"[CONFIG] Config file exists: {config_file.exists()}")
            if config_file.exists():
                print(f"[CONFIG] Attempting to load web config from {config_file}")
                with open(config_file, 'r') as f:
                    config = json.load(f)
                print(f"[CONFIG] Successfully loaded web config from {config_file}")
                print(f"[CONFIG] Loaded Nuke path: {config.get('renderers', {}).get('nuke', {}).get('Nuke 16', 'NOT FOUND')}")
                return config
            else:
                print(f"[CONFIG] No web config found at {config_file}, using defaults")
                # Create default config file
                with open(config_file, 'w') as f:
                    json.dump(default_config, f, indent=2)
                print(f"[CONFIG] Created default web config at {config_file}")
                return default_config
        except Exception as e:
            print(f"[CONFIG] Error loading web config: {e}, using defaults")
            print(f"[CONFIG] Error type: {type(e).__name__}")
            return default_config
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests"""
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()
    
    def send_cors_headers(self):
        """Send CORS headers"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def do_GET(self):
        """Handle GET requests - API and static files"""
        try:
            parsed_path = urllib.parse.urlparse(self.path)
            path = parsed_path.path
            
            # API endpoints
            if path.startswith('/api/'):
                self.handle_api_get(path, parsed_path.query)
            else:
                # Static file serving
                self.serve_static_file(path)
        except Exception as e:
            print(f"[ERROR] GET request failed: {e}")
            self.send_error_response(500, f"Internal server error: {e}")
    
    def handle_api_get(self, path, query_string):
        """Handle API GET requests"""
        query_params = urllib.parse.parse_qs(query_string)
        
        # Throttle job polling logs to reduce spam when no jobs available
        if path == '/api/jobs/next':
            log_with_throttle(f"Worker polling for jobs from {self.client_address[0]}", "DEBUG", 180)
        else:
            print(f"Redis API: GET {path} from {self.client_address[0]}")
        
        if path == '/api/jobs/next':
            worker_id = query_params.get('worker_id', [None])[0]
            if worker_id:
                job = redis_manager.get_next_job(worker_id)
                if job:
                    log_with_throttle(f"Assigned job {job['sub_job_id']} to worker {worker_id}", "INFO", 60)
                    self.send_json_response(job)
                else:
                    self.send_json_response(None, 204)
            else:
                self.send_error_response(400, "Missing worker_id parameter")
                
        elif path == '/api/status':
            try:
                stats = redis_manager.get_stats()
                status = {
                    'status': 'online',
                    'online_workers': stats['online_workers'],
                    'active_jobs': stats.get('active_jobs', 0),
                    'pending_batches': stats['pending_batches'],
                    'version': '3.0-redis-enhanced',
                    'server_ip': self.get_server_ip(),
                    'server_port': 8080,
                    'uptime': time.time() - getattr(self, '_start_time', time.time()),
                    'redis_connected': True,
                    'connection_pool': stats.get('connection_pool', {}),
                    'server_capacity': {
                        'request_queue_size': 500,
                        'server_timeout': 60,
                        'max_redis_connections': stats.get('connection_pool', {}).get('max_connections', 20)
                    },
                    'worker_capacity': {
                        'online_workers': stats['online_workers'],
                        'max_workers_recommended': 20,  # Configurable limit
                        'connection_pool_per_worker': 10,  # From worker_config.json
                        'total_worker_connections': stats['online_workers'] * 10
                    }
                }
                self.send_json_response(status)
            except Exception as e:
                # If Redis is down, still respond but indicate the issue
                status = {
                    'status': 'degraded',
                    'error': f'Redis connection issue: {e}',
                    'version': '3.0-redis-enhanced',
                    'redis_connected': False
                }
                self.send_json_response(status)
                
        elif path == '/api/dashboard':
            # COMBINED API: Returns status + jobs + workers in single call
            try:
                stats = redis_manager.get_stats()
                jobs = redis_manager.get_all_jobs()
                workers = redis_manager.get_all_workers()
                
                dashboard_data = {
                    'status': {
                        'status': 'online',
                        'online_workers': stats['online_workers'],
                        'active_jobs': stats.get('active_jobs', 0),
                        'pending_batches': stats['pending_batches'],
                        'version': '3.0-redis-enhanced',
                        'server_ip': self.get_server_ip(),
                        'server_port': 8080,
                        'uptime': time.time() - getattr(self, '_start_time', time.time()),
                        'redis_connected': True,
                        'worker_capacity': {
                            'online_workers': stats['online_workers'],
                            'max_workers_recommended': 20
                        }
                    },
                    'jobs': jobs,
                    'workers': workers,
                    'timestamp': time.time()
                }
                self.send_json_response(dashboard_data)
            except Exception as e:
                # If Redis is down, still respond but indicate the issue
                dashboard_data = {
                    'status': {
                        'status': 'degraded',
                        'error': f'Redis connection issue: {e}',
                        'version': '3.0-redis-enhanced',
                        'redis_connected': False
                    },
                    'jobs': [],
                    'workers': [],
                    'timestamp': time.time()
                }
                self.send_json_response(dashboard_data)
            
        elif path == '/api/workers':
            try:
                workers = redis_manager.get_all_workers()
                self.send_json_response({
                    'workers': workers,
                    'status': 'success'
                })
            except Exception as e:
                self.send_error_response(500, f"Error getting workers: {e}")
                
        elif path == '/api/jobs':
            try:
                jobs = redis_manager.get_all_jobs()
                self.send_json_response({
                    'jobs': jobs,
                    'status': 'success'
                })
            except Exception as e:
                self.send_error_response(500, f"Error getting jobs: {e}")
                
        elif path.startswith('/api/jobs/') and path.endswith('/workers'):
            # Get job worker details: /api/jobs/{job_id}/workers
            try:
                job_id = path.split('/')[-2]  # Extract job_id from path
                worker_details = redis_manager.get_job_worker_details(job_id)
                self.send_json_response({
                    'worker_details': worker_details,
                    'status': 'success'
                })
            except Exception as e:
                self.send_error_response(500, f"Error getting job worker details: {e}")
                
        elif path == '/api/health':
            # Simple health check endpoint
            try:
                # Test Redis connection
                redis_manager.redis_client.ping()
                health_status = {
                    'status': 'healthy',
                    'timestamp': time.time(),
                    'redis': 'connected',
                    'server': 'running'
                }
                self.send_json_response(health_status)
            except Exception as e:
                health_status = {
                    'status': 'unhealthy',
                    'timestamp': time.time(),
                    'redis': 'disconnected',
                    'server': 'running',
                    'error': str(e)
                }
                self.send_json_response(health_status, 503)
                
        elif path == '/api/config':
            # Web interface configuration from file
            try:
                config = self.load_web_config()
                self.send_json_response(config)
            except Exception as e:
                self.send_error_response(500, f"Error loading web config: {e}")
                
        elif path.startswith('/api/jobs/batch/') and path.endswith('/logs'):
            # Get batch logs endpoint: /api/jobs/batch/{batch_id}/logs
            try:
                batch_id = path.split('/')[-2]  # Extract batch_id from path
                logs = redis_manager.get_batch_logs(batch_id)
                self.send_json_response({"logs": logs, "batch_id": batch_id})
            except Exception as e:
                self.send_error_response(500, f"Error getting batch logs: {e}")
                
        elif path == '/api/files/browse':
            # File browser endpoint
            try:
                current_path = query_params.get('path', [''])[0]
                file_browser_data = self.browse_files(current_path)
                self.send_json_response(file_browser_data)
            except Exception as e:
                self.send_error_response(500, f"Error browsing files: {e}")
        
        elif path == '/api/debug/redis-workers':
            # Debug endpoint to see what's actually in Redis
            try:
                all_workers_raw = redis_manager.redis_client.hgetall('render:workers')
                print(f"\n=== RAW REDIS WORKERS DATA ===")
                for worker_id, worker_data in all_workers_raw.items():
                    if isinstance(worker_id, bytes):
                        worker_id = worker_id.decode('utf-8')
                    print(f"Redis Key: '{worker_id}'")
                    try:
                        data = json.loads(worker_data)
                        print(f"  Hostname: {data.get('hostname', 'unknown')}")
                        print(f"  IP: {data.get('ip_address', 'unknown')}")
                        print(f"  Status: {data.get('status', 'unknown')}")
                    except:
                        print(f"  Raw data: {worker_data}")
                    print("")
                print(f"================================\n")
                
                self.send_json_response({"workers": list(all_workers_raw.keys())})
            except Exception as e:
                print(f"Error getting Redis workers: {e}")
                self.send_error_response(500, f"Error getting Redis data: {e}")
                
        else:
            self.send_error_response(404, "Endpoint not found")
    
    def serve_static_file(self, path):
        """Serve static files for web UI"""
        # Default to index.html for root path
        if path == '/' or path == '':
            path = '/index.html'
        
        # Remove leading slash and resolve file path
        file_path = Path(__file__).parent / 'web' / path.lstrip('/')
        
        try:
            if file_path.exists() and file_path.is_file():
                # Get content type
                content_type, _ = mimetypes.guess_type(str(file_path))
                if content_type is None:
                    content_type = 'application/octet-stream'
                
                # Read and serve file
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(content)))
                # Prevent caching of HTML files
                if content_type == 'text/html':
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(content)
            else:
                # File not found - serve index.html for SPA routing
                index_path = Path(__file__).parent / 'web' / 'index.html'
                if index_path.exists():
                    with open(index_path, 'rb') as f:
                        content = f.read()
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(content)))
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.send_error_response(404, "File not found and no index.html")
                    
        except Exception as e:
            print(f"Error serving static file {path}: {e}")
            self.send_error_response(500, f"Error serving file: {e}")
    
    def do_POST(self):
        """Handle POST requests from workers and web UI"""
        try:
            parsed_path = urllib.parse.urlparse(self.path)
            path = parsed_path.path
            
            # Throttle frequent POST endpoints to reduce log spam
            if path in ['/api/workers/heartbeat', '/api/jobs/complete']:
                log_with_throttle(f"POST {path} from {self.client_address[0]}", "DEBUG", 300)
            else:
                print(f"Redis API: POST {path} from {self.client_address[0]}")
        except Exception as e:
            print(f"[ERROR] POST request failed: {e}")
            self.send_error_response(500, f"Internal server error: {e}")
            return
        
        if path == '/api/workers/register':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                worker_id = data.get('worker_id')
                ip_address = data.get('ip_address')
                hostname = data.get('hostname')
                capabilities = data.get('capabilities')
                
                if worker_id and ip_address:
                    redis_manager.register_worker(worker_id, ip_address, hostname, capabilities)
                    self.send_json_response({"status": "registered"})
                else:
                    self.send_error_response(400, "Missing worker_id or ip_address")
                    
            except Exception as e:
                self.send_error_response(500, f"Error registering worker: {e}")
                
        elif path == '/api/workers/heartbeat':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                worker_id = data.get('worker_id')
                
                if worker_id:
                    success = redis_manager.update_worker_heartbeat(worker_id)
                    if success:
                        self.send_json_response({"status": "ok"})
                    else:
                        self.send_error_response(404, f"Worker {worker_id} not registered")
                else:
                    self.send_error_response(400, "Missing worker_id")
                    
            except Exception as e:
                self.send_error_response(500, f"Error processing heartbeat: {e}")
                
        elif path == '/api/jobs/submit':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))

                # Validate renderer and file extension compatibility
                renderer = data.get('renderer', '').lower()
                project_file = data.get('file_path', '')
                
                validation_errors = []
                
                # Check if project file is provided
                if not project_file:
                    validation_errors.append({
                        'field': 'file_path',
                        'message': 'Project file path is required'
                    })
                else:
                    # Check if file exists
                    if not os.path.exists(project_file):
                        validation_errors.append({
                            'field': 'file_path',
                            'message': f'Project file not found: {project_file}'
                        })
                    else:
                        # Validate file extension matches renderer
                        file_ext = os.path.splitext(project_file)[1].lower()
                        
                        if renderer == 'nuke':
                            if file_ext not in ['.nk', '.nuke']:
                                validation_errors.append({
                                    'field': 'file_path',
                                    'message': f'Nuke renderer requires .nk or .nuke files, but got {file_ext} file. Selected file appears to be for a different renderer.'
                                })
                        elif renderer == 'silhouette':
                            if file_ext not in ['.sfx']:
                                validation_errors.append({
                                    'field': 'file_path',
                                    'message': f'Silhouette renderer requires .sfx files, but got {file_ext} file. Selected file appears to be for a different renderer.'
                                })
                        
                        print(f"[VALIDATION] PROJECT FILE EXISTS: {project_file} (Extension: {file_ext}, Renderer: {renderer})")

                # Validate executable path
                executable_path = data.get('executable_path', '')
                if executable_path:
                    if os.path.exists(executable_path):
                        print(f"[VALIDATION] EXECUTABLE EXISTS: {executable_path}")
                    else:
                        validation_errors.append({
                            'field': 'executable_path',
                            'message': f'Executable not found: {executable_path}'
                        })
                else:
                    validation_errors.append({
                        'field': 'executable_path',
                        'message': 'Executable path is required'
                    })

                # If there are validation errors, return them
                if validation_errors:
                    print(f"[VALIDATION] Job submission failed: {len(validation_errors)} validation errors")
                    for error in validation_errors:
                        print(f"[VALIDATION ERROR] {error['field']}: {error['message']}")
                    
                    self.send_json_response({
                        'status': 'validation_error',
                        'errors': validation_errors
                    }, 400)
                    return

                job_id = redis_manager.submit_job(data)
                print(f"[VALIDATION] Job submission successful: {job_id}")
                self.send_json_response({'status': 'submitted', 'job_id': job_id})
            except Exception as e:
                self.send_error_response(500, f"Error submitting job: {e}")
                
        elif path == '/api/jobs/complete':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                sub_job_id = data.get('sub_job_id')
                success = data.get('success', False)
                error_message = data.get('error_message')
                metrics = data.get('metrics', {})
                
                if sub_job_id is not None:
                    redis_manager.complete_sub_job(sub_job_id, success, error_message, metrics)
                    self.send_json_response({"status": "completed"})
                else:
                    self.send_error_response(400, "Missing sub_job_id")
                    
            except Exception as e:
                self.send_error_response(500, f"Error completing job: {e}")
                
        elif path == '/api/jobs/delete':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                job_id = data.get('job_id')
                if job_id:
                    success = redis_manager.delete_job(job_id)
                    if success:
                        self.send_json_response({"status": "deleted", "job_id": job_id})
                    else:
                        self.send_error_response(404, f"Job {job_id} not found")
                else:
                    self.send_error_response(400, "Missing job_id")
                    
            except Exception as e:
                self.send_error_response(500, f"Error deleting job: {e}")
        
        elif path == '/api/jobs/stop':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                job_id = data.get('job_id')
                if job_id:
                    success = redis_manager.cancel_job(job_id)
                    if success:
                        self.send_json_response({"status": "stopped", "job_id": job_id})
                    else:
                        self.send_error_response(404, f"Job {job_id} not found or already completed")
                else:
                    self.send_error_response(400, "Missing job_id")
                    
            except Exception as e:
                self.send_error_response(500, f"Error stopping job: {e}")
                
        elif path == '/api/jobs/resume':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                job_id = data.get('job_id')
                if job_id:
                    success = redis_manager.resume_job(job_id)
                    if success:
                        self.send_json_response({"status": "resumed", "job_id": job_id})
                    else:
                        self.send_error_response(400, f"Job {job_id} cannot be resumed or not found")
                else:
                    self.send_error_response(400, "Missing job_id")
            except Exception as e:
                self.send_error_response(500, f"Error resuming job: {e}")
                
        elif path.startswith('/api/workers/') and path.endswith('/stop'):
            # Worker stop endpoint: /api/workers/{worker_id}/stop
            try:
                worker_id = path.split('/')[-2]  # Extract worker_id from path
                success = redis_manager.stop_worker(worker_id)
                if success:
                    self.send_json_response({"status": "stopped", "worker_id": worker_id})
                else:
                    self.send_error_response(404, f"Worker {worker_id} not found")
            except Exception as e:
                self.send_error_response(500, f"Error stopping worker: {e}")
                
        elif path.startswith('/api/workers/') and path.endswith('/resume'):
            # Worker resume endpoint: /api/workers/{worker_id}/resume
            try:
                worker_id = path.split('/')[-2]  # Extract worker_id from path
                success = redis_manager.resume_worker(worker_id)
                if success:
                    self.send_json_response({"status": "resumed", "worker_id": worker_id})
                else:
                    self.send_error_response(404, f"Worker {worker_id} not found")
            except Exception as e:
                self.send_error_response(500, f"Error resuming worker: {e}")
        
        elif path.startswith('/api/jobs/batch/') and path.endswith('/retry'):
            # Retry batch endpoint: /api/jobs/batch/{batch_id}/retry
            try:
                batch_id = path.split('/')[-2]  # Extract batch_id from path
                success = redis_manager.retry_batch(batch_id)
                if success:
                    self.send_json_response({"status": "retry_queued", "batch_id": batch_id})
                else:
                    self.send_error_response(404, f"Batch {batch_id} not found or cannot be retried")
            except Exception as e:
                self.send_error_response(500, f"Error retrying batch: {e}")
                
        elif path == '/api/admin/cleanup-stuck-batches':
            # Manual cleanup of stuck batches from offline workers
            try:
                cleanup_count = redis_manager.cleanup_all_stuck_batches()
                self.send_json_response({
                    "status": "cleanup_completed", 
                    "batches_reset": cleanup_count,
                    "message": f"Reset {cleanup_count} stuck batches from offline workers"
                })
            except Exception as e:
                self.send_error_response(500, f"Error cleaning up stuck batches: {e}")
        
        elif path == '/api/debug/worker-delete-result':
            # Debug endpoint to log worker delete results from UI
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                print(f"\n=== WORKER DELETE OPERATION RESULT ===")
                print(f"Attempted: {data.get('attempted', 0)} workers")
                print(f"Successful: {data.get('successful', 0)} workers")
                print(f"Failed: {data.get('failed', 0)} workers")
                
                if data.get('workers'):
                    print(f"Workers processed:")
                    for worker in data['workers']:
                        print(f"  - ID: {worker.get('id', 'unknown')}, Hostname: {worker.get('hostname', 'unknown')}, Status: {worker.get('status', 'unknown')}")
                
                if data.get('errors'):
                    print(f"Errors encountered:")
                    for error in data['errors']:
                        print(f"  - {error.get('worker', 'unknown')}: {error.get('error', 'unknown error')}")
                
                print(f"==========================================\n")
                
                self.send_json_response({"status": "logged"})
            except Exception as e:
                print(f"Error logging worker delete results: {e}")
                self.send_error_response(500, f"Error logging results: {e}")
        
        elif path == '/api/debug/redis-workers':
            # Debug endpoint to see what's actually in Redis
            try:
                all_workers_raw = redis_manager.redis_client.hgetall('render:workers')
                print(f"\n=== RAW REDIS WORKERS DATA ===")
                for worker_id, worker_data in all_workers_raw.items():
                    if isinstance(worker_id, bytes):
                        worker_id = worker_id.decode('utf-8')
                    print(f"Redis Key: '{worker_id}'")
                    try:
                        data = json.loads(worker_data)
                        print(f"  Hostname: {data.get('hostname', 'unknown')}")
                        print(f"  IP: {data.get('ip_address', 'unknown')}")
                        print(f"  Status: {data.get('status', 'unknown')}")
                    except:
                        print(f"  Raw data: {worker_data}")
                    print("")
                print(f"================================\n")
                
                self.send_json_response({"workers": list(all_workers_raw.keys())})
            except Exception as e:
                print(f"Error getting Redis workers: {e}")
                self.send_error_response(500, f"Error getting Redis data: {e}")
        
        elif path == '/api/debug/worker-jobs':
            # Debug endpoint to see worker job assignments
            try:
                worker_jobs_data = {}
                all_workers_raw = redis_manager.redis_client.hgetall('render:workers')
                
                print(f"\n=== WORKER JOB ASSIGNMENTS DEBUG ===")
                for worker_id, worker_data in all_workers_raw.items():
                    if isinstance(worker_id, bytes):
                        worker_id = worker_id.decode('utf-8')
                    
                    # Get worker's current job assignments
                    active_jobs = redis_manager.redis_client.smembers(f"render:worker:{worker_id}:jobs")
                    active_job_list = [job.decode('utf-8') if isinstance(job, bytes) else job for job in active_jobs]
                    
                    print(f"Worker '{worker_id}':")
                    print(f"  Active jobs count: {len(active_job_list)}")
                    
                    for job_id in active_job_list:
                        # Check if this job actually exists and its status
                        sub_job_data = redis_manager.redis_client.hget(f"render:subjobs:{job_id}", "data")
                        if sub_job_data:
                            sub_job = json.loads(sub_job_data)
                            status = sub_job.get('status', 'unknown')
                            print(f"    - Job {job_id[:8]}: {status}")
                        else:
                            print(f"    - Job {job_id[:8]}: MISSING DATA (stale reference)")
                    
                    worker_jobs_data[worker_id] = {
                        'active_count': len(active_job_list),
                        'job_ids': active_job_list
                    }
                
                print(f"=============================================\n")
                
                self.send_json_response({"worker_jobs": worker_jobs_data})
            except Exception as e:
                print(f"Error getting worker job data: {e}")
                self.send_error_response(500, f"Error getting worker job data: {e}")
        
        else:
            self.send_error_response(404, "Endpoint not found")
    
    def do_DELETE(self):
        """Handle DELETE requests"""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        print(f"Redis API: DELETE {path} from {self.client_address[0]}")
        
        if path.startswith('/api/workers/'):
            # Worker delete endpoint: /api/workers/{worker_id}
            try:
                worker_id = path.split('/')[-1]  # Extract worker_id from path
                if not worker_id:
                    self.send_error_response(400, "Missing worker_id")
                    return
                    
                success = redis_manager.delete_worker(worker_id)
                if success:
                    self.send_json_response({"status": "deleted", "worker_id": worker_id})
                else:
                    self.send_error_response(404, f"Worker {worker_id} not found or could not be deleted")
            except Exception as e:
                self.send_error_response(500, f"Error deleting worker: {e}")
        else:
            self.send_error_response(404, "DELETE endpoint not found")
    
    def send_json_response(self, data, status_code=200):
        """Send JSON response with connection validation"""
        try:
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            if data is not None:
                response_json = json.dumps(data, indent=2)
                self.wfile.write(response_json.encode('utf-8'))
        except (ConnectionAbortedError, BrokenPipeError, OSError) as e:
            print(f"Client disconnected during response: {e}")
        except Exception as e:
            print(f"Error sending response: {e}")
    
    def send_error_response(self, status_code, message):
        """Send error response"""
        error_data = {'error': message, 'status_code': status_code}
        self.send_json_response(error_data, status_code)
    
    def finish(self):
        """Override finish to ensure proper connection cleanup"""
        try:
            super().finish()
        except Exception as e:
            print(f"[ERROR] Error during connection cleanup: {e}")
            # Force close connection if cleanup fails
            try:
                if hasattr(self, 'connection'):
                    self.connection.close()
            except:
                pass
    
    def browse_files(self, current_path=""):
        """Browse files and directories for file selection"""
        import os
        import stat
        from datetime import datetime
        
        # If no path provided, start with common network roots or local drives
        if not current_path:
            # Return available drives and common network paths
            drives = []
            
            # Add local drives
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    try:
                        # Test if drive is accessible
                        os.listdir(drive)
                        drives.append({
                            'name': f"Local Drive ({letter}:)",
                            'path': drive,
                            'type': 'drive',
                            'size': None,
                            'modified': None
                        })
                    except:
                        pass  # Skip inaccessible drives
            
            # Add common network paths if they exist
            network_paths = [
                "\\\\localhost",
                "\\\\127.0.0.1", 
                "\\\\10.0.0.10",  # From your logs
                "\\\\server",
                "\\\\storage"
            ]
            
            for net_path in network_paths:
                try:
                    if os.path.exists(net_path):
                        drives.append({
                            'name': f"Network ({net_path})",
                            'path': net_path,
                            'type': 'network',
                            'size': None,
                            'modified': None
                        })
                except:
                    pass  # Skip inaccessible network paths
            
            return {
                'current_path': '',
                'parent_path': None,
                'items': drives
            }
        
        # Browse specific directory
        try:
            if not os.path.exists(current_path):
                raise Exception(f"Path does not exist: {current_path}")
            
            if not os.path.isdir(current_path):
                raise Exception(f"Path is not a directory: {current_path}")
            
            items = []
            
            # Get parent directory
            parent_path = os.path.dirname(current_path.rstrip('\\/'))
            if parent_path == current_path:  # Root level
                parent_path = None
            
            try:
                entries = os.listdir(current_path)
                entries.sort(key=str.lower)  # Case-insensitive sort
                
                for entry in entries:
                    entry_path = os.path.join(current_path, entry)
                    
                    try:
                        stat_info = os.stat(entry_path)
                        is_dir = os.path.isdir(entry_path)
                        
                        # Filter for relevant files/directories
                        if is_dir:
                            item_type = 'folder'
                            size = None
                        else:
                            # Only show relevant file types
                            _, ext = os.path.splitext(entry.lower())
                            if ext in ['.nk', '.sfx', '.comp', '.nuke', '.aep', '.prproj']:
                                item_type = 'file'
                                size = stat_info.st_size
                            else:
                                continue  # Skip irrelevant files
                        
                        modified = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M')
                        
                        items.append({
                            'name': entry,
                            'path': entry_path,
                            'type': item_type,
                            'size': size,
                            'modified': modified
                        })
                        
                    except (OSError, PermissionError):
                        continue  # Skip files we can't access
                        
            except (OSError, PermissionError) as e:
                raise Exception(f"Cannot access directory: {e}")
            
            return {
                'current_path': current_path,
                'parent_path': parent_path,
                'items': items
            }
            
        except Exception as e:
            raise Exception(f"File browser error: {str(e)}")
    
    def log_message(self, format, *args):
        """Override to reduce logging noise"""
        return

class RedisWorkerServer:
    """Redis-enhanced server"""
    
    def __init__(self, config_file="server_config.json"):
        self.load_config(config_file)
        self.httpd = None
        
        # Create web directory if it doesn't exist
        if getattr(sys, 'frozen', False):  # Running as PyInstaller executable
            # When running as executable, look for web directory next to the .exe
            exe_dir = Path(sys.executable).parent
            self.web_dir = exe_dir / 'web'
        else:
            # When running as script, use the normal path
            self.web_dir = Path(__file__).parent / 'web'
        
        self.web_dir.mkdir(exist_ok=True)
        
        print("Redis worker server initialized with high-performance backend")
        print(f"Web files directory: {self.web_dir}")
    
    def load_config(self, config_file):
        """Load server configuration - CONFIG FILE REQUIRED"""
        print(f"Loading server config from: {config_file}")
        
        if not os.path.exists(config_file):
            print(f"ERROR: Required config file not found: {config_file}")
            print("Server cannot start without proper configuration")
            raise FileNotFoundError(f"Required config file missing: {config_file}")
        
        try:
            with open(config_file, 'r') as f:
                user_config = json.load(f)
            
            # Handle nested server config structure
            if 'server' in user_config:
                server_config = user_config['server']
                self.config = server_config
                if 'redis' in user_config:
                    self.config['redis'] = user_config['redis']
            else:
                self.config = user_config
            
            # Validate required fields
            required_fields = ['port', 'host']
            for field in required_fields:
                if field not in self.config:
                    raise ValueError(f"Missing required field '{field}' in config")
            
            print(f"+ Config loaded successfully from {config_file}")
            print(f"+ Server will run on {self.config['host']}:{self.config['port']}")
            
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in config file: {e}")
            raise
        except Exception as e:
            print(f"ERROR: Failed to load config: {e}")
            raise
    
    def start_cleanup_thread(self):
        """Start background cleanup thread"""
        def cleanup_worker():
            """Background worker that runs periodic cleanup"""
            # Get cleanup interval from config (default: 5 minutes)
            jobs_config = self.config.get('jobs', {})
            cleanup_interval_minutes = jobs_config.get('cleanup_interval_minutes', 5)
            cleanup_interval = cleanup_interval_minutes * 60  # Convert to seconds
            max_pending_warning = jobs_config.get('max_pending_batches_warning', 10000)
            last_cleanup = 0

            while not self._stop_cleanup:
                try:
                    current_time = time.time()

                    # Run cleanup at configured interval
                    if current_time - last_cleanup >= cleanup_interval:
                        print(f"[CLEANUP] Starting periodic cleanup (interval: {cleanup_interval_minutes} minutes)...")

                        # 1. Clean up stuck batches from offline workers
                        stuck_count = redis_manager.cleanup_all_stuck_batches()
                        if stuck_count > 0:
                            print(f"[CLEANUP] Reset {stuck_count} stuck batches from offline workers")

                        # 2. Clean up old completed jobs (if enabled in config)
                        if jobs_config.get('auto_cleanup_completed', True):
                            cleanup_days = jobs_config.get('cleanup_after_days', 7)
                            deleted_count = redis_manager.cleanup_old_data(days_old=cleanup_days)
                            if deleted_count > 0:
                                print(f"[CLEANUP] Deleted {deleted_count} jobs older than {cleanup_days} days")

                        # 3. Get Redis memory stats and health check
                        stats = redis_manager.get_stats()
                        redis_memory = stats.get('redis_memory', 'Unknown')
                        pending_batches = stats.get('pending_batches', 0)
                        total_jobs = stats.get('total_jobs', 0)
                        online_workers = stats.get('online_workers', 0)

                        connection_pool = stats.get('connection_pool', {})
                        in_use_connections = connection_pool.get('in_use_connections', 'Unknown')
                        max_connections = connection_pool.get('max_connections', 'Unknown')

                        print(f"[CLEANUP] Redis memory: {redis_memory}, Jobs: {total_jobs}, Pending batches: {pending_batches}")
                        print(f"[CLEANUP] Workers: {online_workers}, Connections: {in_use_connections}/{max_connections}")

                        # Warn if too many pending batches
                        if pending_batches > max_pending_warning:
                            print(f"[WARNING] High number of pending batches: {pending_batches} (threshold: {max_pending_warning})")
                            print(f"[WARNING] Consider increasing workers or checking for stuck jobs")

                        last_cleanup = current_time
                        print("[CLEANUP] Periodic cleanup completed\n")

                    # Sleep for 30 seconds before checking again
                    time.sleep(30)

                except Exception as e:
                    print(f"[ERROR] Cleanup thread error: {e}")
                    time.sleep(60)  # Wait longer on error

        # Start cleanup thread
        self._stop_cleanup = False
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()

        jobs_config = self.config.get('jobs', {})
        cleanup_interval_minutes = jobs_config.get('cleanup_interval_minutes', 5)
        print(f"[OK] Background cleanup thread started (runs every {cleanup_interval_minutes} minutes)")

    def start(self):
        """Start the Redis server"""
        host = self.config['host']
        port = self.config['port']
        server_address = (host, port)

        # Record startup time for uptime tracking
        self._start_time = time.time()

        # Start background cleanup thread
        self.start_cleanup_thread()

        try:
            # Create threaded server for better connection handling
            self.httpd = ThreadedHTTPServer(server_address, EnhancedAPIHandler)
            
            # Set socket timeout to prevent hanging connections (increased for stability)
            self.httpd.timeout = 60  # Increased from 30 for 20+ workers
            
            print("=" * 60)
            print("[SERVER] REDIS ENHANCED RENDER FARM SERVER")
            print("=" * 60)
            print(f"Server running on http://{host}:{port}")
            if host == "0.0.0.0":
                print(f"Web Interface: http://localhost:{port}")
                print(f"Remote Access: http://{self.get_local_ip()}:{port}")
            print()
            print("[REDIS] High-performance backend enabled")
            print("[WEB] Complete web interface available")
            print("[API] Worker APIs available at /api/*")
            print(f"[FILES] Static files served from: {self.web_dir}")
            print()
            print("Features:")
            print("  + Redis atomic operations")
            print("  + 30+ worker support")
            print("  + Sub-second job assignment")
            print("  + Persistent job queue")
            print("  + Real-time monitoring")
            print()
            print("Press Ctrl+C to stop the server")
            print("=" * 60)
            
            # Set up signal handlers for graceful shutdown
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)
            
            self.httpd.serve_forever()
            
        except OSError as e:
            if e.errno == 48:  # Address already in use
                print(f"ERROR: Port {port} is already in use")
                print(f"Please check if another server is running or change port in server_config.json")
            else:
                print(f"ERROR: Server error: {e}")
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self):
        """Stop the server"""
        print("\n[STOP] Shutting down Redis server...")

        # Stop cleanup thread
        if hasattr(self, '_stop_cleanup'):
            self._stop_cleanup = True
            print("[STOP] Stopping cleanup thread...")

        # Close Redis connection pool for clean shutdown
        try:
            redis_manager.close_connection_pool()
        except Exception as e:
            print(f"[WARNING] Error closing Redis connection pool: {e}")

        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        print("Redis server stopped")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.stop()
        sys.exit(0)
    
    def get_local_ip(self):
        """Get local IP address"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "localhost"

def main():
    """Start the Redis server with auto-install"""
    import argparse
    
    # Auto-install service when running as executable
    if getattr(sys, 'frozen', False):  # Running as PyInstaller executable
        print("Installing Render Farm Server Service...")
        try:
            import subprocess
            import os
            
            # Get the directory where the executable is located
            exe_dir = os.path.dirname(sys.executable)
            install_script = os.path.join(exe_dir, 'server_install.bat')
            
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
    
    parser = argparse.ArgumentParser(description='Redis Enhanced Render Farm Server')
    parser.add_argument('--config', default='server_config.json',
                       help='Configuration file path')
    
    args = parser.parse_args()
    
    # When running as executable, look for config in executable directory
    config_path = args.config
    if getattr(sys, 'frozen', False) and not os.path.isabs(config_path):
        exe_dir = os.path.dirname(sys.executable)
        config_path = os.path.join(exe_dir, config_path)
    
    server = RedisWorkerServer(config_path)
    
    try:
        server.start()
    except Exception as e:
        print(f"ERROR: Failed to start server: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()