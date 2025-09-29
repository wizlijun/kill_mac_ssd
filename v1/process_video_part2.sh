#!/bin/bash

# 严格模式，任何命令失败则脚本退出
set -e

# 激活虚拟环境
if [ -f "venv311/bin/activate" ]; then
    echo "激活虚拟环境: venv311"
    source venv311/bin/activate
else
    echo "警告：未找到venv311虚拟环境，使用系统Python"
fi

# --- 默认配置 ---
DEFAULT_VOICE_FILE="bruce.wav"  # IndexTTS使用的默认参考语音文件
DEFAULT_SPEECH_RATE="1.5"  # TTS语速倍数
SUBTITLE_MARGIN_V=50
PRESERVE_BACKGROUND=true  # 是否保留原视频背景音
BACKGROUND_VOLUME=0.2    # 背景音音量 (0.0-1.0)
VOICE_VOLUME=1.0      # 中文配音音量（避免破音）
BACKGROUND_METHOD="karaoke"  # 背景音提取方法: auto, stereo, karaoke, center_channel, frequency, original
SUBTITLE_FONT="AiDianFengYaHeiChangTi"  # 字幕字体
DEFAULT_SUBTITLE_SIZE=15  # 默认字幕大小
SATURATION=1.2           # 饱和度调整 (1.0=原始, >1.0增强, <1.0降低)

# --- 脚本开始 ---

# --- 解析命令行参数 ---
show_help() {
    echo "用法: $0 [选项] <视频文件名或文件ID>"
    echo ""
    echo "选项:"
    echo "  --olang LANG          设置TTS语言 (默认: zh)"
    echo "  -v, --voice FILE       设置参考语音文件 (默认: bruce.wav)"
    echo "  -s, --speed RATE       设置语速倍数 (默认: 1.5)"
    echo "  --fsize SIZE          设置字幕字体大小 (默认: 15)"
    echo "  -hd                   处理高清视频文件"
    echo "  -h, --help            显示帮助信息"
    echo ""
    echo "视频文件输入说明:"
    echo "  支持完整文件名: video.mp4, video_hd.mp4, video_hd_video.webm"
    echo "  支持文件ID: video_1751525030_5107 (自动查找匹配的视频文件)"
    echo "  HD模式下优先查找: *_hd_video.webm, *_hd.mp4 等高清文件"
    echo "  普通模式下优先查找: *_video.webm, *.mp4 等标准文件"
    echo ""
    echo "示例:"
    echo "  $0 video.mp4                        # 使用完整文件名"
    echo "  $0 video_1751525030_5107            # 使用文件ID（自动查找）"
    echo "  $0 -hd video_1751525030_5107        # HD模式处理文件ID"
    echo "  $0 -v female.wav video.mp4         # 使用指定语音文件"
    echo "  $0 -s 2.0 video.mp4                # 使用2倍语速"
    echo "  $0 --fsize 20 video.mp4            # 使用20号字体大小"
    echo "  $0 -v male.wav -s 1.8 --fsize 18 -hd video_1751525030_5107  # 完整参数示例"
}

# 初始化变量
TTS_LANGUAGE="zh"
VOICE_FILE="$DEFAULT_VOICE_FILE"
SPEECH_RATE="$DEFAULT_SPEECH_RATE"
SUBTITLE_SIZE="$DEFAULT_SUBTITLE_SIZE"
HD_MODE=false
INPUT_VIDEO=""

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --olang)
            TTS_LANGUAGE="$2"
            shift 2
            ;;
        -v|--voice)
            VOICE_FILE="$2"
            # 检查语音文件路径：当前目录、index-tts子目录、../index-tts目录
            if [ ! -f "$VOICE_FILE" ] && [ ! -f "index-tts/$VOICE_FILE" ] && [ ! -f "../index-tts/$VOICE_FILE" ]; then
                echo "错误：语音文件 $VOICE_FILE 不存在"
                exit 1
            fi
            shift 2
            ;;
        -s|--speed)
            SPEECH_RATE="$2"
            # 验证语速是否为有效数字
            if ! [[ "$SPEECH_RATE" =~ ^[0-9]+\.?[0-9]*$ ]] || (( $(echo "$SPEECH_RATE <= 0" | bc -l) )); then
                echo "错误：语速倍数必须是大于0的数字"
                exit 1
            fi
            shift 2
            ;;
        --fsize)
            SUBTITLE_SIZE="$2"
            # 验证字体大小是否为有效数字
            if ! [[ "$SUBTITLE_SIZE" =~ ^[0-9]+$ ]] || [ "$SUBTITLE_SIZE" -lt 1 ]; then
                echo "错误：字体大小必须是大于0的整数"
                exit 1
            fi
            shift 2
            ;;
        -hd)
            HD_MODE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo "未知选项: $1"
            show_help
            exit 1
            ;;
        *)
            if [ -z "$INPUT_VIDEO" ]; then
                INPUT_VIDEO="$1"
            else
                echo "错误：只能指定一个视频文件"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 检查输入参数
if [ -z "$INPUT_VIDEO" ]; then
    echo "错误：请提供一个视频文件名作为参数。"
    show_help
    exit 1
fi

# 智能查找视频文件
ORIGINAL_INPUT="$INPUT_VIDEO"
FOUND_VIDEO_FILE=""

# 如果输入的文件直接存在，使用它
if [ -f "$INPUT_VIDEO" ] && [ -s "$INPUT_VIDEO" ]; then
    FOUND_VIDEO_FILE="$INPUT_VIDEO"
    echo "✓ 找到指定的视频文件: $INPUT_VIDEO"
