import csv
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
STUDENTS_CSV = os.path.join(DATA_DIR, 'students.csv')
ATTENDANCE_CSV = os.path.join(DATA_DIR, 'attendance.csv')
ALERTS_CSV = os.path.join(DATA_DIR, 'alerts.csv')

# Ensure data dir and files exist
os.makedirs(DATA_DIR, exist_ok=True)
for path, header in [
    (STUDENTS_CSV, ['student_id','name','programme','part','course_code','group','phone','email']),
    (ATTENDANCE_CSV, ['student_id','name','course_code','group','week','class_label','hours','date']),
    (ALERTS_CSV, ['student_id','name','course_code','group','percent','count','sent7','sent10','sent15'])
]:
    if not os.path.exists(path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)

def load_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def append_csv(path, row):
    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def save_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def sum_hours_missed(course_code, group):
    attendance = load_csv(ATTENDANCE_CSV)
    missed = {}
    for a in attendance:
        if a['course_code'] == course_code and a['group'] == group:
            sid = a['student_id']
            hrs = float(a['hours'])
            missed[sid] = missed.get(sid, 0.0) + hrs
    return missed

def compute_percentages(course_code, group, total_hours):
    students = [s for s in load_csv(STUDENTS_CSV) if s['course_code'] == course_code and s['group'] == group]
    missed = sum_hours_missed(course_code, group)
    result = []
    for s in students:
        sid = s['student_id']
        hours_missed = missed.get(sid, 0.0)
        percent = round((hours_missed / float(total_hours)) * 100, 2) if float(total_hours) > 0 else 0.0
        thresholds = []
        for t in [7,10,15]:
            if percent >= t:
                thresholds.append(f'{t}%')
        result.append({
            'student_id': sid,
            'name': s['name'],
            'hours_missed': int(hours_missed) if hours_missed.is_integer() else hours_missed,
            'percent': percent,
            'thresholds': ', '.join(thresholds) if thresholds else '-',
            'phone': s['phone'],
            'email': s['email'],
        })
    return result

def load_alerts_map(course_code, group):
    alerts = load_csv(ALERTS_CSV)
    m = {}
    for a in alerts:
        if a['course_code'] == course_code and a['group'] == group:
            m[a['student_id']] = a
    return m

def upsert_alert(student_id, name, course_code, group, percent, hit7=False, hit10=False, hit15=False):
    alerts = load_csv(ALERTS_CSV)
    found = None
    for a in alerts:
        if a['student_id'] == student_id and a['course_code'] == course_code and a['group'] == group:
            found = a
            break
    if found:
        found['percent'] = str(percent)
        found['count'] = str(int(found.get('count', '0')) + 1)
        if hit7:  found['sent7']  = 'yes'
        if hit10: found['sent10'] = 'yes'
        if hit15: found['sent15'] = 'yes'
    else:
        alerts.append({
            'student_id': student_id,
            'name': name,
            'course_code': course_code,
            'group': group,
            'percent': str(percent),
            'count': '1',
            'sent7': 'yes' if hit7 else '',
            'sent10': 'yes' if hit10 else '',
            'sent15': 'yes' if hit15 else ''
        })
    save_csv(ALERTS_CSV, alerts, ['student_id','name','course_code','group','percent','count','sent7','sent10','sent15'])

def build_email_text(name, course_code, percent):
    block_note = ""
    if percent >= 20:
        block_note = "\nNote: A student with >=20% absenteeism may be barred from the final exam."
    body = (
        f"Attendance Alert:\n\n"
        f"Please be informed that {name} has {percent}% class absenteeism (course {course_code}).\n"
        f"Kindly contact your lecturer as soon as possible."
        f"{block_note}\n\n"
        f"This is an automated message from AAMAS."
    )
    return body

def send_email(to_email, subject, body, smtp_host='localhost', smtp_port=25, user=None, password=None):
    # Works with a local SMTP server (e.g., postfix) or set custom host/credentials
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = 'aamas@localhost'
    msg['To'] = to_email
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if user and password:
                server.starttls()
                server.login(user, password)
            server.send_message(msg)
        return True, "Email sent"
    except Exception as e:
        return False, f"Email failed: {e}"

def send_sms_stub(phone, text):
    # Stub to keep it offline. Log-only; integrate later with a real SMS gateway.
    print(f"[SMS] to {phone}: {text}")
    return True, "SMS logged"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload-students', methods=['GET', 'POST'])
