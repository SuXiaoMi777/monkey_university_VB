"""資料存取層：所有 SQL 都集中在這個檔案（對應報告的功能需求 F1–F16 與系統管理功能）。

和老師範例的差異：
  * 查詢結果用 RealDictCursor 回傳「欄位名稱 → 值」的 dict，樣板可以直接寫 row.pname。
    PostgreSQL 會把欄位名稱轉小寫，所以 key 都是小寫（tId → tid）。
  * 讀取後也會 rollback，避免連線停在交易中被放回連線池。
"""
import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
USER = os.getenv('DB_USER')
PASSWORD = os.getenv('DB_PASSWORD')
DBNAME = os.getenv('DB_NAME')
HOST = os.getenv('DB_HOST')
PORT = os.getenv('DB_PORT')


class DB:
    connection_pool = pool.SimpleConnectionPool(
        1, 20,  # 最小和最大連線數
        user=USER,
        password=PASSWORD,
        host=HOST,
        port=PORT,
        dbname=DBNAME
    )

    @staticmethod
    def connect():
        return DB.connection_pool.getconn()

    @staticmethod
    def release(connection):
        DB.connection_pool.putconn(connection)

    @staticmethod
    def execute_input(sql, input):
        """執行 INSERT / UPDATE / DELETE 並 commit，回傳影響筆數。"""
        if not isinstance(input, (tuple, list, dict)):
            raise TypeError(f"Input should be a tuple, list or dict, got: {type(input).__name__}")
        connection = DB.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, input)
                connection.commit()
                return cursor.rowcount
        except psycopg2.Error as e:
            print(f"Error executing SQL: {e}")
            connection.rollback()
            raise e
        finally:
            DB.release(connection)

    @staticmethod
    def execute_returning(sql, input):
        """執行帶有 RETURNING 的寫入並 commit，回傳寫入的資料列。"""
        connection = DB.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, input)
                rows = cursor.fetchall()
                connection.commit()
                return rows
        except psycopg2.Error as e:
            print(f"Error executing SQL: {e}")
            connection.rollback()
            raise e
        finally:
            DB.release(connection)

    @staticmethod
    def transaction(statements):
        """在同一個交易中依序執行多句 SQL：全部成功才 commit，任何一句失敗就全部取消。
        statements = [(sql, params), ...]"""
        connection = DB.connect()
        try:
            with connection.cursor() as cursor:
                for sql, params in statements:
                    cursor.execute(sql, params)
            connection.commit()
        except psycopg2.Error as e:
            print(f"Error executing SQL: {e}")
            connection.rollback()
            raise e
        finally:
            DB.release(connection)

    @staticmethod
    def fetchall(sql, input=None):
        connection = DB.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, input)
                return cursor.fetchall()
        except psycopg2.Error as e:
            print(f"Error fetching data: {e}")
            raise e
        finally:
            connection.rollback()
            DB.release(connection)

    @staticmethod
    def fetchone(sql, input=None):
        connection = DB.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, input)
                return cursor.fetchone()
        except psycopg2.Error as e:
            print(f"Error fetching data: {e}")
            raise e
        finally:
            connection.rollback()
            DB.release(connection)


def db_error_message(e):
    """把資料庫錯誤轉成給使用者看的中文訊息。"""
    msg = getattr(getattr(e, 'diag', None), 'message_primary', None) or str(e)
    if 'uq_player_team_jersey' in msg:
        return '同一隊已經有在隊球員使用這個背號'
    if 'player_pkey' in msg:
        return '這個學號已經建檔過了'
    if 'account_pkey' in msg:
        return '這個帳號名稱已經被使用了'
    if 'department_pkey' in msg or 'department_dname_key' in msg:
        return '系所代碼或名稱已經存在'
    if 'uq_team_dept_gender' in msg:
        return '這個系所已經有同組別的隊伍了'
    if 'team_teamname_key' in msg:
        return '隊伍名稱已經存在'
    if 'venue_vname_key' in msg:
        return '場地名稱已經存在'
    if 'chk_event_time' in msg:
        return '結束時間必須晚於開始時間'
    if 'violates foreign key' in msg:
        return '這筆資料已被其他紀錄使用，無法刪除'
    return msg