else
    echo "🔍 智能查找视频文件: $INPUT_VIDEO"
    
    # 获取基础文件名（移除可能的扩展名）
    BASE_NAME="${INPUT_VIDEO%.*}"
    
    # 定义查找模式的优先级
    if [ "$HD_MODE" = true ]; then
        # HD模式：优先查找HD视频文件
        SEARCH_PATTERNS=(
            "${BASE_NAME}_hd_video.webm"
            "${BASE_NAME}_hd.mp4"
            "${BASE_NAME}_hd.mkv"
            "${BASE_NAME}_hd.webm"
            "${BASE_NAME}_video.webm"
            "${BASE_NAME}.mp4"
            "${BASE_NAME}.mkv"
            "${BASE_NAME}.webm"
            "${BASE_NAME}.mov"
        )
    else
        # 普通模式：优先查找普通视频文件
        SEARCH_PATTERNS=(
            "${BASE_NAME}_video.webm"
            "${BASE_NAME}.mp4"
            "${BASE_NAME}.mkv"
            "${BASE_NAME}.webm"
            "${BASE_NAME}.mov"
            "${BASE_NAME}_hd_video.webm"
            "${BASE_NAME}_hd.mp4"
            "${BASE_NAME}_hd.mkv"
            "${BASE_NAME}_hd.webm"
        )
    fi
    
    # 按优先级查找视频文件
    for pattern in "${SEARCH_PATTERNS[@]}"; do
        if [ -f "$pattern" ] && [ -s "$pattern" ]; then
            FOUND_VIDEO_FILE="$pattern"
            echo "✓ 找到匹配的视频文件: $pattern"
            break
        fi
    done
    
    if [ -z "$FOUND_VIDEO_FILE" ]; then
        echo "❌ 错误：找不到匹配的视频文件"
        echo "尝试查找的文件模式："
        for pattern in "${SEARCH_PATTERNS[@]}"; do
            echo "  - $pattern"
        done
        echo ""
        echo "请确保视频文件存在，或提供完整的文件名（包含扩展名）"
        exit 1
    fi
fi

# 更新INPUT_VIDEO为找到的实际文件
INPUT_VIDEO="$FOUND_VIDEO_FILE"
BASENAME=$(basename "${INPUT_VIDEO%.*}")
OUTPUT_VIDEO="${BASENAME}_final.mp4"

# 检查是否存在分离下载的音频文件
SEPARATE_AUDIO_FILE=""
AUDIO_BASE_NAME=$(basename "${INPUT_VIDEO%.*}")

# 改进的分离音频文件检测逻辑
if [[ "$INPUT_VIDEO" == *"_video.webm" ]]; then
    # 如果输入是普通分离视频文件，查找对应的音频文件
    AUDIO_BASE_NAME=$(basename "${INPUT_VIDEO%_video.webm}")
    SEPARATE_AUDIO_FILE="${AUDIO_BASE_NAME}_audio.webm"
elif [[ "$INPUT_VIDEO" == *"_hd_video.webm" ]]; then
    # 如果输入是HD分离视频文件，查找对应的音频文件
    AUDIO_BASE_NAME=$(basename "${INPUT_VIDEO%_hd_video.webm}")
    SEPARATE_AUDIO_FILE="${AUDIO_BASE_NAME}_hd_audio.webm"
else
    # 根据HD模式和文件名智能查找音频文件
    AUDIO_BASE_NAME=$(basename "${INPUT_VIDEO%.*}")
    
    # 移除可能的_hd后缀来获取基础名称
    BASE_NAME_CLEAN=$(echo "$AUDIO_BASE_NAME" | sed 's/_hd$//')
    
    if [ "$HD_MODE" = true ]; then
        # HD模式：优先查找HD音频文件
        SEARCH_PATTERNS=(
            "${AUDIO_BASE_NAME}_hd_audio.webm"
            "${BASE_NAME_CLEAN}_hd_audio.webm"
            "${AUDIO_BASE_NAME}_audio.webm"
            "${BASE_NAME_CLEAN}_audio.webm"
        )
    else
        # 普通模式：优先查找普通音频文件
        SEARCH_PATTERNS=(
            "${AUDIO_BASE_NAME}_audio.webm"
            "${BASE_NAME_CLEAN}_audio.webm"
            "${AUDIO_BASE_NAME}_hd_audio.webm"
            "${BASE_NAME_CLEAN}_hd_audio.webm"
        )
    fi
    
    # 按优先级查找音频文件
    for pattern in "${SEARCH_PATTERNS[@]}"; do
        if [ -f "$pattern" ]; then
            SEPARATE_AUDIO_FILE="$pattern"
            break
        fi
    done
fi

# 检查是否存在HD版本的视频文件，优先使用HD版本进行合成
ACTUAL_VIDEO="$INPUT_VIDEO"
BASE_NAME_NO_EXT=$(basename "${INPUT_VIDEO%.*}")

# 移除可能的_hd后缀来获取基础名称
if [[ "$BASE_NAME_NO_EXT" == *"_hd" ]]; then
    CLEAN_BASE_NAME="${BASE_NAME_NO_EXT%_hd}"
else
    CLEAN_BASE_NAME="$BASE_NAME_NO_EXT"
fi

EXTENSION="${INPUT_VIDEO##*.}"

# 定义HD文件搜索模式，按优先级排序
HD_SEARCH_PATTERNS=(
    "${CLEAN_BASE_NAME}_hd.mp4"
    "${CLEAN_BASE_NAME}_hd.mkv"
    "${CLEAN_BASE_NAME}_hd.webm"
    "${CLEAN_BASE_NAME}_hd.mov"
)

