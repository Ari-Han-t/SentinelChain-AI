import sqlite3
import sys

con = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "sentinelchain.db")
for kind, name, sql in con.execute(
    "select type, name, sql from sqlite_master where tbl_name like 'supply_chain%' or (type='index' and name like '%supply_chain%')"
):
    print(kind, "|", name, "|", sql)
