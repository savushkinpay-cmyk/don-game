import sqlite3
import os
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
import requests

app = Flask(__name__, static_folder='public', static_url_path='')

# ========== БАЗА ДАННЫХ ==========

def init_db():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        status TEXT,
        weapon TEXT,
        equipment TEXT,
        wounds TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS group_inventory (
        id INTEGER PRIMARY KEY,
        item_name TEXT UNIQUE,
        quantity INTEGER,
        unit TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn INTEGER,
        role TEXT,
        content TEXT,
        timestamp TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS game_state (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    c.execute("SELECT COUNT(*) FROM characters")
    if c.fetchone()[0] == 0:
        characters = [
            ('Дон', 'здоров', 'кинжал + 3 метательных ножа', 'бинокль, фонарь, компас', ''),
            ('Рыжий', 'здоров', 'Walther P-38', 'бинокль, фонарь, компас, ножницы', ''),
            ('Соколов', 'старое ранение левой руки', 'Маузер 98k', '', 'левая рука (шрам)'),
            ('Шубин', 'здоров', '', 'рация Северок', ''),
            ('Кравцов', 'здоров', '', '4 толовые шашки, бикфордов шнур', '')
        ]
        c.executemany("INSERT INTO characters (name, status, weapon, equipment, wounds) VALUES (?,?,?,?,?)", characters)
        
        inventory = [
            ('МП-40', 3, 'шт'),
            ('Патроны 9мм', 420, 'шт'),
            ('Патроны 7.92', 300, 'шт'),
            ('Гранаты РГД-33', 10, 'шт'),
            ('Сухой паёк', 5, 'суток'),
            ('Аптечка', 1, 'шт')
        ]
        c.executemany("INSERT INTO group_inventory (item_name, quantity, unit) VALUES (?,?,?)", inventory)
        
        c.execute("INSERT OR IGNORE INTO game_state (key, value) VALUES ('turn', '0')")
    
    conn.commit()
    conn.close()

init_db()

# ========== ПОМОЩНИКИ ==========

def get_context():
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    
    chars = c.execute("SELECT name, status, weapon, equipment, wounds FROM characters").fetchall()
    char_text = "\n".join([f"- {n}: {s}. Оружие: {w or 'нет'}. Вещи: {e or 'нет'}. Раны: {wu or 'нет'}" for n,s,w,e,wu in chars])
    
    inv = c.execute("SELECT item_name, quantity, unit FROM group_inventory").fetchall()
    inv_text = "\n".join([f"- {i}: {q} {u}" for i,q,u in inv])
    
    history = c.execute("SELECT role, content FROM history ORDER BY turn DESC LIMIT 15").fetchall()
    history.reverse()
    hist_text = "\n".join([f"{'Игрок' if r=='user' else 'Нарратор'}: {c[:300]}" for r,c in history])
    
    conn.close()
    return char_text, inv_text, hist_text

def save_history(role, content):
    conn = sqlite3.connect('game.db')
    c = conn.cursor()
    turn = c.execute("SELECT value FROM game_state WHERE key='turn'").fetchone()[0]
    new_turn = int(turn) + 1
    c.execute("INSERT INTO history (turn, role, content, timestamp) VALUES (?,?,?,?)", 
              (new_turn, role, content, datetime.now().isoformat()))
    c.execute("UPDATE game_state SET value=? WHERE key='turn'", (str(new_turn),))
    conn.commit()
    conn.close()

# ========== GROQ API ==========

def call_groq(user_message, char_text, inv_text, hist_text):
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return "❌ Нет API-ключа Groq. Добавь GROQ_API_KEY в Render."
    
    system = f"""Ты — нарратор военной игры. 1941 год.

ПЕРСОНАЖИ:
{char_text}

ИНВЕНТАРЬ:
{inv_text}

ПОСЛЕДНИЕ СОБЫТИЯ:
{hist_text if hist_text else 'Начало игры. Вечер. Группа в землянке.'}

ПРАВИЛА:
1. Игрок управляет ДОНОМ. Ты управляешь остальными.
2. НЕ пиши за Дона.
3. Реализм, без геройства.

Игрок (за Дона): {user_message}

Ответ нарратора:"""
    
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama3-8b-8192",
                "messages": [{"role": "system", "content": system}],
                "temperature": 0.8,
                "max_tokens": 600
            },
            timeout=30
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"❌ Ошибка {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

# ========== СЕРВЕР ==========

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    msg = request.json.get('message', '')
    if not msg:
        return jsonify({"reply": "Нет сообщения", "image": "earth.jpg"})
    
    save_history('user', msg)
    chars, inv, hist = get_context()
    reply = call_groq(msg, chars, inv, hist)
    save_history('assistant', reply)
    
    return jsonify({"reply": reply, "image": "earth.jpg"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)