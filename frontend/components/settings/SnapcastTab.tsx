import React, {useState, useEffect} from 'react';
import type {Server, Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';
import {ServerManager} from '../ServerManager';
import {federationService} from '../../services/federationService';

interface SnapcastTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

export const SnapcastTab: React.FC<SnapcastTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const [servers, setServers] = useState<Server[]>([]);

  // Local state for server name changes (like device name pattern)
  const [localServerName, setLocalServerName] = useState(settings.federation.localServerName);
  const [serverNameStatus, setServerNameStatus] = useState<'idle' | 'pending' | 'applying' | 'success' | 'error'>('idle');
  const [serverNameMessage, setServerNameMessage] = useState('');
  const [isTogglingFederation, setIsTogglingFederation] = useState(false);
  const [isTogglingAutoDiscover, setIsTogglingAutoDiscover] = useState(false);

  // Sync local state when settings change externally
  useEffect(() => {
    setLocalServerName(settings.federation.localServerName);
  }, [settings.federation.localServerName]);

  // Detect pending changes for server name
  const serverNameChanged = localServerName !== settings.federation.localServerName;

  useEffect(() => {
    if (settings.federation.enabled) {
      const fetchServers = async () => {
        const serverList = await federationService.getServers();
        setServers(serverList);
      };
      fetchServers();
    } else {
      setServers([]);
    }
  }, [settings.federation.enabled]);

  const handleFederationToggle = async (enabled: boolean) => {
    setIsTogglingFederation(true);
    try {
      onSettingsChange({
        ...settings,
        federation: {
          ...settings.federation,
          enabled,
        },
      });
    } catch (error) {
      console.error('Failed to toggle federation:', error);
      alert('Error toggling Multi-Server Control');
    } finally {
      setIsTogglingFederation(false);
    }
  };

  const handleAutoDiscoverToggle = async (enabled: boolean) => {
    setIsTogglingAutoDiscover(true);
    try {
      onSettingsChange({
        ...settings,
        federation: {
          ...settings.federation,
          autoDiscover: enabled,
        },
      });
    } catch (error) {
      console.error('Failed to toggle auto-discover:', error);
      alert('Error toggling Auto-Discover');
    } finally {
      setIsTogglingAutoDiscover(false);
    }
  };

  const handleApplyServerName = async () => {
    if (!serverNameChanged) return;

    setServerNameStatus('applying');
    setServerNameMessage('Applying changes...');

    try {
      onSettingsChange({
        ...settings,
        federation: {
          ...settings.federation,
          localServerName,
        },
      });

      setServerNameStatus('success');
      setServerNameMessage('Applied');

      // Clear success message after 3 seconds
      setTimeout(() => {
        setServerNameStatus('idle');
        setServerNameMessage('');
      }, 3000);
    } catch (error: any) {
      setServerNameStatus('error');
      setServerNameMessage(error.message || 'Error applying changes');
    }
  };

  const handleDisplayChange = (key: keyof SettingsType['display'], value: boolean) => {
    onSettingsChange({
      ...settings,
      display: {
        ...settings.display,
        [key]: value,
      },
    });
  };

  const handleAddServer = async (host: string, port: number, name: string) => {
    const result = await federationService.addServer(host, port, name);
    if (result.success && result.server) {
      setServers([...servers, result.server]);
    }
    return result;
  };

  const handleRemoveServer = async (serverId: string) => {
    const result = await federationService.removeServer(serverId);
    if (result.success) {
      setServers(servers.filter(s => s.id !== serverId));
    }
    return result;
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          Multi-Server Federation
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Control multiple Snapcast servers from a single interface
        </p>
      </div>

      <div className="space-y-4">
        <Switch
          label="Multi-Server Control"
          checked={settings.federation.enabled}
          onChange={handleFederationToggle}
          icon="fa-network-wired"
          disabled={isTogglingFederation}
        />

        {isTogglingFederation && (
          <p className="text-xs text-amber-500 ml-8 mt-1">
            Processing...
          </p>
        )}

        {settings.federation.enabled && (
          <>
            <div className="pl-8 space-y-4">
              <Switch
                label="Auto-Discover Servers"
                checked={settings.federation.autoDiscover}
                onChange={handleAutoDiscoverToggle}
                icon="fa-radar"
                disabled={isTogglingAutoDiscover}
              />

              {isTogglingAutoDiscover && (
                <p className="text-xs text-amber-500 ml-8 mt-1">
                  Processing...
                </p>
              )}

              <div>
                <label className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
                  Local Server Name
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={localServerName}
                    onChange={(e) => setLocalServerName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && serverNameChanged) {
                        handleApplyServerName();
                      }
                    }}
                    placeholder="e.g., Main Server"
                    className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-color)] pr-20"
                    disabled={serverNameStatus === 'applying'}
                  />
                  {serverNameChanged && (
                    <button
                      onClick={handleApplyServerName}
                      disabled={serverNameStatus === 'applying'}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 bg-[var(--accent-color)] text-white rounded-md text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {serverNameStatus === 'applying' ? 'Applying...' : 'Apply'}
                    </button>
                  )}
                </div>

                {/* Status feedback */}
                {serverNameMessage && (
                  <p className={`text-xs mt-1 ${
                    serverNameStatus === 'success'
                      ? 'text-green-500'
                      : serverNameStatus === 'error'
                      ? 'text-red-500'
                      : 'text-[var(--text-muted)]'
                  }`}>
                    {serverNameMessage}
                  </p>
                )}

                {/* Pending changes indicator */}
                {serverNameChanged && !serverNameMessage && (
                  <p className="text-xs text-amber-500 mt-1">
                    Pending changes - press Enter or click Apply
                  </p>
                )}

                {!serverNameChanged && !serverNameMessage && (
                  <p className="text-xs text-[var(--text-muted)] mt-1">
                    This name will be visible to other servers on your network
                  </p>
                )}
              </div>

              <div>
                <ServerManager
                  servers={servers}
                  onAddServer={handleAddServer}
                  onRemoveServer={handleRemoveServer}
                />
              </div>
            </div>
          </>
        )}
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Display Options</h4>
        <div className="space-y-4">
          <Switch
            label="Show Offline Devices"
            checked={settings.display.showOfflineDevices}
            onChange={(val) => handleDisplayChange('showOfflineDevices', val)}
            icon="fa-eye"
          />
          <p className="text-xs text-[var(--text-muted)] pl-8 -mt-2">
            Display devices that are currently disconnected or unreachable
          </p>
        </div>
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          About Federation
        </h4>
        <p className="text-xs text-[var(--text-muted)]">
          Federation allows you to control multiple Snapcast servers from one interface. When enabled,
          you can see and control clients across all connected servers, making it easy to manage
          multi-room audio across different locations.
        </p>
      </div>
    </div>
  );
};
