@echo off
REM 重新索引知识库脚本（使用 1024 维 embedding）

echo 开始重新索引知识库...
echo 配置：
echo   - Embedding 模型: text-embedding-v4
echo   - Embedding 维度: 1024
echo   - 查询类型: local_search (向量检索)
echo.

cd app\graphrag\data

REM 运行索引
python -m graphrag index --root .

echo.
echo 索引完成！
echo 现在可以测试查询：消费场景有哪些？
pause