# 搜索HD文件
HD_VIDEO_FILE=""
for pattern in "${HD_SEARCH_PATTERNS[@]}"; do
    if [ -f "$pattern" ] && [ -s "$pattern" ]; then
        HD_VIDEO_FILE="$pattern"
        break
    fi
done

# 决定使用哪个视频文件
if [ -n "$HD_VIDEO_FILE" ]; then
    if [ "$HD_VIDEO_FILE" != "$INPUT_VIDEO" ]; then
        echo "🔍 检测到HD视频文件，优先使用: $HD_VIDEO_FILE"
        ACTUAL_VIDEO="$HD_VIDEO_FILE"
        # 更新BASENAME以使用HD版本
        BASENAME=$(basename "${HD_VIDEO_FILE%.*}")
        OUTPUT_VIDEO="${BASENAME}_final.mp4"
    else
        echo "✅ 使用HD视频文件进行处理: $INPUT_VIDEO"
    fi
else
    echo "📝 未找到HD视频文件，使用普通视频文件进行处理: $INPUT_VIDEO"
fi

# 临时文件定义（基于原始输入视频的basename，保持兼容性）
ORIGINAL_BASENAME=$(basename "${INPUT_VIDEO%.*}")

# 标准化临时目录名：移除所有视频相关后缀以确保目录共享
# 移除 _hd_video, _video, _hd 等后缀，获取基础文件名
TEMP_BASE_NAME="$ORIGINAL_BASENAME"
if [[ "$TEMP_BASE_NAME" == *"_hd_video" ]]; then
    TEMP_BASE_NAME="${TEMP_BASE_NAME%_hd_video}"
elif [[ "$TEMP_BASE_NAME" == *"_video" ]]; then
    TEMP_BASE_NAME="${TEMP_BASE_NAME%_video}"
elif [[ "$TEMP_BASE_NAME" == *"_hd" ]]; then
    TEMP_BASE_NAME="${TEMP_BASE_NAME%_hd}"
fi

TEMP_DIR="$(pwd)/${TEMP_BASE_NAME}_temp"
echo "使用临时目录: $TEMP_DIR"
# 优先使用翻译文件，如果不存在则使用优化文件
TRANSLATED_SRT="$TEMP_DIR/step3.5_translated.srt"
if [ ! -f "$TRANSLATED_SRT" ]; then
    TRANSLATED_SRT="$TEMP_DIR/step3_optimized.srt"
fi
CHINESE_AUDIO="$TEMP_DIR/step5_chinese_audio.wav"
VIDEO_WITH_AUDIO="$TEMP_DIR/step6_with_audio.mp4"

# 检查必要的文件是否存在
if [ ! -d "$TEMP_DIR" ]; then
    echo "错误：临时目录 $TEMP_DIR 不存在。"
    echo "请先运行第一阶段脚本: ./process_video_part1.sh $INPUT_VIDEO"
    exit 1
fi

if [ ! -f "$TRANSLATED_SRT" ]; then
    echo "错误：SRT文件 $TRANSLATED_SRT 不存在。"
    echo "请先运行第一阶段脚本: ./process_video_part1.sh $INPUT_VIDEO"
    echo "然后手动翻译生成的 $TRANSLATED_SRT 文件"
    exit 1
fi

echo "4步骤视频后处理开始: $INPUT_VIDEO"
echo "实际使用的视频文件: $ACTUAL_VIDEO"
if [ "$HD_MODE" = true ]; then
    echo "处理模式: 高清模式"
else
    echo "处理模式: 普通模式"
fi
if [ -f "$SEPARATE_AUDIO_FILE" ] && [ -s "$SEPARATE_AUDIO_FILE" ]; then
    if [[ "$SEPARATE_AUDIO_FILE" == *"_hd_audio.webm" ]]; then
        echo "检测到分离的高清音频文件: $SEPARATE_AUDIO_FILE"
    else
        echo "检测到分离的音频文件: $SEPARATE_AUDIO_FILE"
    fi
fi
echo "使用语音文件: $VOICE_FILE"
echo "使用语速倍数: $SPEECH_RATE"
echo "使用字幕字体大小: $SUBTITLE_SIZE"
echo "强制使用Apple Silicon GPU (MPS)"
echo "=================================================="

# 步骤1: 生成逐句中文配音并合成完整音轨
echo "步骤 1/4: 生成逐句中文配音..."

# 检查中文配音文件是否已存在
if [ -f "$CHINESE_AUDIO" ] && [ -s "$CHINESE_AUDIO" ]; then
    echo "✓ 中文配音文件已存在，跳过生成: $CHINESE_AUDIO"
    # 获取现有音频时长用于后续步骤
    AUDIO_DURATION=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$CHINESE_AUDIO")
    echo "  音频时长: ${AUDIO_DURATION}秒"
else
    echo "  开始生成中文配音..."
python3 -c "
import srt
import subprocess
import os
from datetime import timedelta

# 读取翻译后的SRT
with open('$TRANSLATED_SRT', 'r', encoding='utf-8') as f:
    subs = list(srt.parse(f.read()))

print(f'开始生成 {len(subs)} 个字幕片段的语音')

# 使用增强的TTS音量设置 (提高到150%)
# 150% = 20*log10(1.5) ≈ 3.5dB
standard_tts_volume = -16.0 + 3.5  # -12.5dB (提高到150%)
print(f'使用强化TTS音量: {standard_tts_volume:.1f} dB (标准音量提高到150%)')

