#!/usr/bin/env python3
import argparse
import os
import subprocess
import re
import tempfile
import time
import requests
from pathlib import Path

def check_tts_server_status(port=5000):
    """检查TTS服务器状态"""
    try:
        response = requests.get(f'http://127.0.0.1:{port}/health', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return True, data
        return False, None
    except requests.exceptions.RequestException:
        return False, None

def start_tts_server_if_needed(port=5000):
    """检查并启动TTS服务器"""
    print("Checking TTS server status...")
    
    # 检查服务器是否已运行
    running, status = check_tts_server_status(port)
    if running:
        print(f"✓ TTS Server is already running (PID: {status['pid']}, Model loaded: {status['model_loaded']})")
        return True
    
    print("✗ TTS Server not running, starting server...")
    
    # 启动服务器
    try:
        cmd = ['uv', 'run', 'python3', 'server_manager.py', '--port', str(port), 'start']
        print(f"Starting server with command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd='/Volumes/Disk/index-tts2')
        
        if result.returncode != 0:
            print(f"✗ Failed to start server: {result.stderr}")
            return False
        
        print("Server start command executed, waiting for server to be ready...")
        
        # 等待服务器启动并加载模型
        max_wait_time = 60  # 最多等待60秒
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            running, status = check_tts_server_status(port)
            if running:
                model_loaded = status.get('model_loaded', False)
                if model_loaded:
                    print(f"✓ TTS Server is ready! (PID: {status['pid']}, Model loaded: {model_loaded})")
                    return True
                else:
                    print(f"  Server running but model still loading... (PID: {status['pid']})")
            else:
                print(f"  Waiting for server startup... ({int(time.time() - start_time)}/{max_wait_time}s)")
            
            time.sleep(2)
        
        print(f"✗ Server failed to be ready within {max_wait_time} seconds")
        return False
        
    except Exception as e:
        print(f"✗ Failed to start server: {e}")
        return False

def parse_srt_time(time_str):
    """Parse SRT timestamp to seconds"""
    # Format: 00:00:10,500 -> 10.5 seconds
    time_part, ms_part = time_str.split(',')
    h, m, s = map(int, time_part.split(':'))
    ms = int(ms_part)
    return h * 3600 + m * 60 + s + ms / 1000.0

def parse_srt_file(srt_path):
    """Parse SRT file and return list of subtitle entries"""
    subtitles = []
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    
    # Split by double newlines to separate subtitle blocks
    blocks = re.split(r'\n\s*\n', content)
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            # Line 0: subtitle number
            # Line 1: timestamp
            # Line 2+: text
            try:
                subtitle_num = int(lines[0])
                timestamp_line = lines[1]
                text = '\n'.join(lines[2:])
                
                # Parse timestamp: "00:00:10,500 --> 00:00:13,000"
                start_time_str, end_time_str = timestamp_line.split(' --> ')
                start_time = parse_srt_time(start_time_str.strip())
                end_time = parse_srt_time(end_time_str.strip())
                
                subtitles.append({
                    'num': subtitle_num,
                    'start': start_time,
                    'end': end_time,
                    'text': text.strip()
                })
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse subtitle block: {block[:50]}...")
                continue
    
    return subtitles

def extract_audio(video_path, audio_path):
    """Extract audio from video using ffmpeg"""
    cmd = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', audio_path, '-y']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Failed to extract audio: {result.stderr}")

def split_audio_segment(input_audio, output_audio, start_time, end_time):
    """Extract audio segment using ffmpeg"""
    duration = end_time - start_time
    cmd = ['ffmpeg', '-i', input_audio, '-ss', str(start_time), '-t', str(duration), 
           '-acodec', 'pcm_s16le', output_audio, '-y']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Failed to split audio segment: {result.stderr}")

def generate_tts_simple(voice_sample, text, output_path, temp_dir='temp'):
    """Generate TTS using server mode (faster, no model reloading)"""
    cmd = [
        'uv', 'run', 'python3', 'gentts.py', 
        '--server-mode',  # 使用服务器模式
        '-v', voice_sample,
        '-t', text,
        '-o', output_path,
        '--verbose'
    ]
    
    print(f"    Running TTS command (server mode): {' '.join(cmd)}")
    print(f"    Voice sample: {voice_sample}")
    print(f"    Text: {text}")
    print(f"    Output path: {output_path}")
    
    try:
        import time
        start_time = time.time()
        
        # 增加超时时间到 300 秒 (5分钟)
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300, cwd='/Volumes/Disk/index-tts2')
        
        end_time = time.time()
        duration = end_time - start_time
        
        if result.returncode != 0:
            print(f"    ✗ TTS failed with return code: {result.returncode}")
            print(f"    Duration: {duration:.2f} seconds")
            raise Exception(f"Failed to generate TTS: return code {result.returncode}")
        else:
            print(f"    ✓ TTS generated successfully: {output_path}")
            print(f"    Duration: {duration:.2f} seconds")
            
    except subprocess.TimeoutExpired:
        print(f"    ✗ TTS generation timed out after 300 seconds")
        raise Exception("TTS generation timed out")

def preprocess_voice_sample(input_audio, output_audio):
    """Remove noise from voice sample using ffmpeg highpass/lowpass filters"""
    cmd = [
        'ffmpeg', '-i', input_audio,
        '-af', 'highpass=f=200,lowpass=f=3000,afftdn=nf=-25',
        output_audio, '-y'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: Failed to preprocess voice sample: {result.stderr}")
        import shutil
        shutil.copy2(input_audio, output_audio)

def generate_tts(voice_sample, text, output_path, temp_dir='kid_temp'):
    """Generate TTS using gentts.py with emotion preservation (default enabled)"""
    # Preprocess voice sample to remove noise
    cleaned_voice = os.path.join(str(temp_dir), f"cleaned_voice_{os.path.basename(voice_sample)}")
    if not os.path.exists(cleaned_voice):
        print(f"    Preprocessing voice sample to remove background noise...")
        preprocess_voice_sample(voice_sample, cleaned_voice)
    
    cmd = [
        'uv', 'run', 'python3', 'gentts.py', 
        '-v', cleaned_voice,
        '-t', text,
        '-o', output_path,
        '--verbose'
    ]
    
    print(f"    Running TTS command: {' '.join(cmd)}")
    print(f"    Voice sample: {voice_sample}")
    print(f"    Text: {text}")
    print(f"    Output path: {output_path}")
    
    try:
        import time
        start_time = time.time()
        
        # 增加超时时间到 300 秒 (5分钟)
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300, cwd='/Volumes/Disk/index-tts2')
        
        end_time = time.time()
        duration = end_time - start_time
        
        if result.returncode != 0:
            print(f"    ✗ TTS failed with return code: {result.returncode}")
            print(f"    Duration: {duration:.2f} seconds")
            raise Exception(f"Failed to generate TTS: return code {result.returncode}")
        else:
            print(f"    ✓ TTS generated successfully: {output_path}")
            print(f"    Duration: {duration:.2f} seconds")
            
    except subprocess.TimeoutExpired:
        print(f"    ✗ TTS generation timed out after 300 seconds")
        raise Exception("TTS generation timed out")

def combine_audio_segments(segments, background_audio_path, output_path, temp_dir='temp', tts_volume=1.0):
    """Combine TTS segments with background music using FFmpeg"""
    if not segments:
        return
        
    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda x: x['start'])
    
    print(f"  ✓ 将使用背景音频文件: {background_audio_path}")
    print(f"  ✓ TTS音量设置: {int(tts_volume * 100)}%")
    
    print("  Step 3: 使用FFmpeg快速合并背景音频和TTS片段...")
    
    # 创建FFmpeg输入列表和滤镜
    inputs = ['-i', background_audio_path]  # 背景音频作为第一个输入
    filter_complex_parts = ['[0:a]volume=0.5[bg];']  # 背景音频降低音量
    
    # 添加所有TTS片段作为输入，严格按照SRT开始时间定位
    for i, segment in enumerate(sorted_segments):
        inputs.extend(['-i', segment['audio_path']])
        # 使用SRT中的精确开始时间（毫秒）
        start_time_ms = int(segment['start'] * 1000)
        print(f"    TTS片段 {i+1}: {segment['audio_path']} -> 开始时间 {segment['start']:.3f}s ({start_time_ms}ms), 音量 {int(tts_volume * 100)}%")
        filter_complex_parts.append(f'[{i+1}:a]adelay={start_time_ms}|{start_time_ms},volume={tts_volume}[tts{i}];')
    
    # 构建混音命令 - 混合背景音频和所有TTS片段
    mix_inputs = '[bg]'
    for i in range(len(sorted_segments)):
        mix_inputs += f'[tts{i}]'
    
    filter_complex_parts.append(f'{mix_inputs}amix=inputs={len(sorted_segments)+1}:duration=longest:normalize=0[final]')
    
    filter_complex = ''.join(filter_complex_parts)
    
    # 构建完整的FFmpeg命令
    cmd = ['ffmpeg'] + inputs + [
        '-filter_complex', filter_complex,
        '-map', '[final]',
        '-ac', '2',  # 立体声
        '-ar', '44100',  # 采样率
        output_path, '-y'
    ]
    
    print(f"    FFmpeg命令: {' '.join(cmd[:10])}... (共{len(cmd)}个参数)")
    print(f"    背景音频: {background_audio_path}")
    print(f"    TTS片段数: {len(sorted_segments)}")
    print(f"    时间定位: 严格按照SRT开始时间")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("  ✓ FFmpeg音频合并成功 - TTS已按SRT时间精确定位")
    else:
        print(f"  ✗ FFmpeg音频合并失败: {result.stderr}")
        # 降级方案：只使用背景音频
        import shutil
        shutil.copy2(background_audio_path, output_path)
        print("  ↳ 使用背景音频作为备用输出")

