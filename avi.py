#!/usr/bin/env python3
import os
import subprocess
import urllib.parse
import hashlib
import json
from flask import Flask, jsonify, send_from_directory, render_template_string, request

# === Настройки ===
PORT = 8000
FOLDER = os.path.expanduser("~/Videos")  # Папка, где лежат твои фильмы и папки
HLS_CACHE = os.path.join(FOLDER, ".hls_cache")  # Скрытая папка для кусков HLS
THUMB_DIR = os.path.join(HLS_CACHE, ".thumbnails")  # Скрытая папка для картинок-превью
META_FILE = os.path.join(HLS_CACHE, "meta.json")    # База данных длительности видео

# Разрешенные форматы
MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.wav', '.flac'}

os.makedirs(FOLDER, exist_ok=True)
os.makedirs(HLS_CACHE, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

app = Flask(__name__)

def sizeof_fmt(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def format_duration(seconds):
    if seconds <= 0: return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def get_media_duration(file_path):
    try:
        # Быстрый пробоотборник ffmpeg для вытаскивания длительности
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=2
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

# ==========================================
# 1. МАРШРУТ: ГЛАВНАЯ СТРАНИЦА (ГАЛЕРЕЯ С ПАПКАМИ И СОРТИРОВКОЙ)
# ==========================================
@app.route('/')
def index():
    rel_path = request.args.get('p', '')
    current_dir = os.path.join(FOLDER, rel_path) if rel_path else FOLDER
    
    current_dir = os.path.abspath(current_dir)
    base_dir = os.path.abspath(FOLDER)
    if not current_dir.startswith(base_dir):
        current_dir = base_dir
        rel_path = ''
        
    try:
        items = os.listdir(current_dir)
    except OSError:
        items = []

    # --- УМНЫЙ КЭШ ДЛИТЕЛЬНОСТИ ---
    meta_cache = {}
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, 'r') as f:
                meta_cache = json.load(f)
        except Exception: pass
    meta_changed = False
        
    folders = []
    files = []
    
    for item in items:
        if item.startswith('.'): 
            continue
        full_path = os.path.join(current_dir, item)
        if os.path.isdir(full_path):
            folders.append(item)
        elif os.path.isfile(full_path):
            ext = os.path.splitext(item)[1].lower()
            if ext in MEDIA_EXTS:
                files.append(item)
                
    folders.sort()
    files.sort()

    cards_html = ""
    
    if rel_path:
        parent_path = os.path.dirname(rel_path)
        cards_html += f'''
        <div class="media-card folder-card" onclick="location.href='/?p={urllib.parse.quote(parent_path)}'">
            <div class="card-icon" style="color: #b0bec5;">
                <i class="fas fa-arrow-left"></i>
            </div>
            <div class="card-title">.. (Назад)</div>
            <div class="card-size">Вернуться</div>
        </div>
        '''

    for folder in folders:
        sub_rel_path = os.path.join(rel_path, folder) if rel_path else folder
        safe_p = urllib.parse.quote(sub_rel_path)
        cards_html += f'''
        <div class="media-card folder-card" onclick="location.href='/?p={safe_p}'">
            <div class="card-icon" style="color: #ffca28;">
                <i class="fas fa-folder"></i>
            </div>
            <div class="card-title" title="{folder}">{folder}</div>
            <div class="card-size">Папка</div>
        </div>
        '''

    for f in files:
        file_rel_path = os.path.join(rel_path, f) if rel_path else f
        full_path = os.path.join(FOLDER, file_rel_path)
        ext = os.path.splitext(f)[1].lower()
        
        file_stat = os.stat(full_path)
        file_size = file_stat.st_size
        size_str = sizeof_fmt(file_size)
        
        # Защита процессора: Берем длительность из кэша, если файл не менялся
        cache_key = f"{f}_{file_size}"
        if cache_key in meta_cache:
            duration = meta_cache[cache_key]
        else:
            duration = get_media_duration(full_path)
            meta_cache[cache_key] = duration
            meta_changed = True
            
        dur_str = format_duration(duration)
        info_text = f"{size_str} • {dur_str}" if dur_str else size_str
        
        safe_name = urllib.parse.quote(file_rel_path)
        js_safe_name = f.replace("'", "\\'").replace('"', '&quot;')
        
        is_audio = ext in {'.mp3', '.wav', '.flac'}
        icon = "fa-music" if is_audio else "fa-film"
        color = "#e91e63" if is_audio else "#2196f3"
        
        display_name = os.path.splitext(f)[0]
        display_name = display_name.replace('.', ' ').replace('_', ' ')

        # Дата-атрибуты для JS сортировки (data-name, data-duration)
        if is_audio:
            cards_html += f'''
            <div class="media-card file-card" data-name="{display_name.lower()}" data-duration="{duration}" onclick="openOptionsModal('{safe_name}', '{js_safe_name}')">
                <div class="card-icon" style="color: {color};">
                    <i class="fas {icon}"></i>
                </div>
                <div class="card-title" title="{f}">{display_name}</div>
                <div class="card-size">{info_text}</div>
                <div class="card-play-overlay">
                    <i class="fas fa-sliders-h"></i>
                </div>
            </div>
            '''
        else:
            card_id = hashlib.md5(file_rel_path.encode()).hexdigest()
            thumb_url = f"/thumbnail/{safe_name}"
            cards_html += f'''
            <div class="media-card file-card" data-name="{display_name.lower()}" data-duration="{duration}" onclick="openOptionsModal('{safe_name}', '{js_safe_name}')">
                <div class="thumb-wrapper">
                    <img class="card-thumb" id="thumb-{card_id}" src="{thumb_url}" onerror="this.style.display='none'; document.getElementById('icon-{card_id}').style.display='flex';">
                    <div class="card-icon fallback-icon" id="icon-{card_id}" style="color: {color}; display: none;">
                        <i class="fas {icon}"></i>
                    </div>
                </div>
                <div class="card-title" title="{f}">{display_name}</div>
                <div class="card-size">{info_text}</div>
                <div class="card-play-overlay">
                    <i class="fas fa-sliders-h"></i>
                </div>
            </div>
            '''

    # Сохраняем обновленный кэш на диск
    if meta_changed:
        try:
            with open(META_FILE, 'w') as f:
                json.dump(meta_cache, f)
        except Exception: pass

    path_indicator = f'<div class="path-indicator"><i class="fas fa-folder-open"></i> / {rel_path}</div>' if rel_path else '<div class="path-indicator"><i class="fas fa-home"></i> Главная директория</div>'

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AVI Media Server</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
    body {{
        background: #0f0f1a; color: white;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        margin: 0; padding: 20px; min-height: 100vh;
    }}
    h1 {{
        text-align: center; color: #bbdefb;
        font-weight: 300; letter-spacing: 2px; margin-bottom: 20px;
    }}
    
    /* Верхняя панель: Навигация + Сортировка */
    .top-bar {{
        display: flex; justify-content: space-between; align-items: center;
        max-width: 1200px; margin: 0 auto 30px auto; flex-wrap: wrap; gap: 15px;
    }}
    .path-indicator {{
        color: #888; font-size: 14px; background: rgba(255,255,255,0.05);
        padding: 8px 16px; border-radius: 20px;
    }}
    .sort-select {{
        background: #1e1e2d; color: #e0e0e0; border: 1px solid rgba(255,255,255,0.2);
        padding: 8px 15px; border-radius: 20px; outline: none; font-size: 14px; cursor: pointer;
    }}
    .sort-select:focus {{ border-color: #2196f3; }}

    .media-grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 25px; max-width: 1200px; margin: 0 auto;
    }}
    
    /* Карточка стала чуть выше под 3 строки */
    .media-card {{
        background: rgba(30, 30, 45, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 15px; padding: 20px; text-align: center;
        cursor: pointer; position: relative; overflow: hidden;
        transition: all 0.3s ease; box-shadow: 0 10px 20px rgba(0,0,0,0.3);
        display: flex; flex-direction: column; justify-content: space-between; height: 260px;
        box-sizing: border-box;
    }}
    .media-card:hover {{
        transform: translateY(-10px); box-shadow: 0 15px 30px rgba(33, 150, 243, 0.4);
        border-color: rgba(33, 150, 243, 0.5);
    }}
    .card-icon, .thumb-wrapper {{
        height: 110px; display: flex; align-items: center; justify-content: center;
        font-size: 60px; margin-bottom: 10px; transition: transform 0.3s ease;
        overflow: hidden; border-radius: 8px; position: relative; flex-shrink: 0;
    }}
    .media-card:hover .card-icon, .media-card:hover .thumb-wrapper {{ transform: scale(1.05); }}
    .card-thumb {{ width: 100%; height: 100%; object-fit: cover; }}
    
    /* УМНЫЙ ПЕРЕНОС ТЕКСТА ДО 3-Х СТРОК */
    .card-title {{
        font-weight: 600; font-size: 14px;
        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
        overflow: hidden; text-overflow: ellipsis; white-space: normal; word-wrap: break-word;
        margin-bottom: 5px; color: #e0e0e0; line-height: 1.3; max-height: 3.9em;
    }}
    
    .card-size {{ font-size: 12px; color: #888; margin-top: auto; }}
    .card-play-overlay {{
        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.7); display: flex; align-items: center; justify-content: center;
        font-size: 50px; color: white; opacity: 0; transition: opacity 0.3s ease;
    }}
    .media-card:hover .card-play-overlay {{ opacity: 1; }}

    #options-modal {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.85); display: flex; align-items: center; justify-content: center;
        z-index: 500; opacity: 0; visibility: hidden; transition: all 0.3s ease; backdrop-filter: blur(5px);
    }}
    #options-modal.active {{ opacity: 1; visibility: visible; }}
    .modal-content {{
        background: #1e1e2d; border-radius: 15px; padding: 30px; width: 90%; max-width: 400px;
        border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        position: relative;
    }}
    .close-btn {{
        position: absolute; top: 15px; right: 15px; font-size: 20px; color: #888;
        cursor: pointer; transition: color 0.2s;
    }}
    .close-btn:hover {{ color: white; }}
    .modal-title {{ font-size: 18px; margin-bottom: 20px; word-break: break-all; color: #2196f3; font-weight: bold; }}
    .fps-input-group {{ margin-bottom: 20px; }}
    .fps-input-group label {{ display: block; font-size: 14px; margin-bottom: 8px; color: #ccc; }}
    .fps-input-group input {{
        width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #444;
        background: #151520; color: white; font-size: 16px; box-sizing: border-box;
    }}
    .fps-input-group input:focus {{ border-color: #2196f3; outline: none; }}
    
    .quality-btn {{
        display: block; width: 100%; padding: 15px; margin-bottom: 10px;
        background: #2a2a3f; color: white; border: none; border-radius: 8px;
        font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s;
    }}
    .quality-btn.low:hover {{ background: #4caf50; }}
    .quality-btn.medium:hover {{ background: #ff9800; }}
    .quality-btn.high:hover {{ background: #f44336; }}
    .quality-btn.cinema {{ border: 1px solid #9c27b0; }}
    .quality-btn.cinema:hover {{ background: #9c27b0; }}

    #loading-overlay {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(10, 10, 15, 0.95); display: flex; flex-direction: column; align-items: center; justify-content: center;
        z-index: 1000; opacity: 0; visibility: hidden; transition: all 0.4s ease; backdrop-filter: blur(15px);
    }}
    #loading-overlay.active {{ opacity: 1; visibility: visible; }}
    .loader-icon {{ font-size: 50px; color: #2196f3; margin-bottom: 20px; animation: spin 2s linear infinite; }}
    @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
    .status-text {{ font-size: 24px; font-weight: 300; margin-bottom: 15px; color: #bbdefb; text-align: center; }}
    .progress-container {{ width: 300px; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }}
    .progress-bar {{ height: 100%; width: 0%; background: linear-gradient(90deg, #2196f3, #00bcd4); transition: width 0.5s ease; }}
</style>
</head>
<body>

    <h1><i class="fas fa-server"></i> AVI Media Core</h1>
    
    <div class="top-bar">
        {path_indicator}
        
        <select class="sort-select" id="sort-select" onchange="sortCards()">
            <option value="name_asc">Имя (А-Я)</option>
            <option value="name_desc">Имя (Я-А)</option>
            <option value="dur_desc">Самые длинные</option>
            <option value="dur_asc">Самые короткие</option>
        </select>
    </div>
    
    <div class="media-grid" id="media-grid">
        {cards_html}
    </div>

    <div id="options-modal">
        <div class="modal-content">
            <i class="fas fa-times close-btn" onclick="closeOptionsModal()"></i>
            <div class="modal-title" id="modal-filename-display">Фильм.mp4</div>
            <div class="fps-input-group">
                <label for="fps-input"><i class="fas fa-tachometer-alt"></i> FPS (Кадры в секунду):</label>
                <input type="number" id="fps-input" placeholder="Исходный (напр. 24, 30, 60)" min="1" max="120">
            </div>
            <button class="quality-btn low" onclick="startTranscoding('low')">Слабый (360p + Идеальный поток)</button>
            <button class="quality-btn medium" onclick="startTranscoding('medium')">Средний (720p + Баланс HRD)</button>
            <button class="quality-btn cinema" onclick="startTranscoding('cinema')">Кино (720p + Медленное HQ кодирование)</button>
            <button class="quality-btn high" onclick="startTranscoding('high')">Высокий (Исходное с защитой)</button>
        </div>
    </div>

    <div id="loading-overlay">
        <i class="fas fa-cog loader-icon"></i>
        <div class="status-text" id="status-text">Запуск движка FFmpeg...</div>
        <div class="progress-container">
            <div class="progress-bar" id="progress-bar"></div>
        </div>
    </div>

    <script>
        // МГНОВЕННАЯ JS СОРТИРОВКА
        function sortCards() {{
            const grid = document.getElementById('media-grid');
            const folders = Array.from(grid.querySelectorAll('.folder-card'));
            const files = Array.from(grid.querySelectorAll('.file-card'));
            const sortType = document.getElementById('sort-select').value;

            files.sort((a, b) => {{
                const nameA = a.dataset.name;
                const nameB = b.dataset.name;
                const durA = parseFloat(a.dataset.duration);
                const durB = parseFloat(b.dataset.duration);

                if (sortType === 'name_asc') return nameA.localeCompare(nameB);
                if (sortType === 'name_desc') return nameB.localeCompare(nameA);
                if (sortType === 'dur_asc') return durA - durB;
                if (sortType === 'dur_desc') return durB - durA;
            }});

            grid.innerHTML = '';
            folders.forEach(f => grid.appendChild(f)); // Папки всегда сверху
            files.forEach(f => grid.appendChild(f));
        }}
        // Вызываем сортировку при загрузке страницы, чтобы применить выбранный по умолчанию пункт
        window.addEventListener('DOMContentLoaded', sortCards);

        let currentFileSafeName = "";

        function openOptionsModal(safeName, displayName) {{
            currentFileSafeName = safeName;
            document.getElementById('modal-filename-display').innerHTML = displayName;
            document.getElementById('fps-input').value = ''; 
            document.getElementById('options-modal').classList.add('active');
        }}

        function closeOptionsModal() {{
            document.getElementById('options-modal').classList.remove('active');
        }}

        async function startTranscoding(quality) {{
            closeOptionsModal();
            
            const fpsValue = document.getElementById('fps-input').value;
            const overlay = document.getElementById('loading-overlay');
            const statusText = document.getElementById('status-text');
            const progressBar = document.getElementById('progress-bar');
            
            overlay.classList.add('active');
            progressBar.style.width = '10%';
            statusText.textContent = 'Подготовка параметров...';
            
            try {{
                const payload = {{ quality: quality, fps: fpsValue }};
                
                const startRes = await fetch('/prepare/' + currentFileSafeName, {{ 
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                
                if (!startRes.ok) throw new Error("Ошибка запуска");
                
                const responseData = await startRes.json();
                const streamId = responseData.stream_id;
                
                progressBar.style.width = '40%';
                statusText.textContent = 'Рендеринг потока...';
                
                const checkInterval = setInterval(async () => {{
                    const statusRes = await fetch('/status/' + streamId);
                    const data = await statusRes.json();
                    
                    if (data.ready) {{
                        clearInterval(checkInterval);
                        progressBar.style.width = '100%';
                        statusText.textContent = 'Готово! Запуск плеера...';
                        
                        const currentHost = window.location.origin; 
                        const streamUrl = currentHost + "/stream/" + streamId + "/index.m3u8";
                        
                        setTimeout(() => {{
                            window.location.href = "/player?stream=" + encodeURIComponent(streamUrl);
                        }}, 1000);
                    }}
                }}, 2000);
                
            }} catch (e) {{
                statusText.textContent = 'Ошибка! Проверьте консоль сервера.';
                statusText.style.color = '#f44336';
                setTimeout(() => overlay.classList.remove('active'), 3000);
            }}
        }}
    </script>
</body>
</html>'''
    return render_template_string(html)

# ==========================================
# 2. МАРШРУТ: ЛОКАЛЬНЫЙ ПЛЕЕР (РАЗДАЕМ HTML ПЛЕЕРА)
# ==========================================
PLAYER_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AVI Player</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    
    <style>
        body {
            background-color: #0f0f1a; color: #bbdefb;
            font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
            margin: 0; padding: 0; display: flex; flex-direction: column;
            align-items: center; min-height: 100vh;
        }
        h2 { font-weight: 300; letter-spacing: 2px; margin-top: 20px; }
        #player-wrapper {
            position: relative; width: 100%; max-width: 1000px; background: #000;
            border-radius: 12px; overflow: hidden; box-shadow: 0 15px 40px rgba(0,0,0,0.8);
            margin-top: 20px; user-select: none; -webkit-user-select: none;
        }
        video {
            width: 100%; height: 100%; object-fit: contain; display: block; cursor: pointer;
        }
        #player-wrapper:fullscreen, #player-wrapper:-webkit-full-screen, #player-wrapper:-moz-full-screen {
            max-width: none !important; width: 100vw !important; height: 100vh !important;
            margin: 0 !important; border-radius: 0 !important; display: flex;
            align-items: center; justify-content: center; background: #000;
        }
        #player-wrapper.idle, #player-wrapper.idle video { cursor: none !important; }
        
        #custom-controls {
            position: absolute; bottom: 0; left: 0; width: 100%; background: rgba(15, 15, 26, 0.85);
            padding: 15px 20px; box-sizing: border-box; display: flex; align-items: center; gap: 15px;
            transform: translateY(100%); transition: transform 0.3s ease; z-index: 10;
            border-top: 1px solid rgba(255,255,255,0.1);
        }
        @supports (backdrop-filter: blur(10px)) { #custom-controls { backdrop-filter: blur(10px); } }
        #player-wrapper:hover #custom-controls { transform: translateY(0); }
        #player-wrapper.idle #custom-controls { transform: translateY(100%) !important; }
        #player-wrapper.paused #custom-controls { transform: translateY(0) !important; }

        .ctrl-btn {
            background: none; border: none; color: #fff; font-size: 20px;
            cursor: pointer; outline: none; transition: color 0.2s; padding: 0; width: 30px;
        }
        .ctrl-btn:hover { color: #2196f3; }

        #progress-container {
            flex-grow: 1; height: 6px; background: rgba(255,255,255,0.2);
            border-radius: 3px; cursor: pointer; position: relative;
        }
        #progress-fill {
            position: absolute; top: 0; left: 0; height: 100%; background: #2196f3;
            border-radius: 3px; width: 0%; pointer-events: none; transition: width 0.2s linear;
        }
        #buffer-fill {
            position: absolute; top: 0; left: 0; height: 100%; background: rgba(255, 255, 255, 0.35);
            border-radius: 3px; width: 0%; pointer-events: none; z-index: -1;
        }
        #time-display { font-size: 13px; color: #ddd; min-width: 100px; text-align: center; }

        .tap-indicator {
            position: absolute; top: 50%; transform: translateY(-50%); color: white;
            font-size: 24px; background: rgba(0, 0, 0, 0.6); padding: 15px 25px;
            border-radius: 30px; opacity: 0; pointer-events: none; display: flex;
            align-items: center; gap: 10px; z-index: 5; border: 1px solid rgba(255,255,255,0.2);
        }
        @supports (backdrop-filter: blur(5px)) { .tap-indicator { backdrop-filter: blur(5px); } }
        .tap-indicator.left { left: 10%; }
        .tap-indicator.right { right: 10%; }
        .tap-indicator.pulse { animation: tapPulse 0.5s ease-out forwards; }
        @keyframes tapPulse { 0% { transform: translateY(-50%) scale(0.8); opacity: 1; } 100% { transform: translateY(-50%) scale(1.2); opacity: 0; } }

        #status-msg { margin-top: 15px; color: #888; font-size: 14px; text-align: center; }
        .error { color: #f44336 !important; }
        
        .back-gallery-btn {
            position: absolute; top: 20px; left: 20px; color: white;
            font-size: 24px; cursor: pointer; text-decoration: none;
            opacity: 0.7; transition: opacity 0.2s; z-index: 100;
        }
        .back-gallery-btn:hover { opacity: 1; }
    </style>
</head>
<body>

    <a href="/" class="back-gallery-btn" title="Вернуться к файлам"><i class="fas fa-arrow-left"></i></a>
    <h2><i class="fas fa-play-circle" style="color: #2196f3;"></i> AVI Player</h2>
    
    <div id="player-wrapper" class="paused">
        <video id="video"></video>
        <div id="tap-left" class="tap-indicator left"><i class="fas fa-backward"></i> 5 сек</div>
        <div id="tap-right" class="tap-indicator right">5 сек <i class="fas fa-forward"></i></div>
        
        <div id="custom-controls">
            <button id="play-pause-btn" class="ctrl-btn" title="Play/Pause (Space)"><i class="fas fa-play"></i></button>
            <div id="progress-container">
                <div id="buffer-fill"></div>
                <div id="progress-fill"></div>
            </div>
            <div id="time-display">00:00 / 00:00</div>
            <button id="mute-btn" class="ctrl-btn" title="Mute (M)"><i class="fas fa-volume-up"></i></button>
            <button id="fullscreen-btn" class="ctrl-btn" title="Fullscreen (F)"><i class="fas fa-expand"></i></button>
        </div>
    </div>

    <div id="status-msg">Инициализация плеера...</div>

    <script>
        function getQueryParam(name) {
            var match = RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
            return match && decodeURIComponent(match[1].replace(/\+/g, ' '));
        }

        var streamUrl = getQueryParam('stream');
        var video = document.getElementById('video');
        var statusMsg = document.getElementById('status-msg');

        if (!streamUrl) {
            statusMsg.className = 'error';
            statusMsg.innerHTML = 'URL потока не найден. Запустите видео с главного сервера.';
        } else {
            if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                var hls = new Hls({ 
                    debug: false,
                    maxBufferSize: 300 * 1024 * 1024, 
                    maxBufferLength: 300,             
                    maxMaxBufferLength: 1200,         
                    maxBufferHole: 0.5                
                });
                
                hls.loadSource(streamUrl);
                hls.attachMedia(video);
                
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    statusMsg.innerHTML = 'Поток готов! Нажмите Play.';
                });

                hls.on(Hls.Events.ERROR, function (event, data) {
                    if (data.fatal) {
                        switch (data.type) {
                            case Hls.ErrorTypes.NETWORK_ERROR:
                                hls.startLoad(); break;
                            case Hls.ErrorTypes.MEDIA_ERROR:
                                hls.recoverMediaError(); break;
                            default:
                                hls.destroy(); break;
                        }
                    }
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = streamUrl;
                statusMsg.innerHTML = 'Поток готов (Нативный HLS).';
            } else {
                statusMsg.className = 'error';
                statusMsg.innerHTML = 'Ваш браузер слишком стар для стриминга.';
            }
        }

        var lastCurrentTime = -1;
        setInterval(function() {
            if (!video.paused && video.readyState >= 3) {
                if (video.currentTime === lastCurrentTime) {
                    video.currentTime += 0.1; 
                }
                lastCurrentTime = video.currentTime;
            }
        }, 1500);

        var wrapper = document.getElementById('player-wrapper');
        var playBtn = document.getElementById('play-pause-btn');
        var muteBtn = document.getElementById('mute-btn');
        var fullBtn = document.getElementById('fullscreen-btn');
        var progressContainer = document.getElementById('progress-container');
        var progressFill = document.getElementById('progress-fill');
        var bufferFill = document.getElementById('buffer-fill'); 
        var timeDisplay = document.getElementById('time-display');
        var tapLeftInd = document.getElementById('tap-left');
        var tapRightInd = document.getElementById('tap-right');

        function formatTime(seconds) {
            if (isNaN(seconds)) return "00:00";
            var m = Math.floor(seconds / 60);
            var s = Math.floor(seconds % 60);
            return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
        }

        function togglePlay() {
            if (video.paused) {
                video.play(); playBtn.innerHTML = '<i class="fas fa-pause"></i>'; wrapper.classList.remove('paused');
            } else {
                video.pause(); playBtn.innerHTML = '<i class="fas fa-play"></i>'; wrapper.classList.add('paused');
            }
        }

        function toggleMute() {
            video.muted = !video.muted;
            muteBtn.innerHTML = video.muted ? '<i class="fas fa-volume-mute"></i>' : '<i class="fas fa-volume-up"></i>';
        }

        function toggleFullscreen() {
            if (!document.fullscreenElement && !document.mozFullScreenElement && !document.webkitFullscreenElement && !document.msFullscreenElement) {
                if (wrapper.requestFullscreen) wrapper.requestFullscreen();
                else if (wrapper.msRequestFullscreen) wrapper.msRequestFullscreen();
                else if (wrapper.mozRequestFullScreen) wrapper.mozRequestFullScreen();
                else if (wrapper.webkitRequestFullscreen) wrapper.webkitRequestFullscreen(Element.ALLOW_KEYBOARD_INPUT);
            } else {
                if (document.exitFullscreen) document.exitFullscreen();
                else if (document.msExitFullscreen) document.msExitFullscreen();
                else if (document.mozCancelFullScreen) document.mozCancelFullScreen();
                else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
            }
        }

        function scrub(e) {
            var rect = progressContainer.getBoundingClientRect();
            var pos = (e.clientX - rect.left) / rect.width;
            video.currentTime = pos * video.duration;
        }

        video.addEventListener('timeupdate', function() {
            if (!video.duration) return;
            var percent = (video.currentTime / video.duration) * 100;
            progressFill.style.width = percent + '%';
            timeDisplay.innerText = formatTime(video.currentTime) + " / " + formatTime(video.duration);

            if (video.buffered.length > 0) {
                var bufferedEnd = video.buffered.end(video.buffered.length - 1);
                var bufferPercent = (bufferedEnd / video.duration) * 100;
                bufferFill.style.width = bufferPercent + '%';
            }
        });

        playBtn.addEventListener('click', togglePlay); muteBtn.addEventListener('click', toggleMute);
        fullBtn.addEventListener('click', toggleFullscreen); progressContainer.addEventListener('click', scrub);

        var clickTimer = null;
        function showTapAnimation(element) {
            element.classList.remove('pulse'); void element.offsetWidth; element.classList.add('pulse');
        }

        wrapper.addEventListener('click', function(e) {
            if (e.target.closest('#custom-controls')) return;
            var rect = wrapper.getBoundingClientRect(); var clickX = e.clientX - rect.left;
            var isLeftSide = clickX < (rect.width / 2);

            if (clickTimer === null) {
                clickTimer = setTimeout(function() { togglePlay(); clickTimer = null; }, 250);
            } else {
                clearTimeout(clickTimer); clickTimer = null;
                if (isLeftSide) { video.currentTime -= 5; showTapAnimation(tapLeftInd); } 
                else { video.currentTime += 5; showTapAnimation(tapRightInd); }
            }
        });

        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            switch(e.keyCode) {
                case 32: e.preventDefault(); togglePlay(); break;
                case 39: video.currentTime += 5; showTapAnimation(tapRightInd); break;
                case 37: video.currentTime -= 5; showTapAnimation(tapLeftInd); break;
                case 70: toggleFullscreen(); break;
                case 77: toggleMute(); break;
            }
        });

        var hideControlsTimer = null;
        function resetActivityTimer() {
            wrapper.classList.remove('idle'); clearTimeout(hideControlsTimer);
            if (!video.paused) { hideControlsTimer = setTimeout(function() { wrapper.classList.add('idle'); }, 2500); }
        }

        wrapper.addEventListener('mousemove', resetActivityTimer); wrapper.addEventListener('click', resetActivityTimer);
        document.addEventListener('keydown', resetActivityTimer);
        wrapper.addEventListener('mouseleave', function() { if (!video.paused) wrapper.classList.add('idle'); });
        video.addEventListener('play', resetActivityTimer);
        video.addEventListener('pause', function() { clearTimeout(hideControlsTimer); wrapper.classList.remove('idle'); });
    </script>
</body>
</html>"""

@app.route('/player')
def serve_player():
    return render_template_string(PLAYER_HTML)

# ==========================================
# 3. МАРШРУТ: ДИНАМИЧЕСКАЯ ГЕНЕРАЦИЯ КАРТИНКИ (100 КАДР)
# ==========================================
@app.route('/thumbnail/<path:filename>')
def get_thumbnail(filename):
    video_path = os.path.join(FOLDER, urllib.parse.unquote(filename))
    ext = os.path.splitext(video_path)[1].lower()
    
    if ext in {'.mp3', '.wav', '.flac'}:
        return "Audio file", 404

    file_hash = hashlib.md5(video_path.encode()).hexdigest()
    thumb_file = f"{file_hash}.jpg"
    thumb_path = os.path.join(THUMB_DIR, thumb_file)

    if not os.path.exists(thumb_path):
        command = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', r'select=gte(n\,100),scale=320:-2',  # <--- Теперь берем сотый кадр!
            '-vframes', '1', thumb_path
        ]
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        except Exception:
            pass

    if os.path.exists(thumb_path):
        return send_from_directory(THUMB_DIR, thumb_file)
    else:
        return "Thumbnail generation failed", 404

# ==========================================
# 4. МАРШРУТ: ЗАПУСК ПОДГОТОВКИ (FFMPEG С АВТО-ЦП И HRD)
# ==========================================
@app.route('/prepare/<path:filename>', methods=['POST'])
def prepare_video(filename):
    video_path = os.path.join(FOLDER, urllib.parse.unquote(filename))
    
    data = request.json or {}
    quality = data.get('quality', 'medium')
    fps = data.get('fps', '').strip()

    stream_key = f"{filename}_{quality}_{fps}"
    stream_id = hashlib.md5(stream_key.encode()).hexdigest()
    
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    os.makedirs(stream_dir, exist_ok=True)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')

    if not os.path.exists(m3u8_file):
        total_cores = os.cpu_count() or 4
        threads_to_use = max(1, int(total_cores * 0.75))
        
        command = [
            'ffmpeg', '-i', video_path,
            '-c:v', 'libx264',
            '-threads', str(threads_to_use)
        ]

        if fps and fps.isdigit():
            command.extend(['-r', fps])

        if quality == 'low':
            command.extend([
                '-preset', 'ultrafast',
                '-vf', 'scale=-2:360', 
                '-crf', '32', '-maxrate', '400k', '-bufsize', '800k', 
                '-c:a', 'aac', '-b:a', '64k'
            ])
        elif quality == 'high':
            command.extend([
                '-preset', 'ultrafast',
                '-crf', '23', '-maxrate', '5000k', '-bufsize', '10000k', 
                '-c:a', 'aac', '-b:a', '192k'
            ])
        elif quality == 'cinema':
            command.extend([
                '-preset', 'medium', 
                '-vf', 'scale=-2:720', 
                '-crf', '24', '-maxrate', '2500k', '-bufsize', '5000k', 
                '-c:a', 'aac', '-b:a', '192k'
            ])
        else:  # medium
            command.extend([
                '-preset', 'ultrafast',
                '-vf', 'scale=-2:720', 
                '-crf', '28', '-maxrate', '1500k', '-bufsize', '3000k', 
                '-c:a', 'aac', '-b:a', '128k'
            ])

        command.extend([
            '-start_number', '0', '-hls_time', '5', '-hls_list_size', '0',
            '-hls_playlist_type', 'event',
            '-f', 'hls', m3u8_file
        ])
        
        print(f"Запуск потока: {quality} (FPS: {fps if fps else 'Исходный'})")
        print(f"ЦП: Обнаружено {total_cores} потоков. Используем {threads_to_use} (Ограничение 75%).")
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    return jsonify({"status": "processing", "stream_id": stream_id})

# ==========================================
# 5. МАРШРУТ: ПРОВЕРКА ГОТОВНОСТИ (STATUS)
# ==========================================
@app.route('/status/<stream_id>')
def check_status(stream_id):
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')
    
    is_ready = False
    if os.path.exists(m3u8_file):
        ts_files = [f for f in os.listdir(stream_dir) if f.endswith('.ts')]
        if len(ts_files) >= 1:
            is_ready = True

    return jsonify({"ready": is_ready})

# ==========================================
# 6. МАРШРУТ: ОТДАЧА ВИДЕО ПОТОКА (HLS)
# ==========================================
@app.route('/stream/<stream_id>/<path:file>')
def serve_hls(stream_id, file):
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    return send_from_directory(stream_dir, file)


if __name__ == '__main__':
    total_cores = os.cpu_count() or 4
    calc_threads = max(1, int(total_cores * 0.75))
    print(f"🚀 AVI Media Core [On-Premise Ultimate] запущен!")
    print(f"⚙️ Динамическая оптимизация CPU: {calc_threads}/{total_cores} потоков")
    print(f"📁 Сканирую папку: {FOLDER}")
    print(f"🌐 Сервер доступен на: http://localhost:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
