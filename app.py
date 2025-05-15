import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_very_secret_key_here'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['DATABASE'] = 'file_manager.db'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database
def init_db():
    with sqlite3.connect(app.config['DATABASE']) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                folder_id INTEGER,
                size INTEGER NOT NULL,
                upload_date TEXT NOT NULL,
                FOREIGN KEY (folder_id) REFERENCES folders (id)
            )
        ''')
        conn.commit()

init_db()

# Database helper functions
def get_db():
    return sqlite3.connect(app.config['DATABASE'])

# Utility functions
def get_folder_path(folder_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT path FROM folders WHERE id = ?', (folder_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def get_file_info(file_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT f.name, f.path, fl.name as folder_name 
            FROM files f
            LEFT JOIN folders fl ON f.folder_id = fl.id
            WHERE f.id = ?
        ''', (file_id,))
        return cursor.fetchone()

def get_all_folders():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, path FROM folders ORDER BY name')
        return cursor.fetchall()

def get_files_in_folder(folder_id=None):
    with get_db() as conn:
        cursor = conn.cursor()
        if folder_id:
            cursor.execute('''
                SELECT id, name, size, upload_date 
                FROM files 
                WHERE folder_id = ?
                ORDER BY upload_date DESC
            ''', (folder_id,))
        else:
            cursor.execute('''
                SELECT id, name, size, upload_date 
                FROM files 
                WHERE folder_id IS NULL
                ORDER BY upload_date DESC
            ''')
        return cursor.fetchall()

# Routes
@app.route('/')
def index():
    folders = get_all_folders()
    root_files = get_files_in_folder()
    return render_template('index.html', folders=folders, files=root_files)

@app.route('/folder/<int:folder_id>')
def view_folder(folder_id):
    folders = get_all_folders()
    files = get_files_in_folder(folder_id)
    folder_path = get_folder_path(folder_id)
    return render_template('index.html', folders=folders, files=files, current_folder=folder_id, folder_path=folder_path)

@app.route('/create_folder', methods=['POST'])
def create_folder():
    folder_name = request.form.get('folder_name')
    if not folder_name:
        flash('Folder name is required', 'error')
        return redirect(url_for('index'))

    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(folder_name))
    
    if os.path.exists(folder_path):
        flash('Folder already exists', 'error')
        return redirect(url_for('index'))

    try:
        os.makedirs(folder_path)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO folders (name, path, created_at) VALUES (?, ?, ?)',
                (folder_name, folder_path, datetime.now().isoformat())
            )
            conn.commit()
        flash('Folder created successfully', 'success')
    except Exception as e:
        flash(f'Error creating folder: {str(e)}', 'error')

    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))

    folder_id = request.form.get('folder_id')
    folder_path = app.config['UPLOAD_FOLDER']
    
    if folder_id and folder_id != 'None':
        folder_path = get_folder_path(folder_id)
        if not folder_path:
            flash('Invalid folder selected', 'error')
            return redirect(url_for('index'))

    filename = secure_filename(file.filename)
    file_path = os.path.join(folder_path, filename)
    
    # Check if file exists and add suffix if needed
    counter = 1
    while os.path.exists(file_path):
        name, ext = os.path.splitext(filename)
        file_path = os.path.join(folder_path, f"{name}_{counter}{ext}")
        counter += 1

    try:
        file.save(file_path)
        file_size = os.path.getsize(file_path)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO files (name, path, folder_id, size, upload_date) VALUES (?, ?, ?, ?, ?)',
                (filename, file_path, folder_id if folder_id and folder_id != 'None' else None, 
                 file_size, datetime.now().isoformat())
            )
            conn.commit()
        
        flash('File uploaded successfully', 'success')
    except Exception as e:
        flash(f'Error uploading file: {str(e)}', 'error')

    return redirect(url_for('view_folder', folder_id=folder_id) if folder_id and folder_id != 'None' else url_for('index'))

@app.route('/download/<int:file_id>')
def download_file(file_id):
    file_info = get_file_info(file_id)
    if not file_info:
        flash('File not found', 'error')
        return redirect(url_for('index'))

    filename, filepath, _ = file_info
    directory = os.path.dirname(filepath)
    return send_from_directory(directory, os.path.basename(filepath), as_attachment=True)

@app.route('/delete_file/<int:file_id>')
def delete_file(file_id):
    file_info = get_file_info(file_id)
    if not file_info:
        flash('File not found', 'error')
        return redirect(url_for('index'))

    filename, filepath, _ = file_info
    folder_id = None
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT folder_id FROM files WHERE id = ?', (file_id,))
        result = cursor.fetchone()
        folder_id = result[0] if result else None
        
        try:
            os.remove(filepath)
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            conn.commit()
            flash('File deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting file: {str(e)}', 'error')

    return redirect(url_for('view_folder', folder_id=folder_id) if folder_id else url_for('index'))

@app.route('/delete_folder/<int:folder_id>')
def delete_folder(folder_id):
    folder_path = get_folder_path(folder_id)
    if not folder_path:
        flash('Folder not found', 'error')
        return redirect(url_for('index'))

    # Check if folder has files
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM files WHERE folder_id = ?', (folder_id,))
        file_count = cursor.fetchone()[0]

        if file_count > 0:
            flash('Cannot delete folder with files. Please delete files first.', 'error')
            return redirect(url_for('view_folder', folder_id=folder_id))

        try:
            os.rmdir(folder_path)
            cursor.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
            conn.commit()
            flash('Folder deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting folder: {str(e)}', 'error')

    return redirect(url_for('index'))

# Static files route for cyber theme
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run(debug=True)