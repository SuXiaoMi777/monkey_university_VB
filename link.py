import psycopg2
from dotenv import load_dotenv
import os
load_dotenv()  # Load environment variables from .env file

USER = os.getenv('DB_USER')
PASSWORD = os.getenv('DB_PASSWORD')
DBNAME = os.getenv('DB_NAME')
HOST = os.getenv('DB_HOST')
PORT = os.getenv('DB_PORT')

# 保留老師範例的單一連線，方便在 Python 互動環境中測試 SQL；
# 系統本身的查詢都透過 api/sql.py 的連線池執行。
connection = psycopg2.connect(
    user=USER,
    password=PASSWORD,
    host=HOST,
    port=PORT,
    dbname=DBNAME
)
cursor = connection.cursor()