# 第一步：生成所有TTS音频文件
temp_audio_files = []
for i, sub in enumerate(subs):
    text = sub.content.strip()
    if not text:
        continue
    
    # 去掉句号，让朗读更自然
    text = text.replace('。', '')
    
    # 生成单独的音频文件 (使用wav格式避免mp3格式问题)
    audio_file = f'$TEMP_DIR/segment_{i+1:03d}.wav'
    text_file = f'$TEMP_DIR/segment_{i+1:03d}.txt'
    
    # 写入文本文件
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write(text)
    
    # 检查音频文件是否已存在，如果存在则跳过IndexTTS生成
    tts_already_exists = os.path.exists(audio_file) and os.path.getsize(audio_file) > 0
    if tts_already_exists:
        print(f'✓ 跳过IndexTTS，已存在 {audio_file}')
    else:
        # IndexTTS重试机制：最多重试2次
        max_retries = 2
        retry_count = 0
        tts_success = False
        
        while retry_count <= max_retries and not tts_success:
            if retry_count > 0:
                print(f'   IndexTTS重试第 {retry_count} 次...')
            
            # 直接使用正确的IndexTTS命令
            import subprocess
            
            # 使用绝对路径调用IndexTTS
            tts_commands = [
                f'cd indextts && PYTHONPATH=$(pwd)/..:$PYTHONPATH MPS_FALLBACK=0 python3 cli.py \"{text}\" --voice \"../$VOICE_FILE\" --output \"{audio_file}\" --device mps --model_dir ../checkpoints --config ../checkpoints/config.yaml'
            ]
            print(f'   使用IndexTTS命令: {tts_commands[0]}')
            
            cmd = None
            for tts_cmd in tts_commands:
                cmd = ['bash', '-c', tts_cmd]
                # 先测试命令是否可执行，如果失败则尝试下一个
                test_result = subprocess.run(['bash', '-c', tts_cmd.split('&&')[0]], capture_output=True, text=True)
                if 'cd' in tts_cmd and test_result.returncode != 0:
                    continue  # 目录不存在，尝试下一个命令
                break  # 找到可用的命令
            # Note: Using TTS_LANGUAGE={$TTS_LANGUAGE} for future language support
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # 检查IndexTTS是否成功
            if result.returncode == 0 and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                tts_success = True
                print(f'   IndexTTS生成成功: {audio_file}')
            else:
                retry_count += 1
                error_msg = result.stderr.strip() if result.stderr else \"未知错误\"
                if retry_count <= max_retries:
                    print(f'   IndexTTS失败（尝试 {retry_count}/{max_retries + 1}）: {error_msg}')
                else:
                    print(f'   IndexTTS失败（最终尝试 {retry_count}/{max_retries + 1}）: {error_msg}')
        
        # 如果重试后仍然失败，报错退出
        if not tts_success:
            print(f'\\n❌ 错误：IndexTTS在重试 {max_retries + 1} 次后仍然失败')
            print(f'   失败的文本片段 {i+1}: \"{text[:100]}...\"')
            print(f'   最后错误信息: {result.stderr.strip() if result.stderr else \"未知错误\"}')
            print(f'\\n🔧 建议解决方案:')
            print(f'   1. 检查IndexTTS环境是否正确配置')
            print(f'   2. 检查语音文件 {\"$VOICE_FILE\"} 是否存在')
            print(f'   3. 检查Apple Silicon GPU (MPS) 是否可用')
            print(f'   4. 检查Python虚拟环境是否激活')
            import sys
            sys.exit(1)
    
    # 设置MPS环境变量，强制使用Apple Silicon GPU
    import sys
    import os
    
    # 尝试添加不同的indextts路径到Python路径
    possible_paths = ['indextts', 'index-tts', '../indextts', '../index-tts']
    for path in possible_paths:
        if os.path.exists(path):
            sys.path.append(os.path.abspath(path))
            break
    
    os.environ['MPS_FALLBACK'] = '0'
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '0'
    
    # 第2步：生成加速版本（如果需要）
    if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
        # 生成加速版本的文件名
        speed_audio_file = audio_file.replace('.wav', '_speed.wav')
        print(f'   正在生成{$SPEECH_RATE}倍速版本: {speed_audio_file}')
        
        # 使用ffmpeg调整语速，保持默认音量
        speed_cmd = ['ffmpeg', '-i', audio_file, '-filter:a', f'atempo=$SPEECH_RATE', '-y', speed_audio_file]
        speed_result = subprocess.run(speed_cmd, capture_output=True, text=True)
        
        if speed_result.returncode == 0 and os.path.exists(speed_audio_file) and os.path.getsize(speed_audio_file) > 0:
            print(f'   语速调整成功: {speed_audio_file}')
            # 更新audio_file指向加速版本，后续处理使用加速版本
            audio_file = speed_audio_file
        else:
            print(f'   语速调整失败，使用原速音频: {speed_result.stderr.strip() if speed_result.stderr else \"未知错误\"}')
            # 如果语速调整失败，继续使用原速文件
    
    if os.path.exists(audio_file):
        temp_audio_files.append({
            'file': audio_file,
            'text': text,
            'sub': sub
        })
        print(f'✓ 生成片段 {i+1}/{len(subs)}: {text[:50] + \"...\" if len(text) > 50 else text}')

# 第二步：直接使用TTS音频，不做音量分析和调整
print(f'\\n使用TTS默认音量，不做任何调整')

