# Redis Cleanup System Documentation

## Overview
The RenderFarm server now includes an **automated cleanup system** that runs in the background to prevent Redis database issues, stuck jobs, and connection problems.

## Problem Solved
**Before:** The server would experience continuous disconnections due to:
- Stuck jobs accumulating when workers crash
- Old completed jobs never being deleted
- Redis memory growing indefinitely
- Connection pool exhaustion

**After:** Automated cleanup runs every 5 minutes (configurable) to maintain system health.

## Features

### 1. Automated Stuck Batch Cleanup
- **What it does:** Resets running batches from offline workers back to pending queue
- **When it runs:** Every 5 minutes (configurable)
- **Benefit:** Workers that crash don't leave jobs stuck forever

### 2. Old Job Deletion
- **What it does:** Deletes completed/failed jobs older than N days
- **Default:** 7 days (configurable in `server_config.json`)
- **Benefit:** Prevents Redis from filling up with old job data

### 3. Redis Health Monitoring
- **Monitors:**
  - Redis memory usage
  - Total jobs and pending batches
  - Online workers count
  - Connection pool usage (in-use vs max connections)
- **Warnings:** Alerts when pending batches exceed threshold (default: 10,000)

### 4. Connection Pool Health
- **Tracks:** Active connections vs maximum pool size
- **Benefit:** Helps identify connection exhaustion issues before they cause problems

## Configuration

Edit `server_config.json` to customize cleanup behavior:

```json
{
  "jobs": {
    "auto_cleanup_completed": true,         // Enable/disable old job cleanup
    "cleanup_after_days": 7,                // Delete jobs older than this
    "cleanup_interval_minutes": 5,          // How often to run cleanup
    "max_pending_batches_warning": 10000    // Warning threshold for pending batches
  }
}
```

### Configuration Options:

| Setting | Default | Description |
|---------|---------|-------------|
| `auto_cleanup_completed` | `true` | Enable automatic deletion of old jobs |
| `cleanup_after_days` | `7` | Delete completed/failed jobs older than this many days |
| `cleanup_interval_minutes` | `5` | Run cleanup every N minutes |
| `max_pending_batches_warning` | `10000` | Warn if pending batches exceed this number |

## Server Logs

When cleanup runs, you'll see logs like this:

```
[CLEANUP] Starting periodic cleanup (interval: 5 minutes)...
[CLEANUP] Reset 3 stuck batches from offline workers
[CLEANUP] Deleted 12 jobs older than 7 days
[CLEANUP] Redis memory: 45.2M, Jobs: 28, Pending batches: 156
[CLEANUP] Workers: 8, Connections: 42/200
[CLEANUP] Periodic cleanup completed
```

### Warning Messages:

```
[WARNING] High number of pending batches: 15000 (threshold: 10000)
[WARNING] Consider increasing workers or checking for stuck jobs
```

## Manual Cleanup

### Via API (for immediate cleanup):
```bash
curl http://10.0.0.59:8080/api/admin/cleanup-stuck-batches
```

**Response:**
```json
{
  "status": "cleanup_completed",
  "batches_reset": 45,
  "message": "Reset 45 stuck batches from offline workers"
}
```

### Via Script (for emergency queue clearing):
```bash
python cleanup_redis_queue.py
```
⚠️ **Warning:** This deletes ALL pending batches! Use only in emergencies.

## How It Works

### Cleanup Thread Lifecycle:
1. Server starts → Cleanup thread launches as daemon
2. Thread sleeps for 30 seconds between checks
3. Every 5 minutes (configurable), cleanup runs:
   - Finds offline workers with running batches
   - Resets those batches to pending
   - Deletes old completed/failed jobs
   - Reports Redis health metrics
4. Server stops → Cleanup thread stops gracefully

### Stuck Batch Recovery:
```
Worker crashes → Batch stuck as "running" → Cleanup detects offline worker →
Resets batch to "pending" → Another worker picks it up
```

## Troubleshooting

### Issue: Too many pending batches warning
**Cause:** Jobs are being submitted faster than workers can process them
**Solutions:**
1. Add more workers
2. Increase batch size to reduce number of batches
3. Check if workers are actually processing jobs
4. Look for stuck workers (use web UI Workers tab)

### Issue: Redis memory growing
**Cause:** Old jobs not being cleaned up
**Solutions:**
1. Verify `"auto_cleanup_completed": true` in config
2. Reduce `cleanup_after_days` to delete jobs sooner
3. Manually delete old jobs via web UI
4. Run `cleanup_redis_queue.py` for emergency cleanup

### Issue: Connection pool exhaustion
**Cause:** Too many workers or stuck connections
**Solutions:**
1. Increase `max_connections` in redis_job_manager.py:42
2. Restart server to clear stale connections
3. Check for zombie worker processes

### Issue: Cleanup not running
**Check:**
1. Server logs should show `[OK] Background cleanup thread started`
2. Every 5 minutes, you should see `[CLEANUP] Starting periodic cleanup...`
3. If not visible, restart the server

## Best Practices

1. **Monitor cleanup logs** - Check server logs daily for warnings
2. **Adjust cleanup interval** - If you have high job volume, consider reducing to 3 minutes
3. **Set appropriate retention** - Keep jobs for as long as needed (7 days is typical)
4. **Use manual cleanup** - If system gets overwhelmed, use API endpoint immediately
5. **Regular maintenance** - Restart server weekly to clear any accumulated state

## Technical Details

### Files Modified:
- `server.py` - Added `start_cleanup_thread()` method and background worker
- `server_config.json` - Added cleanup configuration options
- `redis_job_manager.py` - Already had cleanup methods, now they're actually called!

### Thread Safety:
- Cleanup thread is daemon (won't prevent server shutdown)
- Uses existing Redis atomic operations
- No locks needed (Redis handles concurrency)

### Performance Impact:
- **Minimal** - Cleanup runs every 5 minutes, takes 1-3 seconds
- No impact on worker job assignment
- Uses existing Redis connection pool

## Monitoring Checklist

✅ **Healthy System:**
- Pending batches stay under 10,000
- Redis memory stable or slowly growing
- All workers show as "online"
- No stuck batch resets in cleanup logs
- Connection pool < 80% utilization

❌ **Unhealthy System:**
- Pending batches constantly growing
- Redis memory continuously increasing
- Workers frequently going offline
- Many stuck batches reset each cleanup
- Connection pool near max (180+ of 200)

## Support

If you continue to experience disconnection issues after enabling automatic cleanup:

1. Check Redis logs: `redis-cli monitor` (watch for errors)
2. Verify Redis memory: `redis-cli info memory`
3. Check Redis queue size: `redis-cli ZCARD render:jobs:pending`
4. Review server logs for error patterns
5. Consider upgrading Redis or increasing its memory limit

## Version
- **Added:** 2025-01-11
- **Server Version:** 3.0-redis-enhanced
- **Requires:** Redis 3.0+, Python 3.7+
