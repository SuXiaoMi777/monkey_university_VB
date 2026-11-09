from datetime import date
from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from api.api import role_required
from api.sql import Account, Analysis, Attendance, Event, Lookup, Player

player = Blueprint('player', __name__, template_folder='../templates')

STATUS_LIST = ['出席', '遲到', '請假', '缺席']


@player.route('/', methods=['GET'])
@login_required
@role_required('player')
def home():                                                  # F15 出席率、F12 月份明細
    semester = Lookup.current_semester()
    month = request.args.get('month') or date.today().strftime('%Y-%m')
    records = Attendance.player_month(current_user.pid, month + '-01')
    summary = {s: sum(1 for r in records if r['astatus'] == s) for s in STATUS_LIST}
    return render_template(
        'home.html',
        user=current_user.name,
        player=Player.get_player(current_user.pid),
        semester=semester,
        stat=Analysis.player_summary(current_user.pid, semester),
        records=records,
        summary=summary,
        month=month,
    )


@player.route('/leave', methods=['GET', 'POST'])
@login_required
@role_required('player')
def leave():                                                 # F4 請假
    if request.method == 'POST':
        eid = request.form['eid']
        if 'cancel' in request.form:
            count = Attendance.cancel_leave(current_user.pid, eid)
            flash('已取消請假') if count else flash('這場活動無法取消請假', 'danger')
        else:
            note = request.form.get('note', '').strip()
            if not note:
                flash('請填寫請假原因', 'danger')
            else:
                rows = Attendance.request_leave(current_user.pid, eid, note)
                flash('已送出請假') if rows else flash('這場活動已經開始或已取消，無法請假', 'danger')
        return redirect(url_for('player.leave'))

    return render_template(
        'leave.html',
        user=current_user.name,
        events=Event.upcoming_for_player(current_user.pid),
    )


@player.route('/profile', methods=['GET', 'POST'])
@login_required
@role_required('player')
def profile():                                               # F7 修改個人資料
    if request.method == 'POST':
        if 'phone' in request.form:
            Player.update_phone(current_user.pid, request.form['phone'].strip() or None)
            flash('已更新聯絡電話')
        else:
            account = Account.get_account(current_user.id)
            old, new, confirm = (request.form['old_password'], request.form['new_password'],
                                 request.form['confirm_password'])
            if not check_password_hash(account['passwordhash'], old):
                flash('目前密碼不正確', 'danger')
            elif len(new) < 6:
                flash('新密碼至少需要 6 個字元', 'danger')
            elif new != confirm:
                flash('兩次輸入的新密碼不一致', 'danger')
            else:
                Account.update_password(current_user.id, generate_password_hash(new))
                flash('已更新密碼')
        return redirect(url_for('player.profile'))

    return render_template(
        'profile.html',
        user=current_user.name,
        player=Player.get_player(current_user.pid),
    )