# =====================================================================
# 管理範圍
#   球經只能看到、修改「自己系所」的隊伍資料。
#   每個球經用的函式都有 scope 參數（球經負責的系所代碼）；
#   scope 為 None 時代表不限制（系統管理員）。
#   SCOPE_T：限制別名為 t 的 Team；SCOPE_TEAM_IN：限制某個 tId 欄位
# =====================================================================
SCOPE_T = "(%(scope)s::varchar IS NULL OR t.dId = %(scope)s)"


def scope_team_in(col):
    return f"({col} IN (SELECT tId FROM Team WHERE %(scope)s::varchar IS NULL OR dId = %(scope)s))"


# =====================================================================
# 帳號與登入
# =====================================================================
class Account:
    @staticmethod
    def get_account(username):
        sql = 'SELECT username, passwordHash, role, pId, dId FROM Account WHERE username = %s'
        return DB.fetchone(sql, (username,))

    @staticmethod
    def get_user(username):
        """登入後每次請求用來還原使用者身分（user_loader）。"""
        sql = '''
            SELECT a.username, a.role, a.pId, a.dId, p.tId, d.dName,
                   COALESCE(p.pName, a.aName, a.username) AS name
            FROM Account a
            LEFT JOIN Player p     ON p.pId = a.pId
            LEFT JOIN Department d ON d.dId = a.dId
            WHERE a.username = %s
        '''
        return DB.fetchone(sql, (username,))

    # F7 修改密碼
    @staticmethod
    def update_password(username, password_hash):
        sql = 'UPDATE Account SET passwordHash = %s WHERE username = %s'
        DB.execute_input(sql, (password_hash, username))


# =====================================================================
# 下拉選單用的參照資料
# =====================================================================
class Lookup:
    @staticmethod
    def teams(scope=None):
        sql = f'''
            SELECT t.tId, t.teamName, t.tGender, t.dId, d.dName
            FROM Team t JOIN Department d ON d.dId = t.dId
            WHERE {SCOPE_T}
            ORDER BY t.dId, t.tGender DESC
        '''
        return DB.fetchall(sql, {'scope': scope})

    @staticmethod
    def departments():
        return DB.fetchall('SELECT dId, college, dName FROM Department ORDER BY college, dName')

    @staticmethod
    def positions():
        return DB.fetchall('SELECT posId, posName, description FROM Position ORDER BY posId')

    @staticmethod
    def venues():
        return DB.fetchall('SELECT vId, vName, location FROM Venue ORDER BY vId')

    @staticmethod
    def current_semester():
        row = DB.fetchone('''
            SELECT semester FROM Event
            WHERE eventDate <= CURRENT_DATE
            ORDER BY eventDate DESC LIMIT 1
        ''')
        if row:
            return row['semester']
        row = DB.fetchone('SELECT MAX(semester) AS semester FROM Event')
        return row['semester'] if row and row['semester'] else ''


