#!/usr/bin/env python3
"""
Nuke Renderer Module - SIMPLIFIED but COMPLETE
Handles Nuke rendering with essential features
"""

import os
import subprocess
import platform
import time
import logging
import tempfile
import re
from pathlib import Path

logger = logging.getLogger(__name__)

def safe_path_resolve(path):
    """Safely resolve path for network shares and local paths"""
    try:
        return str(Path(path).resolve())
    except:
        return str(Path(path))

class NukeRenderer:
    def __init__(self, config, asset_cache, monitor_process_func, detect_output_files_func, validate_frame_range_func, get_peak_memory_func, render_stats=None):
        self.config = config
        self.asset_cache = asset_cache
        self.detect_output_files = detect_output_files_func
        self.validate_nuke_frame_range = validate_frame_range_func
        self.get_peak_memory_usage = get_peak_memory_func
        self.render_stats = render_stats
        self._monitor_process_with_activity = monitor_process_func
        
    def render_nuke_optimized(self, executable, project_file, frame_range, job_data, batch_id):
        """SIMPLIFIED Nuke rendering with essential features"""
        start_time = time.time()
        
        try:
            # Use UNC-safe path handling
            abs_executable = os.path.abspath(executable)
            abs_project_file = safe_path_resolve(project_file)
            
            
            # Validate paths
            if not os.path.exists(abs_executable):
                error_msg = f"Executable not found: {abs_executable}"
                logger.error(error_msg)
                return False, error_msg, {'render_time': 0}
            
            if not os.path.exists(abs_project_file):
                error_msg = f"Project file not found: {abs_project_file}"
                logger.error(error_msg)
                return False, error_msg, {'render_time': 0}
            
            # Parse frame range
            if '-' in frame_range:
                start_frame, end_frame = map(int, frame_range.split('-'))
            else:
                start_frame = end_frame = int(frame_range)
            
            # Validate frame range against project (if function available)
            # if hasattr(self, 'validate_nuke_frame_range'):
            #     validated_start, validated_end, validation_msg = self.validate_nuke_frame_range(
            #         abs_project_file, start_frame, end_frame
            #     )
                
                # if validated_start is None:
                #     error_msg = f"Frame validation failed: {validation_msg}"
                #     logger.error(f"[ERROR] {error_msg}")
                #     return False, error_msg, {'render_time': 0}
                # 
                # # Use validated range
                # if validated_start != start_frame or validated_end != end_frame:
                #     logger.info(f"[OK] Using validated range: {validated_start}-{validated_end}")
                #     start_frame, end_frame = validated_start, validated_end
            
            frame_count = end_frame - start_frame + 1
            
            # Build command with GPU support and optimized thread count
            use_gpu = self.config.get('performance', {}).get('use_gpu', True)
            
            # When using GPU, reduce CPU threads to prevent resource contention
            if use_gpu and self._gpu_available():
                max_threads = min(8, os.cpu_count() // 2)  # Use half of CPU cores, max 8
            else:
                max_threads = self.config.get('performance', {}).get('max_render_threads', 16)
            
            # Match old backup command but reduce verbosity for speed
            cmd = [
                abs_executable,
                '-i', '-f', '-x',
                '-m', '3',
                '-F', f"{start_frame}-{end_frame}",
                '-m', '14'  # Second -m flag like old backup
                # Removed -V for faster rendering (less console output)
            ]
            
            # Skip GPU flags - they cause "Unknown switch" errors
            
            cmd.extend(['--', abs_project_file])
            
            # Add extra arguments if provided
            extra_args = job_data.get('extra_args', '')
            if extra_args:
                cmd = cmd[:-2] + extra_args.split() + cmd[-2:]
            
            work_dir = os.path.dirname(abs_project_file)
            timeout = frame_count * self.config.get('jobs', {}).get('timeout_per_frame', 180)  # Reduced timeout
            
            # Minimal logging for speed
            
            # Execute render
            env = os.environ.copy()
            
            # Don't set cwd for UNC paths on Windows
            popen_kwargs = {
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'text': True,
                'encoding': 'utf-8',
                'errors': 'replace',
                'env': env,
                'creationflags': subprocess.HIGH_PRIORITY_CLASS if platform.system() == "Windows" else 0
            }
            
            # Only set cwd if it's not a UNC path on Windows
            if not (platform.system() == 'Windows' and work_dir.startswith('\\\\')):
                popen_kwargs['cwd'] = work_dir
            
            with subprocess.Popen(cmd, **popen_kwargs) as process:
                # Use smart monitoring if available (no logging during render)
                if hasattr(self, '_monitor_process_with_activity'):
                    stdout, stderr = self._monitor_process_with_activity(process, timeout)
                else:
                    stdout, stderr = process.communicate(timeout=timeout)
            
            render_time = time.time() - start_time
            
            # Only log errors to avoid slowing down successful renders
            if process.returncode != 0:
                logger.error(f"[NUKE] Failed (exit {process.returncode}) in {render_time:.1f}s")
                if stderr:
                    logger.error(f"[NUKE] Error: {stderr[:200]}...")
            
            # No drive cleanup needed since we're using direct UNC paths
            
            # Check results
            if process.returncode == 0:
                # Get output file information
                output_info = self.detect_output_files(abs_project_file, frame_range, job_data)
                # Minimal success logging for speed
                file_count = 0
                if isinstance(output_info, dict) and 'files' in output_info:
                    file_count = len(output_info['files'])
                elif isinstance(output_info, list):
                    file_count = len(output_info)
                
                metrics = {
                    'render_time': render_time,
                    'output_info': output_info,
                    'memory_peak': self.get_peak_memory_usage(batch_id) if hasattr(self, 'get_peak_memory_usage') else 0,
                    'frames_rendered': frame_count,
                    'fps': frame_count / render_time if render_time > 0 else 0,
                    'cache_stats': self.asset_cache.get_stats() if hasattr(self.asset_cache, 'get_stats') else {}
                }
                
                # Update stats
                if self.render_stats:
                    self.render_stats['jobs_completed'] += 1
                    self.render_stats['frames_rendered'] += frame_count
                    self.render_stats['total_render_time'] += render_time
                
                # Minimal success logging for speed
                return True, None, metrics
            else:
                return False, f"Failed (exit {process.returncode})", {'render_time': render_time}
                
        except subprocess.TimeoutExpired:
            return False, f"Timeout after {timeout}s", {'render_time': time.time() - start_time}
        except Exception as e:
            return False, str(e), {'render_time': time.time() - start_time}
    
    def verify_output_files(self, project_file, start_frame, end_frame):
        """Get exact output path from Nuke project file"""
        output_files = []
        
        try:
            with open(project_file, 'r') as f:
                content = f.read()
            
            # Find Write node output path: Write { file /path/to/output.####.exr }
            match = re.search(r'Write\s*\{[^}]*file\s+([^\s}]+)', content, re.DOTALL)
            if not match:
                logger.warning(f"[VERIFY] No Write node output path found in {project_file}")
                return output_files
            
            output_pattern = match.group(1).strip('\'"')
            logger.debug(f"[VERIFY] Found output pattern: {output_pattern}")
            
            # Check exact files
            for frame in range(start_frame, end_frame + 1):
                # Replace common frame padding patterns
                file_path = output_pattern.replace('####', f'{frame:04d}')
                file_path = file_path.replace('###', f'{frame:03d}')
                file_path = file_path.replace('##', f'{frame:02d}')
                file_path = file_path.replace('%04d', f'{frame:04d}')
                file_path = file_path.replace('%03d', f'{frame:03d}')
                file_path = file_path.replace('%d', str(frame))
                
                if os.path.exists(file_path):
                    output_files.append(file_path)
                    logger.debug(f"[VERIFY] Found: {file_path}")
                else:
                    logger.debug(f"[VERIFY] Missing: {file_path}")
            
            if output_files:
                logger.info(f"[VERIFY] Found {len(output_files)} of {end_frame - start_frame + 1} expected output files")
            else:
                logger.warning(f"[VERIFY] No output files found using pattern: {output_pattern}")
            
            return output_files
            
        except Exception as e:
            logger.error(f"[VERIFY] Error reading Nuke project file: {e}")
            return output_files
    
    def _gpu_available(self):
        """Check if GPU is available for rendering and get GPU info"""
        try:
            # First check GPU utilization
            util_result = subprocess.run([
                'nvidia-smi',
                '--query-gpu=utilization.gpu,memory.used,temperature.gpu',
                '--format=csv,noheader'
            ], capture_output=True, text=True, timeout=2)
            
            if util_result.returncode == 0 and util_result.stdout.strip():
                for line in util_result.stdout.strip().split('\n'):
                    try:
                        util, used, temp = [x.strip() for x in line.split(',')]
                        util = int(util.strip(' %'))
                        used = int(used.strip(' MiB'))
                        temp = int(temp)
                        
                        # If GPU is already heavily used, fall back to CPU
                        if util > 80 or temp > 85:
                            logger.warning(f"[GPU] GPU load {util}% or temp {temp}°C too high, falling back to CPU")
                            return False
                    except Exception:
                        pass
            
            # Get detailed GPU info using nvidia-smi
            result = subprocess.run([
                'nvidia-smi',
                '--query-gpu=name,memory.total,memory.free,compute_mode,persistence_mode',
                '--format=csv,noheader'
            ], capture_output=True, text=True, timeout=2)
            
            if result.returncode == 0 and result.stdout.strip():
                gpus = []
                for line in result.stdout.strip().split('\n'):
                    try:
                        name, total, free, mode, persistence = [x.strip() for x in line.split(',')]
                        total_mb = int(total.split()[0])
                        free_mb = int(free.split()[0])
                        
                        # Only consider GPUs with enough free memory
                        if free_mb >= 2048:  # Minimum 2GB free
                            gpus.append({
                                'name': name,
                                'total_memory': total_mb,
                                'free_memory': free_mb,
                                'compute_mode': mode,
                                'persistence_mode': persistence
                            })
                            logger.debug(f"[GPU] Found {name} with {free_mb}MB/{total_mb}MB free")
                    except Exception as e:
                        logger.debug(f"[GPU] Error parsing GPU info: {e}")
                        continue
                
                if gpus:
                    # Find GPU with most free memory
                    best_gpu = max(gpus, key=lambda x: x['free_memory'])
                    
                    # If GPU has less than 30% free memory, fall back to CPU
                    free_percent = (best_gpu['free_memory'] / best_gpu['total_memory']) * 100
                    if free_percent < 30:
                        logger.warning(f"[GPU] Only {free_percent:.1f}% memory free on {best_gpu['name']}, falling back to CPU")
                        return False
                    
                    # Enable persistence mode for better performance
                    try:
                        if best_gpu['persistence_mode'] == 'Disabled':
                            subprocess.run(['nvidia-smi', '-pm', '1'], timeout=2)
                    except Exception:
                        pass
                    
                    logger.info(f"[GPU] Selected {best_gpu['name']} with {best_gpu['free_memory']}MB free ({free_percent:.1f}%)")
                    
                    # Store GPU info for command line args
                    self._gpu_info = best_gpu
                    return True
                
                logger.warning("[GPU] No GPUs with sufficient free memory found")
                return False
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("[GPU] nvidia-smi not available, falling back to CPU")
            return False
        except Exception as e:
            logger.error(f"[GPU] Error checking GPU: {e}")
            return False
        
        return False  # Fall back to CPU by default
        gpu_config = self.config.get('gpu', {})
        if gpu_config.get('force_enable', False):
            logger.info("[GPU] GPU forced enabled via configuration")
            self._gpu_info = {
                'name': 'Unknown',
                'total_memory': gpu_config.get('memory_limit', 4096),  # Default 4GB
                'free_memory': gpu_config.get('memory_limit', 4096)
            }
            return True
        
        logger.info("[GPU] No GPU detected, using CPU only")
        return False