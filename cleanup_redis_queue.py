#!/usr/bin/env python3
"""
Emergency Redis Queue Cleanup Script
Clears all pending batches from the Redis queue
"""

import redis
import json

def cleanup_queue():
    """Clear the massive pending batch queue"""
    try:
        # Connect to Redis
        redis_client = redis.Redis(
            host='localhost',
            port=6379,
            db=0,
            decode_responses=True
        )

        # Test connection
        redis_client.ping()
        print("[OK] Connected to Redis")

        # Get queue size before cleanup
        pending_count = redis_client.zcard('render:jobs:pending')
        print(f"\n[INFO] Found {pending_count:,} pending batches in queue")

        if pending_count == 0:
            print("[INFO] Queue is already empty!")
            return

        # Confirm before deleting
        print(f"\n[WARNING] This will delete ALL {pending_count:,} pending batches!")
        confirm = input("Type 'YES' to confirm: ")

        if confirm != 'YES':
            print("[CANCELLED] Cleanup cancelled by user")
            return

        # Delete the pending queue
        print("\n[CLEANUP] Deleting pending batch queue...")
        redis_client.delete('render:jobs:pending')

        # Verify it's empty
        new_count = redis_client.zcard('render:jobs:pending')
        print(f"[OK] Queue cleared! Remaining batches: {new_count}")

        # Get all jobs
        print("\n[INFO] Checking job data...")
        all_jobs = redis_client.hgetall('render:jobs:data')
        print(f"[INFO] Found {len(all_jobs)} jobs in system")

        if len(all_jobs) > 0:
            print("\n[JOBS] Job details:")
            for job_id, job_data_str in all_jobs.items():
                try:
                    job_data = json.loads(job_data_str)
                    title = job_data.get('title', 'Untitled')
                    status = job_data.get('status', 'unknown')
                    print(f"  - {job_id[:8]}: '{title}' ({status})")
                except:
                    pass

            print("\n[INFO] To delete all jobs, you can:")
            print("  1. Use the web UI at http://10.0.0.59:8080")
            print("  2. Or run: redis-cli DEL render:jobs:data")

        print("\n[SUCCESS] Cleanup complete!")

    except redis.ConnectionError as e:
        print(f"[ERROR] Cannot connect to Redis: {e}")
        print("[INFO] Make sure Redis is running on localhost:6379")
    except Exception as e:
        print(f"[ERROR] Cleanup failed: {e}")

if __name__ == '__main__':
    print("=" * 60)
    print("REDIS QUEUE CLEANUP SCRIPT")
    print("=" * 60)
    cleanup_queue()