def try_vocal_remover_ai(input_audio, temp_dir):
    """尝试使用vocal-remover AI方法进行人声分离"""
    try:
        print("    正在尝试: AI深度学习人声分离 (vocal-remover)")
        
        # 检查是否存在vocal-remover
        vocal_remover_path = os.path.join('/Volumes/Disk/index-tts2/vocal-removel/vocal-remover')
        if not os.path.exists(vocal_remover_path):
            print("    ✗ vocal-remover路径不存在")
            return False
            
        inference_script = os.path.join(vocal_remover_path, 'inference.py')
        if not os.path.exists(inference_script):
            print("    ✗ vocal-remover inference.py不存在")
            return False
        
        # 检查模型文件是否存在
        model_dir = os.path.join(vocal_remover_path, 'models')
        baseline_model = os.path.join(model_dir, 'baseline.pth')
        if not os.path.exists(baseline_model):
            print(f"    ✗ vocal-remover模型文件不存在: {baseline_model}")
            return False
        
        # 检查虚拟环境
        venv_path = os.path.join(vocal_remover_path, 'venv')
        python_executable = os.path.join(venv_path, 'bin', 'python')
        if not os.path.exists(python_executable):
            print(f"    ✗ vocal-remover虚拟环境不存在: {python_executable}")
            return False
        
        print(f"    ✓ 找到模型文件: {baseline_model}")
        print(f"    ✓ 找到虚拟环境: {python_executable}")
        
        # 验证虚拟环境中的依赖
        print("    检查虚拟环境依赖...")
        dep_check = subprocess.run([
            python_executable, '-c', 
            'import torch, librosa, numpy; print("Dependencies OK")'
        ], capture_output=True, text=True, cwd=vocal_remover_path)
        
        if dep_check.returncode != 0:
            print(f"    ✗ 虚拟环境依赖检查失败: {dep_check.stderr}")
            return False
        
        print("    ✓ 虚拟环境依赖检查通过")
        
        # 运行vocal-remover，使用虚拟环境的Python
        # 确保输入路径是绝对路径
        input_audio_abs = os.path.abspath(input_audio)
        temp_dir_abs = os.path.abspath(temp_dir)
        
        cmd = [
            python_executable, inference_script,
            '--input', input_audio_abs,
            '--output_dir', temp_dir_abs + '/',
            '--pretrained_model', baseline_model,
            '--gpu', '-1'  # 使用CPU
        ]
        
        print(f"    运行命令: {' '.join(cmd)}")
        print(f"    输入文件: {input_audio_abs}")
        print(f"    输出目录: {temp_dir_abs}")
        
        # 确保输入文件存在
        if not os.path.exists(input_audio_abs):
            print(f"    ✗ 输入音频文件不存在: {input_audio_abs}")
            return False
        
        print("    开始执行vocal-remover，实时显示进度...")
        print("    " + "="*50)
        
        # 实时显示输出，不设置超时
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,  # 合并stderr到stdout
            universal_newlines=True,
            cwd=vocal_remover_path
        )
        
        # 实时读取和显示输出
        output_lines = []
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                # 显示进度信息
                print(f"    {output.strip()}")
                output_lines.append(output.strip())
        
        # 等待进程完成
        return_code = process.poll()
        
        print("    " + "="*50)
        print(f"    vocal-remover执行完成，返回码: {return_code}")
        
        if return_code == 0:
            # 检查输出文件，使用绝对路径
            basename = os.path.splitext(os.path.basename(input_audio_abs))[0]
            instruments_file = os.path.join(temp_dir_abs, f"{basename}_Instruments.wav")
            vocals_file = os.path.join(temp_dir_abs, f"{basename}_Vocals.wav")
            
            print(f"    检查输出文件: {instruments_file}")
            
            if os.path.exists(instruments_file):
                # 重命名为我们的命名规则
                ai_output = os.path.join(temp_dir, "vocal_removed_method0_ai_instruments.wav")
                ai_vocals = os.path.join(temp_dir, "vocal_removed_method0_ai_vocals.wav")
                import shutil
                shutil.copy2(instruments_file, ai_output)
                if os.path.exists(vocals_file):
                    shutil.copy2(vocals_file, ai_vocals)
                
                print("    ✓ AI深度学习人声分离成功")
                return True
            else:
                print(f"    ✗ 未找到预期的输出文件: {instruments_file}")
                print(f"    完整输出:")
                for line in output_lines:
                    print(f"      {line}")
                return False
        else:
            print(f"    ✗ vocal-remover执行失败 (返回码: {return_code})")
            print(f"    完整输出:")
            for line in output_lines:
                print(f"      {line}")
            return False
            
    except Exception as e:
        print(f"    ✗ vocal-remover执行异常: {e}")
        return False