audio_files = []
for i, audio_info in enumerate(temp_audio_files):
    sub = audio_info['sub']
    
    # 获取音频时长，增加错误处理
    probe_cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_info['file']]
    duration_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    duration = 0
    if duration_result.stdout.strip():
        try:
            duration_str = duration_result.stdout.strip()
            if duration_str != 'N/A' and duration_str != '':
                duration = float(duration_str)
        except ValueError:
            print(f'   警告：无法解析音频时长: {duration_result.stdout.strip()}，使用默认值0')
            duration = 0
    
    # 计算字幕时间
    start_seconds = sub.start.total_seconds()
    end_seconds = sub.end.total_seconds()
    subtitle_duration = end_seconds - start_seconds
    
    audio_files.append({
        'file': audio_info['file'],
        'start': start_seconds,
        'end': end_seconds,
        'duration': duration,
        'subtitle_duration': subtitle_duration,
        'text': audio_info['text'][:50] + '...' if len(audio_info['text']) > 50 else audio_info['text']
    })
    
    print(f'✓ 片段 {i+1:2d}: 使用默认音量')
    print(f'    文本: {audio_info[\"text\"][:60] + \"...\" if len(audio_info[\"text\"]) > 60 else audio_info[\"text\"]}')

print(f'\\n成功准备 {len(audio_files)} 个音频片段')

# 获取原视频时长
video_probe_cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', '$ACTUAL_VIDEO']
video_duration_result = subprocess.run(video_probe_cmd, capture_output=True, text=True)

# 更安全的视频时长获取逻辑
video_duration = None
if video_duration_result.stdout.strip():
    try:
        video_duration = float(video_duration_result.stdout.strip())
        print(f'原视频时长: {video_duration:.1f}秒')
    except ValueError:
        print(f'警告：无法解析视频时长: {video_duration_result.stdout.strip()}')

# 如果无法获取视频时长，计算音频片段的最大结束时间
if video_duration is None or video_duration <= 0:
    max_end_time = max([audio['end'] for audio in audio_files]) if audio_files else 300
    video_duration = max_end_time + 10  # 添加10秒缓冲
    print(f'使用计算的音频时长: {video_duration:.1f}秒 (基于字幕最大结束时间 + 缓冲)')

# 使用分批处理方法避免文件句柄过多的问题
print(f'\\n=== 使用分批处理合并TTS音频片段 ===')

BATCH_SIZE = 100  # 每批处理100个音频文件
total_files = len(audio_files)
total_batches = (total_files + BATCH_SIZE - 1) // BATCH_SIZE

print(f'总音频片段: {total_files}')
print(f'分批大小: {BATCH_SIZE}')
print(f'总批次: {total_batches}')

# 获取temp_dir路径
temp_dir = '$TEMP_DIR'

# 创建静音背景音轨
silence_file = os.path.join(temp_dir, 'silence_base.wav')
silence_cmd = f'ffmpeg -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100:duration={video_duration} \"{silence_file}\" -y'
print(f'\\n创建静音背景音轨...')
result = subprocess.run(silence_cmd, shell=True, capture_output=True, text=True)
if result.returncode != 0:
    print(f'❌ 创建静音背景音轨失败: {result.stderr}')
    exit(1)

batch_files = []

# 分批处理音频片段
for batch_num in range(total_batches):
    start_idx = batch_num * BATCH_SIZE
    end_idx = min(start_idx + BATCH_SIZE, total_files)
    batch_audio_files = audio_files[start_idx:end_idx]
    
    print(f'\\n处理批次 {batch_num + 1}/{total_batches} (片段 {start_idx + 1}-{end_idx})')
    
    # 为当前批次创建filter_complex
    filter_lines = []
    input_files = []
    
    # 添加静音背景作为第一个输入
    input_files.append(silence_file)
    
    # 添加当前批次的音频文件
    for audio_info in batch_audio_files:
        input_files.append(audio_info['file'])
    
    # 创建filter_complex
    mix_inputs = ['[0:a]']  # 静音背景音轨
    
    for i, audio_info in enumerate(batch_audio_files):
        delay_ms = int(audio_info['start'] * 1000)
        filter_lines.append(f'[{i+1}:a]adelay={delay_ms}|{delay_ms}[delayed{i}];')
        mix_inputs.append(f'[delayed{i}]')
    
    # 混合所有音频
    mix_filter = ''.join(mix_inputs) + f'amix=inputs={len(mix_inputs)}:duration=first:normalize=0[out]'
    filter_lines.append(mix_filter)
    
    # 生成批次输出文件
    batch_output = os.path.join(temp_dir, f'batch_{batch_num:03d}_audio.wav')
    batch_files.append(batch_output)
    
    # 构建ffmpeg命令
    input_args = ' '.join([f'-i \"{file}\"' for file in input_files])
    filter_complex = ''.join(filter_lines)
    
    ffmpeg_cmd = f'ffmpeg {input_args} -filter_complex \"{filter_complex}\" -map \"[out]\" \"{batch_output}\" -y'
    
    print(f'  处理 {len(batch_audio_files)} 个音频片段...')
    result = subprocess.run(ffmpeg_cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f'❌ 批次 {batch_num + 1} 处理失败: {result.stderr}')
        exit(1)
    
    print(f'  ✓ 批次 {batch_num + 1} 处理完成')

# 如果有多个批次，需要合并所有批次的结果
if total_batches == 1:
    # 只有一个批次，直接重命名
    final_audio_path = os.path.join(temp_dir, 'step5_chinese_audio.wav')
    os.rename(batch_files[0], final_audio_path)
    print(f'\\n✓ 单批次处理完成，音频文件: {final_audio_path}')