def upload_students():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            return render_template('upload_students.html', msg="No file selected")
        # Save/overwrite the master students.csv with uploaded content
        try:
            content = file.stream.read().decode('utf-8').splitlines()
            reader = csv.DictReader(content)
            required = ['student_id','name','programme','part','course_code','group','phone','email']
            if reader.fieldnames != required:
                return render_template('upload_students.html', msg=f"Invalid header. Expected: {', '.join(required)}")
            save_csv(STUDENTS_CSV, list(reader), required)
            return render_template('upload_students.html', msg="Students uploaded successfully")
        except Exception as e:
            return render_template('upload_students.html', msg=f"Upload failed: {e}")
    return render_template('upload_students.html')

@app.route('/record-absence', methods=['GET', 'POST'])
def record_absence():
    if request.method == 'POST':
        data = {
            'student_id': request.form.get('student_id', '').strip(),
            'name': '',  # resolve from students list
            'course_code': request.form.get('course_code', '').strip(),
            'group': request.form.get('group', '').strip(),
            'week': request.form.get('week', '').strip(),
            'class_label': request.form.get('class_label', '').strip(),
            'hours': request.form.get('hours', '0').strip(),
            'date': request.form.get('date', '').strip()
        }
        # Basic validation and name resolution
        students = load_csv(STUDENTS_CSV)
        match = next((s for s in students if s['student_id'] == data['student_id']), None)
        if not match:
            return render_template('record_absence.html', msg="Student not found")
        data['name'] = match['name']
        try:
            float(data['hours'])
        except:
            return render_template('record_absence.html', msg="Hours must be numeric")

        append_csv(ATTENDANCE_CSV, data)
        return render_template('record_absence.html', msg="Absence recorded")
    return render_template('record_absence.html')

@app.route('/report', methods=['GET'])
def report():
    course_code = request.args.get('course_code')
    group = request.args.get('group')
    total_hours = request.args.get('total_hours')
    rows = None
    if course_code and group and total_hours:
        rows = compute_percentages(course_code, group, total_hours)
    return render_template('report.html', rows=rows, course_code=course_code, group=group, total_hours=total_hours)

@app.route('/alerts', methods=['GET'])
def alerts():
    course_code = request.args.get('course_code')
    group = request.args.get('group')
    total_hours = request.args.get('total_hours')
    rows = None
    if course_code and group and total_hours:
        computed = compute_percentages(course_code, group, total_hours)
        alert_map = load_alerts_map(course_code, group)
        rows = []
        for r in computed:
            if r['percent'] >= 7:
                a = alert_map.get(r['student_id'], {})
                rows.append({
                    **r,
                    'sent7': a.get('sent7', ''),
                    'sent10': a.get('sent10', ''),
                    'sent15': a.get('sent15', ''),
                    'count': a.get('count', '0')
                })
    return render_template('alerts.html', rows=rows, course_code=course_code, group=group, total_hours=total_hours)

@app.route('/send-alerts', methods=['POST'])
def send_alerts():
    course_code = request.form.get('course_code')
    group = request.form.get('group')
    total_hours = request.form.get('total_hours')
    selected = request.form.getlist('selected')

    computed = compute_percentages(course_code, group, total_hours)
    target = [r for r in computed if r['student_id'] in selected]

    sent_count = 0
    for r in target:
        percent = r['percent']
        hit7 = percent >= 7
        hit10 = percent >= 10
        hit15 = percent >= 15

        subject = f"Attendance Alert ({course_code})"
        body = build_email_text(r['name'], course_code, percent)
        ok_email, _ = send_email(r['email'], subject, body)

        # SMS stub (logged to console only)
        sms_text = f"{r['name']} has {percent}% absenteeism for {course_code}. Please advise."
        ok_sms, _ = send_sms_stub(r['phone'], sms_text)

        if ok_email or ok_sms:
            upsert_alert(r['student_id'], r['name'], course_code, group, percent, hit7, hit10, hit15)
            sent_count += 1

    msg = f"Alerts processed for {sent_count} student(s)"
    return render_template('alerts.html', msg=msg, course_code=course_code, group=group, total_hours=total_hours)

if __name__ == '__main__':
    app.run(debug=True)