def replace_video_audio(video_path, new_audio_path, output_path):
    """Replace video audio with new audio"""
    cmd = ['ffmpeg', '-i', video_path, '-i', new_audio_path, '-c:v', 'copy', '-c:a', 'aac', 
           '-map', '0:v:0', '-map', '1:a:0', output_path, '-y']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Failed to replace video audio: {result.stderr}")

def main():
    parser = argparse.ArgumentParser(description='Replace video audio with TTS based on subtitles')
    parser.add_argument('video', help='Input video file (e.g., kid.mp4)')
    parser.add_argument('-i', '--input-srt', required=True, help='Input SRT subtitle file')
    parser.add_argument('-o', '--output', required=True, help='Output video file')
    parser.add_argument('-v', '--voice-sample', help='Voice sample for TTS (optional, will use first audio segment if not provided)')
    parser.add_argument('--test-first-only', action='store_true', help='Only process first subtitle for testing')
    parser.add_argument('--test-first-n', type=int, help='Only process first N subtitles for testing')
    parser.add_argument('--tts-volume', type=float, default=1.0, help='TTS audio volume adjustment (0.1-1.0, default: 1.0)')
    
    args = parser.parse_args()
    
    # Validate TTS volume parameter
    if args.tts_volume < 0.1 or args.tts_volume > 1.0:
        parser.error("TTS volume must be between 0.1 and 1.0")
    
    # Create temp directory based on video filename
    video_name = Path(args.video).stem  # 获取不带扩展名的文件名
    temp_dir = Path(f'{video_name}_temp')
    temp_dir.mkdir(exist_ok=True)
    
    print(f"Processing video: {args.video}")
    print(f"Using subtitles: {args.input_srt}")
    print(f"Temp directory: {temp_dir}")
    print(f"Output will be saved to: {args.output}")
    
    # Step 0: 确保TTS服务器运行并准备就绪
    print("\nStep 0: Ensuring TTS server is ready...")
    if not start_tts_server_if_needed():
        print("✗ Failed to start TTS server. Please check the server manually.")
        return 1
    print("✓ TTS server is ready for processing!\n")
    
    try:
        # Step 1: Extract audio from video
        print("Step 1: Extracting audio from video...")
        original_audio = temp_dir / 'original_audio.wav'
        extract_audio(args.video, str(original_audio))
        
        # Step 2: AI声音分离 (最优先执行)
        print("Step 2: AI声音分离 (vocal-remover)...")
        basename = original_audio.stem
        ai_instruments_file = temp_dir / f"{basename}_Instruments.wav"
        ai_vocals_file = temp_dir / f"{basename}_Vocals.wav"
        
        if ai_instruments_file.exists() and ai_vocals_file.exists():
            print(f"  ⊙ AI分离文件已存在:")
            print(f"    背景音乐: {ai_instruments_file}")
            print(f"    人声音频: {ai_vocals_file}")
        else:
            print(f"  执行vocal-remover AI处理...")
            success = try_vocal_remover_ai(str(original_audio), str(temp_dir))
            if not success:
                print("  ✗ vocal-remover AI声音分离失败")
                raise Exception("vocal-remover无法加载或执行失败，程序退出")
            print(f"  ✓ AI声音分离完成:")
            print(f"    背景音乐: {ai_instruments_file}")
            print(f"    人声音频: {ai_vocals_file}")
        
        # Step 3: Parse SRT file
        print("Step 3: Parsing subtitle file...")
        subtitles = parse_srt_file(args.input_srt)
        print(f"Found {len(subtitles)} subtitle entries")
        
        if args.test_first_only:
            subtitles = subtitles[:1]
            print("Test mode: Processing only first subtitle")
        elif args.test_first_n:
            subtitles = subtitles[:args.test_first_n]
            print(f"Test mode: Processing first {args.test_first_n} subtitles")
        
        # Step 4: Split vocals audio by subtitle segments (using AI separated vocals)
        print("Step 4: Splitting vocals audio segments...")
        audio_segments = []
        skipped_segments = 0
        for subtitle in subtitles:
            segment_path = temp_dir / f"vocals_segment_{subtitle['num']:03d}.wav"
            
            # 检查vocals segment文件是否已存在
            if segment_path.exists():
                print(f"  ⊙ Vocals segment {subtitle['num']} already exists, skipping: {segment_path}")
                skipped_segments += 1
            else:
                print(f"  Splitting vocals segment {subtitle['num']}: {subtitle['start']:.2f}s - {subtitle['end']:.2f}s")
                split_audio_segment(str(ai_vocals_file), str(segment_path), 
                                  subtitle['start'], subtitle['end'])
                print(f"  ✓ Created vocals segment: {segment_path}")
            
            audio_segments.append({
                'num': subtitle['num'],
                'start': subtitle['start'],
                'end': subtitle['end'],
                'text': subtitle['text'],
                'vocals_path': str(segment_path)  # 使用人声片段路径
            })
        
        print(f"  ========== Vocals Segmentation Summary ==========")
        print(f"  Total segments: {len(audio_segments)}")
        print(f"  Segments skipped (already exist): {skipped_segments}")
        print(f"  Segments created: {len(audio_segments) - skipped_segments}")
        print(f"  Source: AI separated vocals ({ai_vocals_file})")
        print(f"  ===============================================")
        
        # Step 5: Generate TTS for each segment
        print("Step 5: Generating TTS for each segment...")
        fallback_voice_sample = args.voice_sample or audio_segments[0]['vocals_path']
        print(f"Fallback voice sample: {fallback_voice_sample}")
        print(f"Total segments to process: {len(audio_segments)}")
        print("Each segment will use its corresponding vocals audio (no noise reduction)")
        
        tts_segments = []
        skipped_count = 0
        for i, segment in enumerate(audio_segments):
            print(f"\n  ========== Processing segment {i+1}/{len(audio_segments)} ==========")
            print(f"  Segment #{segment['num']}: {segment['start']:.2f}s - {segment['end']:.2f}s")
            print(f"  Text: {segment['text']}")
            print(f"  Using vocals sample: {segment['vocals_path']}")
            tts_path = temp_dir / f"tts_{segment['num']:03d}.wav"
            
            # 检查TTS文件是否已存在
            if tts_path.exists():
                print(f"  ⊙ TTS file already exists, skipping generation: {tts_path}")
                tts_segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'audio_path': str(tts_path)
                })
                skipped_count += 1
                continue
            
            try:
                import time
                segment_start_time = time.time()
                
                # 直接使用对应的人声片段作为 voice sample (无降噪处理)
                generate_tts_simple(segment['vocals_path'], segment['text'], str(tts_path), temp_dir)
                
                segment_end_time = time.time()
                segment_duration = segment_end_time - segment_start_time
                
                tts_segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'audio_path': str(tts_path)
                })
                print(f"  ✓ Segment {i+1} completed in {segment_duration:.2f} seconds")
                print(f"  ✓ Generated: {tts_path}")
                
            except Exception as e:
                print(f"  ✗ Warning: Failed to generate TTS for segment {segment['num']}: {e}")
                # Fall back to original vocals segment
                tts_segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'audio_path': segment['vocals_path']
                })
                print(f"  ↳ Using original vocals audio: {segment['vocals_path']}")
        
        print(f"\n  ========== TTS Generation Summary ==========")
        print(f"  Total segments processed: {len(audio_segments)}")
        successful_tts = sum(1 for seg in tts_segments if 'tts_' in seg['audio_path'])
        print(f"  Successful TTS generations: {successful_tts}")
        print(f"  Skipped (already exist): {skipped_count}")
        print(f"  Fallback to original vocals: {len(audio_segments) - successful_tts}")
        
        # Step 6: Combine generated audio segments with vocal-removed background
        print("Step 6: Combining audio segments with background music...")
        combined_audio = temp_dir / 'combined_audio.wav'
        combine_audio_segments(tts_segments, str(ai_instruments_file), str(combined_audio), temp_dir, args.tts_volume)
        
        # Step 7: Replace video audio
        print("Step 7: Replacing video audio...")
        replace_video_audio(args.video, str(combined_audio), args.output)
        
        print(f"✓ Successfully created {args.output}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == '__main__':
    exit(main())