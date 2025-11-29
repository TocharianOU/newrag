import shutil
import sys
import os
from pathlib import Path

def get_soffice_command():
    """
    获取 LibreOffice (soffice) 的可执行文件路径。
    支持 macOS, Linux, Windows。
    """
    # 1. 优先检查环境变量 SOFFICE_PATH
    env_path = os.environ.get('SOFFICE_PATH')
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. 检查 PATH 中的 soffice 命令
    if shutil.which('soffice'):
        return 'soffice'
    
    # 3. 根据操作系统检查默认安装路径
    if sys.platform == 'darwin':  # macOS
        default_paths = [
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',
            str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice")
        ]
    elif sys.platform == 'win32':  # Windows
        default_paths = [
            r'C:\Program Files\LibreOffice\program\soffice.exe',
            r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
        ]
    else:  # Linux
        default_paths = [
            '/usr/bin/soffice',
            '/usr/bin/libreoffice'
        ]

    for path in default_paths:
        if os.path.exists(path):
            return path

    return None






