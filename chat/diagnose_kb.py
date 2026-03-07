"""
知识库诊断脚本
检查 MySQL 知识库记录 + lancedb 向量数据 + 实际向量检索
在服务器上运行：python3 diagnose_kb.py
"""
import os, sys, asyncio
sys.path.insert(0, "/www/wwwroot/chat.aigcqun.cn/llm_backend")
sys.path.insert(0, "/www/wwwroot/chat.aigcqun.cn/llm_backend/app/graphrag")
os.chdir("/www/wwwroot/chat.aigcqun.cn/llm_backend")

QUERY = "洋洋公社优选商城"

# ── 1. MySQL：查知识库记录 ──────────────────────────────────────────────────
print("\n" + "="*60)
print("1. MySQL 知识库记录")
print("="*60)
try:
    import pymysql
    conn = pymysql.connect(
        host="103.36.221.102", port=3306,
        user="chat_aigcqun_cn", password="f6WzA5XenzCPh4wS",
        database="chat_aigcqun_cn", charset="utf8mb4"
    )
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, original_name, status, embedding_type, created_at FROM knowledge_base ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()
    print(f"{'ID':<6} {'UserID':<8} {'文件名':<35} {'状态':<12} {'Embedding':<15} {'创建时间'}")
    print("-"*100)
    for r in rows:
        print(f"{r[0]:<6} {r[1]:<8} {str(r[2]):<35} {str(r[3]):<12} {str(r[4]):<15} {r[5]}")
    conn.close()
except Exception as e:
    print(f"MySQL 连接失败: {e}")

# ── 2. lancedb：列出所有用户目录的表 ──────────────────────────────────────
print("\n" + "="*60)
print("2. lancedb 表名检查")
print("="*60)
import lancedb, glob
output_base = "/www/wwwroot/chat.aigcqun.cn/llm_backend/app/graphrag/data/output"
lance_dirs = glob.glob(f"{output_base}/*/*/lancedb") + glob.glob(f"{output_base}/*/lancedb")
for ld in sorted(lance_dirs):
    try:
        db = lancedb.connect(ld)
        tables = db.table_names()
        print(f"  {ld}")
        print(f"    表: {tables}")
    except Exception as e:
        print(f"  {ld} -> 错误: {e}")

# ── 3. 直接文本搜索 parquet ────────────────────────────────────────────────
print("\n" + "="*60)
print(f"3. parquet 文本块搜索：'{QUERY}'")
print("="*60)
import pandas as pd
parquet_dirs = glob.glob(f"{output_base}/*/*/artifacts") + glob.glob(f"{output_base}/*/artifacts") + \
               glob.glob(f"{output_base}/*/*") + glob.glob(f"{output_base}/*")
checked = set()
for d in sorted(parquet_dirs):
    tu_path = os.path.join(d, "text_units.parquet")
    if tu_path in checked or not os.path.exists(tu_path):
        continue
    checked.add(tu_path)
    try:
        df = pd.read_parquet(tu_path)
        hits = df[df['text'].str.contains(QUERY, na=False)]
        if len(hits) > 0:
            print(f"\n  ✅ 找到 {len(hits)} 条匹配 [{d}]")
            for _, row in hits.head(3).iterrows():
                print(f"    文本块: {str(row['text'])[:200]}")
        else:
            print(f"  ❌ 无匹配 [{d}] (共 {len(df)} 条)")
    except Exception as e:
        print(f"  错误 [{d}]: {e}")

# ── 4. 向量检索测试 ────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"4. 向量检索测试：'{QUERY}'")
print("="*60)

async def test_vector_search():
    try:
        # 直接用百炼 API 生成 embedding，不依赖 EmbeddingService
        import os
        os.environ.setdefault("DASHSCOPE_API_KEY", "")
        
        # 从 .env 读取 key
        env_path = "/www/wwwroot/chat.aigcqun.cn/llm_backend/.env"
        env_vars = {}
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()

        # 从数据库读取 DASHSCOPE_API_KEY
        import pymysql
        conn = pymysql.connect(
            host="103.36.221.102", port=3306,
            user="chat_aigcqun_cn", password="f6WzA5XenzCPh4wS",
            database="chat_aigcqun_cn", charset="utf8mb4"
        )
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE `key`='DASHSCOPE_API_KEY' LIMIT 1")
        row = cur.fetchone()
        conn.close()
        dashscope_key = row[0] if row else ""
        print(f"  DASHSCOPE_API_KEY 前8位: {dashscope_key[:8]}...")

        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=dashscope_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        resp = await client.embeddings.create(
            model="text-embedding-v4",
            input=[QUERY],
            dimensions=1024,
        )
        query_vec = resp.data[0].embedding
        print(f"  Embedding 维度: {len(query_vec)}")

        for ld in sorted(lance_dirs):
            try:
                db = lancedb.connect(ld)
                tables = db.table_names()
                for tbl_name in tables:
                    if "entity" in tbl_name and "description" in tbl_name:
                        tbl = db.open_table(tbl_name)
                        results = tbl.search(query_vec, vector_column_name="vector").limit(5).to_list()
                        print(f"\n  [{ld.split('/')[-2]}] 表={tbl_name}, 结果数={len(results)}")
                        for r in results:
                            score = 1 - abs(float(r.get('_distance', 1)))
                            text = str(r.get('text', ''))[:150]
                            print(f"    score={score:.3f} | {text}")
            except Exception as e:
                print(f"  [{ld}] 错误: {e}")
    except Exception as e:
        print(f"向量检索失败: {e}")
        import traceback; traceback.print_exc()

asyncio.run(test_vector_search())
print("\n诊断完成")
