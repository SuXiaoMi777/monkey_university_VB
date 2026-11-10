import os
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_login import current_user
from api.api import api, login_manager
from player.views.player import player
from backstage.views.analysis import analysis
from backstage.views.manager import manager
from admin.views.admin import admin
from api.sql import Lookup
load_dotenv()

## Flask-Login : 確保未登入者不能使用系統
app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config.update(SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_HTTPONLY=True)

app.register_blueprint(api, url_prefix='/')
app.register_blueprint(player, url_prefix='/player')          # 球員前台
app.register_blueprint(analysis, url_prefix='/backstage')    # 球經後台：資料分析
app.register_blueprint(manager, url_prefix='/backstage')     # 球經後台：管理功能
app.register_blueprint(admin, url_prefix='/admin')           # 系統管理員

login_manager.init_app(app)


@app.context_processor
def inject_me():
    """讓所有樣板都能用 me 取得登入者資訊（例：球經的系所名稱）。"""
    return {'me': current_user}


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='找不到這個頁面，或資料不在您的管理範圍內。'), 404


@app.route('/')
def index():
    # 首頁列出目前的系隊與學期（未登入也能看）
    return render_template('index.html', teams=Lookup.teams(), semester=Lookup.current_semester())


if __name__ == '__main__':
    app.run(debug=False)
