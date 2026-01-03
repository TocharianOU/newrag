#!/usr/bin/env python3
"""Test authentication and permission fixes"""

import sys
sys.path.insert(0, '.')

from src.database import AuthManager, DatabaseManager
import bcrypt

print("="*80)
print("🧪 测试认证和权限修复")
print("="*80)

# 初始化数据库
db_manager = DatabaseManager(db_path='data/documents.db')
auth_manager = AuthManager(db_manager.engine)

# 测试 1: 用户名登录
print("\n📝 测试 1: 用户名登录")
print("-"*80)
user = auth_manager.get_user_by_username('luke')
if user:
    print(f"✅ 用户名 'luke' 找到: {user.email}")
    password = 'tocharian!'
    result = bcrypt.checkpw(password.encode('utf-8')[:72], user.password_hash.encode('utf-8'))
    print(f"   密码验证: {'✅ 通过' if result else '❌ 失败'}")
else:
    print("❌ 用户名 'luke' 未找到")

# 测试 2: 邮箱登录（新功能）
print("\n📧 测试 2: 邮箱登录（新功能）")
print("-"*80)
user = auth_manager.get_user_by_email('luke@newmindtech.cn')
if user:
    print(f"✅ 邮箱 'luke@newmindtech.cn' 找到: {user.username}")
    password = 'tocharian!'
    result = bcrypt.checkpw(password.encode('utf-8')[:72], user.password_hash.encode('utf-8'))
    print(f"   密码验证: {'✅ 通过' if result else '❌ 失败'}")
else:
    print("❌ 邮箱 'luke@newmindtech.cn' 未找到")

# 测试 3: 文档权限过滤
print("\n📄 测试 3: 文档列表权限过滤")
print("-"*80)
luke_user = auth_manager.get_user_by_username('luke')
if luke_user:
    print(f"用户: {luke_user.username} (ID: {luke_user.id}, Org: {luke_user.org_id})")
    
    # 列出该用户可见的文档
    docs = db_manager.list_documents(
        limit=10,
        user_id=luke_user.id,
        org_id=luke_user.org_id,
        is_superuser=luke_user.is_superuser
    )
    
    print(f"\n可见文档数量: {len(docs)}")
    if docs:
        print("\n文档列表:")
        for doc in docs:
            visibility_label = {
                'public': '🌐 公开',
                'org': '🏢 组织',
                'private': '🔒 私有'
            }.get(doc.visibility, doc.visibility)
            
            owner_label = "👤 自己" if doc.owner_id == luke_user.id else f"👤 用户{doc.owner_id}"
            
            print(f"  - {doc.filename}")
            print(f"    可见性: {visibility_label} | 所有者: {owner_label} | 状态: {doc.status}")
    else:
        print("  (无可见文档)")
else:
    print("❌ 找不到用户luke")

# 测试 4: Admin用户对比
print("\n👑 测试 4: Admin用户对比")
print("-"*80)
admin_user = auth_manager.get_user_by_username('admin')
if admin_user:
    print(f"用户: {admin_user.username} (ID: {admin_user.id}, Superuser: {admin_user.is_superuser})")
    
    admin_docs = db_manager.list_documents(
        limit=10,
        user_id=admin_user.id,
        org_id=admin_user.org_id,
        is_superuser=admin_user.is_superuser
    )
    
    print(f"可见文档数量: {len(admin_docs)}")
    print(f"说明: Superuser可以看到所有文档")

print("\n" + "="*80)
print("✅ 测试完成")
print("="*80)
print("\n💡 现在可以测试登录:")
print("   1. 用户名: luke, 密码: tocharian!")
print("   2. 邮箱: luke@newmindtech.cn, 密码: tocharian!")
print("   两种方式都应该可以登录了！")

