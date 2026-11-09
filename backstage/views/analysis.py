from flask import render_template, Blueprint, request, abort
from flask_login import login_required, current_user
from api.api import role_required
from api.sql import Analysis, Lookup

analysis = Blueprint('analysis', __name__, template_folder='../templates')


def build_charts(scope, tid_arg):
    """整理統計圖表資料；球經 scope=自己系所，系統管理員 scope=None（全校）。"""
    semester = Lookup.current_semester()
    teams = Lookup.teams(scope)
    if not teams:
        return dict(semester=semester, teams=[], tid=None, positions=[], position_series=[],
                    ranking=[], rank_names=[], rank_rates=[], months=[], trend_series=[],
                    overview=Analysis.overview(semester, scope))
    tid = int(tid_arg or teams[0]['tid'])
    if not any(t['tid'] == tid for t in teams):
        abort(404)

    # F14 位置戰力分佈：整理成 ECharts 的分組長條圖格式
    rows = Analysis.position_distribution(scope)
    positions = []
    for r in rows:
        if r['posname'] not in positions:
            positions.append(r['posname'])
    # 「未指定」所有隊伍都沒有人時就不顯示
    if '未指定' in positions and all(r['player_cnt'] == 0 for r in rows if r['posname'] == '未指定'):
        positions.remove('未指定')
    position_series = []
    for t in teams:
        counts = {r['posname']: r['player_cnt'] for r in rows if r['tid'] == t['tid']}
        position_series.append({'name': t['teamname'], 'data': [counts.get(p, 0) for p in positions]})

    # F16 出席率排行
    ranking = Analysis.ranking(tid, semester)

    # 各隊每月出席率趨勢
    monthly = Analysis.team_monthly_rate(semester, scope)
    months = sorted({r['month'] for r in monthly})
    trend_series = []
    for t in teams:
        rates = {r['month']: float(r['rate']) for r in monthly if r['tid'] == t['tid']}
        trend_series.append({'name': t['teamname'], 'data': [rates.get(m) for m in months]})

    return dict(
        semester=semester,
        overview=Analysis.overview(semester, scope),
        teams=teams,
        tid=tid,
        positions=positions,
        position_series=position_series,
        ranking=ranking,
        rank_names=[f"#{r['jerseyno']} {r['pname']}" for r in ranking],
        rank_rates=[float(r['attendance_rate']) for r in ranking],
        months=[m[5:] + '月' for m in months],
        trend_series=trend_series,
    )


@analysis.route('/dashboard')
@login_required
@role_required('manager')
def dashboard():
    return render_template('dashboard.html', user=current_user.name,
                           **build_charts(current_user.did, request.args.get('tid')))
