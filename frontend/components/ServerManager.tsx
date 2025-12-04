import React, { useState } from 'react';
import type { Server } from '../types';

interface ServerManagerProps {
  servers: Server[];
  onAddServer: (host: string, port: number, name: string) => Promise<{ success: boolean; error?: string }>;
  onRemoveServer: (serverId: string) => Promise<{ success: boolean; error?: string }>;
}

export const ServerManager: React.FC<ServerManagerProps> = ({ servers, onAddServer, onRemoveServer }) => {
  const [showAddForm, setShowAddForm] = useState(false);
  const [formData, setFormData] = useState({
    host: '',
    port: '1780',
    name: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const result = await onAddServer(formData.host, Number(formData.port), formData.name);

      if (result.success) {
        setFormData({ host: '', port: '1780', name: '' });
        setShowAddForm(false);
      } else {
        setError(result.error || 'Failed to add server');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemove = async (serverId: string, serverName: string) => {
    if (!confirm(`Remove server "${serverName}"?`)) {
      return;
    }

    const result = await onRemoveServer(serverId);
    if (!result.success && result.error) {
      alert(`Failed to remove server: ${result.error}`);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="font-bold text-lg text-[var(--text-primary)]">Servers</h3>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="bg-[var(--accent-color)] text-white font-bold py-1 px-3 rounded-full hover:bg-[var(--accent-color-hover)] transition-colors text-sm"
        >
          <i className={`fas ${showAddForm ? 'fa-times' : 'fa-plus'} mr-1`}></i>
          {showAddForm ? 'Cancel' : 'Add Server'}
        </button>
      </div>

      {showAddForm && (
        <form onSubmit={handleSubmit} className="bg-[var(--bg-tertiary)] p-4 rounded-lg space-y-3">
          <div>
            <label className="block text-sm font-semibold text-[var(--text-primary)] mb-1">
              Server Name
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Kitchen Server"
              required
              className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-color)]"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-[var(--text-primary)] mb-1">
              Host
            </label>
            <input
              type="text"
              value={formData.host}
              onChange={(e) => setFormData({ ...formData, host: e.target.value })}
              placeholder="e.g., 192.168.1.100"
              required
              className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-color)]"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-[var(--text-primary)] mb-1">
              Port
            </label>
            <input
              type="number"
              value={formData.port}
              onChange={(e) => setFormData({ ...formData, port: e.target.value })}
              required
              min="1"
              max="65535"
              className="w-full px-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-color)]"
            />
          </div>
          {error && (
            <div className="text-red-500 text-sm">{error}</div>
          )}
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full bg-[var(--accent-color)] text-white font-bold py-2 px-4 rounded-lg hover:bg-[var(--accent-color-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? 'Adding...' : 'Add Server'}
          </button>
        </form>
      )}

      <div className="space-y-2">
        {servers.length === 0 && (
          <p className="text-center text-[var(--text-secondary)] py-4">No servers discovered yet</p>
        )}
        {servers.map(server => (
          <div
            key={server.id}
            className="bg-[var(--bg-tertiary)] p-3 rounded-lg flex items-center justify-between"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h4 className="font-semibold text-[var(--text-primary)] truncate">{server.name}</h4>
                {server.isLocal && (
                  <span className="text-xs bg-[var(--accent-color)] text-white px-2 py-0.5 rounded-full">
                    Local
                  </span>
                )}
                {!server.connected && (
                  <span className="text-xs bg-red-500 text-white px-2 py-0.5 rounded-full">
                    Disconnected
                  </span>
                )}
              </div>
              <p className="text-sm text-[var(--text-secondary)] truncate">
                {server.host}:{server.port}
              </p>
            </div>
            {!server.isLocal && (
              <button
                onClick={() => handleRemove(server.id, server.name)}
                className="ml-3 text-red-500 hover:text-red-700 transition-colors"
                title="Remove server"
              >
                <i className="fas fa-trash"></i>
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
