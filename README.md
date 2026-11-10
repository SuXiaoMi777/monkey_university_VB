# 猴子大學排球系隊管理系統

使用 Flask 開發的各系排球隊（系隊）管理系統，後端使用 PostgreSQL。架構沿用課程範例（中山網路書店）。

## 功能

- **系統管理員（體育室）**：新增系所與系隊、建立各系球經帳號、管理場地、查看全校統計。
- **球經（各系一位或多位）**：只能管理自己系所的系隊，包括球員、活動、點名與統計圖表。
- **球員**：查看自己的出缺席與出席率、事先請假、修改電話與密碼。

## 安裝與啟動

步驟和課程範例相同。

```bash
# 1. 建立並啟動 conda 環境（已經有 db-2026 環境可略過）
conda create -n db-2026 python=3.10
conda activate db-2026

# 2. 安裝套件
pip install -r requirements.txt
```

3. 把 `.env.example` 複製一份改名為 `.env`，填入資料庫連線資訊。
4. 在 pgAdmin 的 Query Tool 執行 `volleyball.sql`（已經匯入過可略過）。
5. 啟動程式：

```bash
python app.py
```

打開終端機顯示的網址（預設 http://127.0.0.1:5000）。

## 專案結構（對照課程範例）

| 本專案 | 課程範例 | 內容 |
| --- | --- | --- |
| `app.py` | `app.py` | 建立 Flask、註冊 Blueprint |
| `api/api.py` | `api/api.py` | 登入、登出、角色權限檢查 |
| `api/sql.py` | `api/sql.py` | 所有 SQL（依資料表分 class） |
| `admin/` | （無） | 系統管理員：系所與系隊、球經帳號、場地、全校總覽 |
| `backstage/` | `backstage/` | 球經後台：球員、活動、點名、場地、資料分析 |
| `player/` | `bookstore/` | 球員前台：我的出席、請假、個人資料 |
| `templates/` | `templates/` | 首頁、登入頁、共用元件 |
| `volleyball.sql` | `ebook.sql` | 建表與示範資料 |

## 頁面與功能需求對照

| 頁面 | 網址 | 功能需求 |
| --- | --- | --- |
| 球員管理 | `/backstage/playerManager` | F1 新增、F9 註銷、F11 查詢 |
| 編輯球員 | `/backstage/editPlayer` | F5 球員異動 |
| 出缺席明細 | `/backstage/playerAttendance` | F6 修正狀態、F12 月份明細 |
| 活動與點名 | `/backstage/eventManager` | F2 建立、F8 註銷、F10 刪除 |
| 點名 | `/backstage/rollcall` | F3 批次登記出席 |
| 場地查詢 | `/backstage/venue` | F13 場地使用情況 |
| 資料分析 | `/backstage/dashboard` | F14 位置分佈、F16 出席率排行 |
| 全校總覽 | `/admin/` | 各系隊人數與出席率、全校統計圖表 |
| 系所與系隊 | `/admin/teams` | 新增系所、新增／刪除系隊 |
| 球經帳號 | `/admin/managers` | 建立、重設密碼、刪除球經帳號 |
| 場地 | `/admin/venues` | 新增場地 |
| 我的出席 | `/player/` | F12 月份明細、F15 個人出席率 |
| 請假 | `/player/leave` | F4 請假與取消 |
| 個人資料 | `/player/profile` | F7 修改電話與密碼 |

## 注意事項

- 球經的所有查詢與修改都限制在自己系所（`api/sql.py` 的 `scope` 參數），網址改成別系的編號也只會得到 404。
- 場地由各系隊共用：場地查詢會顯示所有系隊的預約，建立活動時跨系的時段衝突一樣會被擋下。
- 球員的「就讀系所」和「隊伍所屬系所」分開記錄，允許雙主修、輔系的外系同學加入系隊。
- 密碼以 werkzeug 雜湊儲存，不存明碼。
- 球員被註銷（退隊、畢業）後帳號會停用，但出席紀錄保留。
- 示範資料以 2026-11-04 為「今天」：之前的活動已點名，之後的活動可以示範點名與請假。
