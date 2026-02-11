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


def ampm_to_24(time_str):
    """Convert times like '9:00 AM' or '12:30 PM' to '09:00' 24h format."""
    try:
        t = datetime.strptime(time_str.strip(), '%I:%M %p')
        return t.strftime('%H:%M')
    except Exception:
        # try if already in HH:MM
        try:
            t = datetime.strptime(time_str.strip(), '%H:%M')
            return t.strftime('%H:%M')
        except Exception:
            return time_str


def _24_to_ampm(time24):
    try:
        t = datetime.strptime(time24.strip(), '%H:%M')
        hour = t.hour
        minute = t.minute
        suffix = 'AM' if hour < 12 else 'PM'
        hour12 = hour % 12
        if hour12 == 0:
            hour12 = 12
        return f"{hour12}:{minute:02d} {suffix}"
    except Exception:
        return time24

# Initialize database
init_db()

# HOME PAGE
@app.route('/')
def home():
    return render_template('index.html')


# SPORT SELECTION PAGE
@app.route('/select-sport')
def select_sport():
    if 'username' not in session:
        return redirect('/login')

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # list distinct sports and count of facilities per sport
    c.execute('SELECT sport, COUNT(*) FROM facilities GROUP BY sport ORDER BY sport')
    sports = c.fetchall()
    conn.close()
    return render_template('select_sport.html', sports=sports)

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
                return redirect('/select-sport')
            except sqlite3.IntegrityError:
                error = "Username already exists!"
            conn.close()
        
        elif action == 'login':
            c.execute('SELECT password FROM users WHERE username = ?', (username,))
            result = c.fetchone()
            conn.close()
            
            if result and result[0] == password:
                session['username'] = username
                return redirect('/select-sport')
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
    
    # Determine selected facility: allow selecting by facility id or by sport name
    selected_facility = request.args.get('facility')
    sport_param = request.args.get('sport')

    if not selected_facility and sport_param:
        # pick first facility matching the sport
        c.execute('SELECT id FROM facilities WHERE sport = ? LIMIT 1', (sport_param,))
        row = c.fetchone()
        selected_facility = str(row[0]) if row else '1'

    if not selected_facility:
        selected_facility = '1'
    available_slots = []
    
    c.execute('''SELECT s.id, f.name, s.court_number, s.date, s.time 
                FROM slots s 
                JOIN facilities f ON s.facility_id = f.id 
                WHERE s.facility_id = ? AND s.is_booked = 0
                ORDER BY s.date, s.time''', (selected_facility,))
    available_slots = c.fetchall()
    
    # Handle booking
    booking_error = None
    if request.method == 'POST':
        # New form uses slot_time (date|HH:MM) and selected_court
        slot_time_val = request.form.get('slot_time') or request.form.get('slot_radio')
        selected_court = request.form.get('selected_court') or request.form.get('court')

        if slot_time_val:
            try:
                date_part, time_part = slot_time_val.split('|')
            except ValueError:
                # maybe just time
                parts = slot_time_val.split('|')
                date_part = request.form.get('date') or parts[0]
                time_part = parts[-1]

            # Normalize time formats for comparison
            time_24 = time_part.strip()
            time_ampm = _24_to_ampm(time_24)

            # Look for matching slot in DB
            c.execute('''SELECT id, is_booked, facility_id, court_number, date, time FROM slots
                         WHERE facility_id = ? AND court_number = ? AND date = ?
                         AND (time = ? OR time = ? OR time LIKE ?)
                         LIMIT 1''',
                      (selected_facility, selected_court, date_part, time_ampm, time_24, time_24 + '%'))
            slot_row = c.fetchone()

            if slot_row:
                slot_id_db, is_booked, facility_id, court_num, date_db, time_db = slot_row

                if is_booked:
                    booking_error = 'Sorry — that slot was just booked by someone else.'
                else:
                    # mark booked and insert booking
                    c.execute('UPDATE slots SET is_booked = 1 WHERE id = ?', (slot_id_db,))
                    formatted = f"{date_db} at {time_db} (Court {court_num})"
                    c.execute('''INSERT INTO bookings
                                 (username, facility_id, court_number, date, time, formatted_slot)
                                 VALUES (?, ?, ?, ?, ?, ?)''',
                              (session['username'], facility_id, court_num, date_db, time_db, formatted))
                    conn.commit()
                    conn.close()
                    return redirect('/my-bookings')
            else:
                booking_error = 'Selected slot is not available.'

        else:
            booking_error = 'No slot selected.'

    conn.close()
    return render_template('book.html', 
                         facilities=facilities, 
                         selected_facility=int(selected_facility),
                         available_slots=available_slots,
                         booking_error=booking_error)
    
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


@app.route('/api/booked_slots')
def api_booked_slots():
    facility_id = request.args.get('facility')
    date_q = request.args.get('date')
    if not facility_id or not date_q:
        return {'error': 'missing params'}, 400

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT court_number, time FROM slots WHERE facility_id = ? AND date = ? AND is_booked = 1''',
              (facility_id, date_q))
    rows = c.fetchall()
    conn.close()

    result = []
    for court_num, time_val in rows:
        time24 = ampm_to_24(time_val)
        result.append({'court': court_num, 'time': time24})
    return result

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