# =====================================================================
# 球員
# =====================================================================
class Player:
    # F11 依系所、位置（及隊伍、狀態）查詢球員；參數為 None 代表不篩選
    @staticmethod
    def search(scope, tid=None, did=None, posid=None, status='在隊'):
        sql = f'''
            SELECT p.pId, p.pName, p.gender, p.phone, p.joinDate, p.jerseyNo,
                   p.pStatus, p.leaveDate, p.tId, t.teamName, p.dId,
                   COALESCE(d.dName, '未填寫') AS dName,
                   p.posId, COALESCE(pos.posName, '未指定') AS posName
            FROM Player p
            JOIN Team t            ON t.tId = p.tId
            LEFT JOIN Department d ON d.dId = p.dId
            LEFT JOIN Position pos ON pos.posId = p.posId
            WHERE {SCOPE_T}
              AND (%(tid)s::int IS NULL       OR p.tId = %(tid)s)
              AND (%(did)s::varchar IS NULL   OR p.dId = %(did)s)
              AND (%(posid)s::varchar IS NULL OR p.posId = %(posid)s)
              AND (%(status)s::varchar IS NULL OR p.pStatus = %(status)s)
            ORDER BY p.tId, p.pStatus, p.jerseyNo
        '''
        return DB.fetchall(sql, {'scope': scope, 'tid': tid, 'did': did,
                                 'posid': posid, 'status': status})

    @staticmethod
    def get_player(pid, scope=None):
        """取得單一球員；不在球經管理範圍內時回傳 None。"""
        sql = f'''
            SELECT p.*, t.teamName, COALESCE(d.dName, '未填寫') AS dName,
                   COALESCE(pos.posName, '未指定') AS posName
            FROM Player p
            JOIN Team t            ON t.tId = p.tId
            LEFT JOIN Department d ON d.dId = p.dId
            LEFT JOIN Position pos ON pos.posId = p.posId
            WHERE p.pId = %(pid)s AND {SCOPE_T}
        '''
        return DB.fetchone(sql, {'pid': pid, 'scope': scope})

    # F1 球員建檔：新增球員與登入帳號放在同一個交易
    #   INSERT ... SELECT 搭配範圍條件：隊伍不在球經系所內時不會新增任何資料
    @staticmethod
    def create_player(data, password_hash, scope):
        params = dict(data, scope=scope, hash=password_hash)
        DB.transaction([
            (f'''INSERT INTO Player (pId, pName, gender, phone, joinDate, jerseyNo, tId, dId, posId)
                 SELECT %(pid)s, %(pname)s, %(gender)s, %(phone)s, %(joindate)s, %(jerseyno)s,
                        t.tId, %(did)s, %(posid)s
                 FROM Team t
                 WHERE t.tId = %(tid)s AND {SCOPE_T}''', params),
            ('''INSERT INTO Account (username, passwordHash, role, pId)
                SELECT %(pid)s, %(hash)s, 'player', pId FROM Player WHERE pId = %(pid)s''', params),
        ])

    # F5 球員異動：背號、轉系、位置、姓名、電話
    @staticmethod
    def update_player(data, scope):
        sql = f'''
            UPDATE Player
            SET pName = %(pname)s, phone = %(phone)s, jerseyNo = %(jerseyno)s,
                dId = %(did)s, posId = %(posid)s
            WHERE pId = %(pid)s AND {scope_team_in('tId')}
        '''
        return DB.execute_input(sql, dict(data, scope=scope))

    # F7 球員修改自己的電話
    @staticmethod
    def update_phone(pid, phone):
        DB.execute_input('UPDATE Player SET phone = %s WHERE pId = %s', (phone, pid))

    # F9 註銷球員：狀態改為退隊或畢業並記錄離隊日期，同時停用登入帳號
    @staticmethod
    def retire_player(pid, status, scope):
        params = {'pid': pid, 'status': status, 'scope': scope}
        DB.transaction([
            (f'''UPDATE Player SET pStatus = %(status)s, leaveDate = CURRENT_DATE
                 WHERE pId = %(pid)s AND pStatus = '在隊' AND {scope_team_in('tId')}''', params),
            ('''DELETE FROM Account
                WHERE pId = %(pid)s
                  AND EXISTS (SELECT 1 FROM Player WHERE pId = %(pid)s AND pStatus <> '在隊')''', params),
        ])


