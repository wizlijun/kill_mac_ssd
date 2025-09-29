#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Text-to-Speech Command Line Tool for IndexTTS2
Now supports both direct inference and server API modes

Usage:
python gentts.py -v voice.wav -t "文本" -o output.wav
python gentts.py -v voice.wav -f input.txt -o output.wav
python gentts.py -v voice.wav -t "文本" -o output.mp3  # MP3 output (requires ffmpeg)
python gentts.py --server-mode -v voice.wav -t "文本" -o output.wav  # Use server API
"""

import argparse
import os
import re
import shutil
import subprocess
import time
import requests
from datetime import datetime
from typing import List, Tuple, Dict

# Only import IndexTTS2 when not using server mode
IndexTTS2 = None

def check_server_status(port=5000):
    """检查服务器状态"""
    try:
        response = requests.get(f'http://127.0.0.1:{port}/health', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return True, data
        return False, None
    except requests.exceptions.RequestException:
        return False, None

def start_server_if_needed(port=5000):
    """如果服务器未运行则启动"""
    running, status = check_server_status(port)
    if running:
        print(f"✓ IndexTTS2 Server is running (PID: {status['pid']})")
        return True
    
    print("✗ IndexTTS2 Server not running, starting server...")
    try:
        # 启动服务器进程
        subprocess.Popen([
            'python3', '/Volumes/Disk/index-tts2/indextts2server.py',
            '--port', str(port)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待服务器启动
        for i in range(30):  # 等待最多30秒
            time.sleep(1)
            running, _ = check_server_status(port)
            if running:
                print(f"✓ IndexTTS2 Server started successfully")
                return True
            print(f"  Waiting for server startup... ({i+1}/30)")
        
        print("✗ Failed to start IndexTTS2 Server within 30 seconds")
        return False
        
    except Exception as e:
        print(f"✗ Failed to start server: {e}")
        return False

def generate_tts_via_server(voice_file, text, output_file, port=5000):
    """通过服务器API生成TTS（使用文件上传）"""
    try:
        # 准备请求数据
        files = {'voice_file': open(voice_file, 'rb')}
        data = {
            'text': text,
            'use_random': 'false',
            'verbose': 'false',
            'interval_silence': '200'
        }
        
        # 发送生成请求
        response = requests.post(f'http://127.0.0.1:{port}/generate', files=files, data=data, timeout=300)
        files['voice_file'].close()
        
        if response.status_code == 200:
            # 保存生成的音频
            with open(output_file, 'wb') as f:
                f.write(response.content)
            print(f"✓ TTS generated via server: {output_file}")
            return True
        else:
            print(f"✗ Server request failed: {response.status_code}")
            try:
                error_info = response.json()
                print(f"  Error: {error_info.get('error', 'Unknown error')}")
            except:
                print(f"  Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("✗ Server request timed out")
        return False
    except Exception as e:
        print(f"✗ Server request error: {e}")
        return False


def convert_wav_to_mp3(wav_path: str, mp3_path: str) -> str:
    """
    Convert WAV file to MP3 using ffmpeg
    
    Args:
        wav_path: Input WAV file path
        mp3_path: Output MP3 file path
        
    Returns:
        Path to the converted MP3 file
        
    Raises:
        RuntimeError: If ffmpeg is not available or conversion fails
    """
    try:
        # Check if ffmpeg is available
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("ffmpeg is required for MP3 conversion but is not installed or not in PATH")
    
    try:
        # Convert WAV to MP3 with good quality settings
        cmd = [
            'ffmpeg', '-i', wav_path,
            '-codec:a', 'libmp3lame',
            '-b:a', '192k',
            '-y',  # Overwrite output file if exists
            mp3_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
        
        # Remove the temporary WAV file
        try:
            os.remove(wav_path)
        except OSError:
            pass
            
        return mp3_path
        
    except Exception as e:
        raise RuntimeError(f"Failed to convert WAV to MP3: {e}")


class TextParser:
    """文本解析器"""
    
    def __init__(self):
        pass
    
    def parse_line(self, line: str) -> str:
        """
        解析单行文本
        
        Args:
            line: 输入文本行
            
        Returns:
            处理后的文本
        """
        return line.strip()
    
    def parse_text(self, text: str, process_all: bool = True) -> List[str]:
        """
        解析多行文本
        
        Args:
            text: 多行输入文本
            process_all: 是否处理所有行，如果为False则只处理第一行
            
        Returns:
            处理后的文本列表
        """
        lines = text.split('\n')
        results = []
        
        for line in lines:
            parsed_text = self.parse_line(line)
            if parsed_text:  # 只添加非空文本
                results.append(parsed_text)
                if not process_all:  # 如果不处理全部，只处理第一行
                    break
                
        return results


class TTSGenerator:
    """TTS生成器"""
    
    def __init__(self, model_dir="checkpoints", use_fp16=False, use_cuda_kernel=False, use_deepspeed=False, server_mode=False, server_port=5000):
        """
        初始化TTS模型
        
        Args:
            model_dir: 模型目录路径
            use_fp16: 是否使用FP16
            use_cuda_kernel: 是否使用CUDA内核
            use_deepspeed: 是否使用DeepSpeed
            server_mode: 是否使用服务器模式
            server_port: 服务器端口
        """
        self.server_mode = server_mode
        self.server_port = server_port
        self.tts = None
        
        if server_mode:
            print("Using server API mode for TTS generation")
            # 确保服务器运行
            if not start_server_if_needed(server_port):
                raise RuntimeError("Failed to start or connect to IndexTTS2 server")
        else:
            print("Using direct inference mode for TTS generation")
            # 导入和初始化TTS模型
            global IndexTTS2
            if IndexTTS2 is None:
                from indextts.infer_v2 import IndexTTS2
            
            cfg_path = os.path.join(model_dir, "config.yaml")
            self.tts = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=model_dir,
                use_fp16=use_fp16,
                use_cuda_kernel=use_cuda_kernel,
                use_deepspeed=use_deepspeed
            )
            
        self.parser = TextParser()
    
    def generate_audio_segments(self, voice_prompt: str, text_segments: List[str], 
                              verbose: bool = False, process_all: bool = True, 
                              preserve_emotion: bool = True, emotion_strength: float = 1.0,
                              preserve_speed: bool = True, preserve_accent: bool = True,
                              **generation_kwargs) -> List[str]:
        """
        生成音频片段
        
        Args:
            voice_prompt: 声音提示音频路径
            text_segments: 解析后的文本片段列表
            verbose: 是否显示详细信息
            process_all: 是否处理所有片段
            preserve_emotion: 是否保留原声音的情绪特征
            emotion_strength: 情绪保留强度 (0.0-1.0)
            preserve_speed: 是否保留原声音的语速
            preserve_accent: 是否保留原声音的口音特征
            **generation_kwargs: 传递给TTS推理的额外参数
            
        Returns:
            生成的音频文件路径列表
        """
        audio_files = []
        
        for i, text in enumerate(text_segments):
            if verbose:
                print(f"Generating segment {i+1}/{len(text_segments)}: {text}")
            
            # 生成临时文件名
            temp_output = f"temp_segment_{i+1}_{int(time.time())}.wav"
            
            try:
                # 设置情绪和声音特征保留参数
                inference_kwargs = {
                    'use_random': False,
                    'verbose': verbose,
                    'interval_silence': 200,  # 片段间静音200ms
                    **generation_kwargs
                }
                
                # 如果保留情绪，使用同一个音频作为情绪参考
                if preserve_emotion:
                    inference_kwargs['emo_audio_prompt'] = voice_prompt
                    inference_kwargs['emo_alpha'] = max(0.0, min(1.0, emotion_strength))
                
                # 调用TTS推理
                if self.server_mode:
                    # 使用服务器API生成
                    success = generate_tts_via_server(
                        voice_prompt, text, temp_output, self.server_port
                    )
                    if not success:
                        raise Exception("Server TTS generation failed")
                else:
                    # 使用直接推理
                    self.tts.infer(
                        spk_audio_prompt=voice_prompt,
                        text=text,
                        output_path=temp_output,
                        **inference_kwargs
                    )
                audio_files.append(temp_output)
                
                # 如果不处理全部，生成第一个后就退出循环，继续到合并环节
                if not process_all:
                    if verbose:
                        print(f"Generated first segment, proceeding to merge...")
                    break
                
            except Exception as e:
                print(f"Error generating segment {i+1}: {e}")
                # 如果不处理全部且第一个就失败了，继续尝试下一个
                if not process_all and not audio_files:
                    continue
                elif not process_all:
                    break
                else:
                    continue
                
        return audio_files
    
    def merge_audio_files(self, audio_files: List[str], output_path: str, 
                         interval_silence: int = 1000) -> str:
        """
        合并音频文件
        
        Args:
            audio_files: 音频文件路径列表
            output_path: 输出文件路径
            interval_silence: 片段间静音时长(ms)
            
        Returns:
            合并后的音频文件路径
        """
        if not audio_files:
            raise ValueError("No audio files to merge")
            
        if len(audio_files) == 1:
            # 只有一个文件，使用shutil.move()避免跨设备问题
            try:
                shutil.move(audio_files[0], output_path)
                return output_path
            except Exception as e:
                # 如果move失败，使用复制+删除
                try:
                    shutil.copy2(audio_files[0], output_path)
                    os.remove(audio_files[0])
                    return output_path
                except Exception as e2:
                    print(f"Warning: Failed to move/copy file: {e2}")
                    return audio_files[0]
        
        try:
            import torchaudio
            import torch
            
            # 加载所有音频文件
            audio_tensors = []
            sample_rate = None
            
            for audio_file in audio_files:
                waveform, sr = torchaudio.load(audio_file)
                if sample_rate is None:
                    sample_rate = sr
                elif sr != sample_rate:
                    # 重采样到统一采样率
                    resampler = torchaudio.transforms.Resample(sr, sample_rate)
                    waveform = resampler(waveform)
                    
                audio_tensors.append(waveform)
            
            # 插入静音
            silence_samples = int(sample_rate * interval_silence / 1000.0)
            silence_tensor = torch.zeros(audio_tensors[0].shape[0], silence_samples)
            
            # 合并音频
            merged_audio = []
            for i, audio in enumerate(audio_tensors):
                merged_audio.append(audio)
                if i < len(audio_tensors) - 1:  # 不在最后一个片段后添加静音
                    merged_audio.append(silence_tensor)
            
            final_audio = torch.cat(merged_audio, dim=1)
            
            # 保存合并后的音频
            torchaudio.save(output_path, final_audio, sample_rate)
            
            # 清理临时文件
            for audio_file in audio_files:
                try:
                    os.remove(audio_file)
                except OSError:
                    pass
                    
            return output_path
            
        except ImportError:
            print("Warning: torchaudio not available, using first audio file only")
            try:
                shutil.move(audio_files[0], output_path)
            except Exception as e:
                try:
                    shutil.copy2(audio_files[0], output_path)
                    os.remove(audio_files[0])
                except Exception as e2:
                    print(f"Warning: Failed to move/copy file: {e2}")
                    output_path = audio_files[0]
            # 清理其他临时文件
            for audio_file in audio_files[1:]:
                try:
                    os.remove(audio_file)
                except OSError:
                    pass
            return output_path
    
    def generate(self, voice_prompt: str, text: str, output_path: str = None, 
                verbose: bool = False, sleep_ms: int = 1000, process_all: bool = True,
                preserve_emotion: bool = True, emotion_strength: float = 1.0,
                preserve_speed: bool = True, preserve_accent: bool = True,
                **generation_kwargs) -> str:
        """
        生成语音
        
        Args:
            voice_prompt: 声音提示音频路径
            text: 输入文本
            output_path: 输出音频路径
            verbose: 是否显示详细信息
            sleep_ms: 语音片段之间的间隔时长(毫秒)
            process_all: 是否处理所有行
            preserve_emotion: 是否保留原声音的情绪特征
            emotion_strength: 情绪保留强度 (0.0-1.0)
            preserve_speed: 是否保留原声音的语速
            preserve_accent: 是否保留原声音的口音特征
            **generation_kwargs: 传递给TTS推理的额外参数
            
        Returns:
            生成的音频文件路径
        """
        # 解析文本
        text_segments = self.parser.parse_text(text, process_all)
        
        if not text_segments:
            raise ValueError("No valid text segments found")
        
        if verbose:
            print(f"Parsed {len(text_segments)} text segments:")
            for i, segment_text in enumerate(text_segments):
                print(f"  {i+1}. {segment_text}")
        
        # 生成默认输出路径
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"{timestamp}.wav"
        
        # 检查是否需要MP3转换
        needs_mp3_conversion = output_path.lower().endswith('.mp3')
        if needs_mp3_conversion:
            # 先生成WAV文件，然后转换为MP3
            temp_wav_path = output_path.rsplit('.', 1)[0] + '_temp.wav'
            actual_output_path = temp_wav_path
        else:
            actual_output_path = output_path
        
        # 确保输出目录存在
        output_dir = os.path.dirname(actual_output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 生成音频片段
        audio_files = self.generate_audio_segments(
            voice_prompt, text_segments, verbose, process_all,
            preserve_emotion, emotion_strength, preserve_speed, preserve_accent,
            **generation_kwargs
        )
        
        if not audio_files:
            raise RuntimeError("Failed to generate any audio segments")
        
        # 合并音频文件
        wav_output = self.merge_audio_files(audio_files, actual_output_path, sleep_ms)
        
        # 如果需要转换为MP3
        if needs_mp3_conversion:
            if verbose:
                print(f"Converting WAV to MP3: {output_path}")
            try:
                final_output = convert_wav_to_mp3(wav_output, output_path)
            except RuntimeError as e:
                print(f"Warning: MP3 conversion failed: {e}")
                print(f"WAV file saved as: {wav_output}")
                final_output = wav_output
        else:
            final_output = wav_output
        
        if verbose:
            print(f"Audio generation completed: {final_output}")
            
        return final_output


def main():
    parser = argparse.ArgumentParser(
        description="Text-to-Speech Generator for IndexTTS2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python gentts.py                                        # 交互模式，处理一行
  python gentts.py -v ning.wav -t "你好世界！"               # 处理一行文本
  python gentts.py -v ning.wav -f input.txt --all         # 处理文件中所有行
  python gentts.py -v ning.wav -f input.txt               # 只处理文件第一行
  python gentts.py -v ning.wav -t "普通文本" -o output.mp3  # MP3 output (requires ffmpeg)
  python gentts.py -v ning.wav -t "测试文本" --emotion-strength 0.8  # 降低情绪保留强度
  python gentts.py -v ning.wav -t "测试文本" --no-preserve-emotion  # 不保留情绪特征
  python gentts.py -v ning.wav -t "测试文本" --temperature 0.5 --top-p 0.9  # 自定义生成参数

特征保留选项:
  --preserve-emotion / --no-preserve-emotion  # 保留/不保留情绪特征
  --emotion-strength 0.0-1.0                  # 情绪保留强度
  --preserve-speed / --no-preserve-speed      # 保留/不保留语速
  --preserve-accent / --no-preserve-accent    # 保留/不保留口音

注意:
  - 默认保留提供声音文件中的情绪、语速、口音特征
  - 默认只处理第一行文本，使用 --all 参数处理所有行
  - MP3输出需要安装ffmpeg。如果ffmpeg不可用，将保存为WAV格式。
        """
    )
    
    parser.add_argument('-v', '--voice', 
                        help='Voice prompt audio file path (default: ning.wav)')
    parser.add_argument('-t', '--text',
                        help='Input text (default: interactive input)')
    parser.add_argument('-f', '--file',
                        help='Input text file')
    parser.add_argument('-o', '--output',
                        help='Output audio file path (.wav or .mp3, default: timestamp.wav)')
    parser.add_argument('--model-dir', default='checkpoints',
                        help='Model directory path (default: checkpoints)')
    parser.add_argument('--fp16', action='store_true',
                        help='Use FP16 inference (faster, less VRAM)')
    parser.add_argument('--cuda-kernel', action='store_true',
                        help='Use CUDA kernel acceleration')
    parser.add_argument('--deepspeed', action='store_true',
                        help='Use DeepSpeed acceleration')
    parser.add_argument('--verbose', action='store_true',
                        help='Show verbose output')
    parser.add_argument('--sleep', type=int, default=1000,
                        help='Sleep duration in milliseconds between lines (default: 1000)')
    parser.add_argument('--all', action='store_true',
                        help='Process all lines from file/text (default: process only first line)')
    parser.add_argument('--preserve-emotion', action='store_true', default=True,
                        help='Preserve emotion from voice prompt (default: True)')
    parser.add_argument('--no-preserve-emotion', dest='preserve_emotion', action='store_false',
                        help='Do not preserve emotion from voice prompt')
    parser.add_argument('--emotion-strength', type=float, default=1.0,
                        help='Emotion preservation strength (0.0-1.0, default: 1.0)')
    parser.add_argument('--preserve-speed', action='store_true', default=True,
                        help='Preserve speech rate from voice prompt (default: True)')
    parser.add_argument('--no-preserve-speed', dest='preserve_speed', action='store_false',
                        help='Do not preserve speech rate from voice prompt')
    parser.add_argument('--preserve-accent', action='store_true', default=True,
                        help='Preserve accent from voice prompt (default: True)')
    parser.add_argument('--no-preserve-accent', dest='preserve_accent', action='store_false',
                        help='Do not preserve accent from voice prompt')
    
    # TTS generation parameters
    parser.add_argument('--temperature', type=float, default=0.8,
                        help='Temperature for text generation (default: 0.8)')
    parser.add_argument('--top-p', type=float, default=0.8,
                        help='Top-p sampling parameter (default: 0.8)')
    parser.add_argument('--top-k', type=int, default=30,
                        help='Top-k sampling parameter (default: 30)')
    parser.add_argument('--max-mel-tokens', type=int, default=1500,
                        help='Maximum mel tokens to generate (default: 1500)')
    parser.add_argument('--repetition-penalty', type=float, default=10.0,
                        help='Repetition penalty (default: 10.0)')
    
    # Server mode options
    parser.add_argument('--server-mode', action='store_true',
                        help='Use server API instead of direct inference (faster for multiple requests)')
    parser.add_argument('--server-port', type=int, default=5000,
                        help='Server port (default: 5000)')
    
    args = parser.parse_args()
    
    # 默认行为：如果没有提供任何参数，使用默认值
    if not args.voice and not args.text and not args.file:
        args.voice = 'ning.wav'
        args.text = input("请输入要转换的文本: ")
        if not args.text.strip():
            print("Error: No text provided")
            return 1
    
    # 设置默认声音文件
    if not args.voice:
        args.voice = 'ning.wav'
    
    # 验证参数范围
    if not (0.0 <= args.emotion_strength <= 1.0):
        parser.error("emotion-strength must be between 0.0 and 1.0")
    
    if not (0.1 <= args.temperature <= 2.0):
        parser.error("temperature must be between 0.1 and 2.0")
    
    if not (0.0 <= args.top_p <= 1.0):
        parser.error("top-p must be between 0.0 and 1.0")
    
    if args.top_k <= 0:
        parser.error("top-k must be positive")
    
    if args.max_mel_tokens <= 0:
        parser.error("max-mel-tokens must be positive")
    
    if args.repetition_penalty < 1.0:
        parser.error("repetition-penalty must be >= 1.0")
    
    # 检查输入参数
    if not args.text and not args.file:
        args.text = input("请输入要转换的文本: ")
        if not args.text.strip():
            print("Error: No text provided")
            return 1
    
    if args.text and args.file:
        parser.error("Cannot specify both --text and --file")
    
    # 检查声音提示文件
    if not os.path.exists(args.voice):
        parser.error(f"Voice prompt file not found: {args.voice}")
    
    # 检查模型目录
    if not os.path.exists(args.model_dir):
        parser.error(f"Model directory not found: {args.model_dir}")
    
    config_path = os.path.join(args.model_dir, "config.yaml")
    if not os.path.exists(config_path):
        parser.error(f"Config file not found: {config_path}")
    
    try:
        # 获取输入文本
        if args.file:
            if not os.path.exists(args.file):
                parser.error(f"Input file not found: {args.file}")
            with open(args.file, 'r', encoding='utf-8') as f:
                input_text = f.read()
        else:
            input_text = args.text
        
        # 初始化TTS模型
        if args.verbose:
            print("Initializing IndexTTS2 model...")
        
        tts_generator = TTSGenerator(
            model_dir=args.model_dir,
            use_fp16=args.fp16,
            use_cuda_kernel=args.cuda_kernel,
            use_deepspeed=args.deepspeed,
            server_mode=args.server_mode,
            server_port=args.server_port
        )
        
        # 生成音频
        generation_kwargs = {
            'temperature': args.temperature,
            'top_p': args.top_p,
            'top_k': args.top_k,
            'max_mel_tokens': args.max_mel_tokens,
            'repetition_penalty': args.repetition_penalty,
        }
        
        output_path = tts_generator.generate(
            voice_prompt=args.voice,
            text=input_text,
            output_path=args.output,
            verbose=args.verbose,
            sleep_ms=args.sleep,
            process_all=args.all,
            preserve_emotion=args.preserve_emotion,
            emotion_strength=args.emotion_strength,
            preserve_speed=args.preserve_speed,
            preserve_accent=args.preserve_accent,
            **generation_kwargs
        )
        
        print(f"Audio generated successfully: {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())