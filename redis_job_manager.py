#!/usr/bin/env python3
"""
Redis-based Job Manager - High Performance & Scalable
Handles 100+ workers with sub-second response times
"""

import redis
import json
import uuid
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

class RedisJobManager:
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0):
        """Initialize Redis connection"""
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        
        # Define Redis keys first (before connection attempt)
        self.PENDING_JOBS = 'render:jobs:pending'
        self.JOBS_DATA = 'render:jobs:data'
        self.WORKERS = 'render:workers'
        self.WORKER_HEARTBEAT = 'render:workers:heartbeat'
        self.JOB_UPDATES = 'render:updates'
        
        # Initialize Redis connection with retry logic
        self._connect_with_retry()
        
        print("[OK] Redis Job Manager initialized")
        
    def _connect_with_retry(self, max_retries=3):
        """Connect to Redis with connection pooling for better performance"""
        for attempt in range(max_retries):
            try:
                # Create connection pool for multiple concurrent connections
                self.connection_pool = redis.ConnectionPool(
                    host=self.redis_host,
                    port=self.redis_port,
                    db=self.redis_db,
                    max_connections=200,  # Pool of 200 connections for 20+ workers
                    socket_connect_timeout=10,
                    socket_timeout=10,
                    retry_on_timeout=True,
                    decode_responses=True,
                    health_check_interval=30  # Check connection health every 30s
                )
                
                # Create Redis client using the connection pool
                self.redis_client = redis.Redis(connection_pool=self.connection_pool)
                
                # Test connection
                self.redis_client.ping()
                print(f"[OK] Redis connection established (attempt {attempt + 1})")
                return
                
            except redis.ConnectionError as e:
                print(f"[WARNING] Redis connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print(f"[INFO] Retrying in 2 seconds...")
                    time.sleep(2)
                else:
                    print("[ERROR] Redis connection failed after all retries - ensure Redis is running")
                    raise
        
    def ensure_connection(self):
        """Ensure Redis connection is active, reconnect if needed"""
        try:
            self.redis_client.ping()
            return True
        except (redis.ConnectionError, redis.TimeoutError):
            print("[WARNING] Redis connection lost, attempting to reconnect...")
            try:
                self._connect_with_retry(max_retries=2)
                return True
            except Exception as e:
                print(f"[ERROR] Failed to reconnect to Redis: {e}")
                return False
    
    def submit_job(self, job_data: Dict[str, Any]) -> str:
        """Submit job - atomic operation"""
        # Ensure Redis connection is active
        if not self.ensure_connection():
            raise redis.ConnectionError("Cannot connect to Redis")
            
        job_id = str(uuid.uuid4())
        
        # Create job record
        job_record = {
            'id': job_id,
            'title': job_data.get('title', job_data.get('job_title', 'Untitled')),
            'renderer': job_data.get('renderer', 'unknown'),
            'status': 'pending',
            'progress': 0.0,
            'priority': job_data.get('priority', 'normal'),
            'job_data': job_data,
            'created_at': datetime.now().isoformat(),
            'frame_range': job_data.get('frame_range', '1-1'),
            'batch_size': job_data.get('batch_size', 1)
        }
        
        # Create frame batches
        batches = self._create_frame_batches(
            job_data.get('frame_range', '1-1'),
            job_data.get('batch_size', 1)
        )
        
        # Store in Redis pipeline for atomicity
        pipe = self.redis_client.pipeline()
        
        # Store job data
        pipe.hset(self.JOBS_DATA, job_id, json.dumps(job_record))
        
        # Create sub-jobs
        job_timestamp = int(time.time() * 1000)  # Millisecond precision for job submission time
        
        for i, batch_frames in enumerate(batches, 1):
            sub_job_id = str(uuid.uuid4())
            sub_job = {
                'sub_job_id': sub_job_id,
                'parent_job_id': job_id,
                'batch_number': str(i),
                'frame_range': batch_frames,
                'job_data': json.dumps(job_data),
                'priority': job_data.get('priority', 'normal'),
                'created_at': datetime.now().isoformat()
            }
            
            # Add to pending queue (priority queue) with batch sequence
            base_priority = {'critical': 1, 'high': 2, 'normal': 3, 'low': 4}.get(
                job_data.get('priority', 'normal'), 3
            )
            # Combine priority with timestamp and batch sequence to maintain order
            # Format: priority * 1e12 + timestamp * 1000 + batch_index
            # This ensures: 1) priority is respected, 2) FIFO within priority, 3) batch order within job
            priority_score = base_priority * 1e12 + job_timestamp * 1000 + (i - 1)
            pipe.zadd(self.PENDING_JOBS, {sub_job_id: priority_score})
            pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job))
        
        pipe.execute()
        
        # Publish job creation
        self._publish_update('job_created', {'job_id': job_id, 'batches': len(batches)})
        
        # INSTANT NOTIFICATION: Notify all workers that jobs are available
        self._notify_workers_job_available(len(batches))
        
        # Log with large job detection
        if len(batches) > 100:
            print(f"[LARGE_JOB] Job {job_id[:8]} submitted with {len(batches)} batches - Large job mode active")
        else:
            print(f"[OK] Job {job_id[:8]} submitted with {len(batches)} batches")
        
        # Enforce job limit AFTER successful job creation for better performance
        self._enforce_job_limit(10)
        
        return job_id
    
    def get_next_job(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """Get next job - atomic with timeout"""
        # Clean worker's stale jobs before checking capacity
        self._cleanup_worker_stale_jobs(worker_id)
        
        # Check worker is accepting jobs
        if not self._is_worker_accepting_jobs(worker_id):
            return None
        
        # Atomic pop from priority queue - compatible with older Redis versions
        try:
            result = self.redis_client.bzpopmin(self.PENDING_JOBS, timeout=0.5)  # Faster timeout
            if not result:
                return None
            _, sub_job_id, _ = result
        except redis.exceptions.ResponseError as e:
            if "unknown command" in str(e).lower():
                # Fallback for older Redis versions that don't support BZPOPMIN
                pipe = self.redis_client.pipeline()
                pipe.zrange(self.PENDING_JOBS, 0, 0, withscores=True)
                result = pipe.execute()[0]
                if not result:
                    return None
                sub_job_id, score = result[0]
                # Remove the job atomically
                removed = self.redis_client.zrem(self.PENDING_JOBS, sub_job_id)
                if not removed:
                    return None  # Job was taken by another worker
            else:
                raise
        
        # Get sub-job data
        sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
        if not sub_job_json:
            return None
        sub_job_data = json.loads(sub_job_json)
        
        # CHECK: If parent job is cancelled, don't assign this batch
        parent_job_id = sub_job_data['parent_job_id']
        parent_job_data = self.redis_client.hget(self.JOBS_DATA, parent_job_id)
        if parent_job_data:
            parent_job = json.loads(parent_job_data)
            if parent_job.get('status') == 'cancelled':
                print(f"[CANCEL] Skipping assignment of batch {sub_job_id[:8]} - parent job {parent_job_id[:8]} is cancelled")
                # Put the sub-job back as cancelled instead of assigning it
                sub_job_data['status'] = 'cancelled'
                self.redis_client.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
                return None  # Don't assign this batch
        
        # Mark as running atomically
        pipe = self.redis_client.pipeline()
        # Update the sub-job with new status
        sub_job_data['status'] = 'running'
        sub_job_data['worker_id'] = worker_id
        sub_job_data['started_at'] = datetime.now().isoformat()
        pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
        pipe.sadd(f"render:worker:{worker_id}:jobs", sub_job_id)
        pipe.execute()
        
        print(f"[CONCURRENCY] Worker {worker_id} assigned batch {sub_job_id[:8]} from job {parent_job_id[:8]}")
        
        # Update parent job status
        parent_job_id = sub_job_data['parent_job_id']
        self._update_job_status(parent_job_id, 'running')
        
        # Publish update
        self._publish_update('job_assigned', {
            'sub_job_id': sub_job_id,
            'worker_id': worker_id,
            'parent_job_id': parent_job_id
        })
        
        return {
            'sub_job_id': sub_job_id,
            'parent_job_id': parent_job_id,
            'frame_range': sub_job_data['frame_range'],
            'job_data': json.loads(sub_job_data['job_data'])
        }
    
    def complete_sub_job(self, sub_job_id: str, success: bool = True, 
                        error_message: str = None, metrics: Dict = None):
        """Complete sub-job - atomic operation"""
        status = 'completed' if success else 'failed'
        
        # Get sub-job data to find parent FIRST (before any updates)
        sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
        if sub_job_json:
            sub_job_data = json.loads(sub_job_json)
            parent_job_id = sub_job_data.get('parent_job_id')
            worker_id = sub_job_data.get('worker_id')
        else:
            parent_job_id = None
            worker_id = None
        
        # Update sub-job atomically
        pipe = self.redis_client.pipeline()
        if sub_job_json:
            sub_job_data.update({
                'status': status,
                'completed_at': datetime.now().isoformat(),
                'error_message': error_message or '',
                'metrics': json.dumps(metrics or {})
            })
            pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
        
        # Remove from worker's active jobs
        if worker_id:
            pipe.srem(f"render:worker:{worker_id}:jobs", sub_job_id)
            print(f"[CONCURRENCY] Worker {worker_id} completed batch {sub_job_id[:8]} - freed for next batch")
        else:
            print(f"[WARNING] No worker_id found for completed sub-job {sub_job_id[:8]} - cannot free worker")
        
        # Execute all updates atomically
        pipe.execute()
        
        # Update parent job progress AFTER pipeline commits
        if parent_job_id:
            print(f"[DEBUG] Updating progress for job {parent_job_id[:8]} after sub-job {sub_job_id[:8]} completed")
            self._update_job_progress(parent_job_id)
        else:
            print(f"[DEBUG] No parent_job_id found for sub-job {sub_job_id[:8]}")
        
        # Publish update
        self._publish_update('job_completed', {
            'sub_job_id': sub_job_id,
            'parent_job_id': parent_job_id,
            'success': success,
            'worker_id': worker_id
        })
        
        print(f"+ Sub-job {sub_job_id[:8]} {'completed' if success else 'failed'}")
    
    def _find_duplicate_worker(self, hostname: str, ip_address: str, current_worker_id: str) -> str:
        """Find existing worker with same hostname+IP combination"""
        try:
            # Get all workers
            all_workers = self.redis_client.hgetall(self.WORKERS)
            
            for worker_id, worker_data_str in all_workers.items():
                if isinstance(worker_id, bytes):
                    worker_id = worker_id.decode('utf-8')
                
                # Skip current worker
                if worker_id == current_worker_id:
                    continue
                
                try:
                    worker_data = json.loads(worker_data_str)
                    existing_hostname = worker_data.get('hostname', '')
                    existing_ip = worker_data.get('ip_address', '')
                    
                    # Check if hostname and IP match
                    if existing_hostname == hostname and existing_ip == ip_address:
                        return worker_id
                        
                except (json.JSONDecodeError, KeyError):
                    continue
                    
            return None
            
        except Exception as e:
            print(f"Error checking for duplicate workers: {e}")
            return None
    
    def register_worker(self, worker_id: str, ip_address: str, 
                       hostname: str = None, capabilities: Dict = None):
        """Register worker with duplicate detection based on hostname+IP"""
        hostname = hostname or worker_id
        
        # Clear any stale job assignments on registration
        self.redis_client.delete(f"render:worker:{worker_id}:jobs")
        
        # Check for existing worker with same hostname+IP
        existing_worker = self._find_duplicate_worker(hostname, ip_address, worker_id)
        if existing_worker and existing_worker != worker_id:
            print(f"! Worker with hostname '{hostname}' and IP '{ip_address}' already exists as '{existing_worker}'")
            print(f"! Removing old worker '{existing_worker}' and registering as '{worker_id}'")
            # Remove the old worker entry completely
            self.redis_client.hdel(self.WORKERS, existing_worker)
            self.redis_client.delete(f"{self.WORKER_HEARTBEAT}:{existing_worker}")
            self.redis_client.delete(f"render:worker:{existing_worker}:jobs")
            print(f"! Cleaned up old worker '{existing_worker}'")
        
        worker_data = {
            'id': worker_id,
            'ip_address': ip_address,
            'hostname': hostname,
            'status': 'online',
            'accepting_jobs': True,
            'capabilities': json.dumps(capabilities or {}),
            'registered_at': datetime.now().isoformat()
        }
        
        # Store worker data
        self.redis_client.hset(self.WORKERS, worker_id, json.dumps(worker_data))
        
        # Set heartbeat with TTL
        self.redis_client.setex(f"{self.WORKER_HEARTBEAT}:{worker_id}", 120, 'online')
        
        self._publish_update('worker_registered', {'worker_id': worker_id})
        print(f"+ Worker {worker_id} registered")
        return worker_id
    
    def update_worker_heartbeat(self, worker_id: str) -> bool:
        """Update worker heartbeat - high frequency operation"""
        # Clean stale jobs during heartbeat
        self._cleanup_worker_stale_jobs(worker_id)
        
        # Fast heartbeat update with TTL
        result = self.redis_client.setex(f"{self.WORKER_HEARTBEAT}:{worker_id}", 120, 'online')
        return bool(result)
    
    def stop_worker(self, worker_id: str) -> bool:
        """Stop worker from accepting jobs"""
        worker_data = self.redis_client.hget(self.WORKERS, worker_id)
        if not worker_data:
            return False
        
        worker = json.loads(worker_data)
        worker['accepting_jobs'] = False
        worker['status'] = 'stopped'
        
        self.redis_client.hset(self.WORKERS, worker_id, json.dumps(worker))
        self._publish_update('worker_stopped', {'worker_id': worker_id})
        return True
    
    def resume_worker(self, worker_id: str) -> bool:
        """Resume worker to accept jobs"""
        worker_data = self.redis_client.hget(self.WORKERS, worker_id)
        if not worker_data:
            return False
        
        worker = json.loads(worker_data)
        worker['accepting_jobs'] = True
        worker['status'] = 'online'
        
        self.redis_client.hset(self.WORKERS, worker_id, json.dumps(worker))
        self._publish_update('worker_resumed', {'worker_id': worker_id})
        return True
    
    def delete_worker(self, worker_id: str) -> bool:
        """Delete worker from system - only if offline"""
        try:
            # Check if worker exists
            worker_data = self.redis_client.hget(self.WORKERS, worker_id)
            if not worker_data:
                return False
            
            worker_info = json.loads(worker_data)
            
            # Safety check - allow deletion of offline workers or stopped workers
            is_online = self.redis_client.get(f"{self.WORKER_HEARTBEAT}:{worker_id}")
            worker_status = worker_info.get('status', 'unknown')
            
            # Allow deletion if worker is offline OR explicitly stopped
            if is_online and worker_status not in ['stopped', 'offline']:
                print(f"Cannot delete active worker {worker_id} (status: {worker_status})")
                return False
                
            if is_online and worker_status == 'stopped':
                print(f"Deleting stopped worker {worker_id} (removing heartbeat)")
                # Remove heartbeat for stopped workers to clean them up properly
                self.redis_client.delete(f"{self.WORKER_HEARTBEAT}:{worker_id}")
            
            # Clean up worker data
            pipe = self.redis_client.pipeline()
            
            # Remove from workers hash
            pipe.hdel(self.WORKERS, worker_id)
            
            # Remove heartbeat
            pipe.delete(f"{self.WORKER_HEARTBEAT}:{worker_id}")
            
            # Clean up any running jobs for this worker
            self._cleanup_offline_worker_jobs(worker_id)
            
            # Execute pipeline
            pipe.execute()
            
            print(f"Deleted worker {worker_id} from system")
            return True
            
        except Exception as e:
            print(f"Error deleting worker {worker_id}: {e}")
            return False
    
    def get_all_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs with current progress"""
        jobs = []
        job_data = self.redis_client.hgetall(self.JOBS_DATA)
        
        for job_id, job_json in job_data.items():
            job = json.loads(job_json)
            
            # Calculate progress from sub-jobs
            sub_jobs = self._get_job_sub_jobs(job_id)
            if sub_jobs:
                # Count batches by status
                completed = sum(1 for sj in sub_jobs if sj.get('status') == 'completed')
                failed = sum(1 for sj in sub_jobs if sj.get('status') == 'failed')
                running = sum(1 for sj in sub_jobs if sj.get('status') == 'running')
                pending = sum(1 for sj in sub_jobs if sj.get('status') == 'pending')
                
                # Calculate progress based on completed work (success + failed)
                total_finished = completed + failed
                job['progress'] = (total_finished / len(sub_jobs)) * 100
                
                # Determine final job status based on all batches
                if total_finished == len(sub_jobs):
                    # All batches are done (completed or failed)
                    if failed == 0:
                        # All completed successfully
                        job['status'] = 'completed'
                    elif completed == 0:
                        # All failed
                        job['status'] = 'failed'
                    else:
                        # Mixed results - partial completion
                        job['status'] = 'partial'
                        job['failed_batches'] = failed
                        job['completed_batches'] = completed
                elif running > 0 or pending > 0:
                    # Still has active batches
                    job['status'] = 'running'
            
            jobs.append(job)
        
        return sorted(jobs, key=lambda x: x['created_at'], reverse=True)
    
    def get_all_workers(self) -> List[Dict[str, Any]]:
        """Get all workers with live status"""
        workers = []
        worker_data = self.redis_client.hgetall(self.WORKERS)
        
        for worker_id, worker_json in worker_data.items():
            worker = json.loads(worker_json)
            
            # Check live heartbeat
            heartbeat = self.redis_client.get(f"{self.WORKER_HEARTBEAT}:{worker_id}")
            if heartbeat:
                worker['status'] = 'online' if worker.get('accepting_jobs', True) else 'stopped'
                worker['last_heartbeat'] = datetime.now().isoformat()
            else:
                worker['status'] = 'offline'
                worker['last_heartbeat'] = 'No recent heartbeat'
                
                # CLEANUP: Reset running batches from offline workers back to pending
                self._cleanup_offline_worker_jobs(worker_id)
            
            # Get current job count
            active_jobs = self.redis_client.scard(f"render:worker:{worker_id}:jobs")
            worker['current_job_count'] = active_jobs
            worker['current_job_id'] = 'Idle' if active_jobs == 0 else f"{active_jobs} jobs"
            
            workers.append(worker)
        
        return workers
    
    def delete_job(self, job_id: str) -> bool:
        """Delete job and all sub-jobs"""
        # Get all sub-jobs
        sub_jobs = self._get_job_sub_jobs(job_id)
        
        pipe = self.redis_client.pipeline()
        
        # Remove job data
        pipe.hdel(self.JOBS_DATA, job_id)
        
        # Remove sub-jobs
        for sub_job in sub_jobs:
            sub_job_id = sub_job.get('sub_job_id')
            if sub_job_id:
                # Remove from pending queue
                pipe.zrem(self.PENDING_JOBS, sub_job_id)
                # Remove sub-job data
                pipe.delete(f"render:subjobs:{sub_job_id}")
                # Remove from worker assignments
                worker_id = sub_job.get('worker_id')
                if worker_id:
                    pipe.srem(f"render:worker:{worker_id}:jobs", sub_job_id)
        
        pipe.execute()
        
        self._publish_update('job_deleted', {'job_id': job_id})
        return True
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel running job"""
        # Update job status
        job_data = self.redis_client.hget(self.JOBS_DATA, job_id)
        if not job_data:
            return False
        
        job = json.loads(job_data)
        job['status'] = 'cancelled'
        
        self.redis_client.hset(self.JOBS_DATA, job_id, json.dumps(job))
        
        # Cancel running sub-jobs
        sub_jobs = self._get_job_sub_jobs(job_id)
        pipe = self.redis_client.pipeline()
        
        for sub_job in sub_jobs:
            sub_job_id = sub_job.get('sub_job_id')
            status = sub_job.get('status')
            
            if status in ['pending', 'running']:
                # Remove from pending queue
                pipe.zrem(self.PENDING_JOBS, sub_job_id)
                # Update status - get current data and update it
                sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
                if sub_job_json:
                    sub_job_data = json.loads(sub_job_json)
                    sub_job_data['status'] = 'cancelled'
                    pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
        
        pipe.execute()
        
        self._publish_update('job_cancelled', {'job_id': job_id})
        return True
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a cancelled job by re-queuing pending batches"""
        # Get job data
        job_data = self.redis_client.hget(self.JOBS_DATA, job_id)
        if not job_data:
            print(f"[RESUME] Job {job_id[:8]} not found")
            return False
        
        job = json.loads(job_data)
        if job.get('status') not in ['cancelled', 'stopped', 'paused']:
            print(f"[RESUME] Job {job_id[:8]} cannot be resumed - status is '{job.get('status')}'")
            return False
        
        print(f"[RESUME] Resuming job {job_id[:8]} (was {job.get('status')})")
        
        # Update job status to pending 
        job['status'] = 'pending'
        self.redis_client.hset(self.JOBS_DATA, job_id, json.dumps(job))
        
        # Get all sub-jobs for this job
        sub_jobs = self._get_job_sub_jobs(job_id)
        pipe = self.redis_client.pipeline()
        requeued_count = 0
        
        completed_count = 0
        for sub_job in sub_jobs:
            sub_job_id = sub_job.get('sub_job_id')
            status = sub_job.get('status')
            
            if status == 'completed':
                # Keep completed batches as completed
                completed_count += 1
                print(f"[RESUME] Keeping batch {sub_job_id[:8]} as completed")
            elif status in ['cancelled', 'pending', 'failed']:
                # Only re-queue non-completed batches with proper ordering
                batch_number = int(sub_job.get('batch_number', '1'))
                
                # Get original priority from sub-job data
                sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
                if sub_job_json:
                    sub_job_data = json.loads(sub_job_json)
                    job_data_str = sub_job_data.get('job_data', '{}')
                    try:
                        original_job_data = json.loads(job_data_str)
                        priority = original_job_data.get('priority', 'normal')
                    except:
                        priority = 'normal'
                else:
                    priority = 'normal'
                
                # Use same scoring system as submit_job to maintain batch order
                base_priority = {'critical': 1, 'high': 2, 'normal': 3, 'low': 4}.get(priority, 3)
                resume_timestamp = int(time.time() * 1000)
                priority_score = base_priority * 1e12 + resume_timestamp * 1000 + (batch_number - 1)
                pipe.zadd(self.PENDING_JOBS, {sub_job_id: priority_score})
                
                # Update sub-job status back to pending
                sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
                if sub_job_json:
                    sub_job_data = json.loads(sub_job_json)
                    sub_job_data['status'] = 'pending'
                    sub_job_data['worker_id'] = None  # Clear worker assignment from cancelled/failed batches
                    sub_job_data['started_at'] = None  # Clear start time
                    pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
                    requeued_count += 1
                    print(f"[RESUME] Re-queuing batch {sub_job_id[:8]} (was {status})")
            elif status == 'running':
                # Handle currently running batches - leave them as is
                print(f"[RESUME] Leaving batch {sub_job_id[:8]} running on worker")
            else:
                print(f"[RESUME] Unknown status '{status}' for batch {sub_job_id[:8]}")
                
        
        pipe.execute()
        
        print(f"[RESUME] Job {job_id[:8]} resumed: {completed_count} already completed, {requeued_count} re-queued")
        self._publish_update('job_resumed', {
            'job_id': job_id, 
            'batches_requeued': requeued_count,
            'batches_completed': completed_count
        })
        return True
    
    def get_job_worker_details(self, job_id: str) -> Dict[str, Any]:
        """Get detailed worker assignment for job"""
        job_data = self.redis_client.hget(self.JOBS_DATA, job_id)
        if not job_data:
            return {'error': 'Job not found'}
        
        job = json.loads(job_data)
        sub_jobs = self._get_job_sub_jobs(job_id)
        
        # Group by worker
        worker_assignments = {}
        batch_details = []
        
        for sub_job in sub_jobs:
            worker_id = sub_job.get('worker_id')
            batch_details.append({
                'batch_id': sub_job['sub_job_id'][:8],  # Short ID for display
                'full_batch_id': sub_job['sub_job_id'],  # Full ID for API calls
                'batch_number': sub_job.get('batch_number', 0),
                'frame_range': sub_job.get('frame_range', ''),
                'status': sub_job.get('status', 'pending'),
                'worker_id': worker_id or 'Unassigned',
                'started_at': sub_job.get('started_at'),
                'completed_at': sub_job.get('completed_at')
            })
            
            if worker_id:
                if worker_id not in worker_assignments:
                    worker_assignments[worker_id] = {
                        'worker_id': worker_id,
                        'batches': [],
                        'frames_total': 0,
                        'frames_completed': 0,
                        'status_counts': {'pending': 0, 'running': 0, 'completed': 0, 'failed': 0}
                    }
                
                worker_info = worker_assignments[worker_id]
                worker_info['batches'].append({
                    'batch_number': sub_job.get('batch_number', 0),
                    'frame_range': sub_job.get('frame_range', ''),
                    'status': sub_job.get('status', 'pending')
                })
                
                # Calculate frame counts
                frame_range = sub_job.get('frame_range', '1')
                frame_count = self._count_frames(frame_range)
                worker_info['frames_total'] += frame_count
                
                if sub_job.get('status') == 'completed':
                    worker_info['frames_completed'] += frame_count
                
                status = sub_job.get('status', 'pending')
                worker_info['status_counts'][status] = worker_info['status_counts'].get(status, 0) + 1
        
        return {
            'job_id': job_id,
            'job_title': job['title'],
            'total_batches': len(sub_jobs),
            'workers_involved': len(worker_assignments),
            'worker_assignments': list(worker_assignments.values()),
            'batch_details': sorted(batch_details, key=lambda x: x['batch_number']),
            'overall_progress': job.get('progress', 0),
            'job_status': job['status']
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        # Count jobs
        total_jobs = self.redis_client.hlen(self.JOBS_DATA)
        pending_jobs_count = self.redis_client.zcard(self.PENDING_JOBS)
        
        # Count workers
        total_workers = self.redis_client.hlen(self.WORKERS)
        online_workers = len([
            k for k in self.redis_client.keys(f"{self.WORKER_HEARTBEAT}:*")
            if self.redis_client.get(k)
        ])
        
        # Get connection pool stats
        connection_stats = self._get_connection_pool_stats()
        
        return {
            'total_jobs': total_jobs,
            'pending_batches': pending_jobs_count,
            'online_workers': online_workers,
            'total_workers': total_workers,
            'active_jobs': 0,  # Will be calculated
            'redis_memory': self._get_redis_memory_usage(),
            'connection_pool': connection_stats
        }
    
    def cleanup_old_data(self, days_old: int = 7):
        """Clean up old completed jobs"""
        cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
        
        jobs_to_delete = []
        job_data = self.redis_client.hgetall(self.JOBS_DATA)
        
        for job_id, job_json in job_data.items():
            job = json.loads(job_json)
            if (job.get('status') in ['completed', 'failed', 'cancelled'] and 
                job.get('created_at', '') < cutoff_date):
                jobs_to_delete.append(job_id)
        
        for job_id in jobs_to_delete:
            self.delete_job(job_id)
        
        print(f"Cleaned up {len(jobs_to_delete)} old jobs")
        return len(jobs_to_delete)
    
    # Private methods
    def _create_frame_batches(self, frame_range: str, batch_size: int) -> List[str]:
        """Create frame batches from range"""
        try:
            frames = []
            for part in frame_range.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    frames.extend(range(start, end + 1))
                else:
                    frames.append(int(part))
            
            # Group into batches
            batches = []
            for i in range(0, len(frames), batch_size):
                batch = frames[i:i + batch_size]
                if len(batch) == 1:
                    batches.append(str(batch[0]))
                else:
                    batches.append(f"{batch[0]}-{batch[-1]}")
            
            return batches
        except Exception as e:
            print(f"Error parsing frame range '{frame_range}': {e}")
            return [frame_range]
    
    def _count_frames(self, frame_range: str) -> int:
        """Count frames in range"""
        if '-' in frame_range:
            try:
                start, end = map(int, frame_range.split('-'))
                return end - start + 1
            except:
                return 1
        return 1
    
    def _is_worker_accepting_jobs(self, worker_id: str) -> bool:
        """Check if worker is online and accepting jobs"""
        # Check heartbeat
        if not self.redis_client.get(f"{self.WORKER_HEARTBEAT}:{worker_id}"):
            return False
        
        # Check accepting jobs flag
        worker_data = self.redis_client.hget(self.WORKERS, worker_id)
        if worker_data:
            worker = json.loads(worker_data)
            if not worker.get('accepting_jobs', True):
                return False
        
        # CRITICAL: Check if worker already has active batches (enforce single batch per worker)
        active_jobs = self.redis_client.scard(f"render:worker:{worker_id}:jobs")
        if active_jobs > 0:
            print(f"[CONCURRENCY] Worker {worker_id} already has {active_jobs} active batches - skipping new assignment")
            return False
        
        return True
    
    def _get_job_sub_jobs(self, job_id: str) -> List[Dict]:
        """Get all sub-jobs for a job"""
        sub_jobs = []
        
        # Scan for sub-jobs (could be optimized with job->subjob mapping)
        for key in self.redis_client.scan_iter(match="render:subjobs:*"):
            sub_job_json = self.redis_client.hget(key, "data")
            if sub_job_json:
                sub_job_data = json.loads(sub_job_json)
                if sub_job_data.get('parent_job_id') == job_id:
                    sub_jobs.append(sub_job_data)
        
        return sub_jobs
    
    def _update_job_status(self, job_id: str, status: str):
        """Update job status"""
        job_data = self.redis_client.hget(self.JOBS_DATA, job_id)
        if job_data:
            job = json.loads(job_data)
            job['status'] = status
            if status == 'running' and not job.get('started_at'):
                job['started_at'] = datetime.now().isoformat()
            self.redis_client.hset(self.JOBS_DATA, job_id, json.dumps(job))
    
    def _update_job_progress(self, job_id: str):
        """Update job progress based on sub-jobs"""
        print(f"[DEBUG] _update_job_progress called for job {job_id[:8]}")
        sub_jobs = self._get_job_sub_jobs(job_id)
        print(f"[DEBUG] Found {len(sub_jobs)} sub-jobs for job {job_id[:8]}")
        if not sub_jobs:
            print(f"[DEBUG] No sub-jobs found, returning early")
            return
        
        # Count batches by status
        completed = sum(1 for sj in sub_jobs if sj.get('status') == 'completed')
        failed = sum(1 for sj in sub_jobs if sj.get('status') == 'failed')
        running = sum(1 for sj in sub_jobs if sj.get('status') == 'running')
        pending = sum(1 for sj in sub_jobs if sj.get('status') == 'pending')
        
        # Calculate progress based on completed work (success + failed)
        total_finished = completed + failed
        progress = (total_finished / len(sub_jobs)) * 100
        
        job_data = self.redis_client.hget(self.JOBS_DATA, job_id)
        if job_data:
            job = json.loads(job_data)
            old_status = job.get('status')
            old_progress = job.get('progress', 0)
            
            job['progress'] = progress
            
            # Determine final job status based on all batches
            if total_finished == len(sub_jobs):
                # All batches are done (completed or failed)
                if failed == 0:
                    # All completed successfully
                    job['status'] = 'completed'
                elif completed == 0:
                    # All failed
                    job['status'] = 'failed'
                else:
                    # Mixed results - partial completion
                    job['status'] = 'partial'
                    job['failed_batches'] = failed
                    job['completed_batches'] = completed
                
                job['completed_at'] = datetime.now().isoformat()
            elif running > 0 or pending > 0:
                # Still has active batches
                job['status'] = 'running'
            
            # Log progress update for debugging
            if old_status != job['status'] or abs(old_progress - progress) > 0.1:
                print(f"[PROGRESS] Job {job_id[:8]}: {old_status}->{job['status']}, {old_progress:.1f}%->{progress:.1f}% (C:{completed} F:{failed} R:{running} P:{pending})")
            
            self.redis_client.hset(self.JOBS_DATA, job_id, json.dumps(job))
    
    def _publish_update(self, event_type: str, data: Dict):
        """Publish real-time update"""
        message = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        self.redis_client.publish(self.JOB_UPDATES, json.dumps(message))
    
    def _notify_workers_job_available(self, batch_count: int):
        """OPTIMIZED NOTIFICATION: Smart worker notification to reduce Redis load"""
        try:
            # Only notify if there are actual subscribers to avoid wasted cycles
            if self._get_subscriber_count() == 0:
                return  # No workers listening, skip notification
            
            notification = {
                'batches_available': batch_count,
                'timestamp': datetime.now().isoformat(),
                'priority': 'high' if batch_count > 50 else 'normal',
                'notification_id': int(time.time() * 1000)  # Unique ID for deduplication
            }
            
            # Publish to optimized worker notification channel
            channel = 'render:worker:jobs_available'
            result = self.redis_client.publish(channel, json.dumps(notification))
            
            # Only log if workers were actually notified
            if result > 0:
                print(f"[INSTANT_NOTIFY] Notified {result} workers of {batch_count} available batches")
            else:
                print(f"[INSTANT_NOTIFY] {batch_count} batches available (no active workers)")
            
        except Exception as e:
            print(f"[NOTIFY_ERROR] Failed to notify workers (non-critical): {e}")
    
    def _get_subscriber_count(self):
        """Get number of active subscribers to job notification channel"""
        try:
            # Check how many clients are subscribed to the notification channel
            pubsub_info = self.redis_client.pubsub_numsub('render:worker:jobs_available')
            return pubsub_info[0][1] if pubsub_info else 0
        except Exception:
            return 1  # Assume at least one worker if we can't check
    
    def _get_redis_memory_usage(self) -> str:
        """Get Redis memory usage"""
        try:
            info = self.redis_client.info('memory')
            return f"{info['used_memory_human']}"
        except:
            return "Unknown"
    
    def _get_connection_pool_stats(self) -> Dict[str, Any]:
        """Get Redis connection pool statistics"""
        try:
            if hasattr(self, 'connection_pool'):
                pool = self.connection_pool
                return {
                    'max_connections': pool.max_connections,
                    'created_connections': pool.created_connections,
                    'available_connections': len(pool._available_connections),
                    'in_use_connections': pool.created_connections - len(pool._available_connections)
                }
            else:
                return {
                    'max_connections': 1,
                    'created_connections': 1,
                    'available_connections': 1,
                    'in_use_connections': 0
                }
        except Exception as e:
            return {
                'max_connections': 20,
                'created_connections': 'Unknown',
                'available_connections': 'Unknown', 
                'in_use_connections': 'Unknown',
                'error': str(e)
            }
    
    def get_batch_logs(self, batch_id: str) -> str:
        """Get logs for a specific batch"""
        try:
            # Get sub-job data to find worker and parent job
            sub_job_json = self.redis_client.hget(f"render:subjobs:{batch_id}", "data")
            if not sub_job_json:
                return "Batch not found"
            
            sub_job_data = json.loads(sub_job_json)
            worker_id = sub_job_data.get('worker_id', 'unknown')
            parent_job_id = sub_job_data.get('parent_job_id', 'unknown')
            error_message = sub_job_data.get('error_message', '')
            status = sub_job_data.get('status', 'unknown')
            
            # Format logs with batch information
            logs = []
            logs.append(f"=== BATCH DETAILS ===")
            logs.append(f"Batch ID: {batch_id}")
            logs.append(f"Parent Job: {parent_job_id}")
            logs.append(f"Worker: {worker_id}")
            logs.append(f"Status: {status.upper()}")
            logs.append(f"Frame Range: {sub_job_data.get('frame_range', 'N/A')}")
            
            if sub_job_data.get('started_at'):
                logs.append(f"Started: {sub_job_data['started_at']}")
            if sub_job_data.get('completed_at'):
                logs.append(f"Completed: {sub_job_data['completed_at']}")
            
            logs.append("")
            logs.append("=== BATCH LOGS ===")
            
            if error_message:
                logs.append(f"ERROR: {error_message}")
            else:
                logs.append("No specific error logged for this batch.")
            
            # Add metrics if available
            metrics_str = sub_job_data.get('metrics')
            if metrics_str:
                try:
                    metrics = json.loads(metrics_str)
                    logs.append("")
                    logs.append("=== METRICS ===")
                    for key, value in metrics.items():
                        logs.append(f"{key}: {value}")
                except:
                    pass
            
            return "\n".join(logs)
            
        except Exception as e:
            return f"Error retrieving batch logs: {str(e)}"
    
    def retry_batch(self, batch_id: str) -> bool:
        """Retry a failed batch by re-queuing it"""
        try:
            # Get sub-job data
            sub_job_json = self.redis_client.hget(f"render:subjobs:{batch_id}", "data")
            if not sub_job_json:
                return False
            
            sub_job_data = json.loads(sub_job_json)
            
            # Only retry failed batches
            if sub_job_data.get('status') != 'failed':
                return False
            
            # Reset batch to pending status
            sub_job_data.update({
                'status': 'pending',
                'worker_id': None,
                'started_at': None,
                'completed_at': None,
                'error_message': '',
                'retry_count': sub_job_data.get('retry_count', 0) + 1,
                'retried_at': datetime.now().isoformat()
            })
            
            pipe = self.redis_client.pipeline()
            
            # Update sub-job data
            pipe.hset(f"render:subjobs:{batch_id}", "data", json.dumps(sub_job_data))
            
            # Re-add to pending queue with original priority and batch ordering
            job_data_str = sub_job_data.get('job_data', '{}')
            try:
                job_data = json.loads(job_data_str)
                priority = job_data.get('priority', 'normal')
            except:
                priority = 'normal'
            
            # Use same scoring system as submit_job to maintain batch order
            batch_number = int(sub_job_data.get('batch_number', '1'))
            base_priority = {'critical': 1, 'high': 2, 'normal': 3, 'low': 4}.get(priority, 3)
            retry_timestamp = int(time.time() * 1000)
            priority_score = base_priority * 1e12 + retry_timestamp * 1000 + (batch_number - 1)
            pipe.zadd(self.PENDING_JOBS, {batch_id: priority_score})
            
            pipe.execute()
            
            # Publish update
            self._publish_update('batch_retried', {
                'batch_id': batch_id,
                'parent_job_id': sub_job_data.get('parent_job_id'),
                'retry_count': sub_job_data.get('retry_count', 1)
            })
            
            print(f"+ Batch {batch_id[:8]} queued for retry (attempt #{sub_job_data.get('retry_count', 1)})")
            return True
            
        except Exception as e:
            print(f"Error retrying batch {batch_id}: {e}")
            return False
    
    def _cleanup_worker_stale_jobs(self, worker_id: str):
        """Clean stale job assignments from worker's job list"""
        try:
            active_jobs = self.redis_client.smembers(f"render:worker:{worker_id}:jobs")
            if not active_jobs:
                return
            
            removed_count = 0
            for job_id in active_jobs:
                # Check if job actually exists and is running
                job_data = self.redis_client.hget(f"render:subjobs:{job_id}", "data")
                if not job_data:
                    # Job doesn't exist, remove from worker
                    self.redis_client.srem(f"render:worker:{worker_id}:jobs", job_id)
                    removed_count += 1
            
            if removed_count > 0:
                print(f"[CLEANUP] Removed {removed_count} stale job assignments from worker {worker_id}")
                
        except Exception as e:
            print(f"[ERROR] Failed to cleanup stale jobs for worker {worker_id}: {e}")

    def _cleanup_offline_worker_jobs(self, worker_id: str):
        """Reset running batches from offline workers back to pending queue"""
        try:
            # Get all jobs assigned to this worker
            worker_jobs = self.redis_client.smembers(f"render:worker:{worker_id}:jobs")
            if not worker_jobs:
                return
            
            pipe = self.redis_client.pipeline()
            reset_count = 0
            
            for sub_job_id in worker_jobs:
                # Get sub-job data
                sub_job_json = self.redis_client.hget(f"render:subjobs:{sub_job_id}", "data")
                if not sub_job_json:
                    continue
                
                sub_job_data = json.loads(sub_job_json)
                
                # Only reset running jobs (not completed/failed ones)
                if sub_job_data.get('status') == 'running':
                    # Reset to pending
                    sub_job_data.update({
                        'status': 'pending',
                        'worker_id': None,
                        'started_at': None,
                        'reset_at': datetime.now().isoformat(),
                        'reset_reason': f'Worker {worker_id} went offline'
                    })
                    
                    # Update sub-job data
                    pipe.hset(f"render:subjobs:{sub_job_id}", "data", json.dumps(sub_job_data))
                    
                    # Re-add to pending queue with original priority and batch ordering
                    job_data_str = sub_job_data.get('job_data', '{}')
                    try:
                        job_data = json.loads(job_data_str)
                        priority = job_data.get('priority', 'normal')
                    except:
                        priority = 'normal'
                    
                    # Use same scoring system as submit_job to maintain batch order
                    batch_number = int(sub_job_data.get('batch_number', '1'))
                    base_priority = {'critical': 1, 'high': 2, 'normal': 3, 'low': 4}.get(priority, 3)
                    cleanup_timestamp = int(time.time() * 1000)
                    priority_score = base_priority * 1e12 + cleanup_timestamp * 1000 + (batch_number - 1)
                    pipe.zadd(self.PENDING_JOBS, {sub_job_id: priority_score})
                    
                    reset_count += 1
                
                # Remove from worker's job list regardless of status
                pipe.srem(f"render:worker:{worker_id}:jobs", sub_job_id)
            
            pipe.execute()
            
            if reset_count > 0:
                print(f"+ Reset {reset_count} running batches from offline worker {worker_id} back to pending")
                
                # Notify other workers that jobs are available
                self._notify_workers_job_available(reset_count)
                
        except Exception as e:
            print(f"Error cleaning up offline worker {worker_id} jobs: {e}")
    
    def _enforce_job_limit(self, max_jobs: int = 10):
        """Enforce maximum job limit by deleting oldest jobs when exceeded"""
        try:
            # Get current job count
            current_job_count = self.redis_client.hlen(self.JOBS_DATA)
            
            if current_job_count >= max_jobs:
                # Get all jobs sorted by creation time (oldest first)
                job_data = self.redis_client.hgetall(self.JOBS_DATA)
                jobs_with_dates = []
                
                for job_id, job_json in job_data.items():
                    job = json.loads(job_json)
                    created_at = job.get('created_at', '')
                    jobs_with_dates.append((created_at, job_id, job))
                
                # Sort by creation time (oldest first)
                jobs_with_dates.sort(key=lambda x: x[0])
                
                # Calculate how many jobs to delete
                jobs_to_delete = current_job_count - max_jobs + 1
                
                # Delete oldest jobs
                for i in range(jobs_to_delete):
                    if i < len(jobs_with_dates):
                        _, job_id_to_delete, job_info = jobs_with_dates[i]
                        job_title = job_info.get('title', 'Untitled')
                        
                        print(f"[LIMIT] Deleting oldest job {job_id_to_delete[:8]} ('{job_title}') - job limit of {max_jobs} reached")
                        self.delete_job(job_id_to_delete)
                        
        except Exception as e:
            print(f"[ERROR] Failed to enforce job limit: {e}")
    
    def cleanup_all_stuck_batches(self):
        """Manual cleanup of all running batches from offline workers"""
        try:
            cleanup_count = 0
            all_workers = self.redis_client.hgetall(self.WORKERS)
            
            for worker_id in all_workers.keys():
                # Check if worker is offline
                heartbeat = self.redis_client.get(f"{self.WORKER_HEARTBEAT}:{worker_id}")
                if not heartbeat:
                    # Worker is offline, cleanup their jobs
                    worker_jobs = self.redis_client.smembers(f"render:worker:{worker_id}:jobs")
                    if worker_jobs:
                        print(f"Cleaning up {len(worker_jobs)} jobs from offline worker {worker_id}")
                        self._cleanup_offline_worker_jobs(worker_id)
                        cleanup_count += len(worker_jobs)
            
            print(f"Manual cleanup complete: processed {cleanup_count} stuck batches")
            return cleanup_count
            
        except Exception as e:
            print(f"Error in manual cleanup: {e}")
            return 0
    
    def close_connection_pool(self):
        """Properly close Redis connection pool"""
        try:
            if hasattr(self, 'connection_pool'):
                self.connection_pool.disconnect()
                print("[OK] Redis connection pool closed")
        except Exception as e:
            print(f"[WARNING] Error closing connection pool: {e}")

# Global instance
redis_manager = RedisJobManager()