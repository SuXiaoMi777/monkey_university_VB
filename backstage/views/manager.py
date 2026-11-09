from datetime import date
from flask import Blueprint, render_template, request, url_for, redirect, flash, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
import psycopg2
from api.api import role_required
from api.sql import Lookup, Player, Event, Attendance, db_error_message

manager = Blueprint('manager', __name__, template_folder='../templates')

STATUS_LIST = ['出席', '遲到', '請假', '缺席']


def none_if_empty(value):
    value = (value or '').strip()
    return value or None


def this_month():
    return date.today().strftime('%Y-%m')


def scope():
    """目前登入球經負責的系所代碼；所有查詢都用它限制管理範圍。"""
    return current_user.did


def back_to(endpoint):
    return redirect(request.full_path if request.args else url_for(endpoint))


@manager.route('/', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def home():
    return redirect(url_for('manager.playerManager'))


# =====================================================================
# 球員管理：F11 查詢、F1 新增、F9 註銷
# =====================================================================
@manager.route('/playerManager', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def playerManager():
    if request.method == 'POST':
        if 'edit' in request.values:
            return redirect(url_for('manager.editPlayer', pid=request.values.get('edit')))

        if 'retire' in request.values:                      # F9 註銷球員
            pid, status = request.values.get('retire').split(':')
            player = Player.get_player(pid, scope())
            if player is None:
                abort(404)
            Player.retire_player(pid, status, scope())
            flash(f'已將 {player["pname"]} 註銷為「{status}」，歷史出席紀錄仍保留')
            return back_to('manager.playerManager')

    # F11 依條件查詢（只會查到自己系所的隊伍）
    tid = none_if_empty(request.args.get('tid'))
    did = none_if_empty(request.args.get('did'))
    posid = none_if_empty(request.args.get('posid'))
    status = request.args.get('status', '在隊')
    players = Player.search(scope(), tid=tid, did=did, posid=posid, status=none_if_empty(status))

    return render_template(
        'playerManager.html',
        user=current_user.name,
        players=players,
        teams=Lookup.teams(scope()),
        departments=Lookup.departments(),
        positions=Lookup.positions(),
        filters={'tid': tid, 'did': did, 'posid': posid, 'status': status},
        today=date.today().isoformat(),
        my_did=scope(),
    )


@manager.route('/addPlayer', methods=['POST'])
@login_required
@role_required('manager')
def addPlayer():                                             # F1 球員建檔
    form = request.form
    data = {
        'pid': form['pid'].strip(),
        'pname': form['pname'].strip(),
        'gender': form['gender'],
        'phone': none_if_empty(form.get('phone')),
        'joindate': form['joindate'],
        'jerseyno': none_if_empty(form.get('jerseyno')),
        'tid': form['tid'],
        'did': form['did'],
        'posid': none_if_empty(form.get('posid')),
    }
    if not any(str(t['tid']) == data['tid'] for t in Lookup.teams(scope())):
        flash('新增失敗：只能把球員加入自己系所的隊伍', 'danger')
        return redirect(url_for('manager.playerManager'))

    password = form.get('password') or 'player123'
    try:
        Player.create_player(data, generate_password_hash(password), scope())
        flash(f'已新增球員 {data["pname"]}，登入帳號為 {data["pid"]}')
    except psycopg2.Error as e:
        flash('新增失敗：' + db_error_message(e), 'danger')
    return redirect(url_for('manager.playerManager'))


@manager.route('/editPlayer', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def editPlayer():                                            # F5 球員異動
    if request.method == 'POST':
        form = request.form
        data = {
            'pid': form['pid'],
            'pname': form['pname'].strip(),
            'phone': none_if_empty(form.get('phone')),
            'jerseyno': none_if_empty(form.get('jerseyno')),
            'did': form['did'],
            'posid': none_if_empty(form.get('posid')),
        }
        try:
            if Player.update_player(data, scope()):
                flash(f'已更新 {data["pname"]} 的資料')
            else:
                flash('修改失敗：找不到這位球員，或不在您的管理範圍', 'danger')
            return redirect(url_for('manager.playerManager'))
        except psycopg2.Error as e:
            flash('修改失敗：' + db_error_message(e), 'danger')
            return redirect(url_for('manager.editPlayer', pid=data['pid']))

    player = Player.get_player(request.args.get('pid'), scope())
    if player is None:
        abort(404)
    return render_template(
        'editPlayer.html',
        user=current_user.name,
        data=player,
        departments=Lookup.departments(),
        positions=Lookup.positions(),
    )


@manager.route('/playerAttendance', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def playerAttendance():                                      # F12 明細、F6 修正
    pid = request.values.get('pid')
    month = request.values.get('month') or this_month()
    player = Player.get_player(pid, scope())
    if player is None:
        abort(404)

    if request.method == 'POST':
        count = Attendance.update_record(pid, request.form['eid'], request.form['astatus'],
                                         request.form.get('note'), scope())
        if count:
            flash('已修正出席狀態')
        else:
            flash('找不到這筆紀錄', 'danger')
        return redirect(url_for('manager.playerAttendance', pid=pid, month=month))

    records = Attendance.player_month(pid, month + '-01')
    summary = {s: sum(1 for r in records if r['astatus'] == s) for s in STATUS_LIST}
    return render_template(
        'playerAttendance.html',
        user=current_user.name,
        player=player,
        records=records,
        summary=summary,
        month=month,
        status_list=STATUS_LIST,
    )


# =====================================================================
# 活動管理：F2 新增、F8 註銷、F10 刪除、F3 點名
# =====================================================================
@manager.route('/eventManager', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def eventManager():
    if request.method == 'POST':
        if 'rollcall' in request.values:
            return redirect(url_for('manager.rollcall', eid=request.values.get('rollcall')))

        if 'cancel' in request.values:                      # F8 註銷活動
            if Event.cancel_event(request.values.get('cancel'), scope()):
                flash('已註銷活動，不會計入出席率')
            else:
                flash('這場活動已經是取消狀態', 'warning')

        elif 'delete' in request.values:                    # F10 刪除錯誤活動
            if Event.delete_event(request.values.get('delete'), scope()):
                flash('已刪除活動')
            else:
                flash('這場活動已經有出席紀錄，不能刪除；活動取消請改用「註銷」', 'warning')

        return back_to('manager.eventManager')

    tid = none_if_empty(request.args.get('tid'))
    month = request.args.get('month', this_month())
    events = Event.list_events(scope(), tid=tid, month=none_if_empty(month))
    return render_template(
        'eventManager.html',
        user=current_user.name,
        events=events,
        teams=Lookup.teams(scope()),
        venues=Lookup.venues(),
        semester=Lookup.current_semester(),
        filters={'tid': tid, 'month': month},
    )


@manager.route('/addEvent', methods=['POST'])
@login_required
@role_required('manager')
def addEvent():                                              # F2 建立活動排程
    form = request.form
    data = {k: form[k] for k in ('eventdate', 'starttime', 'endtime', 'eventtype',
                                 'semester', 'tid', 'vid')}
    try:
        if Event.create_event(data, scope()):
            flash(f'已建立 {data["eventdate"]} 的{data["eventtype"]}')
        else:
            flash('建立失敗：只能替自己系所的隊伍建立活動', 'danger')
    except psycopg2.Error as e:
        flash('建立失敗：' + db_error_message(e), 'danger')
    return redirect(url_for('manager.eventManager', month=data['eventdate'][:7]))


@manager.route('/rollcall', methods=['GET', 'POST'])
@login_required
@role_required('manager')
def rollcall():                                              # F3 批次登記出席
    eid = request.values.get('eid')
    event = Event.get_event(eid, scope())
    if event is None:                                        # 別系的活動或不存在
        abort(404)

    if request.method == 'POST':
        pids = request.form.getlist('pid')
        statuses = [request.form.get(f'status_{p}') for p in pids]
        notes = [request.form.get(f'note_{p}', '') for p in pids]
        Attendance.save_rollcall(eid, pids, statuses, notes)
        flash(f'已儲存 {event["eventdate"]} {event["teamname"]} 的點名結果（{len(pids)} 人）')
        return redirect(url_for('manager.eventManager', month=event['eventdate'].strftime('%Y-%m')))

    return render_template(
        'rollcall.html',
        user=current_user.name,
        event=event,
        roster=Attendance.roster(eid),
        status_list=STATUS_LIST,
    )


# =====================================================================
# 場地查詢：F13（場地各系共用，顯示所有隊伍的預約）
# =====================================================================
@manager.route('/venue', methods=['GET'])
@login_required
@role_required('manager')
def venue():
    venues = Lookup.venues()
    vid = request.args.get('vid') or str(venues[0]['vid'])
    start = request.args.get('date') or date.today().isoformat()
    schedule = Event.venue_schedule(vid, start)
    return render_template(
        'venue.html',
        user=current_user.name,
        venues=venues,
        vid=int(vid),
        start=start,
        schedule=schedule,
        my_did=scope(),
    )
