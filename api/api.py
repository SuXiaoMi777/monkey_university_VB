from functools import wraps
from flask import render_template, Blueprint, redirect, request, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from api.sql import Account

api = Blueprint('api', __name__, template_folder='./templates')

login_manager = LoginManager(api)
login_manager.login_view = 'api.login'
login_manager.login_message = "請先登入"


class User(UserMixin):
    pass


@login_manager.user_loader
def user_loader(username):
    data = Account.get_user(username)
    if data is None:          # 帳號已被停用（例：球員退隊）
        return None
    user = User()
    user.id = data['username']
    user.role = data['role']
    user.name = data['name']
    user.pid = data['pid']        # 球員才有
    user.tid = data['tid']        # 球員所屬隊伍
    user.did = data['did']        # 球經負責的系所（管理範圍）
    user.dname = data['dname']
    return user


def role_required(role):
    """限制頁面只有某個角色能進入；角色不符時導回自己的首頁。"""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role != role:
                flash('您沒有權限使用這個頁面', 'danger')
                return redirect(home_url(current_user.role))
            return view(*args, **kwargs)
        return wrapper
    return decorator


def home_url(role):
    if role == 'admin':
        return url_for('admin.overview')
    if role == 'manager':
        return url_for('manager.playerManager')
    return url_for('player.home')


@api.route('/login', methods=['POST', 'GET'])
def login():
    if current_user.is_authenticated:
        return redirect(home_url(current_user.role))

    if request.method == 'POST':
        username = request.form['account'].strip()
        password = request.form['password']
        data = Account.get_account(username)

        if data is None:
            flash('*沒有此帳號')
            return redirect(url_for('api.login'))

        if not check_password_hash(data['passwordhash'], password):
            flash('*密碼錯誤，請再試一次')
            return redirect(url_for('api.login'))

        user = User()
        user.id = data['username']
        login_user(user)
        return redirect(home_url(data['role']))

    return render_template('login.html')


@api.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))