# =====================================================================
# 活動場次
# =====================================================================
class Event:
    EVENT_COLUMNS = '''
        e.eId, e.eventDate, e.startTime, e.endTime, e.eventType, e.semester, e.eStatus,
        e.tId, t.teamName, e.vId, v.vName
    '''

    @staticmethod
    def list_events(scope, tid=None, month=None):
        """活動列表；month 為 'YYYY-MM'。附上已點名人數，判斷能否實際刪除。"""
        sql = f'''
            SELECT {Event.EVENT_COLUMNS},
                   COUNT(a.pId) AS record_cnt,
                   COUNT(a.pId) FILTER (WHERE a.aStatus IN ('出席', '遲到')) AS present_cnt,
                   e.eventDate <= CURRENT_DATE AS is_past
            FROM Event e
            JOIN Team t  ON t.tId = e.tId
            JOIN Venue v ON v.vId = e.vId
            LEFT JOIN Attendance a ON a.eId = e.eId
            WHERE {SCOPE_T}
              AND (%(tid)s::int IS NULL OR e.tId = %(tid)s)
              AND (%(month)s::varchar IS NULL
                   OR to_char(e.eventDate, 'YYYY-MM') = %(month)s)
            GROUP BY e.eId, t.teamName, v.vName
            ORDER BY e.eventDate, e.startTime, t.teamName
        '''
        return DB.fetchall(sql, {'scope': scope, 'tid': tid, 'month': month})

    @staticmethod
    def get_event(eid, scope=None):
        sql = f'''
            SELECT {Event.EVENT_COLUMNS}
            FROM Event e
            JOIN Team t  ON t.tId = e.tId
            JOIN Venue v ON v.vId = e.vId
            WHERE e.eId = %(eid)s AND {SCOPE_T}
        '''
        return DB.fetchone(sql, {'eid': eid, 'scope': scope})

    # F2 建立活動排程（場地衝突由資料庫觸發器擋下；隊伍不在範圍內時不會新增）
    @staticmethod
    def create_event(data, scope):
        sql = f'''
            INSERT INTO Event (eventDate, startTime, endTime, eventType, semester, tId, vId)
            SELECT %(eventdate)s, %(starttime)s, %(endtime)s, %(eventtype)s, %(semester)s,
                   t.tId, %(vid)s
            FROM Team t
            WHERE t.tId = %(tid)s AND {SCOPE_T}
            RETURNING eId
        '''
        return DB.execute_returning(sql, dict(data, scope=scope))

    # F8 註銷活動
    @staticmethod
    def cancel_event(eid, scope):
        sql = f'''
            UPDATE Event SET eStatus = '已取消'
            WHERE eId = %(eid)s AND eStatus = '正常' AND {scope_team_in('tId')}
        '''
        return DB.execute_input(sql, {'eid': eid, 'scope': scope})

    # F10 刪除建立錯誤的活動：只有尚無出席紀錄的活動能刪除，回傳 0 代表不能刪
    @staticmethod
    def delete_event(eid, scope):
        sql = f'''
            DELETE FROM Event e
            WHERE e.eId = %(eid)s
              AND {scope_team_in('e.tId')}
              AND NOT EXISTS (SELECT 1 FROM Attendance a WHERE a.eId = e.eId)
        '''
        return DB.execute_input(sql, {'eid': eid, 'scope': scope})

    # F13 場地使用情況：某場地從指定日期起 7 天的活動（場地是各系共用，顯示所有隊伍）
    @staticmethod
    def venue_schedule(vid, start_date):
        sql = '''
            SELECT e.eId, e.eventDate, e.startTime, e.endTime, e.eventType, e.eStatus,
                   t.teamName, t.dId
            FROM Event e
            JOIN Team t ON t.tId = e.tId
            WHERE e.vId = %s
              AND e.eventDate >= %s::date
              AND e.eventDate <  %s::date + 7
            ORDER BY e.eventDate, e.startTime
        '''
        return DB.fetchall(sql, (vid, start_date, start_date))

    # F4 球員請假頁：自己隊上尚未舉行、未取消的活動，以及自己目前的狀態
    @staticmethod
    def upcoming_for_player(pid, limit=12):
        sql = '''
            SELECT e.eId, e.eventDate, e.startTime, e.endTime, e.eventType, v.vName,
                   a.aStatus, a.note
            FROM Player p
            JOIN Event e           ON e.tId = p.tId
            JOIN Venue v           ON v.vId = e.vId
            LEFT JOIN Attendance a ON a.eId = e.eId AND a.pId = p.pId
            WHERE p.pId = %s
              AND e.eventDate > CURRENT_DATE
              AND e.eStatus = '正常'
            ORDER BY e.eventDate, e.startTime
            LIMIT %s
        '''
        return DB.fetchall(sql, (pid, limit))


