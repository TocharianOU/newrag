/**
 * Document Permission Modal Component
 * 
 * Allows users to set document visibility and sharing permissions
 */

import { useState, useEffect } from 'react';
import { X, Globe, Building2, Lock, Users } from 'lucide-react';
import {
  getDocumentPermissions,
  updateDocumentPermissions,
  type DocumentPermission,
  type DocumentPermissionDetail
} from '../api/permissions';
import { listUsers, type User } from '../api/admin';

interface DocumentPermissionModalProps {
  documentId: number;
  documentName: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export default function DocumentPermissionModal({
  documentId,
  documentName,
  isOpen,
  onClose,
  onSuccess
}: DocumentPermissionModalProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [permissions, setPermissions] = useState<DocumentPermissionDetail | null>(null);
  
  const [visibility, setVisibility] = useState<'public' | 'organization' | 'private'>('private');
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  
  const [availableUsers, setAvailableUsers] = useState<User[]>([]);
  
  // Load permissions and available options
  useEffect(() => {
    if (isOpen && documentId) {
      loadPermissions();
      loadAvailableOptions();
    }
  }, [isOpen, documentId]);
  
  const loadPermissions = async () => {
    setLoading(true);
    try {
      const data = await getDocumentPermissions(documentId);
      setPermissions(data);
      setVisibility(data.visibility as any || 'private');
      setSelectedUserIds(data.shared_users.map(u => u.id));
    } catch (error: any) {
      console.error('Failed to load permissions:', error);
      alert(`加载权限失败: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };
  
  const loadAvailableOptions = async () => {
    try {
      // Load users (first page, 100 users)
      const usersData = await listUsers({ page: 1, per_page: 100 });
      setAvailableUsers(usersData.items);
    } catch (error: any) {
      console.error('Failed to load options:', error);
    }
  };
  
  const handleSave = async () => {
    setSaving(true);
    try {
      const permissionData: DocumentPermission = {
        visibility,
        shared_with_users: selectedUserIds,
        shared_with_roles: []  // Always empty - role sharing removed
      };
      
      await updateDocumentPermissions(documentId, permissionData);
      alert('权限设置已保存');
      onSuccess?.();
      onClose();
    } catch (error: any) {
      console.error('Failed to save permissions:', error);
      alert(`保存失败: ${error.response?.data?.detail || error.message}`);
    } finally {
      setSaving(false);
    }
  };
  
  const toggleUser = (userId: number) => {
    setSelectedUserIds(prev =>
      prev.includes(userId)
        ? prev.filter(id => id !== userId)
        : [...prev, userId]
    );
  };
  
  if (!isOpen) return null;
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-slate-200 dark:border-slate-700">
          <div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white">
              文档权限设置
            </h2>
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              {documentName}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>
        
        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <div className="text-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mx-auto"></div>
              <p className="mt-2 text-slate-600 dark:text-slate-400">加载中...</p>
            </div>
          ) : (
            <>
              {/* Visibility Section */}
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
                  可见性
                </label>
                <div className="space-y-2">
                  <label className="flex items-center p-3 border-2 rounded-lg cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-700/50"
                    style={{
                      borderColor: visibility === 'public' ? '#4f46e5' : 'transparent',
                      backgroundColor: visibility === 'public' ? 'rgba(79, 70, 229, 0.05)' : undefined
                    }}
                  >
                    <input
                      type="radio"
                      name="visibility"
                      value="public"
                      checked={visibility === 'public'}
                      onChange={(e) => setVisibility(e.target.value as any)}
                      className="mr-3"
                    />
                    <Globe className="mr-3 text-green-600" size={20} />
                    <div>
                      <div className="font-medium text-slate-900 dark:text-white">公开</div>
                      <div className="text-sm text-slate-600 dark:text-slate-400">所有人都可以查看</div>
                    </div>
                  </label>
                  
                  <label className="flex items-center p-3 border-2 rounded-lg cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-700/50"
                    style={{
                      borderColor: visibility === 'organization' ? '#4f46e5' : 'transparent',
                      backgroundColor: visibility === 'organization' ? 'rgba(79, 70, 229, 0.05)' : undefined
                    }}
                  >
                    <input
                      type="radio"
                      name="visibility"
                      value="organization"
                      checked={visibility === 'organization'}
                      onChange={(e) => setVisibility(e.target.value as any)}
                      className="mr-3"
                    />
                    <Building2 className="mr-3 text-blue-600" size={20} />
                    <div>
                      <div className="font-medium text-slate-900 dark:text-white">组织内</div>
                      <div className="text-sm text-slate-600 dark:text-slate-400">同组织用户可以查看</div>
                    </div>
                  </label>
                  
                  <label className="flex items-center p-3 border-2 rounded-lg cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-700/50"
                    style={{
                      borderColor: visibility === 'private' ? '#4f46e5' : 'transparent',
                      backgroundColor: visibility === 'private' ? 'rgba(79, 70, 229, 0.05)' : undefined
                    }}
                  >
                    <input
                      type="radio"
                      name="visibility"
                      value="private"
                      checked={visibility === 'private'}
                      onChange={(e) => setVisibility(e.target.value as any)}
                      className="mr-3"
                    />
                    <Lock className="mr-3 text-red-600" size={20} />
                    <div>
                      <div className="font-medium text-slate-900 dark:text-white">私有</div>
                      <div className="text-sm text-slate-600 dark:text-slate-400">仅我可以查看</div>
                    </div>
                  </label>
                </div>
              </div>
              
              {/* Shared Users Section */}
              <div>
                <label className="flex items-center text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">
                  <Users className="mr-2" size={16} />
                  共享给用户
                </label>
                <div className="border border-slate-200 dark:border-slate-700 rounded-lg p-3 max-h-48 overflow-y-auto">
                  {availableUsers.length === 0 ? (
                    <p className="text-sm text-slate-500 text-center py-2">暂无可用用户</p>
                  ) : (
                    <div className="space-y-1">
                      {availableUsers.map(user => (
                        <label
                          key={user.id}
                          className="flex items-center p-2 hover:bg-slate-50 dark:hover:bg-slate-700/50 rounded cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={selectedUserIds.includes(user.id)}
                            onChange={() => toggleUser(user.id)}
                            className="mr-3"
                          />
                          <div className="flex-1">
                            <div className="text-sm font-medium text-slate-900 dark:text-white">
                              {user.username}
                            </div>
                            <div className="text-xs text-slate-600 dark:text-slate-400">
                              {user.email}
                            </div>
                          </div>
                          {user.org_name && (
                            <span className="text-xs text-slate-500 dark:text-slate-400">
                              {user.org_name}
                            </span>
                          )}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
        
        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-6 border-t border-slate-200 dark:border-slate-700">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}



