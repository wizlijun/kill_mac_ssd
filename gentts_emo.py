#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emotional Text-to-Speech Command Line Tool for IndexTTS2

支持的情感文本格式:
(emotion,intensity) 文本内容

支持的情感类型:
- happy: 高兴
- angry: 愤怒
- sad: 悲伤
- afraid: 恐惧
- disgusted: 反感
- melancholic: 低落
- surprised: 惊讶
- calm: 自然/平静

示例:
(happy,0.8) 欢迎大家来体验IndexTTS2！
(surprised,0.6) 哇塞！这个效果也太好了吧！
(calm,0.5) 这是一段平静的叙述文本。

Usage:
python gentts_emo.py -v voice.wav -t "文本" -o output.wav
python gentts_emo.py --server-mode -v voice.wav -t "文本" -o output.wav  # Server mode
python gentts_emo.py -v voice.wav -f input.txt -o output.wav
python gentts_emo.py -v voice.wav -t "文本" -o output.mp3  # MP3 output (requires ffmpeg)
"""

import argparse
import os
import re
import shutil
import subprocess
import time
import requests
import json
from datetime import datetime
from typing import List, Tuple, Dict

try:
    from indextts.infer_v2 import IndexTTS2
except ImportError:
    IndexTTS2 = None  # 服务器模式下不需要直接导入


def check_server_status(port=5000):
    """检查TTS服务器状态"""
    try:
        response = requests.get(f'http://127.0.0.1:{port}/health', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return True, data
        return False, None
    except requests.exceptions.RequestException:
        return False, None


def start_server_if_needed(port=5000):
    """检查并启动TTS服务器（如果需要）"""
    running, status = check_server_status(port)
    if running and status.get('model_loaded', False):
        return True
    
    print("TTS Server not ready, please start it manually:")
    print(f"  uv run python3 server_manager.py start --port {port}")
    return False


def generate_tts_with_server(voice_path, text, output_path, port=5000, emo_vector=None, emo_alpha=0.5):
    """使用服务器模式生成TTS（支持情感向量）"""
    try:
        # 准备请求数据
        files = {'voice_file': open(voice_path, 'rb')}
        data = {
            'text': text,
            'use_random': 'false',
            'verbose': 'false',
            'interval_silence': '200'
        }
        
        # 添加情感参数
        if emo_vector:
            data['emo_vector'] = json.dumps(emo_vector)
        if emo_alpha:
            data['emo_alpha'] = str(emo_alpha)
        
        # 发送生成请求
        response = requests.post(f'http://127.0.0.1:{port}/generate', files=files, data=data, timeout=300)
        files['voice_file'].close()
        
        if response.status_code == 200:
            # 保存生成的音频
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
        else:
            print(f"Server request failed: {response.status_code}")
            try:
                error_info = response.json()
                print(f"Error: {error_info.get('error', 'Unknown error')}")
            except:
                print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"Failed to connect to server: {e}")
        return False
    except Exception as e:
        print(f"Error in server request: {e}")
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


class EmotionalTextParser:
    """情感文本解析器"""
    
    EMOTION_MAP = {
        'happy': 'happy',
        'angry': 'angry', 
        'sad': 'sad',
        'afraid': 'afraid',
        'disgusted': 'disgusted',
        'melancholic': 'melancholic',
        'surprised': 'surprised',
        'calm': 'calm'
    }
    
    def __init__(self):
        # 匹配格式: (emotion,intensity) 文本内容
        self.pattern = re.compile(r'\((\w+),(\d*\.?\d+)\)\s*(.+)')
    
    def parse_line(self, line: str) -> Tuple[str, float, str]:
        """
        解析单行情感文本
        
        Args:
            line: 输入文本行
            
        Returns:
            (emotion, intensity, text) 或 (None, None, text) 如果没有情感标记
        """
        line = line.strip()
        if not line:
            return None, None, ""
            
        match = self.pattern.match(line)
        if match:
            emotion, intensity_str, text = match.groups()
            emotion = emotion.lower()
            
            if emotion not in self.EMOTION_MAP:
                print(f"Warning: Unknown emotion '{emotion}', using 'calm' instead")
                emotion = 'calm'
                
            try:
                intensity = float(intensity_str)
                intensity = max(0.0, min(1.0, intensity))  # 限制在0-1范围
            except ValueError:
                print(f"Warning: Invalid intensity '{intensity_str}', using 0.5")
                intensity = 0.5
                
            return emotion, intensity, text.strip()
        else:
            # 没有情感标记，使用默认calm情感
            return 'calm', 0.5, line
    
    def parse_text(self, text: str, process_all: bool = True) -> List[Tuple[str, float, str]]:
        """
        解析多行情感文本
        
        Args:
            text: 多行输入文本
            process_all: 是否处理所有行，如果为False则只处理第一行
            
        Returns:
            List of (emotion, intensity, text) tuples
        """
        lines = text.split('\n')
        results = []
        
        for line in lines:
            emotion, intensity, parsed_text = self.parse_line(line)
            if parsed_text:  # 只添加非空文本
                results.append((emotion, intensity, parsed_text))
                if not process_all:  # 如果不处理全部，只处理第一行
                    break
                
        return results
    
    def create_emotion_vector(self, emotion: str, intensity: float) -> List[float]:
        """
        根据情感类型和强度创建情感向量
        
        Args:
            emotion: 情感类型
            intensity: 情感强度 (0.0-1.0)
            
        Returns:
            8维情感向量 [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
        """
        # 初始化所有情感为0
        vector = [0.0] * 8
        
        # 情感索引映射
        emotion_indices = {
            'happy': 0,
            'angry': 1,
            'sad': 2,
            'afraid': 3,
            'disgusted': 4,
            'melancholic': 5,
            'surprised': 6,
            'calm': 7
        }
        
        if emotion in emotion_indices:
            vector[emotion_indices[emotion]] = intensity
        else:
            # 默认使用calm
            vector[7] = 0.5
            
        return vector


class EmotionalTTS:
    """情感TTS生成器"""
    
    def __init__(self, model_dir="checkpoints", use_fp16=False, use_cuda_kernel=False, use_deepspeed=False, 
                 server_mode=False, server_port=5000):
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
        self.parser = EmotionalTextParser()
        
        if server_mode:
            print("Using server API mode for TTS generation")
            if not start_server_if_needed(server_port):
                raise RuntimeError("Failed to start or connect to IndexTTS2 server")
        else:
            if IndexTTS2 is None:
                raise ImportError("IndexTTS2 not available. Use server mode or install required dependencies.")
            cfg_path = os.path.join(model_dir, "config.yaml")
            self.tts = IndexTTS2(
                cfg_path=cfg_path,
                model_dir=model_dir,
                use_fp16=use_fp16,
                use_cuda_kernel=use_cuda_kernel,
                use_deepspeed=use_deepspeed
            )
    
    def generate_audio_segments(self, voice_prompt: str, text_segments: List[Tuple[str, float, str]], 
                              verbose: bool = False, process_all: bool = True) -> List[str]:
        """
        生成音频片段
        
        Args:
            voice_prompt: 声音提示音频路径
            text_segments: 解析后的文本片段列表
            verbose: 是否显示详细信息
            process_all: 是否处理所有片段
            
        Returns:
            生成的音频文件路径列表
        """
        audio_files = []
        
        for i, (emotion, intensity, text) in enumerate(text_segments):
            if verbose:
                print(f"Generating segment {i+1}/{len(text_segments)}: ({emotion},{intensity}) {text}")
            
            # 创建情感向量
            emo_vector = self.parser.create_emotion_vector(emotion, intensity)
            
            # 生成临时文件名
            temp_output = f"temp_segment_{i+1}_{int(time.time())}.wav"
            
            try:
                if self.server_mode:
                    # 使用服务器模式
                    success = generate_tts_with_server(
                        voice_path=voice_prompt,
                        text=text,
                        output_path=temp_output,
                        port=self.server_port,
                        emo_vector=emo_vector,
                        emo_alpha=intensity
                    )
                    if success:
                        audio_files.append(temp_output)
                    else:
                        print(f"Error generating segment {i+1} with server")
                        if not process_all and not audio_files:
                            continue
                        elif not process_all:
                            break
                        else:
                            continue
                else:
                    # 直接推理模式
                    self.tts.infer(
                        spk_audio_prompt=voice_prompt,
                        text=text,
                        output_path=temp_output,
                        emo_vector=emo_vector,
                        emo_alpha=intensity,
                        use_random=False,
                        verbose=verbose,
                        interval_silence=200  # 片段间静音200ms
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
                verbose: bool = False, sleep_ms: int = 1000, process_all: bool = True) -> str:
        """
        生成情感语音
        
        Args:
            voice_prompt: 声音提示音频路径
            text: 输入文本(支持情感标记)
            output_path: 输出音频路径
            verbose: 是否显示详细信息
            sleep_ms: 语音片段之间的间隔时长(毫秒)
            process_all: 是否处理所有行
            
        Returns:
            生成的音频文件路径
        """
        # 解析文本
        text_segments = self.parser.parse_text(text, process_all)
        
        if not text_segments:
            raise ValueError("No valid text segments found")
        
        if verbose:
            print(f"Parsed {len(text_segments)} text segments:")
            for i, (emotion, intensity, segment_text) in enumerate(text_segments):
                print(f"  {i+1}. ({emotion},{intensity}) {segment_text}")
        
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
        audio_files = self.generate_audio_segments(voice_prompt, text_segments, verbose, process_all)
        
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
        description="Emotional Text-to-Speech Generator for IndexTTS2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
情感文本格式示例:
  (happy,0.8) 欢迎大家来体验IndexTTS2！
  (surprised,0.6) 哇塞！这个效果也太好了吧！
  (calm,0.5) 这是一段平静的叙述文本。

支持的情感类型:
  happy, angry, sad, afraid, disgusted, melancholic, surprised, calm

使用示例:
  python gentts_emo.py                                        # 交互模式，处理一行
  python gentts_emo.py -v ning.wav -t "(happy,0.8) 你好世界！"  # 处理一行文本
  python gentts_emo.py --server-mode -v ning.wav -t "(happy,0.8) 你好世界！"  # 服务器模式
  python gentts_emo.py -v ning.wav -f input.txt --all         # 处理文件中所有行
  python gentts_emo.py -v ning.wav -f input.txt               # 只处理文件第一行
  python gentts_emo.py -v ning.wav -t "普通文本" -o output.mp3  # MP3 output (requires ffmpeg)

注意:
  - 默认只处理第一行文本，使用 --all 参数处理所有行
  - 使用 --server-mode 可以避免重复加载模型，提高性能
  - MP3输出需要安装ffmpeg。如果ffmpeg不可用，将保存为WAV格式。
        """
    )
    
    parser.add_argument('-v', '--voice', 
                        help='Voice prompt audio file path (default: ning.wav)')
    parser.add_argument('-t', '--text',
                        help='Input text with emotion markup (default: interactive input)')
    parser.add_argument('-f', '--file',
                        help='Input text file with emotion markup')
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
    parser.add_argument('--server-mode', action='store_true',
                        help='Use server mode for TTS generation (faster, no model reloading)')
    parser.add_argument('--server-port', type=int, default=5000,
                        help='TTS server port (default: 5000)')
    parser.add_argument('--verbose', action='store_true',
                        help='Show verbose output')
    parser.add_argument('--sleep', type=int, default=1000,
                        help='Sleep duration in milliseconds between lines (default: 1000)')
    parser.add_argument('--all', action='store_true',
                        help='Process all lines from file/text (default: process only first line)')
    
    args = parser.parse_args()
    
    # 默认行为：如果没有提供任何参数，使用默认值
    if not args.voice and not args.text and not args.file:
        args.voice = 'ning.wav'
        args.text = input("请输入要转换的文本 (支持情感标记): ")
        if not args.text.strip():
            print("Error: No text provided")
            return 1
    
    # 设置默认声音文件
    if not args.voice:
        args.voice = 'ning.wav'
    
    # 检查输入参数
    if not args.text and not args.file:
        args.text = input("请输入要转换的文本 (支持情感标记): ")
        if not args.text.strip():
            print("Error: No text provided")
            return 1
    
    if args.text and args.file:
        parser.error("Cannot specify both --text and --file")
    
    # 检查声音提示文件
    if not os.path.exists(args.voice):
        parser.error(f"Voice prompt file not found: {args.voice}")
    
    # 检查模型目录（仅在非服务器模式下检查）
    if not args.server_mode:
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
            mode_str = "server mode" if args.server_mode else "direct inference mode"
            print(f"Initializing IndexTTS2 model in {mode_str}...")
        
        tts_generator = EmotionalTTS(
            model_dir=args.model_dir,
            use_fp16=args.fp16,
            use_cuda_kernel=args.cuda_kernel,
            use_deepspeed=args.deepspeed,
            server_mode=args.server_mode,
            server_port=args.server_port
        )
        
        # 生成音频
        output_path = tts_generator.generate(
            voice_prompt=args.voice,
            text=input_text,
            output_path=args.output,
            verbose=args.verbose,
            sleep_ms=args.sleep,
            process_all=args.all
        )
        
        print(f"Audio generated successfully: {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())