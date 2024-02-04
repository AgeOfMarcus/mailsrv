# mailgun
import requests, os

def send_email(from_, to, subject, html):
    return requests.post(
		"https://api.mailgun.net/v3/mailsrv.marcusj.org/messages",
		auth=("api", os.getenv("MAILGUN")),
		data={"from": from_,
			"to": (to if type(to) == list else [to]),
			"subject": subject,
			"html": html})

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
        return res[0] if not res == [] else False
    
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
    app,
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
        if mdb.check_verification_token(request.args.get('token')):
            mdb.set_verification_token(request.args.get('token'), True)
            return render_template('close.html')
        else:
            return 'err: invalid token'
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
        return jsonify({'ok': True}) # do more
    return jsonify({'ok': False, 'error': 'no key'})

@app.route('/api/mail/verify/send', methods=['POST'])
@limiter.limit('100 per day')
def api_mail_verify_send():
    if not (user := mdb.get_by_key(request.json.get('key'))):
        return jsonify({'ok': False, 'error': 'no key'})
    token = mdb.create_verification_token()
    send_email(f'verify.{user["username"]}@mailsrv.marcusj.org', request.json['to'], 'Verify your email address', f'<a href="https://mailsrv.marcusj.org/mail/verify?token={token}">Click here to verify</a>')
    return jsonify({'ok': True, 'token': token})

@app.route('/api/mail/verify/check', methods=['POST'])
def api_mail_verify_check():
    if not (user := mdb.get_by_key(request.json.get('key'))):
        return jsonify({'ok': False, 'error': 'no key'})
    if (verified := mdb.check_verification_token(request.json['token'])):
        mdb.delete_verification_token(request.json['token'])
    return jsonify({'ok': True, 'verified': verified})