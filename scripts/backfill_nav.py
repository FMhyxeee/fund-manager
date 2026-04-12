#!/usr/bin/env python3
"""Backfill full NAV history for all funds that don't have it yet."""
import akshare as ak
import sqlite3
import pandas as pd
import time
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'fund_manager.db')

def get_funds_needing_nav(conn):
    """Get funds with very little NAV data (< 100 points)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT fm.id, fm.fund_code, fm.fund_name, 
               COALESCE(nav_cnt, 0) as nav_cnt
        FROM fund_master fm
        LEFT JOIN (
            SELECT fund_id, COUNT(*) as nav_cnt 
            FROM nav_snapshot 
            GROUP BY fund_id
        ) ns ON fm.id = ns.fund_id
        WHERE COALESCE(nav_cnt, 0) < 100
        ORDER BY fm.id
    """)
    return cur.fetchall()

def backfill():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    funds = get_funds_needing_nav(conn)
    total = len(funds)
    print(f"[{time.strftime('%H:%M:%S')}] 需要补全净值的基金: {total} 只")
    
    success = 0
    fail = 0
    skipped = 0
    
    for i, (fund_id, fund_code, fund_name, nav_cnt) in enumerate(funds):
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator='单位净值走势')
            
            if len(df) == 0:
                skipped += 1
                continue
            
            df['净值日期'] = pd.to_datetime(df['净值日期'])
            
            # Get accumulated NAV
            acc_map = {}
            try:
                df_acc = ak.fund_open_fund_info_em(symbol=fund_code, indicator='累计净值走势')
                df_acc['净值日期'] = pd.to_datetime(df_acc['净值日期'])
                acc_map = dict(zip(df_acc['净值日期'].dt.strftime('%Y-%m-%d'), df_acc['累计净值']))
            except:
                pass
            
            # Delete old data and insert new
            cur.execute("DELETE FROM nav_snapshot WHERE fund_id = ?", (fund_id,))
            
            rows_to_insert = []
            for _, row in df.iterrows():
                date_str = row['净值日期'].strftime('%Y-%m-%d')
                acc_nav = acc_map.get(date_str, row['单位净值'])
                rows_to_insert.append((
                    fund_id, date_str, 
                    float(row['单位净值']), float(acc_nav),
                    'akshare'
                ))
            
            cur.executemany("""
                INSERT INTO nav_snapshot (fund_id, nav_date, unit_nav_amount, accumulated_nav_amount, source_name, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, rows_to_insert)
            
            conn.commit()
            success += 1
            
            if (i + 1) % 100 == 0 or (i + 1) == total:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate / 60
                print(f"[{time.strftime('%H:%M:%S')}] {i+1}/{total} | 成功{success} 失败{fail} 跳过{skipped} | ETA: {eta:.0f}min")
            
            time.sleep(0.25)  # rate limit
            
        except Exception as e:
            fail += 1
            if fail <= 10 or fail % 50 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] {fund_code} {fund_name}: {e}")
            time.sleep(0.5)
    
    conn.close()
    elapsed = time.time() - start_time
    print(f"\n✅ 完成! 成功{success} 失败{fail} 跳过{skipped} 耗时{elapsed/60:.1f}分钟")

if __name__ == '__main__':
    start_time = time.time()
    backfill()