# =====================================================================
# 出席紀錄
# =====================================================================
class Attendance:
    # F3 步驟 1：這場活動應到的球員與已有紀錄（例：事先請假）
    @staticmethod
    def roster(eid):
        sql = '''
            SELECT p.pId, p.jerseyNo, p.pName, COALESCE(pos.posName, '未指定') AS posName,
                   a.aStatus, a.note
            FROM Event e
            JOIN Player p          ON p.tId = e.tId
            LEFT JOIN Position pos ON pos.posId = p.posId
            LEFT JOIN Attendance a ON a.pId = p.pId AND a.eId = e.eId
            WHERE e.eId = %s
              AND p.joinDate <= e.eventDate
              AND (p.pStatus = '在隊' OR a.pId IS NOT NULL)
            ORDER BY p.jerseyNo
        '''
        return DB.fetchall(sql, (eid,))

    # F3 步驟 2：一次寫入整隊的出席狀態；已有紀錄則更新
    #   呼叫前 views 會先用 Event.get_event(eid, scope) 確認活動屬於球經的系所
    @staticmethod
    def save_rollcall(eid, pids, statuses, notes):
        sql = '''
            INSERT INTO Attendance (pId, eId, aStatus, note)
            SELECT x.pId, %s, x.aStatus, NULLIF(x.note, '')
            FROM unnest(%s::varchar[], %s::varchar[], %s::varchar[]) AS x(pId, aStatus, note)
            ON CONFLICT (pId, eId) DO UPDATE
                SET aStatus = EXCLUDED.aStatus, note = EXCLUDED.note
        '''
        DB.execute_input(sql, (eid, pids, statuses, notes))

    # F6 修正單筆出席狀態
    @staticmethod
    def update_record(pid, eid, status, note, scope):
        sql = f'''
            UPDATE Attendance
            SET aStatus = %(status)s, note = NULLIF(%(note)s, '')
            WHERE pId = %(pid)s AND eId = %(eid)s
              AND eId IN (SELECT eId FROM Event WHERE {scope_team_in('tId')})
        '''
        return DB.execute_input(sql, {'status': status, 'note': note, 'pid': pid,
                                      'eid': eid, 'scope': scope})

    # F12 個人出缺席明細：指定月份（month_start 為該月第一天）
    @staticmethod
    def player_month(pid, month_start):
        sql = '''
            SELECT e.eId, e.eventDate, e.startTime, e.eventType, v.vName, a.aStatus, a.note
            FROM Attendance a
            JOIN Event e ON e.eId = a.eId
            JOIN Venue v ON v.vId = e.vId
            WHERE a.pId = %s
              AND e.eStatus = '正常'
              AND e.eventDate >= %s::date
              AND e.eventDate <  %s::date + INTERVAL '1 month'
              AND e.eventDate <= CURRENT_DATE
            ORDER BY e.eventDate
        '''
        return DB.fetchall(sql, (pid, month_start, month_start))

    # F4 球員請假：只能對自己隊上、尚未舉行、未取消的活動請假，回傳 0 筆代表不符合
    @staticmethod
    def request_leave(pid, eid, note):
        sql = '''
            INSERT INTO Attendance (pId, eId, aStatus, note)
            SELECT p.pId, e.eId, '請假', %s
            FROM Player p
            JOIN Event e ON e.tId = p.tId
            WHERE p.pId = %s AND e.eId = %s
              AND e.eventDate > CURRENT_DATE
              AND e.eStatus = '正常'
            ON CONFLICT (pId, eId) DO UPDATE
                SET aStatus = '請假', note = EXCLUDED.note
            RETURNING pId
        '''
        return DB.execute_returning(sql, (note, pid, eid))

    # F4 取消請假（活動尚未舉行才可以）
    @staticmethod
    def cancel_leave(pid, eid):
        sql = '''
            DELETE FROM Attendance a
            USING Event e
            WHERE a.eId = e.eId
              AND a.pId = %s AND a.eId = %s
              AND a.aStatus = '請假'
              AND e.eventDate > CURRENT_DATE
        '''
        return DB.execute_input(sql, (pid, eid))