else:
    # 多个批次，需要合并
    print(f'\\n合并 {total_batches} 个批次的音频文件...')
    
    # 创建合并用的filter_complex
    input_args = ' '.join([f'-i \"{file}\"' for file in batch_files])
    mix_inputs = ''.join([f'[{i}:a]' for i in range(len(batch_files))])
    filter_complex = f'{mix_inputs}amix=inputs={len(batch_files)}:duration=first:normalize=0[out]'
    
    final_audio_path = os.path.join(temp_dir, 'step5_chinese_audio.wav')
    final_cmd = f'ffmpeg {input_args} -filter_complex \"{filter_complex}\" -map \"[out]\" \"{final_audio_path}\" -y'
    
    result = subprocess.run(final_cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f'❌ 最终合并失败: {result.stderr}')
        exit(1)
    
    print(f'✓ 所有批次合并完成')
    
    # 清理批次文件
    for batch_file in batch_files:
        if os.path.exists(batch_file):
            os.remove(batch_file)
    print(f'✓ 清理批次临时文件完成')

# 清理静音背景文件
if os.path.exists(silence_file):
    os.remove(silence_file)

print(f'\\n✓ 音频合成完成: {final_audio_path}')

# 保留所有临时音频文件用于调试
print(f'\\n保留的TTS音频片段文件:')
for i, audio_info in enumerate(audio_files):
    print(f'  片段 {i+1:2d}: {audio_info[\"file\"]}')
print(f'\\n注意：临时音频文件已保留在 {os.path.dirname(audio_files[0][\"file\"])} 目录中')
"

    if [ ! -f "$CHINESE_AUDIO" ]; then
        echo "错误：TTS语音生成失败。"
        exit 1
    fi

    # 获取生成的音频时长
    AUDIO_DURATION=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$CHINESE_AUDIO" 2>/dev/null || echo "未知")
    echo "✓ 中文配音生成完成: $CHINESE_AUDIO (时长: ${AUDIO_DURATION}秒)"
fi

