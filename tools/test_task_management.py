#!/usr/bin/env python3
"""
Task Management API Test Script
测试任务管理API的各项功能
"""

import requests
import time
import sys

BASE_URL = "http://localhost:8080"


def print_section(title):
    """打印分节标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def list_tasks(status=None):
    """列出所有任务"""
    print_section("📋 列出任务 / List Tasks")
    
    url = f"{BASE_URL}/tasks"
    if status:
        url += f"?status={status}"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        print(f"✅ 找到 {data['total']} 个任务:")
        for task_id, task in data['tasks'].items():
            print(f"  - 任务 {task_id}: {task['status']} ({task['progress_percentage']}%)")
            print(f"    阶段: {task.get('stage', 'N/A')}")
            print(f"    消息: {task.get('message', 'N/A')}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def get_task_detail(task_id):
    """获取任务详情"""
    print_section(f"🔍 任务详情 / Task Detail (ID: {task_id})")
    
    response = requests.get(f"{BASE_URL}/tasks/{task_id}")
    if response.status_code == 200:
        task = response.json()
        print(f"✅ 任务 {task_id} 详情:")
        print(f"  状态: {task['status']}")
        print(f"  阶段: {task.get('stage', 'N/A')}")
        print(f"  进度: {task['progress_percentage']}%")
        print(f"  消息: {task.get('message', 'N/A')}")
        print(f"  总页数: {task.get('total_pages', 0)}")
        print(f"  已处理: {task.get('processed_pages', 0)}")
        print(f"  当前页: {task.get('current_page', 0)}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def pause_task(task_id):
    """暂停任务"""
    print_section(f"⏸️  暂停任务 / Pause Task (ID: {task_id})")
    
    response = requests.post(f"{BASE_URL}/tasks/{task_id}/pause")
    if response.status_code == 200:
        result = response.json()
        print(f"✅ {result['message']}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def resume_task(task_id):
    """恢复任务"""
    print_section(f"▶️  恢复任务 / Resume Task (ID: {task_id})")
    
    response = requests.post(f"{BASE_URL}/tasks/{task_id}/resume")
    if response.status_code == 200:
        result = response.json()
        print(f"✅ {result['message']}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def cancel_task(task_id):
    """取消任务"""
    print_section(f"❌ 取消任务 / Cancel Task (ID: {task_id})")
    
    response = requests.post(f"{BASE_URL}/tasks/{task_id}/cancel")
    if response.status_code == 200:
        result = response.json()
        print(f"✅ {result['message']}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def cleanup_tasks(keep_recent=10):
    """清理旧任务"""
    print_section(f"🧹 清理任务 / Cleanup Tasks (保留最近 {keep_recent} 个)")
    
    response = requests.post(f"{BASE_URL}/tasks/cleanup?keep_recent={keep_recent}")
    if response.status_code == 200:
        result = response.json()
        print(f"✅ {result['message']}")
    else:
        print(f"❌ 错误: {response.status_code} - {response.text}")
    
    return response


def monitor_task(task_id, duration=30):
    """持续监控任务进度"""
    print_section(f"📊 监控任务 / Monitor Task (ID: {task_id})")
    print(f"将监控 {duration} 秒...")
    
    start_time = time.time()
    while time.time() - start_time < duration:
        response = requests.get(f"{BASE_URL}/tasks/{task_id}")
        if response.status_code == 200:
            task = response.json()
            status = task['status']
            progress = task['progress_percentage']
            message = task.get('message', '')
            stage = task.get('stage', 'N/A')
            
            print(f"[{time.strftime('%H:%M:%S')}] {status} | {stage} | {progress}% | {message}")
            
            # 如果任务完成或失败，停止监控
            if status in ['completed', 'failed', 'cancelled']:
                print(f"✅ 任务结束: {status}")
                break
        else:
            print(f"❌ 获取状态失败: {response.status_code}")
            break
        
        time.sleep(2)


def test_pause_resume_workflow(task_id):
    """测试暂停-恢复工作流"""
    print_section("🔄 测试暂停-恢复工作流 / Test Pause-Resume Workflow")
    
    # 1. 获取初始状态
    print("\n1️⃣ 获取初始状态...")
    get_task_detail(task_id)
    time.sleep(1)
    
    # 2. 暂停任务
    print("\n2️⃣ 暂停任务...")
    pause_task(task_id)
    time.sleep(2)
    
    # 3. 确认已暂停
    print("\n3️⃣ 确认暂停状态...")
    get_task_detail(task_id)
    time.sleep(3)
    
    # 4. 恢复任务
    print("\n4️⃣ 恢复任务...")
    resume_task(task_id)
    time.sleep(1)
    
    # 5. 确认已恢复
    print("\n5️⃣ 确认恢复状态...")
    get_task_detail(task_id)


def main():
    """主测试流程"""
    print("\n" + "🚀" * 30)
    print("任务管理系统测试 / Task Management System Test")
    print("🚀" * 30)
    
    if len(sys.argv) < 2:
        print("""
使用方法 / Usage:
    
    # 列出所有任务
    python test_task_management.py list
    
    # 列出运行中的任务
    python test_task_management.py list running
    
    # 获取任务详情
    python test_task_management.py detail <task_id>
    
    # 暂停任务
    python test_task_management.py pause <task_id>
    
    # 恢复任务
    python test_task_management.py resume <task_id>
    
    # 取消任务
    python test_task_management.py cancel <task_id>
    
    # 监控任务进度
    python test_task_management.py monitor <task_id> [duration_seconds]
    
    # 测试暂停-恢复工作流
    python test_task_management.py test-workflow <task_id>
    
    # 清理旧任务
    python test_task_management.py cleanup [keep_recent]
        """)
        sys.exit(1)
    
    command = sys.argv[1]
    
    try:
        if command == "list":
            status = sys.argv[2] if len(sys.argv) > 2 else None
            list_tasks(status)
        
        elif command == "detail":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            get_task_detail(task_id)
        
        elif command == "pause":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            pause_task(task_id)
        
        elif command == "resume":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            resume_task(task_id)
        
        elif command == "cancel":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            
            # 确认取消
            confirm = input(f"⚠️  确定要取消任务 {task_id} 吗？(y/N): ")
            if confirm.lower() == 'y':
                cancel_task(task_id)
            else:
                print("❌ 已取消操作")
        
        elif command == "monitor":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            duration = int(sys.argv[3]) if len(sys.argv) > 3 else 30
            monitor_task(task_id, duration)
        
        elif command == "test-workflow":
            if len(sys.argv) < 3:
                print("❌ 缺少参数: task_id")
                sys.exit(1)
            task_id = int(sys.argv[2])
            test_pause_resume_workflow(task_id)
        
        elif command == "cleanup":
            keep_recent = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            cleanup_tasks(keep_recent)
        
        else:
            print(f"❌ 未知命令: {command}")
            sys.exit(1)
        
        print("\n✅ 测试完成 / Test completed\n")
    
    except requests.exceptions.ConnectionError:
        print("\n❌ 无法连接到服务器。请确保服务器正在运行:")
        print("   uv run python web/app.py")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