# =====================================================================
# 統計（球經看自己系所；系統管理員 scope=None 看全校）
# =====================================================================
class Analysis:
    # F14 位置戰力分佈：各隊每個位置的在隊人數
    @staticmethod
    def position_distribution(scope):
        sql = f'''
            SELECT t.tId, t.teamName,
                   COALESCE(pos.posName, '未指定') AS posName,
                   COUNT(p.pId) AS player_cnt
            FROM Team t
            CROSS JOIN (SELECT posId, posName FROM Position
                        UNION ALL SELECT NULL, NULL) pos
            LEFT JOIN Player p
                   ON p.tId = t.tId
                  AND p.pStatus = '在隊'
                  AND p.posId IS NOT DISTINCT FROM pos.posId
            WHERE {SCOPE_T}
            GROUP BY t.tId, t.teamName, pos.posId, pos.posName
            ORDER BY t.tId, pos.posId NULLS LAST
        '''
        return DB.fetchall(sql, {'scope': scope})

    # F15 個人出席率
    @staticmethod
    def player_summary(pid, semester):
        sql = '''
            SELECT expected_cnt, attended_cnt, late_cnt, leave_cnt, absent_cnt, attendance_rate
            FROM v_player_attendance
            WHERE pId = %s AND semester = %s
        '''
        return DB.fetchone(sql, (pid, semester))

    # F16 全隊出席率排行
    @staticmethod
    def ranking(tid, semester):
        sql = '''
            SELECT RANK() OVER (ORDER BY v.attendance_rate DESC) AS rank,
                   p.pId, p.jerseyNo, v.pName,
                   COALESCE(pos.posName, '未指定') AS posName,
                   v.expected_cnt, v.attended_cnt, v.late_cnt, v.leave_cnt, v.absent_cnt,
                   v.attendance_rate
            FROM v_player_attendance v
            JOIN Player p          ON p.pId = v.pId
            LEFT JOIN Position pos ON pos.posId = p.posId
            WHERE v.tId = %s AND v.semester = %s AND v.pStatus = '在隊'
            ORDER BY rank, p.jerseyNo
        '''
        return DB.fetchall(sql, (tid, semester))

    # 各隊每月出席率（趨勢圖）
    @staticmethod
    def team_monthly_rate(semester, scope):
        sql = f'''
            SELECT e.tId, to_char(e.eventDate, 'YYYY-MM') AS month,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE a.aStatus IN ('出席', '遲到'))
                         / NULLIF(COUNT(*), 0), 1) AS rate
            FROM Attendance a
            JOIN Event e ON e.eId = a.eId
            JOIN Team t  ON t.tId = e.tId
            WHERE e.semester = %(sem)s AND e.eStatus = '正常' AND e.eventDate <= CURRENT_DATE
              AND {SCOPE_T}
            GROUP BY e.tId, month
            ORDER BY month, e.tId
        '''
        return DB.fetchall(sql, {'sem': semester, 'scope': scope})

    # 統計頁上方的摘要數字
    @staticmethod
    def overview(semester, scope):
        sql = f'''
            SELECT
              (SELECT COUNT(*) FROM Player p JOIN Team t ON t.tId = p.tId
                WHERE p.pStatus = '在隊' AND {SCOPE_T}) AS active_players,
              (SELECT COUNT(*) FROM Event e JOIN Team t ON t.tId = e.tId
                WHERE e.semester = %(sem)s AND e.eStatus = '正常'
                  AND e.eventDate <= CURRENT_DATE AND {SCOPE_T}) AS held_events,
              (SELECT COUNT(*) FROM Event e JOIN Team t ON t.tId = e.tId
                WHERE e.semester = %(sem)s AND e.eStatus = '正常'
                  AND e.eventDate > CURRENT_DATE AND {SCOPE_T}) AS upcoming_events,
              (SELECT ROUND(100.0 * SUM(attended_cnt) / NULLIF(SUM(expected_cnt), 0), 1)
                 FROM v_player_attendance v
                WHERE v.semester = %(sem)s
                  AND (%(scope)s::varchar IS NULL OR v.team_dId = %(scope)s)) AS overall_rate
        '''
        return DB.fetchone(sql, {'sem': semester, 'scope': scope})

    # 系統管理員：各系隊總覽（隊伍、人數、活動數、出席率）
    @staticmethod
    def team_summary(semester):
        sql = '''
            SELECT t.tId, t.teamName, t.tGender, d.dId, d.dName,
                   (SELECT COUNT(*) FROM Player p
                     WHERE p.tId = t.tId AND p.pStatus = '在隊') AS active_players,
                   (SELECT COUNT(*) FROM Event e
                     WHERE e.tId = t.tId AND e.semester = %(sem)s AND e.eStatus = '正常'
                       AND e.eventDate <= CURRENT_DATE) AS held_events,
                   (SELECT ROUND(100.0 * SUM(attended_cnt) / NULLIF(SUM(expected_cnt), 0), 1)
                      FROM v_player_attendance v
                     WHERE v.tId = t.tId AND v.semester = %(sem)s) AS attendance_rate
            FROM Team t
            JOIN Department d ON d.dId = t.dId
            ORDER BY d.dId, t.tGender DESC
        '''
        return DB.fetchall(sql, {'sem': semester})


