import os
import sys
from pathlib import Path

# 添加相关路径
ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "app" / "graphrag"))

from app.core.config import settings

def test_paths():
    print(f"ROOT_DIR: {ROOT_DIR}")
    print(f"GRAPHRAG_PROJECT_DIR: {settings.GRAPHRAG_PROJECT_DIR}")
    
    project_dir = Path(settings.GRAPHRAG_PROJECT_DIR)
    data_dir = project_dir / settings.GRAPHRAG_DATA_DIR
    
    config_file = 'settings.yaml'
    config_path = os.path.normpath(os.path.join(data_dir, config_file))
    
    print(f"Data Dir: {data_dir}")
    print(f"Config Path: {config_path}")
    print(f"Config Path Exists: {os.path.exists(config_path)}")
    
    # 验证 resolve
    resolved_data_dir = Path(data_dir).resolve()
    resolved_config_path = Path(config_path).resolve()
    
    print(f"Resolved Data Dir: {resolved_data_dir}")
    print(f"Resolved Config Path: {resolved_config_path}")
    print(f"Resolved Config Path Exists: {resolved_config_path.exists()}")

if __name__ == "__main__":
    test_paths()
