import uvicorn
from app.core.logger import get_logger
import os
import sys
from pathlib import Path

# 强制将本地源码路径加入 sys.path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR.parent / "wx-mp-svr-main" / "src"))
sys.path.insert(0, str(BASE_DIR / "app" / "graphrag"))

logger = get_logger(service="server")

def check_and_install_dependencies():
    """检查并自动安装缺失的关键依赖"""
    import importlib.util
    import subprocess
    import sys

    # 定义关键依赖列表：(模块导入名, pip安装包名)
    # 按照 pyproject.toml 全面补全，防止漏包
    required_packages = [
        ("aiofiles", "aiofiles"),
        ("fnllm", "fnllm[azure,openai]"),
        ("devtools", "devtools"),
        ("json_repair", "json-repair"),
        ("rich", "rich"),
        ("spacy", "spacy"),
        ("numpy", "numpy<2.0.0"),
        ("pandas", "pandas"),
        ("networkx", "networkx"),
        ("tiktoken", "tiktoken"),
        ("lancedb", "lancedb"),
        ("textblob", "textblob"),
        ("gensim", "gensim>=4.0.0"), # 强制安装新版 gensim 以避免 graspologic 依赖旧版导致构建失败
        ("graspologic", "graspologic>=3.4.1"),
        ("umap", "umap-learn"),
        ("pyarrow", "pyarrow"),
        ("yaml", "pyyaml"),
        ("typer", "typer"),
        ("future", "future"),
        ("tqdm", "tqdm"),
        ("dotenv", "python-dotenv"),
        ("environs", "environs"),
        ("azure.search.documents", "azure-search-documents"),
        ("azure.cosmos", "azure-cosmos"),
        ("azure.identity", "azure-identity"),
        ("azure.storage.blob", "azure-storage-blob"),
        ("graphrag", "graphrag"),
        ("wx_crypt", "wx-crypt")
    ]

    logger.info("正在检查关键 Python 依赖...")
    
    for module_name, package_name in required_packages:
        # 特殊处理 graphrag，因为它可能是本地目录
        if module_name == "graphrag":
            # 如果本地有 app/graphrag，import graphrag 可能会成功，但不代表依赖全齐
            # 这里主要依赖其它明确的包名检查
            continue

        try:
            if importlib.util.find_spec(module_name) is None:
                raise ImportError
            
            # 特殊检查：如果已安装 numpy，必须确保版本小于 2.0.0
            if module_name == "numpy":
                import numpy
                if numpy.__version__.startswith("2."):
                    logger.warning(f"检测到不兼容的 Numpy 版本 ({numpy.__version__})，准备降级...")
                    raise ImportError # 抛出异常以触发下方的重装逻辑
        except ImportError:
            logger.warning(f"发现缺失或不兼容依赖: {module_name}，正在自动安装: {package_name} ...")
            try:
                # 尝试标准安装
                subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
                logger.info(f"成功安装 {package_name}")
            except subprocess.CalledProcessError:
                # 如果是 graspologic 且失败，尝试忽略 Python 版本限制 (针对 Python 3.13 环境的兼容性修复)
                if "graspologic" in package_name:
                    logger.warning(f"标准安装 {package_name} 失败，尝试忽略 Python 版本限制强制安装...")
                    try:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name, "--ignore-requires-python"])
                        logger.info(f"强制安装 {package_name} 成功")
                        continue
                    except subprocess.CalledProcessError as e2:
                        logger.error(f"强制安装 {package_name} 仍然失败: {e2}")
                else:
                    logger.error(f"安装 {package_name} 失败")
            except Exception as e:
                logger.error(f"安装 {package_name} 时发生未知错误: {e}")

    # 二进制兼容性自检 (Binary Incompatibility Check)
    # 解决 "numpy.dtype size changed" 问题 (Expected 96 from C header, got 88 from PyObject)
    logger.info("正在执行科学计算库二进制兼容性检查...")
    try:
        import pandas
        import scipy
        import scipy.sparse
        import sklearn
        # 尝试执行一个简单的 pandas 操作以触发潜在的运行时错误
        _ = pandas.DataFrame({"a": [1, 2, 3]})
    except Exception as e:
        logger.warning(f"检测到科学计算库二进制不兼容或损坏: {e}")
        logger.info("正在强制重装 pandas, scipy, scikit-learn 以修复兼容性...")
        try:
            # 强制重装受影响的库，确保它们基于当前的 numpy 重新构建/链接
            fix_cmd = [
                sys.executable, "-m", "pip", "install", 
                "--force-reinstall", "--no-deps", "--ignore-requires-python",
                "pandas", "scipy", "scikit-learn", "numpy<2.0.0"
            ]
            subprocess.check_call(fix_cmd)
            logger.info("库兼容性修复完成。")
        except subprocess.CalledProcessError as e2:
             logger.error(f"修复兼容性失败: {e2}")

def start_server():
    # 确保工作目录正确
    os.chdir(Path(__file__).parent)
    
    # 在启动服务前检查依赖
    check_and_install_dependencies()
    
    logger.info("Starting server...")
    logger.info(f"Working directory: {os.getcwd()}")
    
    uvicorn.run(
        "main:app",        # 使用模块路径
        host="0.0.0.0",
        port=8000,
        access_log=False,
        log_level="info",
        reload=False        #开发模式下启用热重载
    )

if __name__ == "__main__":
    start_server() 