#!/bin/bash

# 远程服务器重新索引脚本
# 服务器路径：/www/wwwroot/chat.aigcqun.cn/llm_backend

echo "=========================================="
echo "GraphRAG 知识库重新索引（1024 维向量）"
echo "=========================================="
echo ""

# 设置路径
BASE_DIR="/www/wwwroot/chat.aigcqun.cn/llm_backend"
DATA_DIR="$BASE_DIR/app/graphrag/data"
OUTPUT_DIR="$DATA_DIR/output/adf3796a-f736-572d-a593-33a9a7f89e46"
LANCEDB_DIR="$OUTPUT_DIR/lancedb"

echo "1. 检查路径..."
echo "   知识库路径: $OUTPUT_DIR"
echo "   向量库路径: $LANCEDB_DIR"

if [ -d "$LANCEDB_DIR" ]; then
    echo ""
    echo "2. 删除旧的 2048 维向量库..."
    rm -rf "$LANCEDB_DIR"
    if [ $? -eq 0 ]; then
        echo "   ✅ 删除成功"
    else
        echo "   ❌ 删除失败"
        exit 1
    fi
else
    echo ""
    echo "2. 向量库不存在，跳过删除"
fi

echo ""
echo "3. 开始重新索引（使用 1024 维 embedding）..."
echo "   这可能需要几分钟，请耐心等待..."
echo ""

cd "$DATA_DIR"

# 运行索引
python -m graphrag index --root .

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ 索引完成！"
    echo "=========================================="
    echo ""
    echo "4. 验证向量库..."
    if [ -d "$LANCEDB_DIR" ]; then
        echo "   ✅ lancedb 目录已创建"
        echo "   路径: $LANCEDB_DIR"
        echo ""
        echo "   文件列表:"
        ls -lh "$LANCEDB_DIR"
    else
        echo "   ❌ lancedb 目录未创建，索引可能失败"
        exit 1
    fi
    
    echo ""
    echo "=========================================="
    echo "下一步：重启服务并测试查询"
    echo "=========================================="
    echo "测试查询："
    echo "  - 消费场景有哪些？"
    echo "  - 目标用户分析"
    echo "  - 推广策略有哪些"
else
    echo ""
    echo "=========================================="
    echo "❌ 索引失败！"
    echo "=========================================="
    echo ""
    echo "请检查："
    echo "  1. .env 文件中的 Embedding_API_KEY 是否正确"
    echo "  2. 网络是否能访问阿里百炼 API"
    echo "  3. input 目录下是否有文档"
    exit 1
fi
