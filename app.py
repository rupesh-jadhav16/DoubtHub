from flask import Flask, render_template, request, jsonify, session, redirect
from flask_cors import CORS
import sqlite3, os, hashlib, json
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'doubthub_secret_2024'
CORS(app)

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_db():
    conn = sqlite3.connect('doubthub.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, email TEXT UNIQUE, password TEXT,
        subjects TEXT DEFAULT '[]',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS doubts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, title TEXT, description TEXT, subject TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doubt_id INTEGER, user_id INTEGER, content TEXT,
        upvotes INTEGER DEFAULT 0, downvotes INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS answer_reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        answer_id INTEGER, user_id INTEGER, reaction TEXT,
        UNIQUE(answer_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, title TEXT, description TEXT, subject TEXT,
        file_name TEXT, file_path TEXT, file_type TEXT,
        content TEXT, downloads INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS match_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER, receiver_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS study_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, subject TEXT, description TEXT, creator_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
        group_id INTEGER, user_id INTEGER,
        PRIMARY KEY(group_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS group_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER, user_id INTEGER, message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, type TEXT, message TEXT,
        is_read INTEGER DEFAULT 0, ref_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def current_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    conn.close()
    return user

def add_notification(user_id, type_, message, ref_id=None):
    conn = get_db()
    conn.execute('INSERT INTO notifications (user_id,type,message,ref_id) VALUES (?,?,?,?)',
                 (user_id, type_, message, ref_id))
    conn.commit()
    conn.close()

# AUTH
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/dashboard')
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/')
    return render_template('dashboard.html')

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    name = data.get('name','').strip()
    email = data.get('email','').strip().lower()
    password = data.get('password','')
    subjects = json.dumps(data.get('subjects', []))
    if not name or not email or not password:
        return jsonify({'error': 'All fields required'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (name,email,password,subjects) VALUES (?,?,?,?)',
                     (name, email, hash_pw(password), subjects))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        session['user_id'] = user['id']
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Email already registered'}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email','').strip().lower()
    password = data.get('password','')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=? AND password=?',
                        (email, hash_pw(password))).fetchone()
    conn.close()
    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401
    session['user_id'] = user['id']
    return jsonify({'success': True})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me')
def me():
    user = current_user()
    if not user:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'id': user['id'], 'name': user['name'],
                    'email': user['email'], 'subjects': json.loads(user['subjects'] or '[]')})

