#!/usr/bin/env python3
"""
IndexTTS2 Server - 持续运行的TTS服务
避免重复加载模型，提供HTTP API接口
"""

import os
import sys
import json
import time
import signal
import psutil
import threading
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import tempfile
import uuid
import shutil

# 添加项目路径
sys.path.insert(0, '/Volumes/Disk/index-tts2')

# 导入TTS模块
try:
    from indextts.infer_v2 import IndexTTS2
    print("✓ Successfully imported IndexTTS2")
except ImportError as e:
    print(f"✗ Failed to import IndexTTS2: {e}")
    sys.exit(1)

class IndexTTS2Server:
    def __init__(self, port=5000):
        self.port = port
        self.pid_file = '/tmp/indextts2server.pid'
        self.model = None
        self.model_loaded = False
        self.lock = threading.Lock()
        
        # Flask app
        self.app = Flask(__name__)
        self.setup_routes()
        
    def check_existing_server(self):
        """检查是否已有服务运行"""
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # 检查进程是否存在
                if psutil.pid_exists(old_pid):
                    try:
                        proc = psutil.Process(old_pid)
                        if 'indextts2server' in ' '.join(proc.cmdline()):
                            print(f"✗ IndexTTS2 Server already running (PID: {old_pid})")
                            print(f"  Use 'kill {old_pid}' to stop the existing server")
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # 清理无效的PID文件
                os.remove(self.pid_file)
            except (ValueError, FileNotFoundError):
                pass
        
        return False
    
    def write_pid_file(self):
        """写入PID文件"""
        with open(self.pid_file, 'w') as f:
            f.write(str(os.getpid()))
        print(f"✓ Server PID: {os.getpid()}")
    
    def cleanup_pid_file(self):
        """清理PID文件"""
        try:
            os.remove(self.pid_file)
        except FileNotFoundError:
            pass
    
    def load_model(self):
        """加载TTS模型"""
        with self.lock:
            if not self.model_loaded:
                print("Loading IndexTTS2 model...")
                start_time = time.time()
                try:
                    self.model = IndexTTS2()
                    self.model_loaded = True
                    load_time = time.time() - start_time
                    print(f"✓ Model loaded successfully in {load_time:.2f}s")
                    return True
                except Exception as e:
                    print(f"✗ Failed to load model: {e}")
                    return False
            return True
    
    def setup_routes(self):
        """设置Flask路由"""
        
        @self.app.route('/health', methods=['GET'])
        def health_check():
            """健康检查"""
            return jsonify({
                'status': 'ok',
                'model_loaded': self.model_loaded,
                'pid': os.getpid()
            })
        
        @self.app.route('/generate', methods=['POST'])
        def generate_tts():
            """生成TTS（支持情感向量）"""
            try:
                # 检查模型是否加载
                if not self.model_loaded:
                    if not self.load_model():
                        return jsonify({'error': 'Model not loaded'}), 500
                
                # 检查请求类型
                if request.content_type and 'multipart/form-data' in request.content_type:
                    # Form data 请求 (用于文件上传)
                    if 'voice_file' not in request.files:
                        return jsonify({'error': 'No voice file provided'}), 400
                    
                    voice_file = request.files['voice_file']
                    if voice_file.filename == '':
                        return jsonify({'error': 'No voice file selected'}), 400
                    
                    # 保存临时voice文件
                    temp_voice_path = os.path.join(tempfile.gettempdir(), f"voice_{uuid.uuid4().hex}.wav")
                    voice_file.save(temp_voice_path)
                    
                    # 获取其他参数
                    text = request.form.get('text')
                    use_random = request.form.get('use_random', 'false').lower() == 'true'
                    verbose = request.form.get('verbose', 'false').lower() == 'true'
                    interval_silence = int(request.form.get('interval_silence', '200'))
                    
                    # 情感参数
                    emo_vector_str = request.form.get('emo_vector')
                    emo_alpha = float(request.form.get('emo_alpha', '0.5'))
                    
                    emo_vector = None
                    if emo_vector_str:
                        try:
                            emo_vector = json.loads(emo_vector_str)
                        except json.JSONDecodeError:
                            return jsonify({'error': 'Invalid emo_vector JSON format'}), 400
                    
                else:
                    # JSON 请求 (兼容性)
                    data = request.get_json()
                    if not data:
                        return jsonify({'error': 'No JSON data provided'}), 400
                    
                    temp_voice_path = data.get('voice_file')
                    text = data.get('text')
                    use_random = data.get('use_random', False)
                    verbose = data.get('verbose', False)
                    interval_silence = data.get('interval_silence', 200)
                    emo_vector = data.get('emo_vector')
                    emo_alpha = data.get('emo_alpha', 0.5)
                    
                    if not os.path.exists(temp_voice_path):
                        return jsonify({'error': f'Voice file not found: {temp_voice_path}'}), 400
                
                if not text:
                    return jsonify({'error': 'No text provided'}), 400
                
                print(f"Generating TTS: {text[:50]}...")
                if emo_vector:
                    print(f"  Emotion vector: {emo_vector}, alpha: {emo_alpha}")
                start_time = time.time()
                
                # 生成临时输出文件
                temp_output = os.path.join(tempfile.gettempdir(), f"output_{uuid.uuid4().hex}.wav")
                
                # 生成TTS
                with self.lock:
                    kwargs = {
                        'spk_audio_prompt': temp_voice_path,
                        'text': text,
                        'output_path': temp_output,
                        'use_random': use_random,
                        'verbose': verbose,
                        'interval_silence': interval_silence
                    }
                    
                    # 添加情感参数（如果提供）
                    if emo_vector:
                        kwargs['emo_vector'] = emo_vector
                        kwargs['emo_alpha'] = emo_alpha
                    
                    self.model.infer(**kwargs)
                
                generation_time = time.time() - start_time
                
                # 清理临时voice文件（如果是上传的）
                if request.content_type and 'multipart/form-data' in request.content_type:
                    try:
                        os.remove(temp_voice_path)
                    except OSError:
                        pass
                
                # 检查输出文件是否生成
                if os.path.exists(temp_output):
                    file_size = os.path.getsize(temp_output)
                    print(f"✓ TTS generated: {file_size} bytes, {generation_time:.2f}s")
                    
                    # 返回音频文件
                    return send_file(temp_output, as_attachment=True, download_name='generated.wav', mimetype='audio/wav')
                else:
                    return jsonify({'error': 'Failed to generate audio file'}), 500
                    
            except Exception as e:
                print(f"Error in TTS generation: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/shutdown', methods=['POST'])
        def shutdown():
            """关闭服务"""
            print("Received shutdown request")
            threading.Thread(target=self.shutdown_server).start()
            return jsonify({'message': 'Server shutting down...'})
    
    def shutdown_server(self):
        """关闭服务器"""
        time.sleep(1)  # 给响应时间
        self.cleanup_pid_file()
        os.kill(os.getpid(), signal.SIGTERM)
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\nReceived signal {signum}, shutting down...")
        self.cleanup_pid_file()
        sys.exit(0)
    
    def run(self):
        """运行服务器"""
        # 检查现有服务
        if self.check_existing_server():
            sys.exit(1)
        
        # 写入PID文件
        self.write_pid_file()
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        print(f"Starting IndexTTS2 Server on port {self.port}...")
        print("API Endpoints:")
        print(f"  GET  http://localhost:{self.port}/health")
        print(f"  POST http://localhost:{self.port}/generate")
        print(f"  POST http://localhost:{self.port}/shutdown")
        print("\nPress Ctrl+C to stop the server")
        
        try:
            # 预加载模型
            print("\nPre-loading model...")
            if self.load_model():
                print("Model ready for requests!")
            else:
                print("Warning: Model failed to load, will retry on first request")
            
            # 启动Flask服务器
            self.app.run(
                host='127.0.0.1',
                port=self.port,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            print(f"Server error: {e}")
            self.cleanup_pid_file()
            sys.exit(1)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='IndexTTS2 Server')
    parser.add_argument('--port', type=int, default=5000, help='Server port (default: 5000)')
    parser.add_argument('--stop', action='store_true', help='Stop running server')
    parser.add_argument('--status', action='store_true', help='Check server status')
    
    args = parser.parse_args()
    
    if args.stop:
        # 停止服务器
        pid_file = '/tmp/indextts2server.pid'
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                print(f"✓ Server stopped (PID: {pid})")
            except (ValueError, ProcessLookupError):
                print("✗ Server not running or already stopped")
                try:
                    os.remove(pid_file)
                except FileNotFoundError:
                    pass
        else:
            print("✗ Server not running")
        return
    
    if args.status:
        # 检查服务器状态
        import requests
        try:
            response = requests.get(f'http://127.0.0.1:{args.port}/health', timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Server running (PID: {data['pid']}, Model loaded: {data['model_loaded']})")
            else:
                print("✗ Server not responding")
        except requests.exceptions.RequestException:
            print("✗ Server not running")
        return
    
    # 启动服务器
    server = IndexTTS2Server(port=args.port)
    server.run()

if __name__ == '__main__':
    main()