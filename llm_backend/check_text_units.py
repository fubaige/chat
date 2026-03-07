import pandas as pd

# 读取 text_units.parquet
df = pd.read_parquet('app/graphrag/data/output/adf3796a-f736-572d-a593-33a9a7f89e46/text_units.parquet')

print(f'文本块总数: {len(df)}')
print(f'列名: {df.columns.tolist()}')

# 搜索包含"消费场景"或"日常必需"的文本块
keywords = ["消费场景", "日常必需", "宿含生活", "学习提升", "社交娱乐"]

print(f'\n搜索关键词: {keywords}')

for keyword in keywords:
    matching = df[df['text'].str.contains(keyword, na=False)]
    print(f'\n包含"{keyword}"的文本块数: {len(matching)}')
    if len(matching) > 0:
        print(f'示例文本块:')
        print(matching.iloc[0]['text'][:500])