# DOUBTS
@app.route('/api/doubts', methods=['GET'])
def get_doubts():
    subject = request.args.get('subject', '')
    search = request.args.get('search', '')
    conn = get_db()
    q = '''SELECT d.*, u.name as author_name,
           (SELECT COUNT(*) FROM answers a WHERE a.doubt_id=d.id) as answer_count
           FROM doubts d JOIN users u ON d.user_id=u.id'''
    params, conds = [], []
    if subject: conds.append('d.subject=?'); params.append(subject)
    if search:  conds.append('(d.title LIKE ? OR d.description LIKE ?)'); params += [f'%{search}%', f'%{search}%']
    if conds: q += ' WHERE ' + ' AND '.join(conds)
    q += ' ORDER BY d.created_at DESC'
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/doubts', methods=['POST'])
def post_doubt():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    data = request.json
    conn = get_db()
    conn.execute('INSERT INTO doubts (user_id,title,description,subject) VALUES (?,?,?,?)',
                 (user['id'], data['title'], data['description'], data['subject']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/doubts/<int:did>', methods=['GET'])
def get_doubt(did):
    conn = get_db()
    d = conn.execute('SELECT d.*,u.name as author_name FROM doubts d JOIN users u ON d.user_id=u.id WHERE d.id=?', (did,)).fetchone()
    answers = conn.execute('SELECT a.*,u.name as author_name FROM answers a JOIN users u ON a.user_id=u.id WHERE a.doubt_id=? ORDER BY a.upvotes DESC', (did,)).fetchall()
    conn.close()
    if not d: return jsonify({'error': 'Not found'}), 404
    return jsonify({'doubt': dict(d), 'answers': [dict(a) for a in answers]})

@app.route('/api/doubts/<int:did>/answers', methods=['POST'])
def post_answer(did):
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    data = request.json
    conn = get_db()
    conn.execute('INSERT INTO answers (doubt_id,user_id,content) VALUES (?,?,?)',
                 (did, user['id'], data['content']))
    doubt = conn.execute('SELECT * FROM doubts WHERE id=?', (did,)).fetchone()
    if doubt and doubt['user_id'] != user['id']:
        add_notification(doubt['user_id'], 'answer', f"{user['name']} answered your doubt!", did)
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/answers/<int:aid>/react', methods=['POST'])
def react_answer(aid):
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    reaction = request.json.get('reaction')
    conn = get_db()
    ex = conn.execute('SELECT * FROM answer_reactions WHERE answer_id=? AND user_id=?', (aid, user['id'])).fetchone()
    if ex:
        if ex['reaction'] == reaction:
            conn.execute('DELETE FROM answer_reactions WHERE answer_id=? AND user_id=?', (aid, user['id']))
        else:
            conn.execute('UPDATE answer_reactions SET reaction=? WHERE answer_id=? AND user_id=?', (reaction, aid, user['id']))
    else:
        conn.execute('INSERT INTO answer_reactions (answer_id,user_id,reaction) VALUES (?,?,?)', (aid, user['id'], reaction))
    ups = conn.execute("SELECT COUNT(*) FROM answer_reactions WHERE answer_id=? AND reaction='up'", (aid,)).fetchone()[0]
    dns = conn.execute("SELECT COUNT(*) FROM answer_reactions WHERE answer_id=? AND reaction='down'", (aid,)).fetchone()[0]
    conn.execute('UPDATE answers SET upvotes=?,downvotes=? WHERE id=?', (ups, dns, aid))
    conn.commit(); conn.close()
    return jsonify({'upvotes': ups, 'downvotes': dns})

# NOTES
@app.route('/api/notes', methods=['GET'])
def get_notes():
    subject = request.args.get('subject', '')
    conn = get_db()
    q = 'SELECT n.*,u.name as author_name FROM notes n JOIN users u ON n.user_id=u.id'
    rows = conn.execute(q + (' WHERE n.subject=?' if subject else ''), ([subject] if subject else [])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/notes', methods=['POST'])
def post_note():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    title = request.form.get('title')
    subject = request.form.get('subject')
    description = request.form.get('description', '')
    content = request.form.get('content', '')
    file_name, file_path, file_type = None, None, 'text'
    if 'file' in request.files:
        f = request.files['file']
        if f.filename:
            filename = secure_filename(f.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            f.save(file_path)
            file_name = filename
            file_type = 'pdf' if filename.endswith('.pdf') else 'image'
    conn = get_db()
    conn.execute('INSERT INTO notes (user_id,title,description,subject,file_name,file_path,file_type,content) VALUES (?,?,?,?,?,?,?,?)',
                 (user['id'], title, description, subject, file_name, file_path, file_type, content))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/notes/<int:nid>/download', methods=['POST'])
def download_note(nid):
    conn = get_db()
    conn.execute('UPDATE notes SET downloads=downloads+1 WHERE id=?', (nid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# MATCHING
@app.route('/api/match/suggestions')
def match_suggestions():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    my_subjects = set(json.loads(user['subjects'] or '[]'))
    conn = get_db()
    all_users = conn.execute('SELECT * FROM users WHERE id!=?', (user['id'],)).fetchall()
    sent = {r[0] for r in conn.execute('SELECT receiver_id FROM match_requests WHERE sender_id=?', (user['id'],)).fetchall()}
    recv = {r[0] for r in conn.execute('SELECT sender_id FROM match_requests WHERE receiver_id=?', (user['id'],)).fetchall()}
    result = []
    for u in all_users:
        their = set(json.loads(u['subjects'] or '[]'))
        common = my_subjects & their
        if common and u['id'] not in sent and u['id'] not in recv:
            result.append({'id': u['id'], 'name': u['name'], 'subjects': list(their), 'common': list(common)})
    conn.close()
    return jsonify(result)

@app.route('/api/match/send', methods=['POST'])
def send_match():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    receiver_id = request.json.get('receiver_id')
    conn = get_db()
    ex = conn.execute('SELECT id FROM match_requests WHERE sender_id=? AND receiver_id=?', (user['id'], receiver_id)).fetchone()
    if ex: conn.close(); return jsonify({'error': 'Already sent'}), 400
    conn.execute('INSERT INTO match_requests (sender_id,receiver_id) VALUES (?,?)', (user['id'], receiver_id))
    add_notification(receiver_id, 'match_request', f"{user['name']} wants to study with you!")
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/match/requests')
def match_requests():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    conn = get_db()
    rows = conn.execute('''SELECT mr.*,u.name as sender_name,u.subjects as sender_subjects
                           FROM match_requests mr JOIN users u ON mr.sender_id=u.id
                           WHERE mr.receiver_id=? AND mr.status='pending' ''', (user['id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/match/respond', methods=['POST'])
def respond_match():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    data = request.json
    req_id, status = data.get('request_id'), data.get('status')
    conn = get_db()
    req = conn.execute('SELECT * FROM match_requests WHERE id=? AND receiver_id=?', (req_id, user['id'])).fetchone()
    if req:
        conn.execute('UPDATE match_requests SET status=? WHERE id=?', (status, req_id))
        if status == 'accepted':
            add_notification(req['sender_id'], 'match_accepted', f"{user['name']} accepted your match request!")
        conn.commit()
    conn.close()
    return jsonify({'success': True})

# GROUPS
@app.route('/api/groups', methods=['GET'])
def get_groups():
    conn = get_db()
    rows = conn.execute('''SELECT g.*,u.name as creator_name,
                           (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id=g.id) as member_count
                           FROM study_groups g JOIN users u ON g.creator_id=u.id
                           ORDER BY g.created_at DESC''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/groups', methods=['POST'])
def create_group():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    data = request.json
    conn = get_db()
    cur = conn.execute('INSERT INTO study_groups (name,subject,description,creator_id) VALUES (?,?,?,?)',
                       (data['name'], data['subject'], data.get('description',''), user['id']))
    gid = cur.lastrowid
    conn.execute('INSERT OR IGNORE INTO group_members (group_id,user_id) VALUES (?,?)', (gid, user['id']))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'group_id': gid})

@app.route('/api/groups/<int:gid>/join', methods=['POST'])
def join_group(gid):
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO group_members (group_id,user_id) VALUES (?,?)', (gid, user['id']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/groups/<int:gid>/messages', methods=['GET'])
def get_messages(gid):
    conn = get_db()
    rows = conn.execute('''SELECT gm.*,u.name as author_name FROM group_messages gm
                           JOIN users u ON gm.user_id=u.id
                           WHERE gm.group_id=? ORDER BY gm.created_at ASC LIMIT 100''', (gid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/groups/<int:gid>/messages', methods=['POST'])
def send_message(gid):
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    conn = get_db()
    conn.execute('INSERT INTO group_messages (group_id,user_id,message) VALUES (?,?,?)',
                 (gid, user['id'], request.json['message']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# NOTIFICATIONS
@app.route('/api/notifications')
def get_notifications():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20', (user['id'],)).fetchall()
    unread = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0', (user['id'],)).fetchone()[0]
    conn.close()
    return jsonify({'notifications': [dict(r) for r in rows], 'unread': unread})

@app.route('/api/notifications/read', methods=['POST'])
def mark_read():
    user = current_user()
    if not user: return jsonify({'error': 'Not logged in'}), 401
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (user['id'],))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/summarize-pdf', methods=['POST'])
def summarize_pdf():
    data = request.json or {}
    pdf_data = data.get('pdf', '')
    if not pdf_data:
        return jsonify({'error': 'No PDF provided'}), 400

    try:
        import base64
        import io
        pdf_bytes = base64.b64decode(pdf_data)
    except Exception:
        return jsonify({'error': 'Invalid PDF data'}), 400

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = reader.pages[:3]
        extracted = []
        for page in pages:
            text = (page.extract_text() or '').strip()
            if text:
                extracted.append(text)

        combined = ' '.join(extracted).strip()
        if not combined:
            return jsonify({
                'summary': 'Could not extract text from this PDF.',
                'key_points': []
            })

        lines = [line.strip(' -•\t') for line in combined.splitlines() if line.strip()]
        key_points = lines[:5] if lines else combined.split('. ')[:5]

        return jsonify({
            'summary': combined[:600],
            'key_points': [point for point in key_points if point][:5]
        })
    except ImportError:
        return jsonify({
            'summary': 'PDF summarization is not available because the PDF parser dependency is missing.',
            'key_points': []
        })
    except Exception:
        return jsonify({'error': 'Unable to analyze PDF'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
