from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'hackathon-secret-key'

# Database setup
DB_FILE = 'app.db'

def init_db():
    """Create database and tables if they don't exist"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
    
    # Facilities table
    c.execute('''CREATE TABLE IF NOT EXISTS facilities 
                 (id INTEGER PRIMARY KEY, name TEXT, sport TEXT, count INTEGER)''')
    
    # Time slots table (for each facility)
    c.execute('''CREATE TABLE IF NOT EXISTS slots 
                 (id INTEGER PRIMARY KEY, facility_id INTEGER, court_number INTEGER, 
                  date TEXT, time TEXT, is_booked INTEGER DEFAULT 0)''')
    
    # Bookings table
    c.execute('''CREATE TABLE IF NOT EXISTS bookings 
                 (id INTEGER PRIMARY KEY, username TEXT, facility_id INTEGER, 
                  court_number INTEGER, date TEXT, time TEXT, formatted_slot TEXT)''')
    
    # Check if facilities table is empty, if so add our facilities
    c.execute('SELECT COUNT(*) FROM facilities')
    if c.fetchone()[0] == 0:
        facilities = [
            ('Volleyball Court', 'Volleyball', 2),
            ('Cricket Net', 'Cricket', 2),
            ('Basketball Court', 'Basketball', 1),
            ('Cricket Field', 'Cricket', 1),
            ('Football Field', 'Football', 1),
            ('Pickleball Court', 'Pickleball', 1),
            ('Badminton Court', 'Badminton', 1),
            ('Table Tennis Table', 'Table Tennis', 2),
            ('Carrom Board', 'Carrom', 2),
        ]
        for name, sport, count in facilities:
            c.execute('INSERT INTO facilities (name, sport, count) VALUES (?, ?, ?)',
                     (name, sport, count))
        
        # Create time slots for each facility for next 7 days
        c.execute('SELECT id, count FROM facilities')
        facs = c.fetchall()
        
        for fac_id, court_count in facs:
            for day_offset in range(7):
                date = (datetime.now() + timedelta(days=day_offset)).strftime('%Y-%m-%d')
                for time_slot in ['9:00 AM', '10:00 AM', '11:00 AM', '12:00 PM', 
                                 '2:00 PM', '3:00 PM', '4:00 PM', '5:00 PM', '6:00 PM']:
                    for court_num in range(1, court_count + 1):
                        c.execute('''INSERT INTO slots 
                                   (facility_id, court_number, date, time, is_booked) 
                                   VALUES (?, ?, ?, ?, 0)''',
                                (fac_id, court_num, date, time_slot))
    
    conn.commit()
    conn.close()

# Initialize database
init_db()

# HOME PAGE
@app.route('/')
def home():
    return render_template('index.html')

# LOGIN/SIGNUP PAGE
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        action = request.form.get('action')  # 'login' or 'signup'
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        if action == 'signup':
            try:
                c.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                         (username, password))
                conn.commit()
                session['username'] = username
                conn.close()
                return redirect('/book')
            except sqlite3.IntegrityError:
                error = "Username already exists!"
            conn.close()
        
        elif action == 'login':
            c.execute('SELECT password FROM users WHERE username = ?', (username,))
            result = c.fetchone()
            conn.close()
            
            if result and result[0] == password:
                session['username'] = username
                return redirect('/book')
            else:
                error = "Invalid username or password!"
    
    return render_template('login.html', error=error)

# BOOKING PAGE
@app.route('/book', methods=['GET', 'POST'])
def book():
    if 'username' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get all facilities
    c.execute('SELECT id, name, sport, count FROM facilities')
    facilities = c.fetchall()
    
    # Get available slots for selected facility (default to first facility)
    selected_facility = request.args.get('facility', '1')
    available_slots = []
    
    c.execute('''SELECT s.id, f.name, s.court_number, s.date, s.time 
                FROM slots s 
                JOIN facilities f ON s.facility_id = f.id 
                WHERE s.facility_id = ? AND s.is_booked = 0
                ORDER BY s.date, s.time''', (selected_facility,))
    available_slots = c.fetchall()
    
    # Handle booking
    if request.method == 'POST':
        slot_id = request.form.get('slot_id')
        
        if slot_id:
            c.execute('SELECT facility_id, court_number, date, time FROM slots WHERE id = ?',
                     (slot_id,))
            slot_data = c.fetchone()
            
            if slot_data:
                facility_id, court_num, date, time = slot_data
                
                # Mark slot as booked
                c.execute('UPDATE slots SET is_booked = 1 WHERE id = ?', (slot_id,))
                
                # Create booking record
                formatted = f"{date} at {time} (Court {court_num})"
                c.execute('''INSERT INTO bookings 
                           (username, facility_id, court_number, date, time, formatted_slot)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                         (session['username'], facility_id, court_num, date, time, formatted))
                
                conn.commit()
        
        conn.close()
        return redirect('/my-bookings')
    
    conn.close()
    return render_template('book.html', 
                         facilities=facilities, 
                         selected_facility=int(selected_facility),
                         available_slots=available_slots)

# MY BOOKINGS PAGE
@app.route('/my-bookings')
def my_bookings():
    if 'username' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''SELECT f.name, b.formatted_slot, b.id 
                FROM bookings b
                JOIN facilities f ON b.facility_id = f.id
                WHERE b.username = ?
                ORDER BY b.date, b.time''', (session['username'],))
    bookings = c.fetchall()
    
    conn.close()
    return render_template('my_books.html', bookings=bookings, username=session['username'])

# CANCEL BOOKING
@app.route('/cancel/<int:booking_id>')
def cancel_booking(booking_id):
    if 'username' not in session:
        return redirect('/login')
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get booking details
    c.execute('''SELECT facility_id, court_number, date, time FROM bookings 
                WHERE id = ? AND username = ?''', 
             (booking_id, session['username']))
    booking = c.fetchone()
    
    if booking:
        facility_id, court_num, date, time = booking
        
        # Mark slot as available
        c.execute('''UPDATE slots SET is_booked = 0 
                    WHERE facility_id = ? AND court_number = ? 
                    AND date = ? AND time = ?''',
                 (facility_id, court_num, date, time))
        
        # Delete booking
        c.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
        
        conn.commit()
    
    conn.close()
    return redirect('/my-bookings')

# LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
