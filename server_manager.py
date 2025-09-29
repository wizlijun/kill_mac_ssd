#!/usr/bin/env python3
"""
IndexTTS2 Server 管理脚本
便捷地启动、停止、检查TTS服务器状态
"""

import os
import sys
import time
import subprocess
import requests

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

def start_server(port=5000, daemon=True):
    """启动服务器"""
    print(f"Starting IndexTTS2 Server on port {port}...")
    
    # 检查服务器是否已运行
    running, status = check_server_status(port)
    if running:
        print(f"✓ Server already running (PID: {status['pid']})")
        return True
    
    # 启动服务器
    script_path = os.path.join(os.path.dirname(__file__), 'indextts2server.py')
    
    if daemon:
        # 后台运行，使用uv环境
        process = subprocess.Popen([
            'uv', 'run', 'python3', script_path, '--port', str(port)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待服务器启动，增加等待时间到60秒（模型加载需要较长时间）
        for i in range(60):
            time.sleep(1)
            running, status = check_server_status(port)
            if running and status and status.get('model_loaded', False):
                print(f"✓ Server started successfully (PID: {status['pid']}, Model loaded: True)")
                return True
            elif running:
                print(f"  Server starting, model loading... ({i+1}/60)")
            else:
                print(f"  Waiting for server startup... ({i+1}/60)")
        
        print("✗ Server failed to start within 60 seconds")
        return False
    else:
        # 前台运行，使用uv环境
        subprocess.run(['uv', 'run', 'python3', script_path, '--port', str(port)])
        return True

def stop_server(port=5000):
    """停止服务器"""
    print("Stopping IndexTTS2 Server...")
    
    # 检查服务器状态
    running, status = check_server_status(port)
    if not running:
        print("✗ Server not running")
        return False
    
    # 发送关闭请求
    try:
        response = requests.post(f'http://127.0.0.1:{port}/shutdown', timeout=5)
        if response.status_code == 200:
            print("✓ Server shutdown signal sent")
            
            # 等待服务器关闭
            for i in range(10):
                time.sleep(1)
                running, _ = check_server_status(port)
                if not running:
                    print("✓ Server stopped successfully")
                    return True
            
            print("⚠ Server may still be running")
            return False
        else:
            print(f"✗ Failed to send shutdown signal: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to connect to server: {e}")
        return False

def show_status(port=5000):
    """显示服务器状态"""
    running, status = check_server_status(port)
    if running:
        print(f"✓ IndexTTS2 Server is running")
        print(f"  PID: {status['pid']}")
        print(f"  Port: {port}")
        print(f"  Model loaded: {status['model_loaded']}")
        print(f"  URL: http://127.0.0.1:{port}")
    else:
        print("✗ IndexTTS2 Server is not running")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='IndexTTS2 Server Manager')
    parser.add_argument('--port', type=int, default=5000, help='Server port (default: 5000)')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start the server')
    start_parser.add_argument('--foreground', action='store_true', help='Run in foreground')
    
    # Stop command
    subparsers.add_parser('stop', help='Stop the server')
    
    # Status command
    subparsers.add_parser('status', help='Check server status')
    
    # Restart command
    subparsers.add_parser('restart', help='Restart the server')
    
    args = parser.parse_args()
    
    if args.command == 'start':
        success = start_server(args.port, daemon=not args.foreground)
        sys.exit(0 if success else 1)
    
    elif args.command == 'stop':
        success = stop_server(args.port)
        sys.exit(0 if success else 1)
    
    elif args.command == 'status':
        show_status(args.port)
    
    elif args.command == 'restart':
        print("Restarting IndexTTS2 Server...")
        stop_server(args.port)
        time.sleep(2)
        success = start_server(args.port)
        sys.exit(0 if success else 1)
    
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python server_manager.py start          # Start server in background")
        print("  python server_manager.py start --foreground  # Start server in foreground")
        print("  python server_manager.py stop           # Stop server")
        print("  python server_manager.py status         # Check status")
        print("  python server_manager.py restart        # Restart server")

if __name__ == '__main__':
    main()