# 步骤2: 音频处理 - 根据配置决定是否保留背景音
if [ "$PRESERVE_BACKGROUND" = true ]; then
    echo "步骤 2/4: 分离人声和背景音，混合中文配音..."
    
    # 从原视频或分离音频文件提取背景音乐
    BACKGROUND_AUDIO="$TEMP_DIR/background_audio.wav"
    
    # 检查背景音频文件是否已存在
    if [ -f "$BACKGROUND_AUDIO" ] && [ -s "$BACKGROUND_AUDIO" ]; then
        echo "  ✓ 背景音频文件已存在，跳过提取: $BACKGROUND_AUDIO"
    else
        echo "  开始提取背景音频..."
        
        # 优先使用分离的音频文件作为音频源
        AUDIO_SOURCE="$ACTUAL_VIDEO"
        if [ -f "$SEPARATE_AUDIO_FILE" ] && [ -s "$SEPARATE_AUDIO_FILE" ]; then
            AUDIO_SOURCE="$SEPARATE_AUDIO_FILE"
            if [[ "$SEPARATE_AUDIO_FILE" == *"_hd_audio.webm" ]]; then
                echo "    🔊 使用分离的高清音频文件作为背景音源: $SEPARATE_AUDIO_FILE"
            else
                echo "    🔊 使用分离的音频文件作为背景音源: $SEPARATE_AUDIO_FILE"
            fi
        else
            # 检查ACTUAL_VIDEO是否有音频流，如果没有则查找原始视频文件
            AUDIO_STREAMS=$(ffprobe -v quiet -select_streams a -show_entries stream=codec_name -of csv=p=0 "$ACTUAL_VIDEO" 2>/dev/null | wc -l)
            if [ "$AUDIO_STREAMS" -eq 0 ]; then
                # HD视频没有音频流，尝试找到原始视频文件
                BASE_NAME_NO_EXT=$(basename "${ACTUAL_VIDEO%.*}")
                if [[ "$BASE_NAME_NO_EXT" == *"_hd" ]]; then
                    ORIGINAL_BASE_NAME="${BASE_NAME_NO_EXT%_hd}"
                    EXTENSION="${ACTUAL_VIDEO##*.}"
                    ORIGINAL_VIDEO_FILE="${ORIGINAL_BASE_NAME}.${EXTENSION}"
                    
                    if [ -f "$ORIGINAL_VIDEO_FILE" ] && [ -s "$ORIGINAL_VIDEO_FILE" ]; then
                        echo "    ⚠️  HD视频文件无音频流，使用原始视频文件作为背景音源: $ORIGINAL_VIDEO_FILE"
                        AUDIO_SOURCE="$ORIGINAL_VIDEO_FILE"
                    else
                        echo "    ❌ 无法找到有音频流的视频文件，跳过背景音提取"
                        PRESERVE_BACKGROUND=false
                    fi
                else
                    echo "    ❌ 视频文件无音频流，跳过背景音提取"
                    PRESERVE_BACKGROUND=false
                fi
            else
                echo "    📹 使用视频文件作为背景音源: $ACTUAL_VIDEO"
            fi
        fi
    
    # 如果没有有效的音频源，跳过背景音提取
    if [ "$PRESERVE_BACKGROUND" = false ]; then
        echo "    ⚠️  没有有效的音频源，跳过背景音提取"
        # 创建一个空的背景音频文件以避免后续错误
        touch "$BACKGROUND_AUDIO"
    else
        case "$BACKGROUND_METHOD" in
        "stereo")
            echo "  使用立体声差分法提取背景音乐..."
            ffmpeg -i "$AUDIO_SOURCE" -af "pan=mono|c0=0.5*c0+-0.5*c1" "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            ;;
        "karaoke")
            echo "  使用卡拉OK算法提取背景音乐..."
            ffmpeg -i "$AUDIO_SOURCE" -af "pan=mono|c0=0.5*c0+-0.5*c1,highpass=f=200,lowpass=f=3400" "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            ;;
        "center_channel")
            echo "  使用中置声道抑制提取背景音乐..."
            ffmpeg -i "$AUDIO_SOURCE" -af "pan=stereo|c0=0.5*c0+-0.5*c1|c1=0.5*c1+-0.5*c0" "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            ;;
        "frequency")
            echo "  使用频率滤波法提取背景音乐..."
            ffmpeg -i "$AUDIO_SOURCE" -af "highpass=f=80,lowpass=f=15000,volume=1.2" "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            ;;
        "original")
            echo "  使用原始音轨作为背景音..."
            ffmpeg -i "$AUDIO_SOURCE" -vn -acodec pcm_s16le "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            ;;
        "auto"|*)
            echo "  自动选择最佳人声分离方法..."
            
            # 尝试多种方法并选择最好的效果
            methods=("karaoke" "center_channel" "stereo")
            best_method=""
            best_peak=-100
            
            for method in "${methods[@]}"; do
                temp_audio="$TEMP_DIR/test_${method}.wav"
                echo "    测试 $method 方法..."
                
                case "$method" in
                    "karaoke")
                        ffmpeg -i "$AUDIO_SOURCE" -af "pan=mono|c0=0.5*c0+-0.5*c1,highpass=f=200,lowpass=f=3400" "$temp_audio" -y -hide_banner -loglevel error
                        ;;
                    "center_channel")
                        ffmpeg -i "$AUDIO_SOURCE" -af "pan=stereo|c0=0.5*c0+-0.5*c1|c1=0.5*c1+-0.5*c0" "$temp_audio" -y -hide_banner -loglevel error
                        ;;
                    "stereo")
                        ffmpeg -i "$AUDIO_SOURCE" -af "pan=mono|c0=0.5*c0+-0.5*c1" "$temp_audio" -y -hide_banner -loglevel error
                        ;;
                esac
                
                if [ -f "$temp_audio" ]; then
                    AUDIO_PEAK=$(ffmpeg -i "$temp_audio" -af "volumedetect" -f null - 2>&1 | grep "max_volume" | awk '{print $5}' | sed 's/dB//' || echo "-60")
                    echo "    $method 峰值: ${AUDIO_PEAK}dB"
                    
                    # 选择峰值最高（绝对值最小）的方法
                    if [ -n "$AUDIO_PEAK" ] && [ "${AUDIO_PEAK%.*}" -gt "${best_peak%.*}" ]; then
                        best_peak="$AUDIO_PEAK"
                        best_method="$method"
                        cp "$temp_audio" "$BACKGROUND_AUDIO"
                    fi
                    rm -f "$temp_audio"
                fi
            done
            
            if [ -n "$best_method" ]; then
                echo "  ✓ 选择 $best_method 方法（峰值: ${best_peak}dB）"
            else
                echo "  所有方法都失败，使用原始音轨..."
                ffmpeg -i "$AUDIO_SOURCE" -vn -acodec pcm_s16le -af "volume=0.8" "$BACKGROUND_AUDIO" -y -hide_banner -loglevel error
            fi
            ;;
        esac
    fi
    fi
    
    if [ ! -f "$BACKGROUND_AUDIO" ]; then
        echo "  ⚠️ 背景音提取失败，将直接使用中文配音"
        # 如果背景音提取失败，直接使用中文配音
        # 检查原视频编码，如果已经兼容则复制，否则重编码
        VIDEO_CODEC=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 "$ACTUAL_VIDEO" 2>/dev/null || echo "unknown")
        if [[ "$VIDEO_CODEC" == "h264" ]]; then
            echo "    使用视频流复制（原视频已是H.264格式）"
            ffmpeg -i "$ACTUAL_VIDEO" -i "$CHINESE_AUDIO" -c:v copy -c:a aac -b:a 192k -ar 44100 -ac 2 -movflags +faststart -map 0:v:0 -map 1:a:0 -shortest "$VIDEO_WITH_AUDIO" -y -hide_banner -loglevel error
        else
            echo "    使用视频重编码（原视频格式: $VIDEO_CODEC -> H.264）"
            ffmpeg -i "$ACTUAL_VIDEO" -i "$CHINESE_AUDIO" -c:v libx264 -c:a aac  -b:a 192k -ar 44100 -ac 2 -movflags +faststart -map 0:v:0 -map 1:a:0 -shortest "$VIDEO_WITH_AUDIO" -y -hide_banner -loglevel error
        fi
    else
        echo "  ✓ 背景音提取完成"
        
        # 混合背景音和中文配音，使用限制器避免破音
        echo "  混合背景音和中文配音（背景音:${BACKGROUND_VOLUME}, 配音:${VOICE_VOLUME}）..."
        MIXED_AUDIO="$TEMP_DIR/mixed_audio.wav"
        
        # 检查混合音频文件是否已存在
        if [ -f "$MIXED_AUDIO" ] && [ -s "$MIXED_AUDIO" ]; then
            echo "    ✓ 混合音频文件已存在，跳过生成: $MIXED_AUDIO"
        else
            echo "    开始混合背景音和中文配音..."
            ffmpeg -i "$BACKGROUND_AUDIO" -i "$CHINESE_AUDIO" \
                   -filter_complex "[0:a]volume=${BACKGROUND_VOLUME}[bg];[1:a]volume=${VOICE_VOLUME}[voice];[bg][voice]amix=inputs=2:duration=first:normalize=0,alimiter=level_in=1:level_out=0.95:limit=0.95:attack=7:release=50[out]" \
                   -map "[out]" "$MIXED_AUDIO" -y -hide_banner -loglevel error
        fi
        
        if [ ! -f "$MIXED_AUDIO" ]; then
            echo "  ⚠️ 音频混合失败，使用纯中文配音"
            ffmpeg -i "$ACTUAL_VIDEO" -i "$CHINESE_AUDIO" -c:v libx264 -c:a aac  -b:a 192k -ar 44100 -ac 2 -movflags +faststart -map 0:v:0 -map 1:a:0 -shortest "$VIDEO_WITH_AUDIO" -y -hide_banner -loglevel error
        else
            echo "  ✓ 音频混合完成"
            
            # 将混合音频与视频合并
            ffmpeg -i "$ACTUAL_VIDEO" -i "$MIXED_AUDIO" -c:v libx264 -c:a aac  -b:a 192k -ar 44100 -ac 2 -movflags +faststart -map 0:v:0 -map 1:a:0 -shortest "$VIDEO_WITH_AUDIO" -y -hide_banner -loglevel error
        fi
    fi
