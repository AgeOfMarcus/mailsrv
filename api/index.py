#from dotenv import load_dotenv; load_dotenv() #DEV

# mailjet
from mailjet_rest import Client
import os

mailjet = Client(auth=(os.getenv('MAILJET_KEY'), os.getenv('MAILJET_SECRET')), version='v3.1')

def send_email(from_, to, subject, html):
    return mailjet.send.create(data={
        'Messages': [
            {
                'From': {
                    'Email': from_,
                },
                'To': [{'Email': email} for email in to] if type(to) == list else [{'Email': to}],
                'Subject': subject,
                'HTMLPart': html
            }
        ]
    })

from flask import Flask, jsonify, request, render_template
from flask_limiter import Limiter
from flask_cors import CORS
import uuid

# database

from sqlalchemy import create_engine
import sqlalchemy, pymysql

pymysql.install_as_MySQLdb()

class ReplDBSQL(object):
    def __init__(self, db_uri: str):
        self.db_uri = db_uri
        self.engine = create_engine(db_uri, pool_size=5, pool_recycle=3600)

    def run(self, query: str, vals: dict={}):
        conn = self.engine.connect()
        query = conn.execute(sqlalchemy.text(query), vals)
        try:
            res = query.fetchall()
        except:
            res = None
        conn.commit()
        conn.close()
        if res:
            return [dict(row._mapping) for row in res]
        return []
    
db = ReplDBSQL(os.getenv('DB_URI'))
db.run('''
CREATE TABLE IF NOT EXISTS mail_users (
    ID INTEGER PRIMARY KEY AUTO_INCREMENT,
    username TEXT NOT NULL,
    api_key TEXT NOT NULL
)
''')
db.run('''
CREATE TABLE IF NOT EXISTS mail_verified (
    ID INTEGER PRIMARY KEY AUTO_INCREMENT,
    token TEXT NOT NULL,
    verified BOOLEAN NOT NULL
)
''')

class MailDB(object):
    def __init__(self, db: ReplDBSQL):
        self.db = db
    
    # get user
    def get_by_username(self, username: str):
        res = db.run('SELECT * FROM mail_users WHERE username = :u', {
            'u': username
        })
        return res[0] if not res == [] else False
    def get_by_key(self, key: str):
        res = db.run('SELECT * FROM mail_users WHERE api_key = :k', {
            'k': key
        })
        return res[0] if not res == [] else False
    
    # create user
    def create_user(self, username: str):
        key = str(uuid.uuid4())
        db.run('INSERT INTO mail_users (username, api_key) VALUES (:u, :k)', {
            'u': username,
            'k': key
        })
        return {'username': username, 'api_key': key}
    
    # verification
    def create_verification_token(self):
        token = str(uuid.uuid4())
        db.run('INSERT INTO mail_verified (token, verified) VALUES (:t, :v)', {
            't': token,
            'v': False
        }) 
        return token
    
    def check_verification_token(self, token: str):
        res = db.run('SELECT verified FROM mail_verified WHERE token = :t', {
            't': token
        })
        return bool(res[0]['verified']) if not res == [] else None
    
    def set_verification_token(self, token: str, verified: bool):
        db.run('UPDATE mail_verified SET verified = :v WHERE token = :t', {
            't': token,
            'v': verified
        })
    
    def delete_verification_token(self, token: str):
        db.run('DELETE FROM mail_verified WHERE token = :t', {
            't': token
        })

mdb = MailDB(db)

# app

app = Flask(__name__)
CORS(app)
ADMIN_KEY = os.getenv('ADMIN_KEY')


limiter = Limiter(
    app=app,
    key_func=lambda: request.json['key'],
    default_limits=[]
)

@app.route('/')
def app_index():
    if (request.args.get('key') == ADMIN_KEY):
        if (username := request.args.get('username')):
            if (user := mdb.get_by_username(username)):
                pass
            else:
                user = mdb.create_user(username)
            return render_template('index.html', logged_in=True, user=user)
        else:
            return 'err: no username provided'
    return render_template('index.html', logged_in=False)

@app.route('/mail/verify')
def app_mail_verify():
    if request.args.get('clicked'):
        check = mdb.check_verification_token(request.args.get('token'))
        if check == None:
            return 'err: invalid token'
        elif check == False:
            mdb.set_verification_token(request.args.get('token'), True)
            return render_template('close.html')
        else:
            return 'already verified'
    else:
        return render_template('click.html', token=request.args['token'])
    return '', 404
    


@app.route('/api/mail/send', methods=['POST'])
@limiter.limit('50 per day')
def api_mail_send():
    if (user := mdb.get_by_key(request.json.get('key'))):
        to = request.json['to']
        if type(to) == str:
            to = to.split(';') # separate emails by semicolom
        subject = request.json['subject']
        html = request.json['html']
        res = send_email(f'{user["username"]}@mailsrv.marcusj.org', to, subject, html) # what
        if res.status_code == 200:
            return jsonify(res.json())
        else:
            return jsonify({'ok': False, 'error': res.text})
    return jsonify({'ok': False, 'error': 'no key'})

@app.route('/api/mail/verify/send', methods=['POST'])
@limiter.limit('100 per day')
def api_mail_verify_send():
    if not (user := mdb.get_by_key(request.json.get('key'))):
        return jsonify({'ok': False, 'error': 'no key'})
    token = mdb.create_verification_token()
    res = send_email(f'verify.{user["username"]}@mailsrv.marcusj.org', request.json['to'], 'Verify your email address', f'<a href="https://mailsrv.marcusj.org/mail/verify?token={token}">Click here to verify</a>')
    if res.status_code == 200:
        return jsonify({'ok': True, 'token': token, 'res': res.json()})
    else:
        return jsonify({'ok': False, 'error': res.json()})

@app.route('/api/mail/verify/check', methods=['POST'])
def api_mail_verify_check():
    if not (user := mdb.get_by_key(request.json.get('key'))):
        return jsonify({'ok': False, 'error': 'no key'})
    verified = mdb.check_verification_token(request.json['token'])
    # ideally i'd like to delete the token after verified=true
    # but id need to make sure the check is done before the delete
    return jsonify({'ok': True, 'verified': verified})