# =====================================================================
# 系統管理員：系所、隊伍、球經帳號、場地
# =====================================================================
class Admin:
    # 系所列表，附上刪除時會一併影響的筆數（顯示在確認視窗）
    @staticmethod
    def departments():
        sql = '''
            SELECT d.dId, d.college, d.dName,
                   (SELECT COUNT(*) FROM Team t WHERE t.dId = d.dId)                   AS team_cnt,
                   (SELECT COUNT(*) FROM Account a WHERE a.dId = d.dId)                AS manager_cnt,
                   (SELECT COUNT(*) FROM Player p JOIN Team t ON t.tId = p.tId
                     WHERE t.dId = d.dId)                                              AS player_cnt,
                   (SELECT COUNT(*) FROM Event e JOIN Team t ON t.tId = e.tId
                     WHERE t.dId = d.dId)                                              AS event_cnt,
                   (SELECT COUNT(*) FROM Player p JOIN Team t ON t.tId = p.tId
                     WHERE p.dId = d.dId AND t.dId <> d.dId)                           AS outside_cnt
            FROM Department d
            ORDER BY d.college, d.dId
        '''
        return DB.fetchall(sql)

    @staticmethod
    def create_department(did, college, dname):
        sql = 'INSERT INTO Department (dId, college, dName) VALUES (%s, %s, %s)'
        DB.execute_input(sql, (did, college, dname))

    # 刪除系所與它的所有資料，全部在同一個交易中完成，任何一步失敗就全部取消：
    #   1. 該系所系隊的出席紀錄  2. 活動  3. 球員（球員帳號因 ON DELETE CASCADE 一併刪除）
    #   4. 系隊  5. 其他系隊中就讀這個系的同學，就讀系所改為未填寫（NULL）
    #   6. 這個系所的球經帳號  7. 系所本身
    @staticmethod
    def delete_department(did):
        p = {'did': did}
        team_ids = 'SELECT tId FROM Team WHERE dId = %(did)s'
        DB.transaction([
            (f'DELETE FROM Attendance WHERE eId IN (SELECT eId FROM Event WHERE tId IN ({team_ids}))', p),
            (f'DELETE FROM Event  WHERE tId IN ({team_ids})', p),
            (f'DELETE FROM Player WHERE tId IN ({team_ids})', p),
            ('DELETE FROM Team   WHERE dId = %(did)s', p),
            ('UPDATE Player SET dId = NULL WHERE dId = %(did)s', p),
            ("DELETE FROM Account WHERE role = 'manager' AND dId = %(did)s", p),
            ('DELETE FROM Department WHERE dId = %(did)s', p),
        ])

    # 系隊列表，附上刪除時會一併影響的筆數
    @staticmethod
    def teams():
        sql = '''
            SELECT t.tId, t.teamName, t.tGender, t.dId, d.dName,
                   COUNT(p.pId) FILTER (WHERE p.pStatus = '在隊')               AS active_players,
                   COUNT(p.pId)                                                  AS player_cnt,
                   (SELECT COUNT(*) FROM Event e WHERE e.tId = t.tId)            AS event_cnt,
                   (SELECT COUNT(*) FROM Attendance a JOIN Event e ON e.eId = a.eId
                     WHERE e.tId = t.tId)                                        AS record_cnt
            FROM Team t
            JOIN Department d    ON d.dId = t.dId
            LEFT JOIN Player p   ON p.tId = t.tId
            GROUP BY t.tId, d.dName
            ORDER BY t.dId, t.tGender DESC
        '''
        return DB.fetchall(sql)

    @staticmethod
    def create_team(team_name, gender, did):
        sql = 'INSERT INTO Team (teamName, tGender, dId) VALUES (%s, %s, %s)'
        DB.execute_input(sql, (team_name, gender, did))

    # 刪除系隊與它的所有資料（同一個交易）：
    #   1. 出席紀錄  2. 活動  3. 球員（帳號隨球員刪除）  4. 系隊本身
    #   外鍵維持 RESTRICT，所以一般操作（例：球經刪除活動）仍會保護歷史紀錄；
    #   只有系統管理員透過這個函式，依順序明確地刪除。
    @staticmethod
    def delete_team(tid):
        p = {'tid': tid}
        DB.transaction([
            ('DELETE FROM Attendance WHERE eId IN (SELECT eId FROM Event WHERE tId = %(tid)s)', p),
            ('DELETE FROM Event  WHERE tId = %(tid)s', p),
            ('DELETE FROM Player WHERE tId = %(tid)s', p),
            ('DELETE FROM Team   WHERE tId = %(tid)s', p),
        ])

    @staticmethod
    def managers():
        sql = '''
            SELECT a.username, a.aName, a.dId, d.dName
            FROM Account a
            JOIN Department d ON d.dId = a.dId
            WHERE a.role = 'manager'
            ORDER BY a.dId, a.username
        '''
        return DB.fetchall(sql)

    @staticmethod
    def create_manager(username, aname, did, password_hash):
        sql = '''
            INSERT INTO Account (username, passwordHash, role, aName, dId)
            VALUES (%s, %s, 'manager', %s, %s)
        '''
        DB.execute_input(sql, (username, password_hash, aname, did))

    @staticmethod
    def reset_manager_password(username, password_hash):
        sql = "UPDATE Account SET passwordHash = %s WHERE username = %s AND role = 'manager'"
        return DB.execute_input(sql, (password_hash, username))

    @staticmethod
    def delete_manager(username):
        sql = "DELETE FROM Account WHERE username = %s AND role = 'manager'"
        return DB.execute_input(sql, (username,))

    @staticmethod
    def venues():
        sql = '''
            SELECT v.vId, v.vName, v.location,
                   COUNT(e.eId) FILTER (WHERE e.eStatus = '正常' AND e.eventDate > CURRENT_DATE)
                       AS upcoming_cnt
            FROM Venue v
            LEFT JOIN Event e ON e.vId = v.vId
            GROUP BY v.vId
            ORDER BY v.vId
        '''
        return DB.fetchall(sql)

    @staticmethod
    def create_venue(vname, location):
        DB.execute_input('INSERT INTO Venue (vName, location) VALUES (%s, %s)', (vname, location))