else
    echo "步骤 2/4: 直接替换为中文配音..."
    # 直接使用中文配音替换原音轨
    ffmpeg -i "$ACTUAL_VIDEO" -i "$CHINESE_AUDIO" -c:v libx264 -c:a aac  -b:a 192k -ar 44100 -ac 2 -movflags +faststart -map 0:v:0 -map 1:a:0 -shortest "$VIDEO_WITH_AUDIO" -y -hide_banner -loglevel error
fi

if [ ! -f "$VIDEO_WITH_AUDIO" ]; then
    echo "错误：视频合并失败。"
    exit 1
fi
echo "✓ 视频与混合音轨合并完成: $VIDEO_WITH_AUDIO"

# 步骤3: 调整视频饱和度并添加中文字幕
echo "步骤 3/4: 调整视频饱和度并烧录中文字幕（字体：$SUBTITLE_FONT）..."

# 检查视频文件大小，决定是否跳过字幕合并
VIDEO_SIZE_MB=0
if [ -f "$VIDEO_WITH_AUDIO" ]; then
    VIDEO_SIZE_BYTES=$(stat -f%z "$VIDEO_WITH_AUDIO" 2>/dev/null || stat -c%s "$VIDEO_WITH_AUDIO" 2>/dev/null || echo "0")
    VIDEO_SIZE_MB=$((VIDEO_SIZE_BYTES / 1024 / 1024))
    echo "视频文件大小: ${VIDEO_SIZE_MB}MB"
fi

# 如果视频大于100MB，直接复制TTS合并后的视频为最终结果，跳过字幕烧录
if [ "$VIDEO_SIZE_MB" -gt 100 ]; then
    echo "⚠️  视频文件较大(${VIDEO_SIZE_MB}MB > 100MB)，跳过字幕烧录以避免处理时间过长和文件过大"
    echo "   直接复制TTS语音合并后的视频作为最终结果"
    
    # 直接复制TTS合并后的视频为最终输出
    cp "$VIDEO_WITH_AUDIO" "$OUTPUT_VIDEO"
    
    if [ ! -f "$OUTPUT_VIDEO" ]; then
        echo "错误：视频复制失败。"
        exit 1
    fi
    
    echo "✓ 大文件处理完成，已跳过字幕烧录: $OUTPUT_VIDEO"
else
    echo "✓ 视频文件适中(${VIDEO_SIZE_MB}MB ≤ 100MB)，应用饱和度调整和字幕烧录"
    # 使用滤镜链：调整饱和度 -> 添加字幕
    # 轻微增强饱和度，让画面更鲜艳自然
    ffmpeg -i "$VIDEO_WITH_AUDIO" -vf "eq=saturation=$SATURATION,subtitles='$TRANSLATED_SRT':force_style='FontName=$SUBTITLE_FONT,Fontsize=$SUBTITLE_SIZE,MarginV=$SUBTITLE_MARGIN_V,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2'" -c:v libx264 -c:a copy -movflags +faststart "$OUTPUT_VIDEO" -y -hide_banner -loglevel error
    
    if [ ! -f "$OUTPUT_VIDEO" ]; then
        echo "错误：字幕添加失败。"
        exit 1
    fi
    
    echo "✓ 饱和度调整和字幕烧录完成: $OUTPUT_VIDEO"
fi

echo "✓ 最终视频生成完成: $OUTPUT_VIDEO"

# 显示处理结果
echo "=================================================="
echo "✅ 第二阶段处理完成！"
echo "输入视频: $INPUT_VIDEO"
echo "实际处理视频: $ACTUAL_VIDEO"
if [ "$HD_MODE" = true ]; then
    echo "处理模式: 高清模式"
fi
if [ -f "$SEPARATE_AUDIO_FILE" ] && [ -s "$SEPARATE_AUDIO_FILE" ]; then
    if [[ "$SEPARATE_AUDIO_FILE" == *"_hd_audio.webm" ]]; then
        echo "使用的分离音频: $SEPARATE_AUDIO_FILE (高清)"
    else
        echo "使用的分离音频: $SEPARATE_AUDIO_FILE"
    fi
fi
echo "输出视频: $OUTPUT_VIDEO"
echo "使用的翻译文件: $TRANSLATED_SRT"
echo "临时文件保存在: $TEMP_DIR/"
echo ""
echo "处理步骤完成："
echo "1. ✓ IndexTTS生成语音"
echo "2. ✓ 合并替换音轨"
if [ "$VIDEO_SIZE_MB" -gt 100 ]; then
    echo "3. ⏭ 跳过字幕烧录（文件大小 ${VIDEO_SIZE_MB}MB > 100MB）"
else
    echo "3. ✓ 添加中文字幕到视频"
fi
echo ""
echo "📝 注意：本脚本直接使用了 $TRANSLATED_SRT 作为翻译文件"
echo "如需重新翻译，请编辑该文件后重新运行此脚本"
echo "=================================================="