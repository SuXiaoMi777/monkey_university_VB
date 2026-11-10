"""系統管理員（體育室）：管理系所、系隊、球經帳號、場地，查看全校統計。"""
from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
import psycopg2
from api.api import role_required
from api.sql import Admin, Analysis, Lookup, db_error_message
from backstage.views.analysis import build_charts

admin = Blueprint('admin', __name__, template_folder='../templates')


@admin.route('/')
@login_required
@role_required('admin')
def overview():
    """全校總覽：各系隊人數、活動數、出席率，加上全校統計圖表。"""
    data = build_charts(None, request.args.get('tid'))
    return render_template('adminOverview.html', user=current_user.name,
                           team_summary=Analysis.team_summary(data['semester']), **data)


# ---------------------------------------------------------------------
# 系所與系隊
# ---------------------------------------------------------------------
@admin.route('/teams', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def teams():
    if request.method == 'POST':
        form = request.form
        try:
            if 'add_department' in form:
                Admin.create_department(form['did'].strip().upper(), form['college'].strip(),
                                        form['dname'].strip())
                flash(f'已新增系所：{form["dname"].strip()}')
            elif 'add_team' in form:
                Admin.create_team(form['teamname'].strip(), form['tgender'], form['did'])
                flash(f'已新增隊伍：{form["teamname"].strip()}')
            elif 'delete_team' in form:
                team = next((t for t in Admin.teams() if str(t['tid']) == form['delete_team']), None)
                if team:
                    Admin.delete_team(team['tid'])
                    flash(f'已刪除 {team["teamname"]}，連同 {team["player_cnt"]} 位球員、'
                          f'{team["event_cnt"]} 場活動、{team["record_cnt"]} 筆出席紀錄')
            elif 'delete_department' in form:
                dept = next((d for d in Admin.departments() if d['did'] == form['delete_department']), None)
                if dept:
                    Admin.delete_department(dept['did'])
                    msg = (f'已刪除 {dept["dname"]}，連同 {dept["team_cnt"]} 支系隊、{dept["player_cnt"]} 位球員、'
                           f'{dept["event_cnt"]} 場活動、{dept["manager_cnt"]} 個球經帳號')
                    if dept['outside_cnt']:
                        msg += f'；另有 {dept["outside_cnt"]} 位在其他系隊的同學，就讀系所已改為未填寫'
                    flash(msg)
        except psycopg2.Error as e:
            flash('操作失敗：' + db_error_message(e), 'danger')
        return redirect(url_for('admin.teams'))

    return render_template('adminTeams.html', user=current_user.name,
                           departments=Admin.departments(), teams=Admin.teams())


# ---------------------------------------------------------------------
# 球經帳號
# ---------------------------------------------------------------------
@admin.route('/managers', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def managers():
    if request.method == 'POST':
        form = request.form
        try:
            if 'add_manager' in form:
                password = form.get('password') or 'manager123'
                Admin.create_manager(form['username'].strip(), form['aname'].strip(),
                                     form['did'], generate_password_hash(password))
                flash(f'已建立球經帳號 {form["username"].strip()}')
            elif 'reset' in form:
                Admin.reset_manager_password(form['reset'], generate_password_hash('manager123'))
                flash(f'已將 {form["reset"]} 的密碼重設為 manager123')
            elif 'delete' in form:
                Admin.delete_manager(form['delete'])
                flash(f'已刪除球經帳號 {form["delete"]}')
        except psycopg2.Error as e:
            flash('操作失敗：' + db_error_message(e), 'danger')
        return redirect(url_for('admin.managers'))

    return render_template('adminManagers.html', user=current_user.name,
                           managers=Admin.managers(), departments=Lookup.departments())


# ---------------------------------------------------------------------
# 場地
# ---------------------------------------------------------------------
@admin.route('/venues', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def venues():
    if request.method == 'POST':
        try:
            Admin.create_venue(request.form['vname'].strip(), request.form.get('location', '').strip())
            flash(f'已新增場地：{request.form["vname"].strip()}')
        except psycopg2.Error as e:
            flash('新增失敗：' + db_error_message(e), 'danger')
        return redirect(url_for('admin.venues'))

    return render_template('adminVenues.html', user=current_user.name, venues=Admin.venues())
